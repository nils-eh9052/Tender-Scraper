"""Sprint 2026-05-09 — Backfill new TED API fields into existing
``relevant.json`` and ``data/raw/details/*.json`` files.

Patches every TED notice (``tender_id`` matches ``\\d+-\\d{4}$``) by
re-fetching it with the extended ``ALL_FIELDS`` list (Sprint 14b's
notice-type fields plus 8 new fields from
``docs/TED_FIELDS_DISCOVERED.md``: ``buyer-internet-address``,
``estimated-value-lot``, ``quantity-lot``, ``procedure-features``,
``place-of-performance-{city,country}-part``,
``deadline-receipt-tender-time-lot``, ``internal-identifier-part``).

Cache-friendly: a notice is skipped when its ``_raw`` already
contains all of the targeted fields. ``--force`` overrides.

Run from ``ted-scraper/ted-scraper/``::

    python3 scripts/_backfill_ted_xml_fields.py [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
import urllib3

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env so SSL_VERIFY_DISABLE works on corporate VPN
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_SSL_VERIFY = (
    os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
    not in ("1", "true", "yes")
)
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Local imports after env wiring
from src.api_client import ALL_FIELDS  # noqa: E402

RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"
DETAILS_DIR = ROOT / "data" / "raw" / "details"
SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)",
}
_TED_PAT = re.compile(r"^\d+-\d{4}$")

# Fields added in this sprint — used as the "is backfill needed" check.
NEW_FIELDS = (
    "buyer-internet-address",
    "estimated-value-lot",
    "quantity-lot",
    "procedure-features",
    "place-of-performance-city-part",
    "place-of-performance-country-part",
    "deadline-receipt-tender-time-lot",
    "internal-identifier-part",
)


def is_ted(notice: dict) -> bool:
    return bool(_TED_PAT.match(str(notice.get("tender_id", ""))))


def already_has_new_fields(raw: dict) -> bool:
    """Cache-check: skip notice if every new field is already present."""
    return all(f in raw for f in NEW_FIELDS)


def fetch_notice(pub_num: str, retries: int = 4) -> dict | None:
    payload = {
        "query": f'publication-number="{pub_num}"',
        "fields": ALL_FIELDS,
        "page": 1,
        "limit": 1,
        "paginationMode": "PAGE_NUMBER",
    }
    for attempt in range(retries):
        try:
            resp = requests.post(
                SEARCH_URL, json=payload, headers=HEADERS,
                timeout=30, verify=_SSL_VERIFY,
            )
        except Exception as exc:
            if attempt + 1 < retries:
                time.sleep(3 * (attempt + 1))
                continue
            print(f"      [error] network: {exc}", file=sys.stderr)
            return None
        if resp.status_code == 200:
            body = resp.json()
            notices = body.get("notices") or []
            return notices[0] if notices else None
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f"      [429] sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        print(f"      [HTTP {resp.status_code}] {resp.text[:120]}", file=sys.stderr)
        return None
    return None


def merge_new_fields(target_raw: dict, fresh_notice: dict) -> int:
    """Copy NEW_FIELDS from ``fresh_notice`` into ``target_raw``.

    Returns the number of fields that were actually written (i.e.
    populated in the API response). Idempotent: existing values are
    overwritten with the fresh ones.
    """
    n = 0
    for f in NEW_FIELDS:
        if f in fresh_notice:
            target_raw[f] = fresh_notice[f]
            n += 1
    # Also pull fresh values for the older lifecycle fields (notice-type
    # etc.) in case they were ever missing — safety net.
    for f in ("notice-type", "form-type", "procedure-type"):
        if f in fresh_notice and f not in target_raw:
            target_raw[f] = fresh_notice[f]
    return n


def detail_path_for(notice_id: str) -> Path:
    safe = notice_id.replace("/", "_").replace("\\", "_")
    return DETAILS_DIR / f"{safe}.json"


def update_detail_file(detail_path: Path, fresh_notice: dict) -> bool:
    """Patch the on-disk ``raw/details/{id}.json`` _raw block."""
    if not detail_path.exists():
        return False
    try:
        data = json.loads(detail_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    raw = data.get("_raw") or {}
    if not isinstance(raw, dict):
        return False
    merge_new_fields(raw, fresh_notice)
    data["_raw"] = raw
    detail_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan only — make no API calls and no file writes.")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if all NEW_FIELDS are already present.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap number of API calls (testing).")
    ap.add_argument("--sleep", type=float, default=1.1,
                    help="Sleep between API calls (TED rate limit, default 1.1s).")
    args = ap.parse_args()

    with open(RELEVANT_JSON, encoding="utf-8") as f:
        rel = json.load(f)

    todo = []
    skipped_already_have = 0
    skipped_non_ted = 0
    for n in rel:
        if not is_ted(n):
            skipped_non_ted += 1
            continue
        raw = n.get("_raw") or {}
        if not args.force and isinstance(raw, dict) and already_has_new_fields(raw):
            skipped_already_have += 1
            continue
        todo.append(n)

    if args.limit:
        todo = todo[: args.limit]

    print(f"  {len(rel)} relevant.json notices total")
    print(f"  {skipped_non_ted} skipped (non-TED)")
    print(f"  {skipped_already_have} skipped (already backfilled)")
    print(f"  {len(todo)} TED notices to backfill")
    if args.dry_run:
        print("  [dry-run] exiting without API calls / file writes")
        return 0

    fields_written_total = 0
    api_calls = 0
    failures: list[str] = []

    for i, n in enumerate(todo):
        tid = n["tender_id"]
        print(f"  [{i+1}/{len(todo)}] {tid}", flush=True)
        time.sleep(args.sleep)
        api_calls += 1
        fresh = fetch_notice(tid)
        if not fresh:
            failures.append(tid)
            continue
        # 1) update relevant.json _raw in-memory
        raw = n.get("_raw") or {}
        if not isinstance(raw, dict):
            raw = {}
        nw = merge_new_fields(raw, fresh)
        n["_raw"] = raw
        fields_written_total += nw
        # 2) update on-disk detail file
        update_detail_file(detail_path_for(tid), fresh)
        # 3) periodic save
        if (i + 1) % 25 == 0:
            with open(RELEVANT_JSON, "w", encoding="utf-8") as fp:
                json.dump(rel, fp, ensure_ascii=False, indent=2)

    # Final save
    with open(RELEVANT_JSON, "w", encoding="utf-8") as fp:
        json.dump(rel, fp, ensure_ascii=False, indent=2)

    print()
    print("  Summary:")
    print(f"    API calls:                      {api_calls}")
    print(f"    Successful patches:             {len(todo) - len(failures)}")
    print(f"    Failures:                       {len(failures)}")
    print(f"    NEW_FIELDS values written:      {fields_written_total}")
    if failures:
        print(f"    First failures: {failures[:10]}")

    # Diagnostic: how many notices in relevant.json now have each field populated
    print()
    print("  Field coverage after backfill:")
    for f in NEW_FIELDS:
        n = sum(1 for x in rel if isinstance(x.get("_raw"), dict)
                and x["_raw"].get(f) not in (None, "", [], {}))
        print(f"    {f:42s} {n:>3} / {len(rel)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

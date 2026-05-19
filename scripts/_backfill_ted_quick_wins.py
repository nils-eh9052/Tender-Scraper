"""Sprint 2026-05-18 — TED Quick-Wins backfill.

Re-fetches every TED-style tender in ``relevant.json`` with the extended
``ALL_FIELDS`` list (see ``src/api_client.py``) and merges the four new
eForms fields into the notice's ``_raw`` block plus the corresponding
top-level shortcuts.

Source: ``docs/TED_DEEP_RESEARCH_260517.md`` §2.2 ("Top-3 ungenutzte
TED-Felder").

New raw fields:
  framework-agreement-lot          → _framework_type
  contract-conclusion-date         → _contract_conclusion_date
  organisation-name-buyer          → _authority_name_structured
  organisation-identifier-buyer    → _authority_id

Idempotent: notices whose ``_raw`` already carries all four new fields
are skipped. ``--force`` re-fetches anyway. Rate-limited to ~1 req/s
to stay below TED's quota.

Run from ``ted-scraper/ted-scraper/``::

    python3 scripts/_backfill_ted_quick_wins.py [--dry-run] [--limit N] [--force]
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

from src.api_client import ALL_FIELDS  # noqa: E402
from src.detail_fetcher import _clean_iso_date, _first_value  # noqa: E402

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
NEW_RAW_FIELDS = (
    "framework-agreement-lot",
    "contract-conclusion-date",
    "organisation-name-buyer",
    "organisation-identifier-buyer",
)

# Mapping raw field name → top-level shortcut name on the notice.
TOP_LEVEL_MAPPING = {
    "framework-agreement-lot": "_framework_type",
    "contract-conclusion-date": "_contract_conclusion_date",
    "organisation-name-buyer": "_authority_name_structured",
    "organisation-identifier-buyer": "_authority_id",
}


def is_ted(notice: dict) -> bool:
    return bool(_TED_PAT.match(str(notice.get("tender_id", ""))))


def already_has_new_fields(raw: dict) -> bool:
    """Cache-check: skip notice if every new raw field is already present."""
    return all(f in raw for f in NEW_RAW_FIELDS)


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


def _extract_text_first_lang(field) -> str | None:
    """Multilingual dict → first non-empty language value."""
    if field is None:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, list):
        for v in field:
            if v:
                return v if isinstance(v, str) else str(v)
        return None
    if isinstance(field, dict):
        for lang in ("eng", "en", "deu", "de", "fra", "fr"):
            v = field.get(lang)
            if v:
                return v if isinstance(v, str) else (
                    v[0] if isinstance(v, list) and v else str(v)
                )
        for v in field.values():
            if v:
                return v if isinstance(v, str) else (
                    v[0] if isinstance(v, list) and v else str(v)
                )
    return None


def merge_new_fields(notice: dict, fresh: dict) -> int:
    """Merge the 4 new raw fields and their top-level shortcuts.

    Mutates ``notice`` in place. Returns the count of raw fields that
    were actually present (non-empty) in the fresh API response.
    """
    raw = notice.get("_raw")
    if not isinstance(raw, dict):
        raw = {}
        notice["_raw"] = raw

    written = 0
    for f in NEW_RAW_FIELDS:
        if f in fresh:
            raw[f] = fresh[f]
            if fresh[f] not in (None, "", [], {}):
                written += 1

    # Top-level shortcuts (overwrite — fresh API response wins).
    ft = _first_value(raw.get("framework-agreement-lot"))
    if ft:
        notice["_framework_type"] = ft
    elif "_framework_type" in notice and "framework-agreement-lot" in raw:
        # API returned the field but with empty payload — clear stale value
        notice.pop("_framework_type", None)

    ccd_raw = _first_value(raw.get("contract-conclusion-date"))
    ccd = _clean_iso_date(ccd_raw) if ccd_raw else None
    if ccd:
        notice["_contract_conclusion_date"] = ccd

    name_structured = _extract_text_first_lang(raw.get("organisation-name-buyer"))
    if name_structured:
        notice["_authority_name_structured"] = name_structured

    auth_id = _first_value(raw.get("organisation-identifier-buyer"))
    if auth_id:
        notice["_authority_id"] = str(auth_id)

    return written


def detail_path_for(notice_id: str) -> Path:
    safe = notice_id.replace("/", "_").replace("\\", "_")
    return DETAILS_DIR / f"{safe}.json"


def update_detail_file(detail_path: Path, fresh: dict) -> bool:
    """Patch on-disk ``data/raw/details/{id}.json`` so future re-runs of
    filter_engine see the same enriched shape."""
    if not detail_path.exists():
        return False
    try:
        data = json.loads(detail_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    merge_new_fields(data, fresh)
    detail_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan only — make no API calls and no file writes.")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if all NEW_RAW_FIELDS are present.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap number of API calls (testing).")
    ap.add_argument("--sleep", type=float, default=1.1,
                    help="Sleep between API calls (TED rate limit, default 1.1s).")
    args = ap.parse_args()

    with open(RELEVANT_JSON, encoding="utf-8") as f:
        rel = json.load(f)

    todo: list[dict] = []
    skipped_already = 0
    skipped_non_ted = 0
    for n in rel:
        if not is_ted(n):
            skipped_non_ted += 1
            continue
        raw = n.get("_raw") or {}
        if not args.force and isinstance(raw, dict) and already_has_new_fields(raw):
            skipped_already += 1
            continue
        todo.append(n)

    if args.limit:
        todo = todo[: args.limit]

    print(f"  {len(rel)} relevant.json notices total")
    print(f"  {skipped_non_ted} skipped (non-TED)")
    print(f"  {skipped_already} skipped (already backfilled)")
    print(f"  {len(todo)} TED notices to backfill")
    if args.dry_run:
        print("  [dry-run] exiting without API calls / file writes")
        return 0

    api_calls = 0
    failures: list[str] = []
    fields_written_total = 0

    for i, n in enumerate(todo):
        tid = n["tender_id"]
        print(f"  [{i+1}/{len(todo)}] {tid}", flush=True)
        time.sleep(args.sleep)
        api_calls += 1
        fresh = fetch_notice(tid)
        if not fresh:
            failures.append(tid)
            continue
        nw = merge_new_fields(n, fresh)
        fields_written_total += nw
        update_detail_file(detail_path_for(tid), fresh)
        if (i + 1) % 25 == 0:
            with open(RELEVANT_JSON, "w", encoding="utf-8") as fp:
                json.dump(rel, fp, ensure_ascii=False, indent=2)

    with open(RELEVANT_JSON, "w", encoding="utf-8") as fp:
        json.dump(rel, fp, ensure_ascii=False, indent=2)

    print()
    print("  Summary:")
    print(f"    API calls:                  {api_calls}")
    print(f"    Successful patches:         {len(todo) - len(failures)}")
    print(f"    Failures:                   {len(failures)}")
    print(f"    Raw values written (sum):   {fields_written_total}")
    if failures:
        print(f"    First failures: {failures[:10]}")

    # Coverage report — count how many TED notices have each new field
    print()
    print("  Field coverage after backfill (TED notices only):")
    ted_total = 0
    counts_raw = {f: 0 for f in NEW_RAW_FIELDS}
    counts_top = {f: 0 for f in TOP_LEVEL_MAPPING.values()}
    for x in rel:
        if not is_ted(x):
            continue
        ted_total += 1
        raw = x.get("_raw") or {}
        for f in NEW_RAW_FIELDS:
            v = raw.get(f) if isinstance(raw, dict) else None
            if v not in (None, "", [], {}):
                counts_raw[f] += 1
        for f in counts_top:
            if x.get(f) not in (None, "", [], {}):
                counts_top[f] += 1
    print(f"    (TED total: {ted_total})")
    for f in NEW_RAW_FIELDS:
        pct = (100 * counts_raw[f] / ted_total) if ted_total else 0.0
        print(f"    raw {f:35s} {counts_raw[f]:>3} / {ted_total}  ({pct:5.1f} %)")
    for f, count in counts_top.items():
        pct = (100 * count / ted_total) if ted_total else 0.0
        print(f"    top {f:35s} {count:>3} / {ted_total}  ({pct:5.1f} %)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

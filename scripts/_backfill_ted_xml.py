"""Sprint 2026-05-10 — XML backfill for TED notices.

Fetches the TED-XML representation for every TED-style tender in
``relevant.json`` and merges the XML-only fields into a new ``_xml``
sub-block of each notice's ``_raw``. Companion to
``scripts/_backfill_ted_xml_fields.py`` (which only adds JSON-API fields).

Cache: TED-XML is cached on disk by ``ted_xml_fetcher`` at
``data/ted_xml_cache/{id}.xml`` so re-runs are zero-network.

Run from ``ted-scraper/ted-scraper/``::

    python3 scripts/_backfill_ted_xml.py [--dry-run] [--limit N] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env for SSL_VERIFY_DISABLE
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from src.ted_xml_fetcher import fetch_xml, parse_xml_fields  # noqa: E402

RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"
DETAILS_DIR = ROOT / "data" / "raw" / "details"
_TED_PAT = re.compile(r"^\d+-\d{4}$")

# Sub-set of XML-only field names this sprint introduces. Used for the
# "is backfill needed" cache check.
XML_FIELDS = (
    "internal_reference",
    "tender_documents_access",
    "buyer_profile_url_full",
    "contract_folder_id",
    "notice_uuid",
)


def is_ted(notice: dict) -> bool:
    return bool(_TED_PAT.match(str(notice.get("tender_id", ""))))


def already_has_xml(raw: dict) -> bool:
    """True if ``_raw._xml`` already carries every XML_FIELDS key."""
    xml_block = raw.get("_xml") if isinstance(raw, dict) else None
    if not isinstance(xml_block, dict):
        return False
    return all(f in xml_block for f in XML_FIELDS)


def detail_path_for(notice_id: str) -> Path:
    safe = notice_id.replace("/", "_").replace("\\", "_")
    return DETAILS_DIR / f"{safe}.json"


def update_detail_file(detail_path: Path, xml_fields: dict) -> bool:
    """Patch ``data/raw/details/{id}.json`` _raw._xml block."""
    if not detail_path.exists():
        return False
    try:
        data = json.loads(detail_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    raw = data.get("_raw") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return False
    raw.setdefault("_xml", {}).update(xml_fields)
    data["_raw"] = raw
    detail_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan only — no network calls, no writes.")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch + re-parse even when XML_FIELDS already populated.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap number of fetches (testing).")
    ap.add_argument("--sleep", type=float, default=1.1,
                    help="Sleep between TED-XML calls (default 1.1 s).")
    args = ap.parse_args()

    with open(RELEVANT_JSON, encoding="utf-8") as f:
        rel = json.load(f)

    todo = []
    skipped_already = 0
    skipped_non_ted = 0
    for n in rel:
        if not is_ted(n):
            skipped_non_ted += 1
            continue
        raw = n.get("_raw") or {}
        if not args.force and isinstance(raw, dict) and already_has_xml(raw):
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
        print("  [dry-run] exiting without network or writes")
        return 0

    succ = 0
    fail = []
    for i, n in enumerate(todo):
        tid = n["tender_id"]
        if i > 0:
            time.sleep(args.sleep)
        # fetch_xml uses disk cache automatically
        xml = fetch_xml(tid)
        if not xml:
            fail.append(tid)
            print(f"  [{i + 1}/{len(todo)}] {tid} — no XML available")
            continue
        fields = parse_xml_fields(xml)
        if not fields:
            fail.append(tid)
            print(f"  [{i + 1}/{len(todo)}] {tid} — empty parse result")
            continue
        # Merge into relevant.json _raw._xml
        raw = n.get("_raw") or {}
        if not isinstance(raw, dict):
            raw = {}
        raw.setdefault("_xml", {}).update(fields)
        n["_raw"] = raw
        # Mirror into raw/details/{id}.json
        update_detail_file(detail_path_for(tid), fields)
        succ += 1
        if (i + 1) % 25 == 0:
            with open(RELEVANT_JSON, "w", encoding="utf-8") as fp:
                json.dump(rel, fp, ensure_ascii=False, indent=2)
            print(f"  …checkpoint {succ}/{i + 1} (failures so far: {len(fail)})")

    with open(RELEVANT_JSON, "w", encoding="utf-8") as fp:
        json.dump(rel, fp, ensure_ascii=False, indent=2)

    print()
    print("  Summary")
    print(f"    backfilled:  {succ}")
    print(f"    failures:    {len(fail)}{f'  ({fail[:5]} …)' if fail else ''}")
    print()
    print("  Field coverage (counted on relevant.json _raw._xml):")
    counts = {f: 0 for f in XML_FIELDS}
    total = 0
    for n in rel:
        if not is_ted(n):
            continue
        total += 1
        x = (n.get("_raw") or {}).get("_xml") or {}
        for f in XML_FIELDS:
            if x.get(f):
                counts[f] += 1
    for f in XML_FIELDS:
        pct = (100 * counts[f] / total) if total else 0.0
        print(f"    {f:30s} {counts[f]:>3} / {total}  ({pct:5.1f} %)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

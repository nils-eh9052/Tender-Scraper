"""
Doc-Coverage-Audit — Sprint 2026-05-10

Classifies every tender in relevant.json into one of four buckets:

  HAS_SPECS            — _extracted_specs present with ≥1 trailer type
  HAS_SPECS_LOW_CONF   — _extracted_specs present but confidence=0 or types=0
  NO_DOCS_AUTH_BLOCKED — discovery hardcoded to return [] (CZ, UK)
  NO_DOCS_NO_HANDLER   — source has no discovery handler (FR, NO, EE, NL, UA)
  TED_NO_SPECS         — TED tender, links field present, but extraction missing

Output:
  - console table by source × bucket
  - top-3 examples per bucket (for the markdown audit doc)

Usage:
    python3 scripts/_doc_coverage_audit.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEVANT = ROOT / "data" / "filtered" / "relevant.json"

# Sources where discovery.py explicitly returns []
_AUTH_BLOCKED = {"CZ-NEN", "UK-CF"}

# National sources with no document discovery handler at all
_NO_HANDLER = {"FR-BP", "NO-DF", "EE-RP", "NL-TN", "UA-PR", "LV-IUB",
               "DE-EB", "PL-NP", "FI-HI", "SE-UM", "DK-UD", "BE-EP",
               "ES-PL", "IT-AP", "RO-SE", "CH-SM", "TR-EK"}


def _specs_quality(specs: dict) -> str:
    """Return 'good', 'empty', or 'none'."""
    if not specs:
        return "none"
    types = specs.get("trailer_types", []) or []
    conf = specs.get("confidence", 0) or 0
    if types and conf > 0:
        return "good"
    return "empty"


def _classify(notice: dict) -> str:
    source = notice.get("source", notice.get("_source", "?"))
    specs = notice.get("_extracted_specs") or notice.get("extracted_specs")

    if specs:
        q = _specs_quality(specs)
        if q == "good":
            return "HAS_SPECS"
        return "HAS_SPECS_LOW_CONF"

    if source in _AUTH_BLOCKED:
        return "NO_DOCS_AUTH_BLOCKED"

    if source in _NO_HANDLER:
        return "NO_DOCS_NO_HANDLER"

    # TED notices (source=?) — should have links → extraction possible
    if source == "?":
        return "TED_NO_SPECS"

    # Unknown national source
    return "NO_DOCS_NO_HANDLER"


def _short_title(n: dict) -> str:
    t = (n.get("_title_final") or n.get("title") or n.get("_title_english") or "")[:60]
    return t.strip()


def main() -> None:
    with RELEVANT.open(encoding="utf-8") as f:
        notices = json.load(f)
    if isinstance(notices, dict):
        notices = notices.get("notices", [])

    # Classify
    buckets: dict[str, list[dict]] = defaultdict(list)
    source_bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for n in notices:
        src = n.get("source", n.get("_source", "?"))
        bucket = _classify(n)
        buckets[bucket].append(n)
        source_bucket[src][bucket] += 1

    total = len(notices)

    # ── Summary table ──────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"DOC-COVERAGE-AUDIT  —  {total} tenders total")
    print(f"{'='*70}")

    bucket_order = [
        "HAS_SPECS", "HAS_SPECS_LOW_CONF",
        "TED_NO_SPECS",
        "NO_DOCS_NO_HANDLER", "NO_DOCS_AUTH_BLOCKED",
    ]

    for bk in bucket_order:
        lst = buckets.get(bk, [])
        pct = len(lst) / total * 100 if total else 0
        print(f"  {bk:<26} {len(lst):>4}  ({pct:5.1f}%)")

    print(f"\n{'─'*70}")
    print(f"  {'Source':<14} {'Total':>6}  {'HAS_SPECS':>9}  {'LOW_CONF':>8}  "
          f"{'NO_HANDLER':>10}  {'AUTH_BLOCK':>10}  {'TED_MISS':>8}")
    print(f"{'─'*70}")

    for src in sorted(source_bucket):
        sb = source_bucket[src]
        row_total = sum(sb.values())
        print(f"  {src:<14} {row_total:>6}  "
              f"{sb.get('HAS_SPECS', 0):>9}  "
              f"{sb.get('HAS_SPECS_LOW_CONF', 0):>8}  "
              f"{sb.get('NO_DOCS_NO_HANDLER', 0):>10}  "
              f"{sb.get('NO_DOCS_AUTH_BLOCKED', 0):>10}  "
              f"{sb.get('TED_NO_SPECS', 0):>8}")

    # ── Examples per bucket ────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("TOP-3 EXAMPLES PER BUCKET")
    print(f"{'='*70}")

    for bk in bucket_order:
        lst = buckets.get(bk, [])
        if not lst:
            continue
        print(f"\n[{bk}]")
        for n in lst[:3]:
            src = n.get("source", n.get("_source", "?"))
            tid = n.get("tender_id", "")
            title = _short_title(n)
            specs = n.get("_extracted_specs") or {}
            conf = specs.get("confidence", "-") if specs else "-"
            print(f"  {tid:<35} src={src:<8} conf={conf} | {title}")

    # ── TED missing analysis ───────────────────────────────────────────────────
    ted_miss = buckets.get("TED_NO_SPECS", [])
    if ted_miss:
        print(f"\n{'='*70}")
        print(f"TED_NO_SPECS detail ({len(ted_miss)} tenders)")
        print(f"{'='*70}")
        for n in ted_miss:
            tid = n.get("tender_id", "")
            has_links = bool(n.get("links"))
            has_raw_links = bool((n.get("_raw") or {}).get("links"))
            pub_date = n.get("_pub_date") or n.get("_pub_date_clean", "")
            title = _short_title(n)
            link_info = "links=Y" if has_links else ("_raw.links=Y" if has_raw_links else "no_links")
            print(f"  {tid:<20} {link_info:<14} {pub_date}  {title[:50]}")

    print()


if __name__ == "__main__":
    main()

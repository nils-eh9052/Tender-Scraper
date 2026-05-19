"""
Sprint 2026-05-20 — Backfill `_published_at_source` marker on every notice
in data/filtered/relevant.json.

Background
==========
`published_at` in the frontend must show the **original tender start date**
(when the procurement was first publicly published). Several sources only
deliver post-award records, so the field carried the contract-notice
publication date instead. This script tags each record with a source
marker so we know whether the date is the real tender start or a fallback.

Rules
-----
- TED notices (numeric ``NNNNNN-YYYY``):
    * No award                            → ``tender_notice``
    * Award injected via award_matcher    → ``tender_notice``
      (record itself is the CN, the CAN was matched in)
    * Award winner present without match  → ``contract_notice_fallback``
      (record itself IS the CAN — original CN was not crawled)
- AusTender OCDS (``AU-CN…``)             → ``contract_notice_fallback``
  AusTender OCDS post-award feed has no ``tender.tenderPeriod`` /
  ``tender.publishedDate`` field. The au_ocds_adapter still tries those
  candidates first (defensive) — see ``_pick_publication_date``.
- CanadaBuys (``CA-…``)                   → ``tender_notice``
- UK FTS, CZ, FR, NO, EE                  → ``tender_notice``
- Anything else with a date                → ``tender_notice``
- No date at all                          → ``unknown``

The script does NOT change ``publication_date`` / ``_pub_date_clean``
itself — the existing values stay. It only adds the source marker so
the frontend export can keep emitting a sane date AND callers (audit,
backlog) can distinguish real tender-start dates from fallbacks.

Usage
-----
    python3 scripts/_backfill_publication_dates.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"

_TED_PAT = re.compile(r"^\d+-\d{4}$")


def _has_any_date(notice: dict) -> bool:
    for key in ("_pub_date", "_pub_date_clean", "publication_date"):
        v = notice.get(key)
        if v:
            return True
    raw = notice.get("_raw") or {}
    if isinstance(raw, dict) and raw.get("publication-date"):
        return True
    return False


def _classify(notice: dict) -> str:
    tid = str(notice.get("tender_id", ""))

    # TED ------------------------------------------------------------------
    if _TED_PAT.match(tid):
        award = notice.get("award") or {}
        is_self_can = (
            (award.get("awarded") or award.get("winner_name"))
            and not award.get("_from_award_match")
            and not award.get("_from_award_match_llm")
        )
        if is_self_can:
            return "contract_notice_fallback"
        return "tender_notice"

    # AusTender OCDS post-award --------------------------------------------
    if tid.startswith("AU-CN") or notice.get("_source") == "AU-TEN":
        return "contract_notice_fallback"

    # CanadaBuys -----------------------------------------------------------
    if tid.startswith("CA-"):
        return "tender_notice"

    # Other national adapters (UK-FTS, CZ, FR, NO, EE, NL, UA): the feeds
    # publish tender notices (pre-award), so the publication date is the
    # tender start. Records without ANY date land on `unknown`.
    if not _has_any_date(notice):
        return "unknown"
    return "tender_notice"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write changes back to disk")
    args = parser.parse_args()

    with RELEVANT_JSON.open(encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    counts: Counter = Counter()
    changed = 0
    for n in notices:
        marker = _classify(n)
        prev = n.get("_published_at_source")
        if prev != marker:
            changed += 1
        n["_published_at_source"] = marker
        counts[marker] += 1

    total = len(notices)
    print(f"\nBackfill scope: {total} notices")
    print(f"Updated marker on {changed} notices")
    print("\n_published_at_source distribution:")
    for marker, n in counts.most_common():
        pct = 100.0 * n / total
        print(f"  {marker:<28} {n:>4}   ({pct:5.1f} %)")

    if args.dry_run:
        print("\n[dry-run] not writing back to relevant.json")
        return

    with RELEVANT_JSON.open("w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)
    print(f"\nWritten back → {RELEVANT_JSON}")


if __name__ == "__main__":
    main()

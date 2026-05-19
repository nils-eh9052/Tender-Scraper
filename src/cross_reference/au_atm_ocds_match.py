"""
AU-ATM × AU-OCDS Cross-Reference (TEIL B)

PURPOSE
-------
AusTender's OCDS post-award feed (au_ocds_adapter, source=AU-TEN) never
carries the original tender publication date — only the contract-notice date
(post-award).  This sets ``_published_at_source = "contract_notice_fallback"``
on every AU-TEN notice, making the ``publication_date`` field unreliable for
time-to-award and pipeline-age analysis.

The pre-award ATM feed (au_atm_adapter, source=AU-AT) contains the *actual*
tender publication dates.  Matching AU-TEN post-award records to AU-ATM
pre-award records lets us upgrade ``_published_at_source`` from
``contract_notice_fallback`` to ``related_lookup`` and fill in the real
tender date.

MATCH STRATEGY
--------------
AusTender's ATM reference numbers (e.g. ``GA2026/564``) appear in OCDS
``contracts[0].description`` or ``releases.contracts[0].id`` for some
contracts — but coverage is patchy.  We use three match keys in priority order:

  1. **ATM reference number substring** — look for the ATM ref in the OCDS
     contract description or title.  High precision, low recall.
  2. **Buyer name + title word-overlap** — normalise buyer name and split
     title into tokens; require ≥ 3 overlapping non-stopword tokens AND
     matching buyer.  Medium precision, medium recall.
  3. **Buyer + UNSPSC + date proximity** — same buyer, same 4-digit UNSPSC
     prefix, ATM close date within ±180 days of OCDS contract date.
     Lower precision; use as soft signal only.

RESULT FIELDS
-------------
Matched AU-TEN notice gets:
  ``_atm_ref``              AU-ATM reference number (e.g. "ATM/2024/1234")
  ``_atm_pub_date``         ATM publish date (ISO YYYY-MM-DD) — becomes the
                            new ``publication_date`` in frontend export
  ``_atm_close_date``       ATM closing date (for time-to-award calculation)
  ``_published_at_source``  Upgraded to "related_lookup"

USAGE
-----
Standalone cross-reference run on a loaded relevant.json:

    from src.cross_reference.au_atm_ocds_match import cross_reference_au

    # atm_records: list[dict] loaded from ATM adapter run or disk cache
    # ocds_notices: list[dict] — AU-TEN entries from relevant.json
    updated = cross_reference_au(ocds_notices, atm_records)
    # updated is the same list, with matched entries enriched in-place

Or via main.py (Window F):
    python main.py --cross-ref-au

CACHE
-----
``data/.au_atm_match_cache.json`` — keyed by OCDS tender_id.
Entries survive relevvant.json re-runs; re-matched on `--force` or if the
ATM record has changed (detected by atm_ref change).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_PATH = _ROOT / "data" / ".au_atm_match_cache.json"

# ── Stopwords excluded from title token overlap ───────────────────────────────

_STOPWORDS = frozenset([
    "a", "an", "the", "of", "in", "for", "to", "and", "or", "with",
    "by", "at", "on", "is", "be", "are", "was", "were", "as", "from",
    "supply", "supplies", "provision", "procurement", "services",
    "contract", "purchase", "acquisition",
    "defence", "defense", "military", "australian", "australia",
])

# Maximum days between ATM close date and OCDS contract date for proximity match
_PROXIMITY_DAYS_MAX = 180


# ── Text normalisation ────────────────────────────────────────────────────────

def _normalise_buyer(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _title_tokens(title: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z0-9]+", (title or "").lower())
    return frozenset(t for t in tokens if t not in _STOPWORDS and len(t) > 2)


def _iso_date_to_days(date_str: str) -> Optional[int]:
    """Convert ISO YYYY-MM-DD to days since epoch (for proximity arithmetic)."""
    if not date_str:
        return None
    try:
        from datetime import date
        d = date.fromisoformat(date_str)
        return (d - date(2000, 1, 1)).days
    except ValueError:
        return None


# ── ATM record helpers ────────────────────────────────────────────────────────

def _atm_ref(atm: dict) -> str:
    """Extract ATM reference number (e.g. 'ATM/2024/1234' or 'LAND121/2025')."""
    return (
        atm.get("reference_id")
        or atm.get("atm_id")
        or atm.get("_reference_id")
        or ""
    ).strip()


def _atm_pub_date(atm: dict) -> str:
    return (atm.get("_pub_date_clean") or atm.get("publication_date") or "").strip()[:10]


def _atm_close_date(atm: dict) -> str:
    return (
        atm.get("submission_deadline")
        or atm.get("_closing_date")
        or atm.get("deadline")
        or ""
    ).strip()[:10]


def _atm_buyer(atm: dict) -> str:
    return _normalise_buyer(atm.get("_authority_name") or atm.get("authority") or "")


def _atm_unspsc(atm: dict) -> str:
    """Return first 4-digit UNSPSC prefix from ATM record."""
    raw = (atm.get("_national_raw_text") or "")
    m = re.search(r"UNSPSC:\s*(\d{4,8})", raw, re.IGNORECASE)
    if m:
        return m.group(1)[:4]
    return ""


def _atm_title_tokens(atm: dict) -> frozenset[str]:
    title = atm.get("_title_final") or atm.get("title") or ""
    return _title_tokens(title)


# ── OCDS notice helpers ───────────────────────────────────────────────────────

def _ocds_buyer(n: dict) -> str:
    return _normalise_buyer(
        n.get("_authority_name_structured")
        or n.get("_authority_name")
        or ""
    )


def _ocds_contract_date(n: dict) -> str:
    return (
        n.get("_pub_date_clean")
        or n.get("_pub_date")
        or n.get("publication_date")
        or ""
    ).strip()[:10]


def _ocds_title_tokens(n: dict) -> frozenset[str]:
    title = n.get("title_en") or n.get("_title_final") or ""
    return _title_tokens(title)


def _ocds_unspsc(n: dict) -> str:
    raw = n.get("_national_raw_text") or ""
    m = re.search(r"UNSPSC:\s*(\d{4,8})", raw, re.IGNORECASE)
    if m:
        return m.group(1)[:4]
    return ""


def _ocds_description(n: dict) -> str:
    return (n.get("_description_final") or n.get("_title_final") or "").lower()


# ── Match strategies ──────────────────────────────────────────────────────────

def _match_atm_ref_in_ocds(ocds_desc: str, atm_ref_str: str) -> bool:
    """Strategy 1: ATM reference appears in OCDS description/title."""
    if not atm_ref_str:
        return False
    # Normalise slash separators (ATM/2024/1234 vs ATM-2024-1234)
    ref_clean = re.sub(r"[/_-]", "", atm_ref_str.lower())
    desc_clean = re.sub(r"[/_-]", "", ocds_desc)
    return len(ref_clean) >= 6 and ref_clean in desc_clean


def _match_buyer_title(
    ocds_buyer: str, ocds_tokens: frozenset,
    atm_buyer: str, atm_tokens: frozenset,
    min_overlap: int = 3,
) -> bool:
    """Strategy 2: Same buyer + title token overlap ≥ min_overlap."""
    if not ocds_buyer or not atm_buyer:
        return False
    # Require at least one major buyer word to match
    buyer_match = any(
        word in atm_buyer for word in ocds_buyer.split()
        if len(word) > 4 and word not in _STOPWORDS
    )
    if not buyer_match:
        return False
    overlap = len(ocds_tokens & atm_tokens)
    return overlap >= min_overlap


def _match_buyer_unspsc_date(
    ocds_buyer: str, ocds_unspsc: str, ocds_date_days: Optional[int],
    atm_buyer: str, atm_unspsc: str, atm_close_days: Optional[int],
) -> bool:
    """Strategy 3: Same buyer + UNSPSC + date proximity."""
    if not ocds_buyer or not atm_buyer:
        return False
    if not any(w in atm_buyer for w in ocds_buyer.split() if len(w) > 4):
        return False
    if ocds_unspsc and atm_unspsc and ocds_unspsc != atm_unspsc:
        return False
    if ocds_date_days is not None and atm_close_days is not None:
        if abs(ocds_date_days - atm_close_days) > _PROXIMITY_DAYS_MAX:
            return False
    return True


# ── Main cross-reference function ─────────────────────────────────────────────

def cross_reference_au(
    ocds_notices: list[dict],
    atm_records: list[dict],
    *,
    force: bool = False,
) -> dict[str, str]:
    """Match AU-TEN OCDS post-award notices to AU-ATM pre-award records.

    Mutates matched OCDS notices in-place, adding:
      ``_atm_ref``, ``_atm_pub_date``, ``_atm_close_date``,
      ``_published_at_source`` (upgraded to "related_lookup").

    Returns a stats dict with match counts.

    Args:
        ocds_notices:  All notices from relevant.json (function filters to AU-TEN).
        atm_records:   AU-AT notices (from separate ATM adapter run or disk cache).
        force:         Re-match even if cached entry exists.
    """
    cache = _load_cache()

    au_ten = [
        n for n in ocds_notices
        if n.get("_source") == "AU-TEN"
        or str(n.get("tender_id", "")).startswith("AU-CN")  # OCDS contract-notice IDs
    ]
    logger.info("AU cross-ref: %d AU-TEN notices, %d ATM records", len(au_ten), len(atm_records))

    if not au_ten or not atm_records:
        logger.warning("AU cross-ref: nothing to match (empty input)")
        return {"total_ocds": len(au_ten), "matched": 0, "skipped_cached": 0}

    # Pre-compute ATM index structures
    atm_by_ref: dict[str, dict] = {}
    for atm in atm_records:
        ref = _atm_ref(atm)
        if ref:
            atm_by_ref[ref.lower()] = atm

    # List of (atm, atm_buyer, atm_tokens, atm_close_days, atm_unspsc) for bulk match
    atm_precomputed = []
    for atm in atm_records:
        ref = _atm_ref(atm)
        buyer = _atm_buyer(atm)
        tokens = _atm_title_tokens(atm)
        close_days = _iso_date_to_days(_atm_close_date(atm))
        unspsc = _atm_unspsc(atm)
        atm_precomputed.append((atm, ref, buyer, tokens, close_days, unspsc))

    stats = {"total_ocds": len(au_ten), "matched": 0, "skipped_cached": 0,
             "strat1": 0, "strat2": 0, "strat3": 0}

    for n in au_ten:
        tid = n.get("tender_id", "")

        # Skip if already matched and not forcing
        if not force and tid in cache:
            cached = cache[tid]
            if cached.get("_atm_ref"):
                n.update({k: v for k, v in cached.items() if k.startswith("_atm")})
                n["_published_at_source"] = "related_lookup"
                stats["skipped_cached"] += 1
                continue

        # Skip if already has a real date (not fallback)
        if n.get("_published_at_source") not in (None, "contract_notice_fallback", ""):
            continue

        ocds_buyer = _ocds_buyer(n)
        ocds_tokens = _ocds_title_tokens(n)
        ocds_desc = _ocds_description(n)
        ocds_date_days = _iso_date_to_days(_ocds_contract_date(n))
        ocds_unspsc = _ocds_unspsc(n)

        match_atm: Optional[dict] = None
        strategy_used = ""

        for atm, ref, buyer, tokens, close_days, unspsc in atm_precomputed:
            # Strategy 1 — ATM ref in OCDS description
            if _match_atm_ref_in_ocds(ocds_desc, ref):
                match_atm = atm
                strategy_used = "strat1"
                break

            # Strategy 2 — buyer + title overlap
            if _match_buyer_title(ocds_buyer, ocds_tokens, buyer, tokens):
                match_atm = atm
                strategy_used = "strat2"
                # Don't break — prefer strat1 if we find it later; but strat2
                # match could be false positive so keep looking for strat1.
                # We store first strat2 hit and continue.
                # (If a strat1 hit is found later the break will override.)
                continue  # allow strat1 to override

            # Strategy 3 — buyer + UNSPSC + proximity (soft signal; only if
            # strat1/2 not yet found)
            if not match_atm:
                if _match_buyer_unspsc_date(
                    ocds_buyer, ocds_unspsc, ocds_date_days,
                    buyer, unspsc, close_days
                ):
                    match_atm = atm
                    strategy_used = "strat3"

        if match_atm:
            pub_date = _atm_pub_date(match_atm)
            close_date = _atm_close_date(match_atm)
            ref_str = _atm_ref(match_atm)

            n["_atm_ref"] = ref_str
            n["_atm_pub_date"] = pub_date
            n["_atm_close_date"] = close_date
            n["_published_at_source"] = "related_lookup"

            # Store in cache
            cache[tid] = {
                "_atm_ref": ref_str,
                "_atm_pub_date": pub_date,
                "_atm_close_date": close_date,
                "_match_strategy": strategy_used,
            }
            stats["matched"] += 1
            stats[strategy_used] = stats.get(strategy_used, 0) + 1
            logger.debug("AU cross-ref: matched %s → %s (%s)", tid, ref_str, strategy_used)

    _save_cache(cache)
    logger.info(
        "AU cross-ref: %d/%d AU-TEN matched (strat1=%d strat2=%d strat3=%d, cached=%d)",
        stats["matched"], len(au_ten),
        stats.get("strat1", 0), stats.get("strat2", 0), stats.get("strat3", 0),
        stats["skipped_cached"],
    )
    return stats


# ── Backfill helper ───────────────────────────────────────────────────────────

def backfill_published_at_source(notices: list[dict]) -> int:
    """Rule-based backfill of ``_published_at_source`` for notices that lack it.

    Rules (applied to any source where the field is None / missing):
      CA-CB       → "tender_notice" (CanadaBuys publicationDate = RFP go-live)
      AU-TEN      → "contract_notice_fallback" (no pre-award date in OCDS)
      UK-FTS/CF   → "tender_notice"
      CZ-NEN      → "tender_notice"
      FR-BP       → "tender_notice"
      NO-DFF      → "tender_notice"
      UA-PZ       → "tender_notice"
      NL-TN       → "tender_notice"
      EE-RP       → "tender_notice"
      TED (numeric ids) → rule-based on notice-type / _raw fields:
        - CAN / Contract Award Notice → "contract_notice_fallback" (post-award)
        - PIN → "pin_notice"
        - CN  → "tender_notice"

    Returns count of notices updated.
    """
    import re as _re

    _TED_PATTERN = _re.compile(r"^\d+-\d{4}$")

    updated = 0
    for n in notices:
        existing = n.get("_published_at_source")
        if existing and existing != "unknown":
            continue  # already set to a meaningful value

        tid = str(n.get("tender_id", ""))

        if tid.startswith("CA-"):
            n["_published_at_source"] = "tender_notice"
        elif tid.startswith("AU-CN"):
            # OCDS post-award feed — no original tender date available
            n["_published_at_source"] = "contract_notice_fallback"
        elif tid.startswith("AU-"):
            # ATM pre-award notices — publication_date is the real tender go-live
            n["_published_at_source"] = "tender_notice"
        elif tid.startswith("UK-"):
            # UK-FTS, UK-CF, and legacy UK-tender_* formats
            n["_published_at_source"] = "tender_notice"
        elif tid.startswith(("CZ-", "FR-", "NO-", "UA-", "NL-", "EE-", "NATO-")):
            n["_published_at_source"] = "tender_notice"
        elif _TED_PATTERN.match(tid):
            raw = n.get("_raw") or {}
            ntype = ""
            if isinstance(raw, dict):
                ntype = str(raw.get("notice-type") or raw.get("form-type") or "").lower()
            if "award" in ntype or "can" in ntype or "result" in ntype:
                n["_published_at_source"] = "contract_notice_fallback"
            elif "prior" in ntype or "pin" in ntype:
                n["_published_at_source"] = "pin_notice"
            else:
                n["_published_at_source"] = "tender_notice"
        else:
            n["_published_at_source"] = "unknown"

        updated += 1

    logger.info("backfill_published_at_source: %d notices updated", updated)
    return updated


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> int:
    """Standalone run: cross-reference AU-TEN vs AU-ATM in relevant.json.

    Requires AU-ATM records to be present in relevant.json (source=AU-AT)
    OR in a separate dump specified by --atm-file.

    Usage:
        python -m src.cross_reference.au_atm_ocds_match [--force] [--atm-file PATH]
    """
    import argparse

    p = argparse.ArgumentParser(description="AU-ATM × AU-OCDS cross-reference")
    p.add_argument("--force", action="store_true", help="Re-match cached entries")
    p.add_argument(
        "--atm-file", type=Path, default=None,
        help="Path to JSON file containing AU-ATM records (default: use relevant.json)"
    )
    p.add_argument(
        "--backfill-only", action="store_true",
        help="Only run backfill_published_at_source (no ATM matching)"
    )
    args = p.parse_args()

    rel_path = _ROOT / "data" / "filtered" / "relevant.json"
    notices: list[dict] = json.loads(rel_path.read_text(encoding="utf-8"))

    if args.backfill_only:
        n = backfill_published_at_source(notices)
        rel_path.write_text(json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Backfilled _published_at_source for {n} notices → {rel_path}")
        return 0

    # Load ATM records
    if args.atm_file:
        atm_records: list[dict] = json.loads(Path(args.atm_file).read_text(encoding="utf-8"))
    else:
        # Use AU-AT notices already in relevant.json (adapter sets "source", not "_source")
        atm_records = [
            n for n in notices
            if n.get("_source") == "AU-AT" or n.get("source") == "AU-AT"
        ]

    if not atm_records:
        print("[WARN] No AU-AT records found. Run au_atm_adapter first or pass --atm-file.")
        print("       Running backfill_published_at_source only...")
        backfill_published_at_source(notices)
    else:
        stats = cross_reference_au(notices, atm_records, force=args.force)
        print(f"[OK] AU cross-ref: {stats}")
        backfill_published_at_source(notices)

    rel_path.write_text(json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Wrote updated relevant.json → {rel_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

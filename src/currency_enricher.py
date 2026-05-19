"""
Description currency enrichment — Sprint 2026-05-09.

Goal
----
Whenever a tender description mentions a non-EUR amount with currency code
(e.g. ``"123,293.66 CZK"``), append a EUR equivalent in parentheses
(``"123,293.66 CZK (~€4.9K)"``). Pure regex + dictionary FX, no LLM calls.

Strategy
--------
* Regex scans the description for ``<number><optional space><currency>``.
* ``_parse_amount()`` normalises EU/EN/FR thousand-separator and decimal
  conventions to a single Python float.
* FX rates are imported from ``src.exporter_frontend._FX``; this module
  never mutates that dict (additive only when a missing currency is added,
  via a local extension if needed).
* Cache key: tender_id + sha1 of source description. Re-runs hit the cache
  whenever the description hasn't changed.
* Idempotent: an already-enriched description (containing ``"(~€"``)
  passes through unchanged.

Cache schema
------------
``data/.description_enrich_cache.json``::

    {
      "<tender_id>": {
        "hash":           "<sha1 of source description>",
        "enriched":       "<resulting text>",
        "matches":        int,
        "ts":             "2026-05-09 10:00:00"
      }
    }
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DESCRIPTION_CACHE_PATH = (
    Path(__file__).parent.parent / "data" / ".description_enrich_cache.json"
)

# Currencies the enricher recognises. Must be a superset of FX keys in
# exporter_frontend._FX. Codes the FX dict cannot price are silently
# left untouched in the description.
_SUPPORTED = (
    "CZK", "PLN", "UAH", "NOK", "SEK", "DKK", "HUF", "RON", "BGN",
    "GBP", "CHF", "TRY", "USD", "JPY", "CNY",
)

# Pattern: number with thousand separators (comma, dot, whitespace) and
# optional decimal, followed by an ISO currency code (case-insensitive).
# Boundary lookarounds keep us out of word-internals (no matching
# "abc123CZKxyz").
AMOUNT_PATTERN = re.compile(
    r'(?<![\w\d])'  # left boundary: not in a word/number
    r'(\d{1,3}(?:[,.\s ]\d{3})*(?:[,.]\d{1,4})?)'  # number with sep
    r'\s*'
    r'(' + '|'.join(_SUPPORTED) + r')'
    r'(?![A-Za-z])',  # right boundary: not followed by another letter
    re.IGNORECASE,
)


def _parse_amount(text: str) -> Optional[float]:
    """Robust amount parser.

    Handles:
        ``123,293.66``      → 123293.66  (EN)
        ``123.293,66``      → 123293.66  (EU)
        ``123 293,66``      → 123293.66  (FR / NBSP)
        ``39999.99``        → 39999.99
        ``1,234``           → 1234.0     (ambiguous; treated as thousands)
        ``1,23``            → 1.23       (ambiguous; treated as decimal)
        ``20,800,000``      → 20800000.0
        ``20.800.000``      → 20800000.0

    Returns ``None`` on parse failure.
    """
    if not text:
        return None
    # Strip spaces (incl. NBSP)
    s = text.strip().replace(" ", "").replace(" ", "")
    if not s:
        return None

    if "," in s and "." in s:
        # Whichever separator appears LAST is the decimal mark.
        if s.rfind(",") > s.rfind("."):
            # EU: 1.234,56 → 1234.56
            s = s.replace(".", "").replace(",", ".")
        else:
            # EN: 1,234.56 → 1234.56
            s = s.replace(",", "")
    elif "," in s:
        # Ambiguous. Heuristic: "1,234" with exactly 3 digits after comma
        # → likely a thousand-separator. Otherwise → decimal.
        parts = s.split(",")
        if all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")
        elif len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        # Ambiguous as well. ``"20.800.000"`` (3-digit groups) → thousand
        # separator. ``"39999.99"`` (≤2 trailing digits) → decimal.
        parts = s.split(".")
        if len(parts) > 2 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")
        # else: leave the single dot as decimal.

    try:
        return float(s)
    except ValueError:
        return None


def _format_eur(amount: float) -> str:
    """Format an EUR amount with thousand-units (K / M)."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"{amount / 1_000:.1f}K"
    return f"{amount:.0f}"


def enrich_description(text: str, fx_rates: dict[str, float]) -> tuple[str, int]:
    """Append EUR equivalents to currency mentions in ``text``.

    Returns ``(enriched_text, num_matches_enriched)``. Idempotent:
    text that already contains an enrichment marker for a particular
    occurrence is left untouched there. Out-of-range conversions
    (< €1 or > €10 B) are skipped to avoid noise from typos / placeholders.
    """
    if not text:
        return text, 0

    counter = {"n": 0}

    def _replacer(match: re.Match) -> str:
        full = match.group(0)
        # Idempotency: if the very next characters already contain an
        # enrichment, leave this occurrence alone.
        end = match.end()
        suffix = text[end:end + 5]
        if suffix.lstrip().startswith("(~€"):
            return full

        amount_str = match.group(1)
        currency = match.group(2).upper()
        amount = _parse_amount(amount_str)
        if amount is None or currency not in fx_rates:
            return full
        rate = fx_rates[currency]
        if rate <= 0:
            return full
        eur = amount * rate
        if eur < 1 or eur > 1e10:
            return full

        counter["n"] += 1
        return f"{full} (~€{_format_eur(eur)})"

    enriched = AMOUNT_PATTERN.sub(_replacer, text)
    return enriched, counter["n"]


# ───────────────────────────────────────────────────────────────────
# Cache helpers + top-level entry
# ───────────────────────────────────────────────────────────────────

def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _source_description(notice: dict) -> str:
    """Pick the best non-empty description string from a notice."""
    for f in ("_description_final", "_description_english", "description"):
        v = notice.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for lang in ("eng", "en"):
                val = v.get(lang)
                if val:
                    if isinstance(val, list):
                        val = next((x for x in val if x), "")
                    if val:
                        return str(val).strip()
            for val in v.values():
                if isinstance(val, list):
                    val = next((x for x in val if x), "")
                if val:
                    return str(val).strip()
    return ""


def enrich_all(
    relevant_path: str | Path,
    *,
    cache_path: str | Path = DESCRIPTION_CACHE_PATH,
    fx_rates: Optional[dict[str, float]] = None,
    target_ids: Optional[list[str]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Iterate ``relevant.json``, enrich descriptions in-place.

    For each notice, set ``description_enriched`` to the EUR-augmented
    text. The original description fields stay untouched (audit trail).

    Args:
        relevant_path: Path to ``data/filtered/relevant.json``.
        cache_path: Path to the description-enrich cache.
        fx_rates: FX dict (default: ``exporter_frontend._FX``).
        target_ids: Restrict to these tender ids (smoke testing).
        dry_run: Compute matches but do not write back to file.

    Returns: summary dict.
    """
    relevant_path = Path(relevant_path)
    cache_path = Path(cache_path)

    # Late import to avoid circular dep when classifier imports translator etc.
    if fx_rates is None:
        from src.exporter_frontend import _FX as fx_rates  # type: ignore

    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    cache = _load_cache(cache_path)

    summary: dict[str, Any] = {
        "total":               len(notices),
        "evaluated":           0,
        "skipped_no_desc":     0,
        "skipped_no_currency": 0,
        "from_cache":          0,
        "enriched_now":        0,
        "match_count_total":   0,
        "samples":             [],   # first 5 (id, before, after)
    }

    target_set: Optional[set[str]] = (
        set(target_ids) if target_ids is not None else None
    )

    for notice in notices:
        tid = notice.get("tender_id")
        if not tid:
            continue
        if target_set is not None and tid not in target_set:
            continue
        summary["evaluated"] += 1

        desc = _source_description(notice)
        if not desc:
            summary["skipped_no_desc"] += 1
            continue

        h = _hash_text(desc)
        cached = cache.get(tid)
        if cached and cached.get("hash") == h:
            enriched = cached.get("enriched", desc)
            matches = int(cached.get("matches", 0))
            notice["description_enriched"] = enriched
            summary["from_cache"] += 1
            summary["match_count_total"] += matches
            continue

        enriched, matches = enrich_description(desc, fx_rates)
        if matches == 0:
            # Cache the no-match decision too — saves the regex-pass next time.
            cache[tid] = {
                "hash":     h,
                "enriched": desc,
                "matches":  0,
                "ts":       time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            summary["skipped_no_currency"] += 1
            continue

        cache[tid] = {
            "hash":     h,
            "enriched": enriched,
            "matches":  matches,
            "ts":       time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        notice["description_enriched"] = enriched
        summary["enriched_now"] += 1
        summary["match_count_total"] += matches
        if len(summary["samples"]) < 5:
            summary["samples"].append({
                "id":       tid,
                "before":   desc[:240],
                "after":    enriched[:280],
                "matches":  matches,
            })

    if not dry_run:
        _save_cache(cache_path, cache)
        # Backfill description_enriched from cache for notices we didn't
        # touch this run (target_ids subset) so the field is always present.
        for notice in notices:
            if "description_enriched" in notice:
                continue
            tid = notice.get("tender_id")
            cached = cache.get(tid) if tid else None
            if cached and cached.get("enriched"):
                notice["description_enriched"] = cached["enriched"]
        with open(relevant_path, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)

    return summary

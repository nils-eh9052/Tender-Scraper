"""Count tenders per adapter from relevant.json.

Reads data/filtered/relevant.json and computes, for each adapter key:
  - tender_count   — number of notices attributed to this adapter
  - newest_pub_date — ISO date of the most recent publication
  - oldest_pub_date — ISO date of the oldest publication

The adapter is determined from the tender_id prefix using the SOURCE_PREFIX
mapping defined in the spec. TED notices are those whose tender_id begins
with a digit (no national prefix).

pub_date is taken from _pub_date, _pub_date_clean, or publication_date —
whichever is first non-None (only the YYYY-MM-DD portion is kept).
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from src.health_monitor import PROJECT_ROOT

RELEVANT_JSON: Path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"

# Source-prefix → adapter key mapping (matches parser.py / spec)
_PREFIX_TO_ADAPTER: list[tuple[str, str]] = [
    ("CA-CB",    "ca"),
    ("CA-cb",    "ca"),
    ("AU-TEN",   "au"),
    ("AU-AT",    "au-atm"),
    ("CZ-NEN",   "cz"),
    ("CZ-N006",  "cz"),
    ("FR-BP",    "fr"),
    ("FR-",      "fr"),
    ("UK-CF",    "gb"),
    ("UK-tender","gb"),
    ("UK-RQ",    "gb"),
    ("NO-",      "no"),
    ("EE-RP",    "ee"),
    ("NL-",      "nl"),
    ("UA-",      "ua"),
    ("NSPA-EP",  "nspa"),
    ("NATO-",    "nspa"),
]

# Regex: tender_id starts with a digit → TED
_RE_TED_ID = re.compile(r"^\d")


def _adapter_from_tender_id(tender_id: str) -> str:
    """Infer adapter key from a tender_id string."""
    if _RE_TED_ID.match(tender_id):
        return "ted"
    for prefix, adapter in _PREFIX_TO_ADAPTER:
        if tender_id.startswith(prefix):
            return adapter
    return "unknown"


def _adapter_from_source(source: Optional[str], tender_id: str) -> str:
    """Infer adapter key from _source field, falling back to tender_id."""
    if source:
        for prefix, adapter in _PREFIX_TO_ADAPTER:
            if source.startswith(prefix):
                return adapter
    return _adapter_from_tender_id(tender_id)


def _parse_pub_date(raw: Optional[str]) -> Optional[str]:
    """Extract the ISO date portion (YYYY-MM-DD) from a raw date string."""
    if not raw:
        return None
    candidate = str(raw)[:10]
    try:
        date.fromisoformat(candidate)
        return candidate
    except ValueError:
        return None


def compute_counts(relevant_json_path: Path = RELEVANT_JSON) -> dict[str, dict]:
    """Load relevant.json and compute per-adapter counts and date ranges.

    Returns:
        dict mapping adapter_key → {
            "tender_count": int,
            "newest_pub_date": str | None,
            "oldest_pub_date": str | None,
        }
    """
    if not relevant_json_path.exists():
        return {}

    with relevant_json_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        return {}

    # Separate count tracking from date tracking so we never miss tenders
    # that lack a publication date.
    per_adapter_counts: dict[str, int] = {}
    per_adapter_dates: dict[str, list[str]] = {}

    for item in data:
        if not isinstance(item, dict):
            continue
        tender_id = item.get("tender_id", "")
        source = item.get("_source") or None
        adapter = _adapter_from_source(source, tender_id)

        per_adapter_counts[adapter] = per_adapter_counts.get(adapter, 0) + 1

        # Try multiple date fields in priority order
        raw_date = (
            item.get("_pub_date")
            or item.get("_pub_date_clean")
            or item.get("publication_date")
        )
        parsed = _parse_pub_date(raw_date)
        if parsed:
            per_adapter_dates.setdefault(adapter, []).append(parsed)

    result: dict[str, dict] = {}
    for adapter, count in per_adapter_counts.items():
        dates = per_adapter_dates.get(adapter, [])
        result[adapter] = {
            "tender_count": count,
            "newest_pub_date": max(dates) if dates else None,
            "oldest_pub_date": min(dates) if dates else None,
        }

    return result

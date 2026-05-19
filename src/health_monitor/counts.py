"""Count tenders per adapter from relevant.json.

Reads data/filtered/relevant.json and computes, for each adapter key:
  - tender_count   — number of notices attributed to this adapter
  - newest_pub_date — ISO date of the most recent publication
  - oldest_pub_date — ISO date of the oldest publication

The adapter is determined from the tender_id prefix using the SOURCE_PREFIX
mapping defined in the spec. TED notices are those whose tender_id begins
with a digit (no national prefix).

pub_date is taken from the "_pub_date" field first, then "publication_date"
(which may carry timezone info — only the date part is kept).
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
    ("CA-cb",    "ca"),
    ("CA-CB",    "ca"),
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
    # Unknown prefix — return "unknown"
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
    # Take only the first 10 chars (handles "2024-09-15+02:00", "2024-09-15Z", etc.)
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

    per_adapter: dict[str, list[str]] = {}  # adapter → list of pub_dates

    for item in data:
        if not isinstance(item, dict):
            continue
        tender_id = item.get("tender_id", "")
        source = item.get("_source")
        adapter = _adapter_from_source(source, tender_id)

        if adapter not in per_adapter:
            per_adapter[adapter] = []

        # Try _pub_date first, then publication_date
        raw_date = item.get("_pub_date") or item.get("publication_date")
        parsed = _parse_pub_date(raw_date)
        if parsed:
            per_adapter[adapter].append(parsed)

    result: dict[str, dict] = {}
    for adapter, dates in per_adapter.items():
        result[adapter] = {
            "tender_count": len(dates),
            "newest_pub_date": max(dates) if dates else None,
            "oldest_pub_date": min(dates) if dates else None,
        }

    return result

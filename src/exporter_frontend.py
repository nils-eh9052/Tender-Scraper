"""
Frontend JSON exporter: data/filtered/relevant.json → shared/tenders.json

Writes Tender objects compatible with the defence-intel-web frontend schema.
Does NOT touch pipeline logic, filter engine, or existing exporter.py.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# iso3 → (iso2, full_name)
_ISO3: dict[str, tuple[str, str]] = {
    "DEU": ("DE", "Germany"),    "FRA": ("FR", "France"),
    "POL": ("PL", "Poland"),     "ROU": ("RO", "Romania"),
    "CZE": ("CZ", "Czech Republic"), "DNK": ("DK", "Denmark"),
    "SWE": ("SE", "Sweden"),     "NLD": ("NL", "Netherlands"),
    "IRL": ("IE", "Ireland"),    "BEL": ("BE", "Belgium"),
    "ESP": ("ES", "Spain"),      "ITA": ("IT", "Italy"),
    "AUT": ("AT", "Austria"),    "CHE": ("CH", "Switzerland"),
    "LUX": ("LU", "Luxembourg"), "SVN": ("SI", "Slovenia"),
    "NOR": ("NO", "Norway"),     "MKD": ("MK", "North Macedonia"),
    "SVK": ("SK", "Slovakia"),   "GBR": ("GB", "United Kingdom"),
    "FIN": ("FI", "Finland"),    "HRV": ("HR", "Croatia"),
    "LTU": ("LT", "Lithuania"),  "EST": ("EE", "Estonia"),
    "BGR": ("BG", "Bulgaria"),   "HUN": ("HU", "Hungary"),
    "PRT": ("PT", "Portugal"),   "GRC": ("GR", "Greece"),
    "LVA": ("LV", "Latvia"),     "MLT": ("MT", "Malta"),
    "CYP": ("CY", "Cyprus"),     "UKR": ("UA", "Ukraine"),
    "TUR": ("TR", "Turkey"),     "CAN": ("CA", "Canada"),
    "USA": ("US", "United States"), "AUS": ("AU", "Australia"),
}

# full_name → iso2 (derived from _ISO3)
# full_name → iso2 (derived from _ISO3, plus common aliases)
_NAME_TO_ISO2: dict[str, str] = {name: iso2 for _, (iso2, name) in _ISO3.items()}
_NAME_TO_ISO2.update({
    "Czechia": "CZ",
    "UK": "GB",
    "NATO": "XN",  # pseudo-code for NATO/NSPA notices (not ISO 3166-1)
})

_FX: dict[str, float] = {
    "EUR": 1.0,   "DKK": 0.134, "SEK": 0.087, "PLN": 0.233,
    "CZK": 0.040, "RON": 0.201, "NOK": 0.085, "GBP": 1.17,
    "CHF": 1.06,  "HRK": 0.133, "BGN": 0.511, "HUF": 0.0025,
    "UAH": 0.023, "CAD": 0.68,  "AUD": 0.60,
}

_TED_PATTERN = re.compile(r"^\d+-\d{4}$")

_DATA_DIR = Path(__file__).parent.parent / "data"
_FIRST_SEEN_STATE_PATH = _DATA_DIR / ".first_seen_state.json"
_BACKFILL_TS = "2026-05-04T10:00:00Z"


def _format_tender_id(tender_id: str, country_code: str) -> str:
    """Defensive ID normalisation when emitting to ``shared/tenders.json``.

    Three rules applied in order:

    1. **TED-style numeric IDs** (``572650-2024``) are passed through unchanged
       — TED has its own ID space, no country prefix is wanted there.
    2. **Duplicate country-code prefix** (``UA-UA-...``, ``NL-NL-...``) is
       stripped to a single prefix. Sprint 14c already fixed this in
       ``base_adapter.py:to_standard_format``, so any leftover doubles in
       ``relevant.json`` are pre-Sprint-14c residue.
    3. **Missing country-code prefix** on a national-shaped ID
       (``2026-04-08-011067-a``) gets the prefix prepended so the frontend
       has a stable namespace.

    Idempotent on already-correct inputs (``UA-2026-...`` stays unchanged).
    """
    if not tender_id or not country_code:
        return tender_id
    # 1) TED-style → never touch
    if _TED_PATTERN.match(tender_id):
        return tender_id
    cc_prefix = f"{country_code}-"
    double_prefix = f"{cc_prefix}{cc_prefix}"
    # 2) Strip exactly one excess prefix when doubled
    if tender_id.startswith(double_prefix):
        return tender_id[len(cc_prefix):]
    # 3) Add prefix if missing entirely
    if not tender_id.startswith(cc_prefix):
        return f"{cc_prefix}{tender_id}"
    return tender_id
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(month|year|week|day)s?", re.IGNORECASE)
_TZ_SUFFIX = re.compile(r"[Z+][0-9:+]*$")

# TED API prepends "<Country> - " or "<Country> Defence - " to many titles.
# Maps resolved full country names to additional short forms TED uses as prefix.
_TED_PREFIX_ALIASES: dict[str, list[str]] = {
    "Czech Republic": ["Czech", "Czechia"],
    "United Kingdom": ["UK"],
}
# Matches " - " or " – " (en-dash) as the separator after the prefix
_PREFIX_SEP = re.compile(r"\s*[-–]\s+")


def strip_country_prefix(title: str, country: str) -> str:
    """Remove TED-prepended country name from the title.

    TED API prefixes titles with the country name, e.g.:
      "Sweden - Aircraft Maintenance Trailers..." → "Aircraft Maintenance Trailers..."
      "Belgium Defence - 780 Military Trailers..." → "780 Military Trailers..."
      "Netherlands Ministry of Defence - ..."  → "..."

    Safety net: if the stripped result is shorter than 8 characters the
    original title is returned unchanged.
    """
    if not title or not country or country in ("Unknown", ""):
        return title
    candidates = [country] + _TED_PREFIX_ALIASES.get(country, [])
    for candidate in candidates:
        escaped = re.escape(candidate)
        pattern = re.compile(
            rf"^{escaped}(?:\s+(?:Ministry of Defence|Defence))?\s*[-–]\s+",
            re.IGNORECASE,
        )
        m = pattern.match(title)
        if m:
            stripped = title[m.end():]
            return stripped if len(stripped) >= 8 else title
    return title


_NATO_PORTAL_SOURCES = frozenset(["NSPA-EP"])

def _resolve_source(notice: dict) -> str:
    src = notice.get("_source") or notice.get("source") or "?"
    if src in _NATO_PORTAL_SOURCES:
        return "NATO"
    if src and src not in ("?", "", None):
        return "TED" if src == "TED" else "National"
    if _TED_PATTERN.match(str(notice.get("tender_id", ""))):
        return "TED"
    return "National"


def _resolve_country(notice: dict) -> tuple[str, str]:
    """Returns (full_name, iso2). Tries three fallback paths."""
    # 1. _country_normalized — pre-resolved full name, set for national entries
    cn = notice.get("_country_normalized")
    if cn and cn not in ("?", "Unknown", ""):
        iso2 = _NAME_TO_ISO2.get(cn)
        if iso2:
            return cn, iso2

    # 2. contracting_authority.country (ISO3, full name, or ISO2)
    ca = notice.get("contracting_authority")
    if isinstance(ca, dict):
        raw = (ca.get("country") or "").split("\n")[0].strip()
        if raw and raw not in ("?", ""):
            # ISO3 code
            if raw in _ISO3:
                iso2, name = _ISO3[raw]
                return name, iso2
            # Full country name (may be in English, direct or alias)
            if raw in _NAME_TO_ISO2:
                return raw, _NAME_TO_ISO2[raw]
            # Case-insensitive full name
            raw_title = raw.title()
            if raw_title in _NAME_TO_ISO2:
                return raw_title, _NAME_TO_ISO2[raw_title]
            # ISO2 code fallback
            raw_upper = raw.upper()
            for name, code in _NAME_TO_ISO2.items():
                if code == raw_upper:
                    return name, raw_upper

    # 3. _raw.organisation-country-buyer[0] (ISO3)
    raw_blob = notice.get("_raw") or {}
    if isinstance(raw_blob, dict):
        ocb = raw_blob.get("organisation-country-buyer")
        if ocb:
            code = (ocb[0] if isinstance(ocb, list) else str(ocb)).split("\n")[0].strip()
            if code in _ISO3:
                iso2, name = _ISO3[code]
                return name, iso2

    # 4. tender_id prefix fallback (e.g. "CZ-N006/...", "NL-577684", "UA-2026-...")
    tid = str(notice.get("tender_id", ""))
    if tid:
        m = re.match(r"^([A-Z]{2})-", tid)
        if m:
            iso2 = m.group(1)
            if iso2 == "UK":
                iso2 = "GB"
            for name, code in _NAME_TO_ISO2.items():
                if code == iso2:
                    return name, iso2

    logger.warning("Cannot resolve country for tender %s", notice.get("tender_id"))
    return "Unknown", ""


# Status keyword sets for Tier-1 notice-type / form-type matching.
# Order matters when applied to the same string — destructive states first.
_STATUS_CANCEL_TOKENS = ("cancel", "withdraw")
_STATUS_MOD_TOKENS    = ("modification", "corrigendum")
_STATUS_OPEN_TOKENS   = ("contract notice", "call for tenders", "competition")

# Tier-3 heuristic thresholds. Defaults from Sprint 14b spec; replace with
# values calibrated from docs/STATUS_AUDIT.md when the audit ships.
_STATUS_OPEN_DAYS_MAX     = 90    # younger than this AND no deadline → Open
_STATUS_CLOSED_DAYS_MIN   = 365   # older than this AND no winner → Closed
# Tier-1b: CN-type notice with no deadline is still called "Open" if published
# within this many days — covers typical 6-month procurement cycle + buffer.
_STATUS_CN_OPEN_DAYS_MAX  = 180
_VALID_STATUS = ("Open", "Closed", "Awarded", "Cancelled")


def _pub_date(notice: dict) -> Optional[str]:
    """Best-effort publication date string (ISO YYYY-MM-DD) from any of the
    fields the upstream pipeline writes."""
    s = notice.get("_pub_date") or notice.get("_pub_date_clean")
    if not s:
        raw = notice.get("_raw") or {}
        if isinstance(raw, dict):
            s = raw.get("publication-date")
    cleaned = _clean_date(s)
    return cleaned or None


def _deadline_date(notice: dict) -> Optional[str]:
    for f in ("submission_deadline", "_closing_date", "_deadline_mined"):
        v = _clean_date(notice.get(f))
        if v:
            return v
    return None


def _resolve_status(notice: dict, today: Optional[_dt.date] = None) -> str:
    """Resolve frontend status using a 3-tier waterfall.

    TIER 1 — Hard signals
      a) Explicit winner (``_winner_name`` / ``award.awarded`` /
         ``award.winner_name``) → Awarded.
      b) Notice-type / form-type from ``_raw`` keyword match.
         Order: cancel/withdraw → Cancelled, modification/corrigendum →
         Closed, award/result/can → Awarded, contract-notice/cn → Open
         candidate (confirmed via deadline; otherwise falls through).
    TIER 2 — National-adapter status
      ``_status`` already in {Open, Closed, Awarded, Cancelled} is trusted.
    TIER 3 — Publication-date heuristic
      pub_date age < 90d AND no deadline → Open;
      deadline still in future → Open;
      pub_date age > 365d → Closed; otherwise → Closed (conservative).
    """
    today = today or _dt.date.today()

    # ── TIER 1a — explicit winner ──
    if notice.get("_winner_name"):
        return "Awarded"
    award = notice.get("award")
    if isinstance(award, dict) and (award.get("awarded") or award.get("winner_name")):
        return "Awarded"

    # ── TIER 1b — notice-type / form-type keyword match ──
    raw = notice.get("_raw") or {}
    if isinstance(raw, dict):
        ntype = raw.get("notice-type") or raw.get("form-type") or ""
        if isinstance(ntype, list):
            ntype = " ".join(str(x) for x in ntype)
        nt = str(ntype).lower()
        if nt:
            if any(tok in nt for tok in _STATUS_CANCEL_TOKENS):
                return "Cancelled"
            if any(tok in nt for tok in _STATUS_MOD_TOKENS):
                return "Closed"
            # "can" matches CAN / Contract-Award-Notice form codes; "cancel"
            # is already filtered above so this won't false-positive.
            if "award" in nt or "result" in nt or "can" in nt:
                return "Awarded"
            if any(tok in nt for tok in _STATUS_OPEN_TOKENS) or "cn" in nt:
                # Open candidate — confirm with deadline if available
                deadline = _deadline_date(notice)
                if deadline:
                    try:
                        if _dt.date.fromisoformat(deadline) > today:
                            return "Open"
                        return "Closed"
                    except ValueError:
                        pass
                # No deadline: use pub-date age as fallback.
                # CN notices published within _STATUS_CN_OPEN_DAYS_MAX days are
                # called "Open" — covers a typical 6-month procurement cycle.
                pub = _pub_date(notice)
                if pub:
                    try:
                        age = (today - _dt.date.fromisoformat(pub)).days
                        if age <= _STATUS_CN_OPEN_DAYS_MAX:
                            return "Open"
                    except ValueError:
                        pass
                # Older CN or no pub-date → fall through to Tier 2/3

    # ── TIER 2 — adapter-supplied status ──
    s = notice.get("_status")
    if s in _VALID_STATUS:
        return s  # type: ignore[return-value]

    # ── TIER 3 — publication-date heuristic ──
    pub = _pub_date(notice)
    if not pub:
        return "Closed"
    try:
        pub_d = _dt.date.fromisoformat(pub)
    except ValueError:
        return "Closed"

    deadline = _deadline_date(notice)
    if deadline:
        try:
            if _dt.date.fromisoformat(deadline) > today:
                return "Open"
        except ValueError:
            pass

    age_days = (today - pub_d).days
    if age_days < _STATUS_OPEN_DAYS_MAX and not deadline:
        return "Open"
    if age_days > _STATUS_CLOSED_DAYS_MIN:
        return "Closed"
    return "Closed"  # conservative middle band


def _resolve_value_eur(notice: dict) -> float:
    """Resolve estimated value in EUR using three lookup paths.

    1. ``_value_eur_num`` — already-converted EUR value from upstream.
    2. ``estimated_value`` dict — TED-shaped ``{amount, currency}`` payload.
       Currency strings are sanitised against the TED newline bug
       (e.g. ``'NOK\\nNOK'`` → ``'NOK'``).
    3. ``_value_amount`` + ``_value_currency`` — flat fields written by
       national adapters via ``BaseAdapter.to_standard_format``.

    Currencies absent from ``_FX`` are logged once per run so unknown
    currencies surface in the export log without crashing.
    """
    # 1. pre-calculated
    v = notice.get("_value_eur_num")
    if v is not None:
        try:
            f = float(v)
            if f > 0.01:
                return f
        except (ValueError, TypeError):
            pass

    # 2. derive from estimated_value dict (TED + UK-CF shape)
    ev = notice.get("estimated_value")
    if isinstance(ev, dict):
        try:
            amount = float(ev.get("amount") or 0)
            currency = str(ev.get("currency") or "").split("\n")[0].strip().upper()
            if amount > 0.01:
                rate = _FX.get(currency, 0.0)
                if rate > 0:
                    return round(amount * rate, 2)
                if currency:
                    _warn_unknown_currency(currency, notice.get("tender_id"))
        except (ValueError, TypeError):
            pass

    # 3. flat _value_amount + _value_currency (national adapters via
    # BaseAdapter.to_standard_format)
    raw_amount = notice.get("_value_amount")
    raw_currency = notice.get("_value_currency") or ""
    if raw_amount is not None:
        try:
            amount = float(raw_amount)
            currency = str(raw_currency).split("\n")[0].strip().upper()
            if amount > 0.01:
                rate = _FX.get(currency, 0.0)
                if rate > 0:
                    return round(amount * rate, 2)
                if currency:
                    _warn_unknown_currency(currency, notice.get("tender_id"))
        except (ValueError, TypeError):
            pass

    return 0


# Track unknown currencies so we log each one once per run instead of
# spamming the log when the same code recurs across many notices.
_UNKNOWN_CURRENCIES_SEEN: set[str] = set()


def _warn_unknown_currency(currency: str, tender_id: Any) -> None:
    if currency in _UNKNOWN_CURRENCIES_SEEN:
        return
    _UNKNOWN_CURRENCIES_SEEN.add(currency)
    logger.warning(
        "Unknown currency %r in _FX (first seen on tender %s) — value will be 0",
        currency, tender_id,
    )


# ── Deduplication ──────────────────────────────────────────────────────────

def _source_tier(record: dict) -> int:
    if record.get("source") == "TED":
        return 10
    tid = record.get("id") or ""
    if tid.startswith("UK-CF-"):
        return 5
    if tid.startswith("UK-FTS-"):
        return 3
    return 0


def _record_completeness(t: dict) -> int:
    score = 0
    for v in t.values():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, (int, float)) and v == 0:
            continue
        score += 1
    return score


def _deduplicate_records(records: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    insertion_order: list[str] = []

    for r in records:
        tid = r.get("id") or ""
        if not tid:
            continue
        if tid not in groups:
            groups[tid] = []
            insertion_order.append(tid)
        groups[tid].append(r)

    result: list[dict] = []
    total_removed = 0
    for tid in insertion_order:
        group = groups[tid]
        if len(group) == 1:
            result.append(group[0])
            continue
        best = max(group, key=lambda rec: (
            _record_completeness(rec),
            _source_tier(rec),
            rec.get("publication_date") or "",
        ))
        removed = len(group) - 1
        total_removed += removed
        logger.info(
            "Dedup: removed %d duplicate(s) for ID %s (kept source=%s)",
            removed, tid, best.get("source"),
        )
        result.append(best)

    if total_removed:
        logger.info("Dedup: %d duplicate(s) removed → %d unique records", total_removed, len(result))
    return result


# ── First-seen tracking ────────────────────────────────────────────────────

def _load_first_seen_state(state_path: Path, shared_path: Path) -> dict[str, str]:
    if state_path.exists():
        try:
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Could not load first-seen state from %s: %s", state_path, exc)

    # First run: backfill from any tenders.json.*.bak snapshots in shared/
    state: dict[str, str] = {}
    for bak in sorted(shared_path.glob("tenders.json.*.bak")):
        try:
            with open(bak, encoding="utf-8") as f:
                old_tenders: list[dict] = json.load(f)
            before = len(state)
            for t in old_tenders:
                if (tid := t.get("id")) and tid not in state:
                    state[tid] = _BACKFILL_TS
            logger.info(
                "First-seen backfill: +%d IDs from %s (total %d)",
                len(state) - before, bak.name, len(state),
            )
        except Exception as exc:
            logger.warning("Could not backfill first-seen from %s: %s", bak, exc)
    return state


def _apply_first_seen(tenders: list[dict], state_path: Path, shared_path: Path) -> None:
    state = _load_first_seen_state(state_path, shared_path)
    now_ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for t in tenders:
        tid = t.get("id")
        if not tid:
            continue
        if tid not in state:
            state[tid] = now_ts
        t["_first_seen_at"] = state[tid]

    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as exc:
        logger.warning("Could not save first-seen state to %s: %s", state_path, exc)


def _clean_date(value: Any) -> str:
    if not value:
        return ""
    # List input (some adapters return [date, date, ...])
    if isinstance(value, list):
        value = value[0] if value else None
        if not value:
            return ""
    # Multi-line strings: TED API repeats the same date for each lot separated by \n
    s = str(value).split("\n")[0].strip()
    s = _TZ_SUFFIX.sub("", s).strip()
    if "T" in s:
        s = s.split("T")[0]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else ""


def _parse_duration_months(text: Any) -> Optional[int]:
    m = _DURATION_RE.search(str(text or ""))
    if not m:
        return None
    try:
        num = float(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("month"):
            return int(round(num))
        if unit.startswith("year"):
            return int(round(num * 12))
        if unit.startswith("week"):
            return max(1, int(round(num * 7 / 30)))
        if unit.startswith("day"):
            return max(1, int(round(num / 30)))
    except (ValueError, TypeError):
        pass
    return None


def _resolve_winner(notice: dict) -> Optional[str]:
    """Return cleaned awarded supplier name or None.

    Backend stores winner in `_winner_name` (preferred) or `award.winner_name`.
    Multi-line / repeated names are common (e.g. ``"ZASLAW...\nZASLAW...\nZASLAW..."``);
    we keep the first non-empty line and strip trailing whitespace.
    """
    raw = notice.get("_winner_name")
    if not raw:
        award = notice.get("award") or {}
        if isinstance(award, dict):
            raw = award.get("winner_name")
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first or None


_TRAILER_CATEGORY_ENUM = {
    "Low-Bed", "Semitrailer", "Dolly", "Tank Trailer", "Mission Module",
    "Loading System", "Special Purpose", "Ammunition Trailer",
    "Field Kitchen", "Cargo Trailer", "Other",
}


def _build_vehicle_types(notice: dict) -> list[dict]:
    entries = []
    for i in range(1, 4):
        name = notice.get(f"_trailer_type_{i}_ai")
        if not name:
            break
        entry: dict[str, Any] = {"name": name, "category": "trailer"}
        cat_ai = notice.get(f"_trailer_category_{i}_ai")
        if cat_ai and cat_ai in _TRAILER_CATEGORY_ENUM:
            entry["trailer_category"] = cat_ai
        qty = notice.get(f"_trailer_quantity_{i}_ai")
        if qty is None and i == 1:
            qty = notice.get("_qty_mined")
        if qty is not None:
            try:
                entry["quantity"] = int(qty)
            except (ValueError, TypeError):
                pass
        entries.append(entry)
    return entries


# ── Trailer spec lifting from extracted_specs ────────────────────────────────

# Regex to derive axle count and payload from _trailer_type_1_ai strings
# e.g. "3.5t 2-axle cargo trailer" → axle_config="2-axle", payload_kg=3500
_AXLE_RE = re.compile(r"(\d+)[\s-]axle", re.IGNORECASE)
_PAYLOAD_T_RE = re.compile(r"([\d.]+)\s*t(?:onne|on)?(?:ne)?[\s-]", re.IGNORECASE)
_PAYLOAD_KG_RE = re.compile(r"([\d.]+)\s*kg", re.IGNORECASE)


def _lift_specs(notice: dict) -> dict:
    """Extract axle_config, payload_kg, dimensions, protection_class from
    extracted_specs.trailer_types[0] (preferred) or from _trailer_type_1_ai string.

    Returns a dict with any of the four keys set (only non-null values included).
    """
    result: dict[str, Any] = {}

    # Primary: extracted_specs.trailer_types[0]
    specs = notice.get("_extracted_specs") or {}
    tt_list = specs.get("trailer_types") or []
    tt = tt_list[0] if tt_list else None

    if tt:
        # axle_config: derive from axle_load_t count or type string
        axle_load = tt.get("axle_load_t")
        type_str = str(tt.get("type") or "")
        m = _AXLE_RE.search(type_str)
        if m:
            result["axle_config"] = f"{m.group(1)}-axle"
        elif axle_load is not None:
            result["axle_config"] = "single-axle"

        # payload_kg: prefer payload_t over mass_t (mass_t = GVW)
        if tt.get("payload_t") is not None:
            result["payload_kg"] = int(round(float(tt["payload_t"]) * 1000))
        elif tt.get("mass_t") is not None:
            result["payload_kg"] = int(round(float(tt["mass_t"]) * 1000))

        # dimensions: build string from length × width × height if available
        parts = []
        if tt.get("length_mm"):
            parts.append(f"{int(tt['length_mm'])}mm")
        if tt.get("width_mm"):
            parts.append(f"{int(tt['width_mm'])}mm")
        if tt.get("height_mm"):
            parts.append(f"{int(tt['height_mm'])}mm")
        if len(parts) >= 2:
            result["dimensions"] = " × ".join(parts)

    # Secondary: derive from _trailer_type_1_ai string if primary missed
    t_ai = str(notice.get("_trailer_type_1_ai") or "")
    if t_ai:
        if "axle_config" not in result:
            m = _AXLE_RE.search(t_ai)
            if m:
                result["axle_config"] = f"{m.group(1)}-axle"

        if "payload_kg" not in result:
            m = _PAYLOAD_KG_RE.search(t_ai)
            if m:
                try:
                    result["payload_kg"] = int(round(float(m.group(1))))
                except (ValueError, TypeError):
                    pass
            else:
                m = _PAYLOAD_T_RE.search(t_ai)
                if m:
                    try:
                        result["payload_kg"] = int(round(float(m.group(1)) * 1000))
                    except (ValueError, TypeError):
                        pass

    # Protection class: look for armoured/MRAP/blast/ballistic keywords
    combined = t_ai + " " + (notice.get("description_en") or "")[:500]
    if re.search(r"\b(?:armou?red|mrap|blast[\s-]proof|ballistic|protected)\b", combined, re.IGNORECASE):
        result["protection_class"] = "armoured"

    return result


def _map_notice(notice: dict, overrides: dict) -> dict:
    raw_tid = str(notice.get("tender_id", ""))
    country, country_code = _resolve_country(notice)
    # Defensive against pre-Sprint-14c double-prefix residue
    # (e.g. ``UA-UA-2026-...`` → ``UA-2026-...``)
    tid = _format_tender_id(raw_tid, country_code)

    # Title: prefer the Haiku-translated ``title_en`` from src/translator.py,
    # fall back to ``_title_final`` (252/252 coverage), then ``_title_english``,
    # then the multilingual ``title`` dict the TED API ships with.
    title = (
        notice.get("title_en")
        or notice.get("_title_final")
        or notice.get("_title_english")
        or notice.get("title")
        or ""
    )
    title = strip_country_prefix(title, country)

    # Description priority:
    #  1. description_en  — translated/summarised English (translate_descriptions)
    #  2. _description_english — AI-classifier English summary (classify phase)
    #  3. description_enriched — currency-annotated source (may be non-English for
    #     national notices whose source language is not English)
    #  4. _description_final — raw national-portal description
    #  5. description — TED API multilingual dict or fallback string
    description = (
        notice.get("description_en")
        or notice.get("_description_english")
        or notice.get("description_enriched")
        or notice.get("_description_final")
        or notice.get("description")
        or ""
    )

    # Contracting authority name — priority order:
    #   1. _authority_name_structured  (TED eForms organisation-name-buyer,
    #      Sprint 2026-05-18 — multilingual & cleaner than buyer-name)
    #   2. _authority_name             (national adapters)
    #   3. contracting_authority.name  (legacy TED buyer-name fallback)
    authority = (
        notice.get("_authority_name_structured")
        or notice.get("_authority_name")
        or ""
    )
    if not authority:
        ca = notice.get("contracting_authority")
        if isinstance(ca, dict):
            authority = ca.get("name") or ca.get("name_short") or ""
        elif isinstance(ca, str):
            authority = ca

    # Publication date: _pub_date_clean (49/252) → publication_date (199/252)
    pub_date = _clean_date(
        notice.get("_pub_date")
        or notice.get("_pub_date_clean")
        or notice.get("publication_date")
    )

    # Source URL: TED url preferred, national portal url as fallback
    source_url = (
        notice.get("ted_url")
        or notice.get("source_url_national")
        or notice.get("_source_url_national")
        or ""
    )

    # Publication-date source provenance — emitted as optional field.
    # Also drives null-published-date policy for AU post-award records.
    _pub_date_src = notice.get("_published_at_source") or ""

    # OEM overrides: empty by default, merge from shared/overrides if present
    recommended_oems: list = []
    if tid in overrides:
        ov_oems = overrides[tid].get("recommended_oems")
        if isinstance(ov_oems, list):
            recommended_oems = ov_oems

    # Null-published-date policy (TEIL C, 2026-05-21):
    # AU-TEN Awarded records with contract_notice_fallback have only the
    # post-award contract-notice date.  Emitting it as publication_date would
    # mislead the frontend (and pipeline-age metrics) into thinking this is the
    # original tender start date.  Set null unless an ATM cross-reference
    # upgraded the source to "related_lookup" (which carries the real date).
    resolved_status = _resolve_status(notice)
    effective_pub_date: Optional[str] = pub_date or None
    if (
        _pub_date_src == "contract_notice_fallback"
        and resolved_status == "Awarded"
        and not notice.get("_atm_pub_date")
    ):
        effective_pub_date = None

    # If ATM cross-ref upgraded the date, use the ATM publish date instead.
    if notice.get("_atm_pub_date"):
        atm_pub = _clean_date(notice["_atm_pub_date"])
        if atm_pub:
            effective_pub_date = atm_pub

    out: dict[str, Any] = {
        "id": tid,
        "title": title,
        "country": country,
        "country_code": country_code,
        "source": _resolve_source(notice),
        "source_url": source_url,
        "deadline": _deadline_date(notice) or "",
        "publication_date": effective_pub_date,
        "status": resolved_status,  # computed above for null-policy check
        "estimated_value_eur": _resolve_value_eur(notice),
        "description": description,
        "contracting_authority": authority,
        "is_relevant": bool(notice.get("_trailer_type_1_ai")),
        "comments": [],
        "vehicle_types": _build_vehicle_types(notice),
        "recommended_oems": recommended_oems,
    }

    # Emit publication_date_source when known — lets frontend show provenance
    # and warn user when date is a fallback.
    _valid_pub_sources = frozenset([
        "tender_notice", "pin_notice", "contract_notice_fallback",
        "related_lookup", "unknown",
    ])
    if _pub_date_src in _valid_pub_sources:
        out["publication_date_source"] = _pub_date_src

    # Optional: title_en — raw machine-translated title before country-prefix stripping
    if notice.get("title_en"):
        out["title_en"] = notice["title_en"]

    # Optional: procurement_method from _raw (omit if unavailable)
    raw_blob = notice.get("_raw") or {}
    if isinstance(raw_blob, dict):
        proc = raw_blob.get("procedure-type") or raw_blob.get("procurement-method")
        if proc:
            out["procurement_method"] = str(proc)

    # Optional: contract_duration_months (omit on parse failure)
    dur = _parse_duration_months(notice.get("_contract_duration_ai"))
    if dur is not None:
        out["contract_duration_months"] = dur

    # Optional: winner — only emit when present (schema allows null but skipping
    # the key entirely keeps the JSON tidy for non-Awarded tenders)
    winner = _resolve_winner(notice)
    if winner:
        out["winner"] = winner

    # Optional: structured specs from document extraction (Phase 3g)
    specs = notice.get("_extracted_specs")
    if specs and isinstance(specs, dict) and specs.get("trailer_types"):
        out["extracted_specs"] = specs

    # Optional: Strategy A specs (Window E — proactive DE/PL/CZ portal scraping)
    sa_specs = notice.get("_strategy_a_specs")
    if sa_specs and isinstance(sa_specs, dict):
        out["strategy_a_specs"] = sa_specs

    # Optional: contract type (Phase 3j)
    ct = notice.get("_contract_type")
    if ct:
        out["contract_type"] = ct
        ext = notice.get("_extension_options")
        if ext:
            out["extension_options"] = bool(ext)

    # Optional: URL health (Phase 3l, 2026-05-20). Lets the frontend hide / warn
    # about dead links instead of silently shipping 404-redirects. Omitted when
    # the validator hasn't run yet so old exports stay unchanged.
    url_status = notice.get("_url_status")
    if url_status:
        out["url_status"] = str(url_status)

    # ── Sprint 2026-05-18 — TED Quick-Wins exposure ─────────────────────────
    # framework_type   — raw eForms code (fa-wo-rc / fa-w-rc / fa-mix / none).
    # contract_conclusion_date — real award/signature date (precedes
    #   publication-date of the CAN). Falls back to award.award_date so we
    #   still emit a usable date for older CAN-standard notices that lack
    #   the eForms field.
    # authority_identifier — buyer registration code (TED organisation-
    #   identifier-buyer). Cross-reference key for buyer-profile aggregation.
    ft = notice.get("_framework_type")
    if ft:
        out["framework_type"] = str(ft).strip().lower()
    ccd = notice.get("_contract_conclusion_date")
    if ccd:
        cleaned_ccd = _clean_date(ccd)
        if cleaned_ccd:
            out["contract_conclusion_date"] = cleaned_ccd
    auth_id = notice.get("_authority_id")
    if auth_id:
        out["authority_identifier"] = str(auth_id).strip()

    # Optional: trailer specs lifted from extracted_specs / _trailer_type_1_ai
    lifted = _lift_specs(notice)
    if lifted.get("axle_config"):
        out["axle_config"] = lifted["axle_config"]
    if lifted.get("payload_kg"):
        out["payload_kg"] = lifted["payload_kg"]
    if lifted.get("dimensions"):
        out["dimensions"] = lifted["dimensions"]
    if lifted.get("protection_class"):
        out["protection_class"] = lifted["protection_class"]

    # ── Sprint 2026-05-09 (TED-JSON §B) + 2026-05-10 (TED-XML §B+) ──
    # JSON-API supplies: buyer-internet-address, internal-identifier-part,
    # procedure-features, estimated-value-lot + quantity-lot.
    # XML supplies (richer): _xml.{internal_reference, tender_documents_access,
    # buyer_profile_url_full, contract_folder_id, notice_uuid}.
    # When both sides have a value we prefer the XML one (better URL with
    # tender-id, better internal_reference for eForms notices).
    if isinstance(raw_blob, dict):
        xml_block = raw_blob.get("_xml") if isinstance(raw_blob.get("_xml"), dict) else {}

        # buyer_profile_url — XML's buyer_profile_url_full preferred (often
        # carries the full path with buyer-code, e.g. ".../pn/12wog");
        # fall back to JSON's buyer-internet-address (often just the host).
        bp_xml = xml_block.get("buyer_profile_url_full")
        bia = raw_blob.get("buyer-internet-address")
        if isinstance(bia, list):
            bia = next((str(x).strip() for x in bia if x), None)
        elif isinstance(bia, str):
            bia = bia.strip()
        chosen_bp = bp_xml or bia
        if chosen_bp:
            out["buyer_profile_url"] = chosen_bp

        # internal_reference — XML's ProcurementProject/ID is the canonical
        # buyer-internal reference (free-text, e.g. "Q/U2BP/RA029/NA103");
        # fall back to JSON's internal-identifier-part.
        ir_xml = xml_block.get("internal_reference")
        iip = raw_blob.get("internal-identifier-part")
        if isinstance(iip, list):
            iip = next((str(x).strip() for x in iip if x), None)
        elif isinstance(iip, str):
            iip = iip.strip()
        chosen_ir = ir_xml or iip
        if chosen_ir:
            out["internal_reference"] = chosen_ir

        # tender_documents_access — XML-only, the deeplink that includes
        # the buyer's tender-id (e.g. "?id=771723"). Foreign-Key for the
        # National-Portal-Lookup pipeline (§A).
        tda = xml_block.get("tender_documents_access")
        if tda:
            out["tender_documents_access"] = tda

        # contract_folder_id — XML-only eForms procurement-folder UUID.
        cfid = xml_block.get("contract_folder_id")
        if cfid:
            out["contract_folder_id"] = cfid

        # procedure-features — multilingual prose; pick English when
        # available, fall back to first non-empty value.
        pf = raw_blob.get("procedure-features")
        pf_text: Optional[str] = None
        if isinstance(pf, dict):
            for lang in ("eng", "en", "fra", "fr", "deu", "de"):
                v = pf.get(lang)
                if v:
                    pf_text = str(v[0]) if isinstance(v, list) and v else str(v)
                    break
            if not pf_text:
                for v in pf.values():
                    if v:
                        pf_text = str(v[0]) if isinstance(v, list) and v else str(v)
                        break
        elif isinstance(pf, list) and pf:
            pf_text = str(pf[0])
        elif isinstance(pf, str):
            pf_text = pf
        if pf_text:
            out["procedure_features"] = pf_text.strip()

        # Lot breakdown — pair estimated-value-lot with quantity-lot
        # element-wise (TED returns parallel arrays of lots).
        evl = raw_blob.get("estimated-value-lot")
        qty = raw_blob.get("quantity-lot")
        if isinstance(evl, list) and any(v not in (None, "", "0") for v in evl):
            lots: list[dict[str, Any]] = []
            for i, v in enumerate(evl):
                lot_entry: dict[str, Any] = {"id": f"LOT-{i + 1:04d}"}
                try:
                    lot_entry["value"] = float(v) if v not in (None, "") else None
                except (TypeError, ValueError):
                    lot_entry["value"] = None
                if isinstance(qty, list) and i < len(qty) and qty[i] not in (None, ""):
                    try:
                        lot_entry["quantity"] = int(float(qty[i]))
                    except (TypeError, ValueError):
                        pass
                lots.append(lot_entry)
            if lots:
                out["lots"] = lots

    return out


def export_tenders_for_frontend(relevant_path: Path, output_path: Path) -> int:
    """
    Read relevant.json, write frontend-schema tenders.json.
    Returns number of tenders written.
    """
    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    # Merge OEM overrides if the file exists (silent skip otherwise)
    overrides: dict[str, Any] = {}
    overrides_path = output_path.parent / "overrides" / "tenders_overrides.json"
    if overrides_path.exists():
        try:
            with open(overrides_path, encoding="utf-8") as f:
                raw_ov = json.load(f)
            if isinstance(raw_ov, list):
                overrides = {item["id"]: item for item in raw_ov if "id" in item}
            elif isinstance(raw_ov, dict):
                overrides = raw_ov
        except Exception as exc:
            logger.warning("Could not load OEM overrides from %s: %s", overrides_path, exc)

    tenders = [_map_notice(n, overrides) for n in notices]

    # Sprint 14j Safety-Net: drop any tender below the EUR threshold that may
    # have slipped through relevant.json (e.g. legacy entries written before
    # the filter-hardening migration).
    try:
        from src.filter_engine import (
            MIN_VALUE_EUR as _MIN_VALUE_EUR,
            is_above_value_threshold as _safe_above_threshold,
            is_repair_only as _safe_repair_only,
        )
    except Exception:
        _MIN_VALUE_EUR = 100_000
        _safe_above_threshold = None
        _safe_repair_only = None

    if _safe_above_threshold is not None:
        pre = len(tenders)
        tenders = [t for t in tenders if _safe_above_threshold(t) and not _safe_repair_only(t)]
        if len(tenders) < pre:
            logger.info(
                "Exporter safety-net: dropped %d tenders (value<€%d or repair-only)",
                pre - len(tenders), int(_MIN_VALUE_EUR),
            )

    tenders = _deduplicate_records(tenders)
    _apply_first_seen(tenders, _FIRST_SEEN_STATE_PATH, output_path.parent)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tenders, f, ensure_ascii=False, indent=2)

    logger.info("Frontend export: %d tenders → %s", len(tenders), output_path)
    return len(tenders)


# ── Standalone entry point: python -m src.exporter_frontend ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    _scraper_root = Path(__file__).parent.parent
    _relevant = _scraper_root / "data" / "filtered" / "relevant.json"
    _shared = _scraper_root.parent.parent / "shared"
    _output = _shared / "tenders.json"

    _count = export_tenders_for_frontend(_relevant, _output)
    print(f"[OK] Wrote {_count} tenders → {_output}")

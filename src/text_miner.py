"""
Text-Mining Module (Phase 3k) — multilingual regex + optional LLM fallback
that pulls hard data (quantity, delivery deadline, contract duration) directly
from `_description_final` / `description_en` / `_national_raw_text`.

Why this exists:
  Many sources (CanadaBuys, AU OCDS, several national portals) carry the qty
  and delivery date in free text only. The AI classifier picks up `_trailer_*`
  fields but routinely misses bare "Qty 27" / "120 days after contract award"
  numbers when they sit outside a structured paragraph.

Output fields written back onto each notice:
  _qty_mined              : int or None
  _qty_mined_source       : "regex" | "llm" | None
  _deadline_mined         : ISO date string (YYYY-MM-DD) or None
  _deadline_mined_source  : "regex" | "llm" | None
  _duration_months_mined  : int or None  (heuristic — only when explicit)
  _duration_months_mined_source : "regex" | "llm" | None
  _text_mining_meta       : { fragment: str, pattern_id: str, mined_at: iso }

Cache: data/.text_mining_cache.json
  Key format: "{tender_id}:{sha1_of_input_text}"
  Hits avoid both regex and LLM work.

Default precedence (applied in main.py Phase 3k):
  Pipeline prefers `_trailer_quantity_1_ai` (AI-classifier) when present;
  this module ONLY supplies fallback values for tenders where the
  classifier produced no quantity. The mined value is also exposed
  side-by-side under `_qty_mined` so the Excel/JSON exporter can audit it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / ".text_mining_cache.json"

# ── Source allow-list (Sprint 2026-05-18, TEIL B) ───────────────────────────
# Phase 3k Audit (`docs/TEXT_MINING_TED_VALUE_260518.md`) measured 0/29 new
# quantity signals on TED notices — the AI classifier already extracts every
# integer the regex finds, since both read the same translated description.
# Deactivate TED by default to save audit-surface and noise. Re-activation:
# include "TED" in TEXT_MINING_SOURCES env-var (comma-separated), or call
# ``mine_all(..., source_allowlist=...)`` directly.
#
# UK is also excluded: 6 UK-FTS tenders in current pool, 0 new mined signals.
# All other adapters (CA-CB highest yield, AU-OCDS, national portals) stay on.
DEFAULT_TEXT_MINING_SOURCES = (
    "CA",       # CanadaBuys CSV
    "AU-TEN",   # AusTender OCDS
    "AU-AT",    # AusTender ATM
    "DE",
    "DE-EV",
    "PL",
    "CZ",
    "FR",
    "NO",
    "DK",
    "NL",
    "BE",
    "ES",
    "IT",
    "UA",
    "CH",
    "FI",
    "SE",
    "RO",
    "EE",
    "LV",
    "LT",
    "GR",
    "NSPA-EP",
)


def _resolve_text_mining_sources() -> tuple[str, ...]:
    """Allow-list from ``TEXT_MINING_SOURCES`` env-var (comma-separated) or the
    module-level default. Empty / unset env-var → default list."""
    raw = (os.environ.get("TEXT_MINING_SOURCES") or "").strip()
    if not raw:
        return DEFAULT_TEXT_MINING_SOURCES
    parts = tuple(s.strip().upper() for s in raw.split(",") if s.strip())
    return parts or DEFAULT_TEXT_MINING_SOURCES


_TED_PUB_RE = re.compile(r"^\d+-\d{4}$")


def _is_in_scope(notice: dict, allow: tuple[str, ...]) -> bool:
    """True when the notice's source is in the allow-list.

    Detection priority:
      1. Explicit ``_source`` field on the notice (national adapters set this).
      2. tender_id prefix (e.g. ``CA-cb-...`` → ``CA``).
      3. TED pattern ``\\d+-\\d{4}$`` → ``TED``.
    """
    src = (notice.get("_source") or "").strip().upper()
    if src:
        return src in allow
    tid = str(notice.get("tender_id", "")).strip()
    if _TED_PUB_RE.match(tid):
        return "TED" in allow
    if "-" in tid:
        prefix = tid.split("-", 1)[0].upper()
        return prefix in allow
    return False

# ── Quantity patterns ─────────────────────────────────────────────────────────
# Capture group 1 always holds the integer.
_QTY_PATTERNS: list[tuple[str, str]] = [
    # English
    (r"qty_en_inline",       r"\b(?:Qty\.?|QTY)\s*[:=]?\s*(\d{1,5})\b"),
    (r"quantity_en_inline",  r"\bQuantity\s*[:=]\s*(\d{1,5})\b"),
    (r"quantity_en_of",      r"\bquantity\s+of\s+(\d{1,5})\b"),
    (r"qty_en_units",        r"\b(\d{1,5})\s+(?:units?|pieces?|pcs?|items?)\b"),
    (r"qty_en_trailers",     r"\b(\d{1,5})\s+(?:trailers?|semi[- ]?trailers?|"
                              r"dollies|tankers?|kitchens?|shelters?|"
                              r"remorques?|Anhänger|naczep[ay])\b"),
    (r"qty_en_lowbed",       r"\b(?:procure|supply|deliver(?:y of)?|provision of)\s+(?:Qty\.?\s*)?"
                              r"(\d{1,5})\s+(?:Lowbed|Low[- ]bed|Cargo|Tank|Ammunition|Mobile Kitchen|Field)"),
    (r"qty_en_total",        r"\btotal\s+(?:of\s+)?(\d{1,5})\s+(?:units?|trailers?|pieces?)\b"),

    # German
    (r"qty_de_stueck",       r"\b(\d{1,5})\s+Stück\b"),
    (r"qty_de_anzahl",       r"\bAnzahl\s*[:=]?\s*(\d{1,5})\b"),
    (r"qty_de_menge",        r"\bMenge\s*[:=]?\s*(\d{1,5})\b"),

    # French
    (r"qty_fr_quantite",     r"\bquantité\s*[:=]?\s*(\d{1,5})\b"),
    (r"qty_fr_nombre",       r"\bnombre\s+de\s+(\d{1,5})\b"),

    # Polish
    (r"qty_pl_ilosc",        r"\bilość\s*[:=]?\s*(\d{1,5})\b"),
    (r"qty_pl_szt",          r"\b(\d{1,5})\s+szt\.?\b"),
    (r"qty_pl_sztuk",        r"\b(\d{1,5})\s+sztuk\b"),

    # Czech / Slovak
    (r"qty_cz_pocet",        r"\bpočet\s*(?:ks\.?)?\s*[:=]?\s*(\d{1,5})\b"),
    (r"qty_cz_kusy",         r"\b(\d{1,5})\s+(?:ks\.?|kusů|kusy)\b"),

    # Italian
    (r"qty_it_quantita",     r"\bquantità\s*[:=]?\s*(\d{1,5})\b"),

    # Spanish / Portuguese
    (r"qty_es_cantidad",     r"\bcantidad\s*[:=]?\s*(\d{1,5})\b"),
    (r"qty_es_unidades",     r"\b(\d{1,5})\s+unidades\b"),

    # Ukrainian / Russian (Cyrillic)
    (r"qty_ua_kilkist",      r"кількість\s*[:=]?\s*(\d{1,5})"),
    (r"qty_ua_shtuk",        r"(\d{1,5})\s+шт(?:ук)?\.?"),

    # Swedish / Norwegian / Danish
    (r"qty_sv_antal",        r"\bantal\s*[:=]?\s*(\d{1,5})\b"),
    (r"qty_sv_stk",          r"\b(\d{1,5})\s+stk\.?\b"),

    # Dutch
    (r"qty_nl_aantal",       r"\baantal\s*[:=]?\s*(\d{1,5})\b"),
]

_QTY_COMPILED: list[tuple[str, re.Pattern]] = [
    (pid, re.compile(pat, re.IGNORECASE | re.UNICODE)) for pid, pat in _QTY_PATTERNS
]

# Reject values outside this band (parsing artefacts: phone numbers, prices)
_QTY_MIN = 1
_QTY_MAX = 10_000

# Phrases that, if present in the IMMEDIATE neighbourhood of the match,
# signal a non-quantity number (file numbers, contract IDs).
#
# "nscm/cage", "nsn", "gsin" appear near procurement line-items that DO carry
# real quantities ("NSN: 21-8969342 ... Quantity: 10"). We must NOT reject in
# that case. So the guardrail only fires when the rejected keyword sits on
# the same side of the integer as the match group itself — typically within
# ~20 chars before or after, and ONLY when the keyword appears between the
# match-keyword ("quantity") and the integer, or directly attached to the
# integer (e.g. "NSN: 12345").
_QTY_REJECT_NEAR = re.compile(
    r"(?:file\s+number\s*[:=]?\s*\S*\d|"
    r"nsn\s*[:=][^.]*?\d|"
    r"reference\s+(?:no|number)\s*[:=]?\s*\S*\d|"
    r"contract\s+(?:no|number)\s*[:=]?\s*\S*\d|"
    r"page\s+\d|seite\s+\d)",
    re.IGNORECASE,
)


# ── Deadline patterns ─────────────────────────────────────────────────────────
# Two flavours:
#  (A) absolute date  →  "(by|until|before) <date>"
#  (B) relative offset →  "<N> days after contract award" / "within N months"

_MONTH_NAMES = {
    "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5, "mai": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12, "dez": 12,
    # German
    "januar": 1, "februar": 2, "märz": 3, "marz": 3, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
}

_DEADLINE_ABS_PATTERNS = [
    # "by July 7, 2026" / "by July 7 2026"
    (r"dl_en_by_monthname",
     r"\b(?:by|until|before|no\s+later\s+than|on\s+or\s+before|"
     r"delivery\s+(?:by|date|date\s+of|date\s+is)|delivery\s+is\s+requested\s+(?:at[^.]*?)\s*by)"
     r"\s+([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b"),
    # "by 11-Apr-2026"
    (r"dl_en_by_dashdate",
     r"\b(?:by|until|before|delivery\s+by)\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})\b"),
    # "by 11/04/2026"  (DD/MM/YYYY)
    (r"dl_en_by_slashdate_dmy",
     r"\b(?:by|until|before|delivery\s+by)\s+(\d{1,2})/(\d{1,2})/(\d{4})\b"),
    # "Lieferung bis 11.04.2026"
    (r"dl_de_bis",
     r"\b(?:Lieferung|delivery)\s+(?:bis|until)\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\b"),
    # German: "bis zum 31. Dezember 2026"
    (r"dl_de_bis_zum_dotted",
     r"\bbis\s+(?:zum\s+)?(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s+(\d{4})\b"),
    # ISO: "by 2026-07-07"
    (r"dl_iso_by",
     r"\b(?:by|until|before|delivery\s+by|deadline)\s+(\d{4})-(\d{2})-(\d{2})\b"),
]

_DEADLINE_REL_PATTERNS = [
    # "120 days after contract award" / "within 90 days of award"
    (r"dl_en_days_after_award",
     r"\b(\d{1,4})\s+days?\s+(?:after|from|of|following)\s+(?:the\s+)?"
     r"(?:contract\s+award|award\s+of\s+the\s+contract|signing|award)\b",
     "days"),
    (r"dl_en_within_days_award",
     r"\bwithin\s+(\d{1,4})\s+days?\s+(?:of|after|from|following)\s+(?:the\s+)?award\b",
     "days"),
    # "X months after contract award"
    (r"dl_en_months_after_award",
     r"\b(\d{1,3})\s+(?:months?|m)\s+(?:after|from|following)\s+(?:contract\s+award|signing|award)\b",
     "months"),
    # "delivery requested 120 days after award"
    (r"dl_en_delivery_days",
     r"\bdelivery\s+(?:is\s+)?(?:requested|required|expected)\s+(?:within\s+)?(\d{1,4})\s+days?\b",
     "days"),
    # German
    (r"dl_de_tage_nach",
     r"\b(\d{1,4})\s+Tage\s+nach\s+(?:Zuschlag|Vertragsschluss|Auftragserteilung)\b",
     "days"),
    (r"dl_de_monate_nach",
     r"\b(\d{1,3})\s+Monate\s+nach\s+(?:Zuschlag|Vertragsschluss|Auftragserteilung)\b",
     "months"),
    # French
    (r"dl_fr_jours_apres",
     r"\b(\d{1,4})\s+jours?\s+(?:à\s+compter\s+de|après)\s+(?:la\s+notification|"
     r"l['']attribution|signature\s+du\s+contrat)\b",
     "days"),
]

_DEADLINE_ABS_COMPILED = [
    (pid, re.compile(pat, re.IGNORECASE | re.UNICODE))
    for pid, pat in _DEADLINE_ABS_PATTERNS
]
_DEADLINE_REL_COMPILED = [
    (pid, re.compile(pat, re.IGNORECASE | re.UNICODE), unit)
    for pid, pat, unit in _DEADLINE_REL_PATTERNS
]


# ── Duration patterns ─────────────────────────────────────────────────────────
# Already partially covered by contract_type.py; here we capture explicit numbers
# that show up in description-free-text but didn't make it into _contract_duration_months.
_DURATION_PATTERNS = [
    (r"dur_en_months",
     r"\bcontract\s+duration\s*[:=]?\s*(\d{1,3})\s+months?\b"),
    (r"dur_en_period_months",
     r"\b(?:period|term)\s+of\s+(\d{1,3})\s+months?\b"),
    (r"dur_en_years_months",
     r"\b(\d{1,2})\s+years?\s+(?:and\s+)?(\d{1,2})\s+months?\s+contract\b"),
    (r"dur_de_monate",
     r"\bVertragsdauer\s*[:=]?\s*(\d{1,3})\s+Monate\b"),
    (r"dur_fr_mois",
     r"\bdurée\s+(?:du\s+marché|contractuelle)\s*[:=]?\s*(\d{1,3})\s+mois\b"),
]
_DURATION_COMPILED = [
    (pid, re.compile(pat, re.IGNORECASE | re.UNICODE))
    for pid, pat in _DURATION_PATTERNS
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _ctx_around(text: str, span: tuple[int, int], radius: int = 60) -> str:
    a = max(0, span[0] - radius)
    b = min(len(text), span[1] + radius)
    return text[a:b]


def _looks_like_reject(context: str) -> bool:
    return bool(_QTY_REJECT_NEAR.search(context))


def _month_to_int(name: str) -> Optional[int]:
    return _MONTH_NAMES.get(name.strip().lower())


def _safe_date(year: int, month: int, day: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


# ── Quantity mining ───────────────────────────────────────────────────────────

def mine_quantity(text: str) -> tuple[Optional[int], Optional[str], dict]:
    """Return (qty, source_tag, meta) for the strongest quantity signal in text.

    Strategy:
      Sequential pass through the pattern list. The FIRST plausible match wins;
      patterns are ordered with the most specific defence-trailer-flavoured
      patterns first, so "(Qty 27) Lowbed Trailers" beats a stray "27 page".

    A guardrail (_looks_like_reject) drops matches whose surrounding context
    contains "file number", "NSN", "contract number" etc. — these are usually
    document identifiers, not order quantities.
    """
    if not text:
        return None, None, {}

    for pid, pat in _QTY_COMPILED:
        m = pat.search(text)
        if not m:
            continue
        try:
            val = int(m.group(1))
        except (ValueError, IndexError):
            continue
        if val < _QTY_MIN or val > _QTY_MAX:
            continue
        context = _ctx_around(text, m.span())
        if _looks_like_reject(context):
            continue
        return val, "regex", {
            "pattern_id": pid,
            "fragment": context.strip()[:200],
            "match": m.group(0),
        }

    return None, None, {}


# ── Deadline mining ───────────────────────────────────────────────────────────

def mine_deadline(text: str, *, anchor_date: Optional[str] = None) -> tuple[
        Optional[str], Optional[str], dict]:
    """Return (iso_date, source_tag, meta) for the strongest delivery-date signal.

    `anchor_date` should be the publication date (ISO YYYY-MM-DD). It is used
    as the base for relative offsets ("120 days after contract award"). If
    omitted, today's date is used and the meta dict flags it as approximate.
    """
    if not text:
        return None, None, {}

    # (A) Absolute dates first — they don't need an anchor.
    for pid, pat in _DEADLINE_ABS_COMPILED:
        m = pat.search(text)
        if not m:
            continue
        iso = None
        if pid == "dl_en_by_monthname":
            mon = _month_to_int(m.group(1))
            day = int(m.group(2))
            year = int(m.group(3))
            if mon:
                iso = _safe_date(year, mon, day)
        elif pid == "dl_en_by_dashdate":
            mon = _month_to_int(m.group(2))
            day = int(m.group(1))
            year = int(m.group(3))
            if mon:
                iso = _safe_date(year, mon, day)
        elif pid == "dl_en_by_slashdate_dmy":
            iso = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif pid == "dl_de_bis":
            iso = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        elif pid == "dl_de_bis_zum_dotted":
            mon = _month_to_int(m.group(2))
            if mon:
                iso = _safe_date(int(m.group(3)), mon, int(m.group(1)))
        elif pid == "dl_iso_by":
            iso = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

        if iso:
            return iso, "regex", {
                "pattern_id": pid,
                "fragment": _ctx_around(text, m.span()).strip()[:200],
                "match": m.group(0),
            }

    # (B) Relative offsets — need an anchor.
    if anchor_date:
        try:
            base = datetime.fromisoformat(anchor_date[:10]).date()
            anchor_approx = False
        except ValueError:
            base = date.today()
            anchor_approx = True
    else:
        base = date.today()
        anchor_approx = True

    for pid, pat, unit in _DEADLINE_REL_COMPILED:
        m = pat.search(text)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except (ValueError, IndexError):
            continue
        if unit == "days":
            target = base + timedelta(days=n)
        elif unit == "months":
            # Approximate month math (30-day) — good enough for procurement.
            target = base + timedelta(days=30 * n)
        else:
            continue
        return target.isoformat(), "regex", {
            "pattern_id": pid,
            "fragment": _ctx_around(text, m.span()).strip()[:200],
            "match": m.group(0),
            "anchor": base.isoformat(),
            "anchor_approx": anchor_approx,
            "offset": n,
            "unit": unit,
        }

    return None, None, {}


# ── Duration mining ───────────────────────────────────────────────────────────

def mine_duration_months(text: str) -> tuple[Optional[int], Optional[str], dict]:
    if not text:
        return None, None, {}
    for pid, pat in _DURATION_COMPILED:
        m = pat.search(text)
        if not m:
            continue
        try:
            if pid == "dur_en_years_months":
                years = int(m.group(1))
                months = int(m.group(2))
                total = years * 12 + months
            else:
                total = int(m.group(1))
        except (ValueError, IndexError):
            continue
        if 1 <= total <= 600:
            return total, "regex", {
                "pattern_id": pid,
                "fragment": _ctx_around(text, m.span()).strip()[:200],
                "match": m.group(0),
            }
    return None, None, {}


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_key(tender_id: str, text: str) -> str:
    return f"{tender_id}:{_sha1(text)}"


# ── Top-level API ─────────────────────────────────────────────────────────────

def _candidate_text(tender: dict) -> str:
    """Combine the most useful text fields into one mining target."""
    parts = []
    for f in ("_description_final", "description_en", "_description_english",
              "description", "_national_raw_text"):
        v = tender.get(f)
        if isinstance(v, str) and v:
            parts.append(v)
    return "\n\n".join(parts)


def mine_all(tender: dict, *, cache: Optional[dict] = None,
             save_to_cache: bool = True,
             source_allowlist: Optional[tuple[str, ...]] = None) -> dict:
    """Apply quantity + deadline + duration mining to a single tender dict.

    Args:
        tender:           Notice dict (from relevant.json).
        cache:            Pre-loaded cache dict (avoid re-loading per call).
        save_to_cache:    Persist updates to disk. Set False for batch callers
                          that prefer to save once at the end.
        source_allowlist: Override the default source allow-list (see
                          ``DEFAULT_TEXT_MINING_SOURCES``). When None, the env-var
                          ``TEXT_MINING_SOURCES`` or the module default is used.

    Out-of-scope sources (TED + UK by default after Sprint 2026-05-18 audit)
    return an empty result with ``_skipped="out_of_scope"`` — the existing
    cache entry (if any) is preserved so a future re-activation does not need
    a fresh recompute.

    Returns:
        Dict with at minimum the four `_*_mined*` keys (None when not found).
        Does NOT mutate the input tender — caller decides how to merge.
    """
    tid = (tender.get("tender_id") or "").strip()
    text = _candidate_text(tender)

    # No text → no work, regardless of source. Keeps the "no_text" reason
    # precise (debugging signal: missing description vs. excluded source).
    if not text:
        return {
            "_qty_mined": None, "_qty_mined_source": None,
            "_deadline_mined": None, "_deadline_mined_source": None,
            "_duration_months_mined": None, "_duration_months_mined_source": None,
            "_text_mining_meta": {"skipped": "no_text"},
        }

    allow = source_allowlist or _resolve_text_mining_sources()
    if not _is_in_scope(tender, allow):
        return {
            "_qty_mined": None, "_qty_mined_source": None,
            "_deadline_mined": None, "_deadline_mined_source": None,
            "_duration_months_mined": None, "_duration_months_mined_source": None,
            "_text_mining_meta": {"skipped": "out_of_scope"},
        }

    key = _cache_key(tid, text)
    if cache is None:
        cache = _load_cache()
    if key in cache:
        return cache[key]

    anchor = tender.get("_pub_date") or tender.get("_pub_date_clean") or tender.get("pub_date")

    qty, qty_src, qty_meta = mine_quantity(text)
    deadline, dl_src, dl_meta = mine_deadline(text, anchor_date=anchor)
    dur, dur_src, dur_meta = mine_duration_months(text)

    result = {
        "_qty_mined": qty,
        "_qty_mined_source": qty_src,
        "_deadline_mined": deadline,
        "_deadline_mined_source": dl_src,
        "_duration_months_mined": dur,
        "_duration_months_mined_source": dur_src,
        "_text_mining_meta": {
            "qty": qty_meta,
            "deadline": dl_meta,
            "duration": dur_meta,
            "mined_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "text_sha1": _sha1(text),
        },
    }

    cache[key] = result
    if save_to_cache:
        _save_cache(cache)

    return result


def run_text_mining(notices: list[dict], *, save_each: bool = False,
                    source_allowlist: Optional[tuple[str, ...]] = None) -> dict:
    """Apply mine_all() across a list of notices and write fields in place.

    Returns aggregate statistics.

    Source filtering (Sprint 2026-05-18): notices outside the
    ``source_allowlist`` (default excludes TED + UK) are skipped silently and
    return ``_skipped="out_of_scope"`` in their meta. Their `_*_mined*` fields
    remain None — the AI classifier is the canonical source for those
    sources.

    Conservative merge:
      - Always writes _qty_mined and _deadline_mined (additive, non-destructive).
      - Does NOT overwrite existing `_trailer_quantity_1_ai` — main.py decides
        when to promote `_qty_mined` to the canonical quantity field.
    """
    cache = _load_cache()
    allow = source_allowlist or _resolve_text_mining_sources()
    stats = {
        "total":                len(notices),
        "qty_found":             0,
        "qty_from_text_only":    0,  # qty mined where no AI qty was present
        "deadline_found":        0,
        "duration_found":        0,
        "skipped_out_of_scope":  0,
    }

    for n in notices:
        result = mine_all(n, cache=cache, save_to_cache=False,
                          source_allowlist=allow)
        # Write all output fields in place
        for k, v in result.items():
            n[k] = v

        meta = result.get("_text_mining_meta") or {}
        if meta.get("skipped") == "out_of_scope":
            stats["skipped_out_of_scope"] += 1
            continue

        if result.get("_qty_mined") is not None:
            stats["qty_found"] += 1
            # Did the AI classifier already supply a quantity?
            ai_qty = (n.get("_trailer_quantity_1_ai")
                      or n.get("_trailer_quantity_ai")
                      or n.get("_trailer_qty_1_ai"))
            if not ai_qty:
                stats["qty_from_text_only"] += 1

        if result.get("_deadline_mined") is not None:
            stats["deadline_found"] += 1
        if result.get("_duration_months_mined") is not None:
            stats["duration_found"] += 1

        if save_each:
            _save_cache(cache)

    _save_cache(cache)
    return stats

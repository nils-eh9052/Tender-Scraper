"""
Contract type classifier for defence procurement tenders.

Classifies each notice into:
  framework_agreement — multi-supplier or open-ended framework contract
  recurring           — periodic/service contract (transport, maintenance)
  one_time            — single delivery / one-off procurement
  unknown             — insufficient signal

Strategy:
  1. Regex on title + description_en (multilingual keywords) — covers 95%+
  2. Optional Sonnet pass for ambiguous cases (only if needed)

Also extracts:
  duration_months   — parsed from text ("48 months", "4 years")
  extension_options — bool, True if option/extension language found

Public API:
    classify_contract_type(notice) -> dict
    run_contract_type_pass(relevant_path, *, force, dry_run) -> summary
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
CONTRACT_TYPE_CACHE_PATH = _ROOT / "data" / ".contract_type_cache.json"

# ── Keyword sets (case-insensitive) ─────────────────────────────────────────

_FRAMEWORK_KWS = re.compile(
    r"\b(?:"
    r"framework[\s-]?agreement|framework[\s-]?contract|"
    r"rahmenvertrag|rahmenvereinbarung|"
    r"accord[\s-]cadre|"
    r"umowa[\s-]ramowa|"
    r"rámcová[\s-]smlouva|rámcová[\s-]dohoda|"
    r"ramavtal|rammeaftale|rammeavtale|"
    r"raamovereenkomst|"
    r"accordo[\s-]quadro|"
    r"acuerdo[\s-]marco|"
    r"contrat[\s-]cadre|"
    r"dynami[cč]k[ýé][\s-]nákupní[\s-]systém|"
    r"dynamic[\s-]purchasing[\s-]system|"
    r"kader[\s-]overeenkomst"
    r")\b",
    re.IGNORECASE,
)

_RECURRING_KWS = re.compile(
    r"\b(?:"
    r"recurring|periodic|repeat|standing[\s-]offer|indefinite[\s-]delivery|"
    r"monthly|quarterly|annual(?:ly)?|jährlich|annuel(?:lement)?|"
    r"transport[\s-]service|logistics[\s-]service|forwarding[\s-]service|"
    r"freight[\s-]forwarding|spedition(?:sdienst)?|"
    r"maintenance[\s-]service|service[\s-]contract|dienstleistung"
    r")\b",
    re.IGNORECASE,
)

_DELIVERY_KWS = re.compile(
    r"\b(?:"
    r"supply[\s-]and[\s-]delivery|supply[\s-]of|procurement[\s-]of|"
    r"acquisition[\s-]of|purchase[\s-]of|"
    r"lieferung[\s-]von|liefern|"
    r"fourniture[\s-]de|livraison[\s-]de|"
    r"dostawa|dostarczenie|"
    r"dodávk[ay]|dodání|"
    r"fornitura[\s-]di|"
    r"suministro[\s-]de"
    r")\b",
    re.IGNORECASE,
)

_EXTENSION_KWS = re.compile(
    r"\b(?:"
    r"option|extension|renewal|verlängerung|prorogation|"
    r"extend|renew|optional[\s-]period"
    r")\b",
    re.IGNORECASE,
)

# Duration regexes: "48 months", "4 years", "12 Monate", "2 ans", "48 měsíců"
_DURATION_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*(month|months|monate?|mois|месяц|måneder?|månader?|mesi|meses|měsíc[ůi]?)", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)\s*(year|years|jahre?|ans?|years?|rok[ůi]?|år|anni?)", re.IGNORECASE),
]

_MONTHS_PER_UNIT = {
    "month": 1, "months": 1, "monat": 1, "monate": 1, "mois": 1,
    "måneder": 1, "månader": 1, "mesi": 1, "meses": 1,
    "měsíc": 1, "měsíců": 1, "měsíci": 1,
    "year": 12, "years": 12, "jahr": 12, "jahre": 12,
    "an": 12, "ans": 12, "rok": 12, "roků": 12, "roki": 12,
    "år": 12, "anno": 12, "anni": 12,
}


def _extract_duration_months(text: str) -> Optional[int]:
    """Extract contract duration in months from free text."""
    if not text:
        return None
    for pattern in _DURATION_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                num = float(m.group(1))
                unit = m.group(2).lower().strip()
                multiplier = _MONTHS_PER_UNIT.get(unit, 0)
                if multiplier > 0:
                    return max(1, int(round(num * multiplier)))
            except (ValueError, TypeError):
                pass
    return None


def _combined_text(notice: dict) -> str:
    title = (
        notice.get("title_en")
        or notice.get("_title_final")
        or str(notice.get("title") or "")
    )
    desc = notice.get("description_en") or ""
    dur = notice.get("_contract_duration_ai") or ""
    return " ".join([title, desc, dur])[:4000]


def classify_contract_type(notice: dict) -> dict:
    """
    Returns:
    {
      'contract_type': 'one_time' | 'framework_agreement' | 'recurring' | 'unknown',
      'duration_months': int | None,
      'extension_options': bool,
    }

    Priority order:
      0. Structured TED eForms `_framework_type` code (Sprint 2026-05-18) — 100 %
         deterministic for eForms-CN/CAN notices, replaces fragile regex.
      1-3. Regex on title + description (multilingual keywords).
    """
    text = _combined_text(notice)

    # Duration: prefer _contract_duration_ai, fall back to full text
    dur_src = notice.get("_contract_duration_ai") or text
    duration_months = _extract_duration_months(str(dur_src))

    has_extension = bool(_EXTENSION_KWS.search(text))

    # ── Tier 0 — structured eForms code from TED API (Sprint 2026-05-18) ──
    # `_framework_type` is set by detail_fetcher when the notice comes back
    # with `framework-agreement-lot`. Values per eForms SDK:
    #   fa-wo-rc → framework agreement WITHOUT reopening of competition
    #   fa-w-rc  → framework agreement WITH reopening of competition
    #   fa-mix   → mixed framework regime
    #   none     → no framework — one-time procurement
    # We only branch when the code is decisive; otherwise we fall through to
    # the regex layer (which still covers non-TED tenders and legacy notices).
    ft = notice.get("_framework_type")
    if ft:
        ft = str(ft).strip().lower()
        if ft in ("fa-wo-rc", "fa-w-rc", "fa-mix"):
            return {
                "contract_type": "framework_agreement",
                "duration_months": duration_months,
                "extension_options": has_extension,
                "_source": "ted_framework_agreement_lot",
            }
        if ft == "none":
            # Strong signal it's NOT a framework — but it could still be
            # recurring (service contract). Defer to keyword tiers below
            # rather than forcing one_time here.
            pass

    # Classification hierarchy
    if _FRAMEWORK_KWS.search(text):
        return {
            "contract_type": "framework_agreement",
            "duration_months": duration_months,
            "extension_options": has_extension,
        }

    if _RECURRING_KWS.search(text):
        return {
            "contract_type": "recurring",
            "duration_months": duration_months,
            "extension_options": has_extension,
        }

    if _DELIVERY_KWS.search(text):
        return {
            "contract_type": "one_time",
            "duration_months": duration_months,
            "extension_options": has_extension,
        }

    # No clear signal → default to one_time for defence procurement
    # (most are single-delivery contracts for physical equipment)
    return {
        "contract_type": "one_time",
        "duration_months": duration_months,
        "extension_options": has_extension,
    }


# ── Batch pass ───────────────────────────────────────────────────────────────

def run_contract_type_pass(
    relevant_path: Path | str,
    *,
    cache_path: Path | str = CONTRACT_TYPE_CACHE_PATH,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Classify contract type for every notice in relevant.json.
    Writes `_contract_type`, `_duration_months_inferred`, `_extension_options`
    into each notice.

    Returns summary dict.
    """
    relevant_path = Path(relevant_path)
    cache_path = Path(cache_path)

    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    cache: dict = {}
    if cache_path.exists() and not force:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)

    summary: dict[str, Any] = {
        "total": len(notices),
        "framework_agreement": 0,
        "recurring": 0,
        "one_time": 0,
        "unknown": 0,
        "from_cache": 0,
        "classified_now": 0,
    }

    for notice in notices:
        tid = notice.get("tender_id") or ""
        if not tid:
            continue

        ck = f"{tid}:ctype"

        # Sprint 2026-05-18: when the structured `_framework_type` is available
        # on the notice but the cache entry predates the eForms-source upgrade,
        # invalidate it so the deterministic value wins over the old regex
        # verdict.
        has_eforms_src = bool(notice.get("_framework_type"))
        cache_stale = (
            has_eforms_src
            and ck in cache
            and cache[ck].get("_source") != "ted_framework_agreement_lot"
        )

        if not force and not cache_stale and ck in cache:
            entry = cache[ck]
            notice["_contract_type"] = entry.get("contract_type", "one_time")
            dm = entry.get("duration_months")
            if dm:
                notice["_duration_months_inferred"] = dm
            notice["_extension_options"] = entry.get("extension_options", False)
            summary["from_cache"] += 1
            ct = notice["_contract_type"]
            summary[ct] = summary.get(ct, 0) + 1
            continue

        result = classify_contract_type(notice)
        ct = result["contract_type"]
        dm = result["duration_months"]
        ext = result["extension_options"]

        notice["_contract_type"] = ct
        if dm:
            notice["_duration_months_inferred"] = dm
        notice["_extension_options"] = ext

        summary[ct] = summary.get(ct, 0) + 1
        summary["classified_now"] += 1

        cache[ck] = {
            "contract_type": ct,
            "duration_months": dm,
            "extension_options": ext,
            "_source": result.get("_source", "regex"),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # Save cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    if not dry_run:
        with open(relevant_path, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)

    return summary

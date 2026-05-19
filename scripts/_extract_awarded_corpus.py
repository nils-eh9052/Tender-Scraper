"""Extract a corpus of resolved/awarded defence-trailer tenders for Opus keyword brainstorming.

Selection criteria (any of):
    1. award.awarded == True
    2. _status in {"Awarded", "Closed"}  — both signal a resolved procurement
    3. _winner_name populated

Output: docs/AWARDED_CORPUS.json (UTF-8, indent=2)
Schema per entry:
{
  "tender_id": str,
  "country": str,         # ISO-2 if resolvable, else "?"
  "country_full": str,
  "language": str,        # heuristic from country
  "title_original": str,  # ORIGINAL (non-translated) title
  "title_english": str,   # if available
  "description_original": str,
  "description_english": str,
  "authority": str,
  "cpv_codes": list[str],
  "value_eur": float | None,
  "winner": str | None,
  "award_status": str,
  "publication_date": str,
  "source": str,          # TED / UA / UK / CZ / ...
}
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RELEVANT = ROOT / "data" / "filtered" / "relevant.json"
OUT = ROOT / "docs" / "AWARDED_CORPUS.json"

ISO3_TO_2 = {
    "DEU": "DE", "FRA": "FR", "POL": "PL", "ROU": "RO", "CZE": "CZ",
    "DNK": "DK", "SWE": "SE", "NLD": "NL", "BEL": "BE", "ESP": "ES",
    "ITA": "IT", "AUT": "AT", "CHE": "CH", "LUX": "LU", "SVN": "SI",
    "NOR": "NO", "SVK": "SK", "GBR": "GB", "FIN": "FI", "HRV": "HR",
    "LTU": "LT", "EST": "EE", "BGR": "BG", "HUN": "HU", "PRT": "PT",
    "GRC": "GR", "LVA": "LV", "MLT": "MT", "CYP": "CY", "UKR": "UA",
    "TUR": "TR", "CAN": "CA", "USA": "US", "IRL": "IE",
}

ISO2_NAME = {
    "DE": "Germany", "FR": "France", "PL": "Poland", "RO": "Romania",
    "CZ": "Czech Republic", "DK": "Denmark", "SE": "Sweden",
    "NL": "Netherlands", "BE": "Belgium", "ES": "Spain", "IT": "Italy",
    "AT": "Austria", "CH": "Switzerland", "LU": "Luxembourg",
    "SI": "Slovenia", "NO": "Norway", "SK": "Slovakia",
    "GB": "United Kingdom", "FI": "Finland", "HR": "Croatia",
    "LT": "Lithuania", "EE": "Estonia", "BG": "Bulgaria", "HU": "Hungary",
    "PT": "Portugal", "GR": "Greece", "LV": "Latvia", "UA": "Ukraine",
    "TR": "Turkey",
}

# Heuristic language per country
ISO2_LANG = {
    "DE": "de", "AT": "de", "CH": "de",
    "FR": "fr", "BE": "fr",  # BE has both, default to fr; if NL adapter set then nl
    "PL": "pl", "RO": "ro", "CZ": "cs", "DK": "da", "SE": "sv",
    "NL": "nl", "ES": "es", "IT": "it", "SI": "sl", "NO": "no",
    "SK": "sk", "GB": "en", "FI": "fi", "HR": "hr", "LT": "lt",
    "EE": "et", "BG": "bg", "HU": "hu", "PT": "pt", "GR": "el",
    "LV": "lv", "UA": "uk", "TR": "tr",
}


def _resolve_country(notice: dict) -> tuple[str, str, str]:
    """Return (iso2, country_full, language)."""
    cn = notice.get("_country_normalized") or ""
    iso2 = ""
    if cn:
        for code, name in ISO2_NAME.items():
            if name == cn:
                iso2 = code
                break

    if not iso2:
        ca = notice.get("contracting_authority") or {}
        if isinstance(ca, dict):
            raw = (ca.get("country") or "").split("\n")[0].strip()
            if raw in ISO3_TO_2:
                iso2 = ISO3_TO_2[raw]
            elif raw in ISO2_NAME:
                iso2 = raw

    if not iso2:
        raw = notice.get("_raw") or {}
        ocb = raw.get("organisation-country-buyer") if isinstance(raw, dict) else None
        if ocb:
            code = (ocb[0] if isinstance(ocb, list) else str(ocb)).strip()
            if code in ISO3_TO_2:
                iso2 = ISO3_TO_2[code]

    if not iso2:
        # Try tender_id prefix
        tid = notice.get("tender_id", "")
        if tid.startswith(("UA-", "UK-", "CZ-")):
            iso2 = tid.split("-")[0]
            if iso2 == "UK":
                iso2 = "GB"

    full = ISO2_NAME.get(iso2, "Unknown") if iso2 else "Unknown"
    lang = ISO2_LANG.get(iso2, "?") if iso2 else "?"
    return iso2 or "?", full, lang


def _is_resolved(notice: dict) -> bool:
    """True if procurement is awarded/closed (not still open)."""
    award = notice.get("award")
    if isinstance(award, dict) and award.get("awarded") is True:
        return True
    if (notice.get("_status") or "").strip().lower() in {"awarded", "closed"}:
        return True
    if notice.get("_winner_name"):
        return True
    return False


def _pick_text(*candidates: Any, max_len: int = 4000) -> str:
    """Pick the first non-empty string-ish value, dict-of-langs OK."""
    for c in candidates:
        if not c:
            continue
        if isinstance(c, dict):
            # Multilingual dict: pick non-empty value
            for v in c.values():
                if isinstance(v, str) and v.strip():
                    return v[:max_len].strip()
        elif isinstance(c, str) and c.strip():
            return c[:max_len].strip()
    return ""


def _extract_value_eur(notice: dict) -> float | None:
    v = notice.get("_value_eur_num") or notice.get("_value_num")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    ev = notice.get("estimated_value")
    if isinstance(ev, dict):
        amt = ev.get("amount")
        if isinstance(amt, (int, float)) and amt > 0:
            return float(amt)
    return None


def _extract_winner(notice: dict) -> str | None:
    w = notice.get("_winner_name")
    if w:
        return str(w).strip()
    award = notice.get("award")
    if isinstance(award, dict):
        wn = award.get("winner_name")
        if wn:
            return str(wn).strip()
    return None


def _normalize_cpv(notice: dict) -> list[str]:
    cpvs = notice.get("cpv_codes") or []
    if isinstance(cpvs, list):
        return [str(c)[:8] for c in cpvs if c]
    if isinstance(cpvs, str):
        return [cpvs[:8]]
    return []


def _source(notice: dict) -> str:
    tid = notice.get("tender_id", "")
    if tid.startswith("UA-"):
        return "UA"
    if tid.startswith("UK-"):
        return "UK"
    if tid.startswith("CZ-"):
        return "CZ"
    raw = notice.get("_raw") or {}
    if isinstance(raw, dict) and raw.get("source"):
        return str(raw["source"])
    if re.match(r"^\d+-\d{4}$", tid):
        return "TED"
    return "?"


def main() -> None:
    if not RELEVANT.exists():
        print(f"ERROR: {RELEVANT} not found", file=sys.stderr)
        sys.exit(1)

    with open(RELEVANT, encoding="utf-8") as f:
        notices = json.load(f)

    corpus: list[dict] = []
    for n in notices:
        if not _is_resolved(n):
            continue

        iso2, full, lang = _resolve_country(n)
        title_orig = _pick_text(
            n.get("title"),
            n.get("_title_final"),
            n.get("contract_title"),
            n.get("announcement_title"),
            max_len=600,
        )
        title_en = _pick_text(
            n.get("title_en"),
            n.get("_title_english"),
            max_len=600,
        )
        desc_orig = _pick_text(
            n.get("description"),
            n.get("_description_final"),
            n.get("_raw", {}).get("description") if isinstance(n.get("_raw"), dict) else None,
            max_len=4000,
        )
        desc_en = _pick_text(
            n.get("description_en"),
            n.get("_description_english"),
            max_len=4000,
        )

        authority = ""
        ca = n.get("contracting_authority")
        if isinstance(ca, dict):
            authority = ca.get("name") or ca.get("name_short") or ""
        if not authority:
            authority = n.get("_authority_name") or ""

        award = n.get("award") if isinstance(n.get("award"), dict) else {}
        award_status = "awarded" if award.get("awarded") else (
            (n.get("_status") or "").lower() or "resolved"
        )

        corpus.append({
            "tender_id": n.get("tender_id", ""),
            "country": iso2,
            "country_full": full,
            "language": lang,
            "title_original": title_orig,
            "title_english": title_en,
            "description_original": desc_orig,
            "description_english": desc_en,
            "authority": authority[:160],
            "cpv_codes": _normalize_cpv(n),
            "value_eur": _extract_value_eur(n),
            "winner": _extract_winner(n),
            "award_status": award_status,
            "publication_date": (n.get("publication_date") or n.get("_pub_date") or "")[:10],
            "source": _source(n),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)

    # Summary
    from collections import Counter
    by_country = Counter(c["country"] for c in corpus)
    by_lang = Counter(c["language"] for c in corpus)
    by_source = Counter(c["source"] for c in corpus)

    print(f"Awarded/resolved corpus written to {OUT.relative_to(ROOT)}")
    print(f"  Tenders         : {len(corpus)}")
    print(f"  Countries       : {len(by_country)}")
    print(f"  Top countries   : {dict(by_country.most_common(8))}")
    print(f"  Top languages   : {dict(by_lang.most_common(8))}")
    print(f"  Sources         : {dict(by_source)}")


if __name__ == "__main__":
    main()

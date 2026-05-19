"""
CanadaBuys Adapter — Canada Federal Procurement (CanadaBuys Open Data CSVs)

Data sources:
  newTenderNotice    — Delta feed, updated every 2h (06:15–22:15 UTC-5)
  openTenderNotice   — Full snapshot of currently active tenders, daily
  2025-2026 / 2026-2027 Tender Notice archives — fiscal-year history
  contractHistory    — Awarded contracts with vendor + value, monthly

Licence:
  Contains information licensed under the Open Government Licence – Canada
  https://open.canada.ca/en/open-government-licence-canada

Column naming convention (actual CSV):
  bilingual columns use  -eng / -fra suffixes, e.g.
  title-titre-eng, contractingEntityName-nomEntitContractante-eng

Public API of this module:
  fetch_canadabuys_csvs()       → {file_type: Path}
  parse_canadabuys_csv(path)    → list[dict]
  filter_defence_relevant(rows) → list[dict]   (adds _confidence_tier)

The module also exposes CanadaBuysAdapter for BaseAdapter-compatible usage
from main.py --national ca.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")

# ── Constants ──────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[3]   # ted-scraper/ted-scraper/
_DATA_DIR = _ROOT / "data" / "canada" / "raw"
_CONFIG_DIR = _ROOT / "config"
_CACHE_META_PATH = _DATA_DIR / ".etag_cache.json"

LICENSE_NOTICE = "Contains information licensed under the Open Government Licence – Canada"

CSV_ENDPOINTS: dict[str, str] = {
    "newTender": (
        "https://canadabuys.canada.ca/opendata/pub/"
        "newTenderNotice-nouvelAvisAppelOffres.csv"
    ),
    "openTender": (
        "https://canadabuys.canada.ca/opendata/pub/"
        "openTenderNotice-ouvertAvisAppelOffres.csv"
    ),
    "fy2526": (
        "https://canadabuys.canada.ca/opendata/pub/"
        "2025-2026-TenderNotice-AvisAppelOffres.csv"
    ),
    "fy2627": (
        "https://canadabuys.canada.ca/opendata/pub/"
        "2026-2027-TenderNotice-AvisAppelOffres.csv"
    ),
    "contractHistory": (
        "https://canadabuys.canada.ca/opendata/pub/"
        "contractHistoryComplete-contratsOctroyesComplet.csv"
    ),
}

# Minimum text length for _national_raw_text fallback
_TEXT_MIN_LEN = 80

# ── Column name constants (actual CSV) ────────────────────────────────────────

COL_TITLE_EN    = "title-titre-eng"
COL_TITLE_FR    = "title-titre-fra"
COL_REF         = "referenceNumber-numeroReference"
COL_SOL         = "solicitationNumber-numeroSollicitation"
COL_AMEND_NUM   = "amendmentNumber-numeroModification"
COL_PUB_DATE    = "publicationDate-datePublication"
COL_CLOSE_DATE  = "tenderClosingDate-appelOffresDateCloture"
COL_STATUS_EN   = "tenderStatus-appelOffresStatut-eng"
COL_GSIN        = "gsin-nibs"
COL_GSIN_DESC   = "gsinDescription-nibsDescription-eng"
COL_UNSPSC      = "unspsc"
COL_BUYER_EN    = "contractingEntityName-nomEntitContractante-eng"
COL_ENDUSER_EN  = "endUserEntitiesName-nomEntitesUtilisateurFinal-eng"
COL_DESC_EN     = "tenderDescription-descriptionAppelOffres-eng"
COL_DESC_FR     = "tenderDescription-descriptionAppelOffres-fra"
COL_URL_EN      = "noticeURL-URLavis-eng"
COL_NOTICE_TYPE = "noticeType-avisType-eng"
COL_REGIONS_DEL = "regionsOfDelivery-regionsLivraison-eng"
COL_PROC_CAT    = "procurementCategory-categorieApprovisionnement"

# contractHistory extras
COL_VENDOR_LEGAL = "supplierLegalName-nomLegalFournisseur-eng"
COL_VENDOR_STD   = "supplierStandardizedName-nomNormaliseFournisseur-eng"
COL_CONTRACT_AMT = "contractAmount-montantContrat"
COL_TOTAL_VAL    = "totalContractValue-valeurTotaleContrat"
COL_CONTRACT_CCY = "contractCurrency-contratMonnaie"
COL_AWARD_DATE   = "contractAwardDate-dateAttributionContrat"

# ── Config loaders ─────────────────────────────────────────────────────────────

def _load_gsin_whitelist() -> set[str]:
    """Return set of GSIN code prefixes from config."""
    path = _CONFIG_DIR / "canada_gsin_whitelist.json"
    if not path.exists():
        return {"23", "2310", "2320", "2330", "2340", "2350",
                "2510", "2520", "2530", "2540", "2590", "2610"}
    data = json.loads(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for section_key, section in data.items():
        if section_key.startswith("_"):
            continue
        if isinstance(section, dict):
            codes.update(k for k in section if not k.startswith("_"))
    return codes


def _load_buyer_whitelist() -> dict:
    """Return buyer whitelist dict from config."""
    path = _CONFIG_DIR / "canada_buyer_whitelist.json"
    if not path.exists():
        return {
            "primary": ["national defence", "défense nationale", "dnd",
                        "canadian armed forces", "forces armées canadiennes"],
            "secondary": ["defence construction canada", "dcc"],
            "pspc": ["public works and government services", "pspc", "tpsgc"],
            "enduser_dnd": ["national defence", "dnd"],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "primary":     [p.lower() for p in data.get("primary_buyers", {}).get("patterns", [])],
        "secondary":   [p.lower() for p in data.get("secondary_buyers", {}).get("patterns", [])],
        "pspc":        [p.lower() for p in data.get("pspc_as_procuring_agent", {}).get("patterns", [])],
        "enduser_dnd": [p.lower() for p in data.get("end_user_dnd_patterns", {}).get("patterns", [])],
    }


# Trailer keywords checked in TITLE for high-precision matching
_TRAILER_KW_TITLE = [
    "trailer", "semi-trailer", "semitrailer", "remorque", "semi-remorque",
    "low-bed", "lowbed", "low bed", "flatbed", "cargo trailer", "fuel trailer",
    "tank trailer", "ammunition trailer", "lsvw", "msvs", "hlvw",
    "axle", "essieu", "running gear", "landing gear",
    "mobile kitchen", "field kitchen", "shelter trailer",
]

# Broader keywords for description-level matching (higher false-positive risk)
_TRAILER_KW_DESC = _TRAILER_KW_TITLE + [
    "pintle", "drawbar", "fifth wheel", "suspension", "trailer hitch",
    "container transport", "materiel trailer", "load carrier",
]

# Security keywords → Defence indicator even without DND buyer
_SECURITY_KW = [
    "security clearance", "controlled goods program",
    "secret", "protected b", "protected-b",
]


# ── HTTP session ───────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    s = requests.Session()
    s.verify = _SSL_VERIFY
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,text/csv,*/*",
    })
    return s


# ── ETag / Last-Modified cache ─────────────────────────────────────────────────

def _load_etag_cache() -> dict:
    if _CACHE_META_PATH.exists():
        try:
            return json.loads(_CACHE_META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_etag_cache(cache: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_META_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_canadabuys_csvs(
    file_types: Optional[list[str]] = None,
    force: bool = False,
) -> dict[str, Path]:
    """Download CanadaBuys CSV files to data/canada/raw/.

    Idempotent: skips download when ETag / Last-Modified matches cached value.

    Args:
        file_types: subset of CSV_ENDPOINTS keys to fetch. None = all 5.
        force: bypass ETag cache and always re-download.

    Returns:
        dict mapping file_type → local Path (only files that exist on disk).
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    etag_cache = _load_etag_cache()
    session = _make_session()
    result: dict[str, Path] = {}
    targets = file_types or list(CSV_ENDPOINTS.keys())

    for ftype in targets:
        url = CSV_ENDPOINTS.get(ftype)
        if not url:
            logger.warning(f"Canada: unknown file_type '{ftype}'")
            continue

        local_path = _DATA_DIR / f"{ftype}.csv"
        cached_meta = etag_cache.get(ftype, {})

        # Conditional GET headers
        headers: dict[str, str] = {}
        if not force and local_path.exists():
            if cached_meta.get("etag"):
                headers["If-None-Match"] = cached_meta["etag"]
            elif cached_meta.get("last_modified"):
                headers["If-Modified-Since"] = cached_meta["last_modified"]

        try:
            resp = session.get(url, headers=headers, timeout=120, stream=True)
        except Exception as exc:
            logger.error(f"Canada fetch {ftype}: {exc}")
            if local_path.exists():
                result[ftype] = local_path   # use stale cache
            continue

        if resp.status_code == 304:
            logger.info(f"Canada {ftype}: not modified (304)")
            if local_path.exists():
                result[ftype] = local_path
            continue

        if resp.status_code != 200:
            logger.warning(f"Canada {ftype}: HTTP {resp.status_code}")
            if local_path.exists():
                result[ftype] = local_path
            continue

        # Stream to disk
        size = 0
        with local_path.open("wb") as fh:
            for chunk in resp.iter_content(65536):
                fh.write(chunk)
                size += len(chunk)

        # Update ETag cache
        new_meta: dict = {}
        if resp.headers.get("ETag"):
            new_meta["etag"] = resp.headers["ETag"]
        if resp.headers.get("Last-Modified"):
            new_meta["last_modified"] = resp.headers["Last-Modified"]
        etag_cache[ftype] = new_meta
        _save_etag_cache(etag_cache)

        logger.info(f"Canada {ftype}: downloaded {size // 1024} KB → {local_path.name}")
        result[ftype] = local_path
        time.sleep(0.5)   # polite delay

    return result


def parse_canadabuys_csv(path: Path) -> list[dict]:
    """Parse a CanadaBuys CSV file into a list of row dicts.

    Handles:
    - UTF-8 BOM encoding
    - Spill-over rows (rows without valid publicationDate are dropped)
    - Amendment deduplication: keeps the row with highest amendmentNumber per
      referenceNumber (last amendment = authoritative state)

    Returns list of dicts with the raw CSV column names as keys.
    """
    if not path.exists():
        logger.warning(f"Canada parse: file not found: {path}")
        return []

    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8-sig", errors="replace")

    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        # Drop spill-over rows (Excel wrapping artefacts): no valid pub date
        pub = (row.get(COL_PUB_DATE) or "").strip()
        if not re.match(r"\d{4}-\d{2}-\d{2}", pub):
            continue
        rows.append(dict(row))

    # Deduplicate by referenceNumber, keep highest amendmentNumber
    by_ref: dict[str, dict] = {}
    for row in rows:
        ref = (row.get(COL_REF) or "").strip()
        if not ref:
            ref = (row.get(COL_SOL) or row.get("_row_idx", "")).strip()
        if not ref:
            continue
        existing = by_ref.get(ref)
        if existing is None:
            by_ref[ref] = row
        else:
            try:
                new_amend = int(row.get(COL_AMEND_NUM) or 0)
                old_amend = int(existing.get(COL_AMEND_NUM) or 0)
                if new_amend > old_amend:
                    by_ref[ref] = row
            except (ValueError, TypeError):
                pass

    result = list(by_ref.values())
    logger.info(f"Canada parse {path.name}: {len(rows)} rows → {len(result)} after dedup")
    return result


def filter_defence_relevant(notices: list[dict]) -> list[dict]:
    """Apply multi-stage defence filter to CanadaBuys rows.

    Returns only notices deemed defence-relevant, with added fields:
      _confidence_tier : "high" | "review"
      _match_reason    : comma-separated list of triggered rules

    Filter stages (applied in order; first match wins):
    (HIGH)   1. Primary DND/CAF/CSE buyer + trailer keyword in title
    (HIGH)   2. Primary DND/CAF/CSE buyer + GSIN vehicle code
    (HIGH)   3. PSPC/DCC buyer + DND end-user + trailer keyword in title
    (HIGH)   4. PSPC/DCC buyer + DND end-user + GSIN vehicle code
    (REVIEW) 5. Any DND buyer + trailer keyword in description only
    (REVIEW) 6. GSIN vehicle code + trailer keyword in title (any buyer)
    (REVIEW) 7. Security clearance keyword + trailer keyword in title
    """
    gsin_prefixes = _load_gsin_whitelist()
    buyers = _load_buyer_whitelist()

    def _is_primary_dnd(buyer: str, enduser: str) -> bool:
        combined = buyer + " " + enduser
        return any(p in combined for p in buyers["primary"])

    def _is_secondary(buyer: str) -> bool:
        return any(p in buyer for p in buyers["secondary"])

    def _is_pspc(buyer: str) -> bool:
        return any(p in buyer for p in buyers["pspc"])

    def _is_dnd_enduser(enduser: str) -> bool:
        return any(p in enduser for p in buyers["enduser_dnd"])

    def _has_gsin(gsin: str) -> bool:
        return bool(gsin) and any(gsin.startswith(p) for p in gsin_prefixes)

    def _kw_title(title_en: str, title_fr: str) -> bool:
        combined = title_en + " " + title_fr
        return any(k in combined for k in _TRAILER_KW_TITLE)

    def _kw_desc(desc_en: str, desc_fr: str) -> bool:
        combined = desc_en + " " + desc_fr
        return any(k in combined for k in _TRAILER_KW_DESC)

    def _kw_security(desc_en: str) -> bool:
        return any(k in desc_en for k in _SECURITY_KW)

    result: list[dict] = []
    for row in notices:
        buyer   = (row.get(COL_BUYER_EN)   or "").lower().strip()
        enduser = (row.get(COL_ENDUSER_EN) or "").lower().strip()
        title_en = (row.get(COL_TITLE_EN)  or "").lower()
        title_fr = (row.get(COL_TITLE_FR)  or "").lower()
        desc_en  = (row.get(COL_DESC_EN)   or "").lower()
        desc_fr  = (row.get(COL_DESC_FR)   or "").lower()
        gsin     = (row.get(COL_GSIN)      or "").strip()

        tier = ""
        reason = ""

        if _is_primary_dnd(buyer, enduser) and _kw_title(title_en, title_fr):
            tier, reason = "high", "primary_dnd+kw_title"
        elif _is_primary_dnd(buyer, enduser) and _has_gsin(gsin):
            tier, reason = "high", "primary_dnd+gsin"
        elif (_is_pspc(buyer) or _is_secondary(buyer)) and _is_dnd_enduser(enduser) and _kw_title(title_en, title_fr):
            tier, reason = "high", "pspc_dcc+dnd_enduser+kw_title"
        elif (_is_pspc(buyer) or _is_secondary(buyer)) and _is_dnd_enduser(enduser) and _has_gsin(gsin):
            tier, reason = "high", "pspc_dcc+dnd_enduser+gsin"
        elif _is_primary_dnd(buyer, enduser) and _kw_desc(desc_en, desc_fr):
            tier, reason = "review", "primary_dnd+kw_desc"
        elif _has_gsin(gsin) and _kw_title(title_en, title_fr):
            tier, reason = "review", "gsin+kw_title"
        elif _kw_security(desc_en) and _kw_title(title_en, title_fr):
            tier, reason = "review", "security_kw+kw_title"

        if tier:
            row = dict(row)   # copy before mutating
            row["_confidence_tier"] = tier
            row["_match_reason"] = reason
            result.append(row)

    high = sum(1 for r in result if r["_confidence_tier"] == "high")
    review = len(result) - high
    logger.info(
        f"Canada filter: {len(notices)} → {len(result)} defence-relevant "
        f"({high} high, {review} review)"
    )
    return result


# ── Award enrichment ───────────────────────────────────────────────────────────

def build_award_index(contract_history_path: Path) -> dict[str, dict]:
    """Parse contractHistory CSV and return index keyed by solicitationNumber.

    solicitationNumber (WS-prefixed) is the shared key between contractHistory
    and tender notices (1218 overlaps confirmed in FY2526 vs contractHistory).
    referenceNumber uses different ID formats across the two datasets.

    Returns dict: solicitationNumber → {winner, value, currency, award_date}
    Keeps the record with highest totalContractValue per key.
    """
    if not contract_history_path.exists():
        return {}

    rows = parse_canadabuys_csv(contract_history_path)
    index: dict[str, dict] = {}

    def _upsert(key: str, vendor: str, value: float, currency: str, award_date: str) -> None:
        existing = index.get(key)
        if existing is None or value > existing.get("_value", 0):
            index[key] = {
                "_winner_name": vendor,
                "_value_amount": value if value > 0 else None,
                "_value_currency": currency or "CAD",
                "_award_date": award_date,
                "_value": value,
            }

    for row in rows:
        sol = (row.get(COL_SOL) or "").strip()
        ref = (row.get(COL_REF) or "").strip()
        if not sol and not ref:
            continue
        vendor = (row.get(COL_VENDOR_STD) or row.get(COL_VENDOR_LEGAL) or "").strip()
        try:
            value = float(row.get(COL_TOTAL_VAL) or row.get(COL_CONTRACT_AMT) or 0)
        except (ValueError, TypeError):
            value = 0.0
        currency = (row.get(COL_CONTRACT_CCY) or "CAD").strip()
        award_date = (row.get(COL_AWARD_DATE) or "")[:10]

        # Index by solicitationNumber (primary match key) and referenceNumber
        if sol:
            _upsert(sol, vendor, value, currency, award_date)
        if ref and ref != sol:
            _upsert(ref, vendor, value, currency, award_date)

    logger.info(f"Canada award index: {len(index)} contracts loaded")
    return index


def enrich_with_awards(notices: list[dict], award_index: dict[str, dict]) -> list[dict]:
    """Merge award data into notices using solicitationNumber as primary lookup key."""
    enriched = 0
    for row in notices:
        # Try solicitationNumber first (1218 overlaps), then referenceNumber as fallback
        sol = (row.get(COL_SOL) or "").strip()
        ref = (row.get(COL_REF) or "").strip()
        award = award_index.get(sol) or award_index.get(ref)
        if award and award.get("_winner_name"):
            row.setdefault("_winner_name", award["_winner_name"])
            if award.get("_value_amount"):
                row.setdefault("_value_amount", award["_value_amount"])
                row.setdefault("_value_currency", award["_value_currency"])
            if award.get("_award_date"):
                row.setdefault("_award_date", award["_award_date"])
            enriched += 1
    logger.info(f"Canada award enrich: {enriched}/{len(notices)} notices enriched")
    return notices


# ── Status mapping ─────────────────────────────────────────────────────────────

def _map_status(raw: str) -> str:
    s = (raw or "").lower().strip()
    if s in ("open", "ouvert"):
        return "Open"
    if s in ("awarded", "attribué", "attribue"):
        return "Awarded"
    if s in ("cancelled", "annulé", "annule"):
        return "Cancelled"
    if s in ("expired", "expiré", "expire", "closed", "fermé", "ferme"):
        return "Closed"
    return "Open"   # default for active tenders


# ── Standard format conversion ─────────────────────────────────────────────────

def to_standard_format(row: dict) -> dict:
    """Convert a CanadaBuys row to the pipeline's standard notice format.

    Schema-compatible with TED notices and other national adapters.
    """
    ref     = (row.get(COL_REF)    or "").strip()
    sol     = (row.get(COL_SOL)    or "").strip()
    title_en = (row.get(COL_TITLE_EN) or row.get(COL_TITLE_FR) or "").strip()
    title_fr = (row.get(COL_TITLE_FR) or "").strip()
    pub_date = (row.get(COL_PUB_DATE) or "")[:10]
    close_date = (row.get(COL_CLOSE_DATE) or "")[:10]
    # strip time component if present: "2026-05-31T14:00:00" → "2026-05-31"
    if "T" in close_date:
        close_date = close_date.split("T")[0]
    status_raw = (row.get(COL_STATUS_EN) or "open").strip()
    buyer   = (row.get(COL_BUYER_EN) or "Department of National Defence (Canada)").strip()
    desc_en = (row.get(COL_DESC_EN) or "").strip()
    desc_fr = (row.get(COL_DESC_FR) or "").strip()
    url_en  = (row.get(COL_URL_EN) or "").strip()
    gsin    = (row.get(COL_GSIN)    or "").strip()
    gsin_desc = (row.get(COL_GSIN_DESC) or "").strip()
    notice_type = (row.get(COL_NOTICE_TYPE) or "").strip()
    regions = (row.get(COL_REGIONS_DEL) or "").strip()
    enduser = (row.get(COL_ENDUSER_EN) or "").strip()

    # Build canonical tender_id
    base_id = ref or sol
    tender_id = f"CA-{base_id}" if base_id and not base_id.startswith("CA-") else base_id

    # Fallback source URL
    if not url_en and sol:
        url_en = (
            f"https://canadabuys.canada.ca/en/tender-opportunities"
            f"/tender-notice/{sol}"
        )

    # Build raw_text for national_raw_text / doc-pipeline fallback
    raw_parts = [f"TITLE: {title_en}"]
    if title_fr and title_fr != title_en:
        raw_parts.append(f"TITRE (FR): {title_fr}")
    if gsin:
        raw_parts.append(f"GSIN: {gsin} {gsin_desc}".strip())
    if notice_type:
        raw_parts.append(f"NOTICE TYPE: {notice_type}")
    if regions:
        raw_parts.append(f"REGIONS: {regions}")
    if enduser:
        raw_parts.append(f"END USER: {enduser}")
    if desc_en:
        raw_parts.append(f"DESCRIPTION:\n{desc_en[:3000]}")
    elif desc_fr:
        raw_parts.append(f"DESCRIPTION (FR):\n{desc_fr[:3000]}")
    raw_text = "\n".join(raw_parts)

    # Award / winner fields from award enrichment
    winner = row.get("_winner_name", "")
    value  = row.get("_value_amount")
    if value is None:
        # Sometimes contractAmount appears in the row directly (contractHistory)
        try:
            v = float(row.get(COL_CONTRACT_AMT) or row.get(COL_TOTAL_VAL) or 0)
            value = v if v > 0 else None
        except (ValueError, TypeError):
            value = None

    return {
        "tender_id":               tender_id,
        "source":                  "CA-CB",
        "source_url_national":     url_en,
        "_title_final":            title_en[:200],
        "_title_english":          title_en[:200],
        "_country_normalized":     "Canada",
        "_authority_name":         buyer[:100],
        "_pub_date_clean":         pub_date,
        "_value_amount":           value,
        "_value_currency":         row.get("_value_currency", "CAD"),
        "_winner_name":            winner,
        "ted_url":                 "",
        "_description_final":      desc_en[:500] or desc_fr[:500],
        "_national_raw_text":      raw_text[:10000],
        "_status":                 _map_status(status_raw),

        # CA-specific extras
        "_gsin":                   gsin,
        "_gsin_description":       gsin_desc,
        "_notice_type":            notice_type,
        "_solicitation_number":    sol,
        "_closing_date":           close_date,
        "_confidence_tier":        row.get("_confidence_tier", ""),
        "_match_reason":           row.get("_match_reason", ""),
        "_license_notice":         LICENSE_NOTICE,

        # _pub_date_clean above is the CanadaBuys openTenderNotice publicationDate
        # (i.e. RFP/RSO/RFSO go-live). See docs/DATE_AUDIT_260520.md.
        "_published_at_source":    "tender_notice",

        # AI classification placeholders
        "_trailer_type_1_ai":      None,
        "_trailer_category_1_ai":  None,
        "_trailer_qty_1_ai":       None,
        "_ai":                     {},
        "_overflow_ai":            {},
    }


# ── High-level loader (used by main.py --national ca) ─────────────────────────

def load_canadabuys(
    file_types: Optional[list[str]] = None,
    with_awards: bool = True,
    force_download: bool = False,
    test_mode: bool = False,
) -> list[dict]:
    """Full pipeline: fetch → parse → filter → award-enrich → normalize.

    Args:
        file_types:      which CSV files to load (default: openTender + fy2627)
        with_awards:     also download contractHistory and enrich with vendor names
        force_download:  bypass ETag cache
        test_mode:       limit to fy2627 only (smaller, faster)

    Returns list of pipeline-compatible notice dicts.
    """
    if test_mode:
        file_types = ["fy2627"]
    elif file_types is None:
        # fy2526 = current FY archive (highest contractHistory overlap: 1218 matches)
        file_types = ["openTender", "fy2627", "fy2526"]

    if with_awards and not test_mode:
        file_types = list(set(file_types) | {"contractHistory"})

    # 1. Download
    paths = fetch_canadabuys_csvs(file_types=file_types, force=force_download)

    # 2. Parse + merge all tender files
    all_rows: dict[str, dict] = {}
    tender_files = [ft for ft in file_types if ft != "contractHistory"]
    for ftype in tender_files:
        path = paths.get(ftype)
        if path:
            for row in parse_canadabuys_csv(path):
                ref = (row.get(COL_REF) or "").strip()
                if ref and ref not in all_rows:
                    all_rows[ref] = row

    logger.info(f"Canada: {len(all_rows)} unique tender records from {tender_files}")

    # 3. Filter
    filtered = filter_defence_relevant(list(all_rows.values()))

    # 4. Award enrichment
    if with_awards and not test_mode:
        hist_path = paths.get("contractHistory")
        if hist_path:
            award_idx = build_award_index(hist_path)
            enrich_with_awards(filtered, award_idx)

    # 5. Normalize
    normalized = [to_standard_format(row) for row in filtered]
    logger.info(f"Canada: {len(normalized)} defence-relevant notices ready for pipeline")
    return normalized


# ── BaseAdapter-compatible wrapper ─────────────────────────────────────────────
# Allows --national ca registration in main.py using the standard pattern.

try:
    from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

    class CanadaBuysAdapter(BaseAdapter):
        """Thin BaseAdapter wrapper around the CSV-based CanadaBuys pipeline."""

        def __init__(self, browser, config: AdapterConfig):
            super().__init__(browser, config)
            self._notices: Optional[list[dict]] = None

        def search(self, keyword: str, max_results: int = 50) -> list:
            """Return SearchResult list — delegates to CSV pipeline."""
            if self._notices is None:
                test_mode = getattr(self.browser, "_test_mode", False)
                self._notices = load_canadabuys(test_mode=test_mode)
            results = []
            kw = keyword.lower()
            for n in self._notices:
                title = (n.get("_title_final") or "").lower()
                desc  = (n.get("_description_final") or "").lower()
                if kw in title or kw in desc:
                    results.append(SearchResult(
                        title=n.get("_title_final", ""),
                        url=n.get("source_url_national", ""),
                        authority=n.get("_authority_name", ""),
                        date=n.get("_pub_date_clean", ""),
                        reference_id=n.get("tender_id", ""),
                        snippet=desc[:200],
                    ))
            return results[:max_results]

        def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
            """Notices are fully parsed at search time; no separate fetch needed."""
            if self._notices is None:
                return None
            for n in self._notices:
                if n.get("tender_id") == result.reference_id:
                    return NoticeDetail(
                        title=n.get("_title_final", ""),
                        description=n.get("_description_final", ""),
                        authority=n.get("_authority_name", ""),
                        date=n.get("_pub_date_clean", ""),
                        winner=n.get("_winner_name", ""),
                        deadline=n.get("_closing_date", ""),
                        reference_id=result.reference_id,
                        url=result.url,
                        source_code="CA-CB",
                        raw_text=n.get("_national_raw_text", ""),
                        status=n.get("_status", ""),
                    )
            return None

        def search_all_keywords(self, max_results_per_keyword: int = 30,
                                test_mode: bool = False) -> list:
            """Return all defence-relevant notices directly (no keyword loop needed)."""
            if self._notices is None:
                self._notices = load_canadabuys(test_mode=test_mode)
            return [
                SearchResult(
                    title=n.get("_title_final", ""),
                    url=n.get("source_url_national", ""),
                    authority=n.get("_authority_name", ""),
                    date=n.get("_pub_date_clean", ""),
                    reference_id=n.get("tender_id", ""),
                )
                for n in self._notices
            ]

        def to_standard_format(self, detail: NoticeDetail) -> dict:
            """Find the cached notice and return its standard format dict."""
            if self._notices:
                for n in self._notices:
                    if n.get("tender_id") == detail.reference_id:
                        return n
            return super().to_standard_format(detail)

        def _default_currency(self) -> str:
            return "CAD"

    def create_canada_config() -> AdapterConfig:
        return AdapterConfig(
            country_name="Canada",
            country_code="CA",
            source_code="CA-CB",
            base_url="https://canadabuys.canada.ca",
            search_url="https://canadabuys.canada.ca/en/tender-opportunities",
            language="en",
            trailer_keywords=["trailer", "remorque", "axle", "lsvw", "msvs"],
            defence_authorities=["national defence", "dnd", "defence construction"],
        )

except ImportError:
    # Standalone usage without the full adapter framework
    pass

"""
Canada Open Data Loader

Two data sources:
1. Historical contracts (CKAN Datastore API) — completed DND contracts since ~2009
   Dataset: Proactive Publication - Contracts
   Resource: fac950c0-00d5-4ec1-a4d3-9cbebf98a305

2. Active/recent tender notices (CanadaBuys Open Data CSVs) — updated every 2h
   Source: open.canada.ca, dataset 6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2
   Files: open tenders (currently active), yearly archives (2022-2027)
   Access: canadabuys.canada.ca CSV files, no login needed, Browser UA required

Active tenders get source="CA-CB" (CanadaBuys) and go into the main pipeline.
Historical contracts keep source="CA-OD" and appear in the Canada (Historical) Excel tab.
"""

import logging
import json
import os
import io
import csv
import requests
import urllib3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "") != "1"

CKAN_BASE = "https://open.canada.ca/data/api/3/action"
DATASET_ID = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
RESOURCE_ID = "fac950c0-00d5-4ec1-a4d3-9cbebf98a305"

DND_ORG = "dnd-mdn"

# CanadaBuys CSV URLs (updated every 2 hours)
CB_OPEN_TENDERS_URL   = "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"
CB_YEARLY_URLS = [
    "https://canadabuys.canada.ca/opendata/pub/2026-2027-TenderNotice-AvisAppelOffres.csv",
    "https://canadabuys.canada.ca/opendata/pub/2025-2026-TenderNotice-AvisAppelOffres.csv",
    "https://canadabuys.canada.ca/opendata/pub/2024-2025-TenderNotice-AvisAppelOffres.csv",
]

# DND filter terms (column values in CanadaBuys CSVs)
DND_TERMS = [
    "national defence", "défense nationale", "department of national defence",
    "ministère de la défense nationale", "dnd-mdn",
]

TRAILER_KEYWORDS_EN = [
    "trailer",
    "semi-trailer",
    "semitrailer",
    "low-bed",
    "lowbed",
    "tank trailer",
    "fuel trailer",
    "field kitchen",
    "container trailer",
    "flatbed trailer",
    "flatbed",
    "hook lift",
    "hooklift",
    "ammunition trailer",
    "loading system",
    "low loader",
    "cargo trailer",
    "remorque",
    "pintle",
    "shelter",
    "cisterne",
    "semi-remorque",
]


class CanadaOpenDataLoader:
    """Loads Canadian DND procurement data from open.canada.ca."""

    def __init__(self, cache_dir: str = "data/raw/canada"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.verify = SSL_VERIFY
        # CanadaBuys requires a browser-like User-Agent for CSV access
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml,text/csv,*/*",
        })

    def discover_all_resource_urls(self) -> list:
        """Return all resources for the dataset (for transparency/debugging)."""
        try:
            resp = self._session.get(
                f"{CKAN_BASE}/package_show",
                params={"id": DATASET_ID},
                timeout=30,
            )
            resp.raise_for_status()
            resources = resp.json().get("result", {}).get("resources", [])
            return [
                {
                    "name": r.get("name", ""),
                    "format": r.get("format", ""),
                    "url": r.get("url", ""),
                }
                for r in resources
            ]
        except Exception as e:
            logger.error(f"Resource discovery failed: {e}")
            return []

    def _datastore_search(self, keyword: str, offset: int = 0, limit: int = 1000) -> dict:
        """
        Query the CKAN Datastore for DND contracts matching a keyword in description_en.

        Uses per-field q dict: {"description_en": keyword, "owner_org": "dnd-mdn"}
        """
        try:
            resp = self._session.get(
                f"{CKAN_BASE}/datastore_search",
                params={
                    "resource_id": RESOURCE_ID,
                    "q": json.dumps({"description_en": keyword, "owner_org": DND_ORG}),
                    "limit": limit,
                    "offset": offset,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                logger.warning(f"CKAN API error for keyword '{keyword}': {data.get('error')}")
                return {}
            return data.get("result", {})
        except Exception as e:
            logger.error(f"Datastore search failed for keyword '{keyword}': {e}")
            return {}

    def _fetch_all_for_keyword(self, keyword: str) -> list:
        """Paginate through all results for a given keyword."""
        all_records = []
        offset = 0
        limit = 1000

        first_page = self._datastore_search(keyword, offset=0, limit=limit)
        total = first_page.get("total", 0)
        records = first_page.get("records", [])
        all_records.extend(records)

        logger.info(f"  DND '{keyword}': {total} total records, fetching...")

        while len(all_records) < total and records:
            offset += limit
            page = self._datastore_search(keyword, offset=offset, limit=limit)
            records = page.get("records", [])
            all_records.extend(records)

        return all_records

    def load_and_filter(self, test_mode: bool = False) -> list:
        """Query DND contracts for all trailer keywords, deduplicate, and cache."""
        cache_path = self.cache_dir / "canada_filtered.json"
        if cache_path.exists():
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            logger.info(f"Canada: {len(cached)} cached results")
            return cached

        all_records: dict = {}  # keyed by reference_number for dedup

        keywords = TRAILER_KEYWORDS_EN if not test_mode else TRAILER_KEYWORDS_EN[:3]

        for kw in keywords:
            records = self._fetch_all_for_keyword(kw)
            for rec in records:
                ref = rec.get("reference_number", "")
                if ref and ref not in all_records:
                    all_records[ref] = rec

            if test_mode and len(all_records) >= 10:
                break

        matches = [self._normalize_row(rec) for rec in all_records.values()]
        logger.info(f"Canada: {len(matches)} unique DND trailer contracts found")

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)

        return matches

    def _normalize_row(self, row: dict) -> dict:
        """Normalize a CKAN datastore record to our standard notice format."""
        return {
            "tender_id": f"CA-{row.get('reference_number', '')}",
            "source": "CA-OD",
            "title": (
                row.get("description_en") or row.get("description_fr", "")
            )[:200],
            "authority": "Department of National Defence (Canada)",
            "country": "Canada",
            "value": row.get("contract_value", row.get("original_value", "")),
            "currency": "CAD",
            "date": row.get("contract_date", row.get("contract_period_start", "")),
            "winner": row.get("vendor_name", ""),
            "description": (
                row.get("description_en", row.get("description_fr", ""))
            )[:500],
        }

    # ── CanadaBuys Active Tenders ─────────────────────────────────────────

    def load_active_tenders(self, test_mode: bool = False,
                            years_back: int = 2) -> list:
        """
        Load active/recent DND trailer tenders from CanadaBuys Open Data CSVs.

        Downloads:
        1. Open tender notices (currently active, updated every 2h)
        2. Yearly archives for the last `years_back` fiscal years

        Returns list of normalized notice dicts with source="CA-CB".
        """
        cache_path = self.cache_dir / "canadabuys_tenders.json"
        if cache_path.exists() and not test_mode:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            logger.info(f"CanadaBuys: {len(cached)} cached active/recent tenders")
            return cached

        all_rows: dict = {}  # keyed by referenceNumber for dedup

        # 1. Currently open tenders
        open_rows = self._fetch_cb_csv(CB_OPEN_TENDERS_URL, "open tenders")
        for r in open_rows:
            key = r.get("referenceNumber-numeroReference", "")
            if key and key not in all_rows:
                all_rows[key] = r

        # 2. Recent yearly archives
        limit = 1 if test_mode else years_back
        for url in CB_YEARLY_URLS[:limit]:
            year_rows = self._fetch_cb_csv(url, url.split("/")[-1][:20])
            for r in year_rows:
                key = r.get("referenceNumber-numeroReference", "")
                if key and key not in all_rows:
                    all_rows[key] = r

        # Filter for DND + trailer keywords
        dnd_trailer = [r for r in all_rows.values()
                       if self._is_dnd_cb(r) and self._is_trailer_cb(r)]

        logger.info(f"CanadaBuys: {len(dnd_trailer)} DND trailer tenders "
                    f"(from {len(all_rows)} total)")

        normalized = [self._normalize_tender_row(r) for r in dnd_trailer]

        if not test_mode:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(normalized, f, ensure_ascii=False, indent=2)

        return normalized

    def _fetch_cb_csv(self, url: str, label: str) -> list:
        """Download a CanadaBuys CSV and return rows as list of dicts."""
        try:
            resp = self._session.get(url, timeout=60)
            if resp.status_code == 200:
                text = resp.content.decode("utf-8-sig", errors="replace")
                rows = list(csv.DictReader(io.StringIO(text)))
                logger.info(f"CanadaBuys {label}: {len(rows)} rows")
                return rows
            else:
                logger.warning(f"CanadaBuys {label}: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"CanadaBuys {label} download error: {e}")
        return []

    @staticmethod
    def _is_dnd_cb(row: dict) -> bool:
        """Check if a CanadaBuys row is from DND."""
        text = " ".join(str(v) for v in row.values()).lower()
        return any(d in text for d in DND_TERMS)

    @staticmethod
    def _is_trailer_cb(row: dict) -> bool:
        """Check if a CanadaBuys row is trailer-related."""
        title_en = str(row.get("title-titre-eng", "")).lower()
        title_fr = str(row.get("title-titre-fra", "")).lower()
        desc_en  = str(row.get("tenderDescription-descriptionAppelOffres-eng", "")).lower()
        desc_fr  = str(row.get("tenderDescription-descriptionAppelOffres-fra", "")).lower()
        combined = f"{title_en} {title_fr} {desc_en} {desc_fr}"
        return any(kw in combined for kw in TRAILER_KEYWORDS_EN)

    def _normalize_tender_row(self, row: dict) -> dict:
        """Normalize a CanadaBuys CSV row to our standard notice format."""
        ref = row.get("referenceNumber-numeroReference", "")
        sol = row.get("solicitationNumber-numeroSollicitation", "")
        title_en = row.get("title-titre-eng", "") or row.get("title-titre-fra", "")
        title_fr = row.get("title-titre-fra", "")
        pub_date  = row.get("publicationDate-datePublication", "")[:10]
        close_date = row.get("tenderClosingDate-appelOffresDateCloture", "")[:10]
        status    = row.get("tenderStatus-appelOffresStatut-eng", "Open")
        authority = (row.get("contractingEntityName-nomEntitContractante-eng", "")
                     or "Department of National Defence (Canada)")
        desc_en   = row.get("tenderDescription-descriptionAppelOffres-eng", "")[:500]
        url_en    = row.get("noticeURL-URLavis-eng", "")
        gsin      = row.get("gsin-nibs", "")
        gsin_desc = row.get("gsinDescription-nibsDescription-eng", "")

        # CanadaBuys source URL on the portal
        if not url_en and sol:
            url_en = f"https://canadabuys.canada.ca/en/tender-opportunities/tender-notice/{sol}"

        return {
            "tender_id": f"CA-CB-{ref}" if ref else f"CA-CB-{sol}",
            "source": "CA-CB",
            "_source": "CA-CB",
            "_source_url_national": url_en,
            "ted_url": "",
            "_title_final": title_en[:200],
            "_title_english": title_en[:200],
            "_country_normalized": "Canada",
            "_authority_name": authority[:100],
            "_pub_date": pub_date,
            "_status": "Open" if not close_date or close_date >= "2026-01-01" else "Closed",
            "_value_num": None,
            "_value_currency": "CAD",
            "_value_eur_num": None,
            "_description_final": desc_en,
            "_trailer_type_1_ai": None,   # will be classified later
            "_trailer_category_1_ai": None,
            "_trailer_qty_1_ai": None,
            "title": title_en,
            "title_fr": title_fr,
            "closing_date": close_date,
            "solicitation_number": sol,
            "gsin": gsin,
            "gsin_description": gsin_desc,
            "country": "Canada",
            "currency": "CAD",
        }

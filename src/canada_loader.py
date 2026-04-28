"""
Canada Open Data Loader

Queries Canadian DND procurement contract data via the open.canada.ca
CKAN Datastore API. Only historical/completed contracts — no open tenders.
Useful for market sizing and competitor analysis.

Dataset: Proactive Publication - Contracts
URL: https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b
API resource: fac950c0-00d5-4ec1-a4d3-9cbebf98a305
"""

import logging
import json
import os
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

TRAILER_KEYWORDS_EN = [
    "trailer",
    "semi-trailer",
    "semitrailer",
    "low-bed",
    "tank trailer",
    "fuel trailer",
    "field kitchen",
    "container trailer",
    "flatbed trailer",
    "hook lift",
    "ammunition trailer",
    "loading system",
    "low loader",
    "cargo trailer",
    "remorque",
]


class CanadaOpenDataLoader:
    """Loads Canadian DND procurement data via the open.canada.ca CKAN Datastore API."""

    def __init__(self, cache_dir: str = "data/raw/canada"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.verify = SSL_VERIFY

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

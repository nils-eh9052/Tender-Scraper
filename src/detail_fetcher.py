"""
Phase 2: Detail Fetcher – Fetch full notice data for all indexed notices.

- Reads the index from Phase 1
- Fetches full detail for each notice via the Search API (with expanded fields)
- Saves each notice as individual JSON (crash-safe)
- Supports resume from checkpoint

Note: The TED detail endpoint (GET /v3/notices/{id}) requires authentication.
Instead, we re-query the search API with publication-number and request all
detail fields. This is slower (one query per notice) but works without auth.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from .api_client import TedApiClient

logger = logging.getLogger(__name__)


def _first_value(field: Any) -> Optional[str]:
    """Return the first scalar value of a TED API field (list / str / None)."""
    if field is None:
        return None
    if isinstance(field, list):
        for item in field:
            if item not in (None, ""):
                return item if isinstance(item, str) else str(item)
        return None
    if isinstance(field, dict):
        for v in field.values():
            if isinstance(v, list) and v:
                return v[0] if isinstance(v[0], str) else str(v[0])
            if v not in (None, ""):
                return v if isinstance(v, str) else str(v)
        return None
    return str(field)


_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _clean_iso_date(value: Any) -> Optional[str]:
    """Strip TED timezone-suffix (``2025-04-16+02:00`` → ``2025-04-16``)."""
    if not value:
        return None
    m = _ISO_DATE_RE.match(str(value))
    return m.group(1) if m else None


class DetailFetcher:
    """Fetches and stores full detail data for indexed notices."""

    def __init__(self, config: dict, raw_dir: str = "data/raw"):
        self.config = config
        self.raw_dir = Path(raw_dir)
        self.details_dir = self.raw_dir / "details"
        self.details_dir.mkdir(parents=True, exist_ok=True)
        self.client = TedApiClient(config)

    def _get_fetched_ids(self) -> set[str]:
        """Get set of notice IDs already fetched (for resume)."""
        fetched = set()
        for f in self.details_dir.glob("*.json"):
            fetched.add(f.stem)
        return fetched

    def _save_detail(self, notice_id: str, data: dict):
        """Save notice detail as individual JSON file."""
        safe_id = notice_id.replace("/", "_").replace("\\", "_")
        path = self.details_dir / f"{safe_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _normalize_notice(self, raw: dict, notice_id: str) -> dict:
        """
        Normalize the TED Search API response into our standard structure.

        The search API returns multilingual fields as dicts like:
        {"eng": ["value"], "deu": ["value"], ...}
        We extract the best available language version.
        """
        def get_text(field_data, prefer_langs=("eng", "deu", "fra")):
            """Extract text from multilingual field."""
            if field_data is None:
                return None
            if isinstance(field_data, str):
                return field_data
            if isinstance(field_data, list):
                return "\n".join(str(v) for v in field_data if v) if field_data else None
            if isinstance(field_data, dict):
                # Try preferred languages first
                for lang in prefer_langs:
                    if lang in field_data:
                        val = field_data[lang]
                        if isinstance(val, list):
                            return "\n".join(str(v) for v in val if v) if val else None
                        return val
                # Fallback: first available language
                for val in field_data.values():
                    if isinstance(val, list):
                        return "\n".join(str(v) for v in val if v) if val else None
                    return val
            return None

        def get_list(field_data):
            """Extract list from field."""
            if isinstance(field_data, list):
                return field_data
            if isinstance(field_data, str):
                return [field_data]
            return []

        normalized = {
            "tender_id": notice_id,
            "publication_number": raw.get("publication-number", notice_id),
            "ted_url": f"https://ted.europa.eu/en/notice/-/detail/{notice_id}",

            # Basic fields
            "title": get_text(raw.get("notice-title")),
            "announcement_title": get_text(raw.get("announcement-title")),
            "contract_title": get_text(raw.get("contract-title")),
            "description": get_text(raw.get("description-lot")
                                    or raw.get("description-proc")
                                    or raw.get("description-part")),

            # Authority
            "contracting_authority": {
                "name": get_text(raw.get("buyer-name")),
                "country": (get_text(raw.get("organisation-country-buyer"))
                            or self._extract_country_from_title(
                                get_text(raw.get("notice-title")))),
            },

            # Classification
            "cpv_codes": get_list(raw.get("classification-cpv")),
            "legal_basis": get_text(raw.get("legal-basis")
                                    or raw.get("legal-basis-proc")
                                    or raw.get("legal-basis-notice")),

            # Dates
            "publication_date": get_text(raw.get("publication-date")),
            "submission_deadline": get_text(raw.get("deadline-receipt-tender-date-lot")),

            # Value
            "estimated_value": None,

            # Award
            "award": None,

            # Links (from search API)
            "links": raw.get("links", {}),

            # Keep raw for re-processing
            "_raw": raw,
        }

        # Extract value
        total_value = raw.get("total-value")
        total_value_cur = raw.get("total-value-cur")
        if total_value is not None:
            val = total_value
            if isinstance(val, list):
                val = val[0] if val else None
            if isinstance(val, dict):
                # Try to get first value
                for v in val.values():
                    val = v[0] if isinstance(v, list) else v
                    break
            if val is not None:
                normalized["estimated_value"] = {
                    "amount": val,
                    "currency": get_text(total_value_cur) or "EUR",
                }

        # Extract award info
        winner_name = get_text(raw.get("winner-name"))
        if winner_name:
            normalized["award"] = {
                "awarded": True,
                "winner_name": winner_name,
                "winner_country": get_text(raw.get("winner-country")),
                "award_date": get_text(raw.get("winner-decision-date")),
            }

        # Sprint 2026-05-18 — TED Quick-Wins: surface 4 eForms fields as
        # top-level shortcuts so downstream phases (contract_type, exporter,
        # award_matcher) don't need to dig through _raw. See
        # docs/TED_DEEP_RESEARCH_260517.md §4.2 for code semantics.
        ft = _first_value(raw.get("framework-agreement-lot"))
        if ft:
            normalized["_framework_type"] = ft  # "fa-wo-rc" | "fa-w-rc" | "fa-mix" | "none"
        ccd = _first_value(raw.get("contract-conclusion-date"))
        if ccd:
            normalized["_contract_conclusion_date"] = _clean_iso_date(ccd)
        auth_struct = get_text(raw.get("organisation-name-buyer"))
        if auth_struct:
            normalized["_authority_name_structured"] = auth_struct
        auth_id = _first_value(raw.get("organisation-identifier-buyer"))
        if auth_id:
            normalized["_authority_id"] = str(auth_id)

        return normalized

    @staticmethod
    def _extract_country_from_title(title: str) -> Optional[str]:
        """
        Extract country from TED notice title format: "Country-City: Description"
        e.g. "Finland-Tampere: Refuelling trailers" -> "Finland"
        """
        if not title or "-" not in title:
            return None
        country = title.split("-")[0].strip()
        # Sanity check: country should be a short word
        if country and len(country) < 30 and country[0].isupper():
            return country
        return None

    # ──────────────────────────────────────────────
    # Main fetch pipeline
    # ──────────────────────────────────────────────

    def fetch_all_details(self, index_path: str = "data/raw/notice_index.json",
                          limit: Optional[int] = None) -> int:
        """
        Fetch details for all notices in the index.

        Args:
            index_path: Path to the index JSON from Phase 1
            limit: Optional limit for testing (fetch only N notices)

        Returns:
            Number of successfully fetched notices
        """
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)

        notice_ids = list(index.get("notices", {}).keys())
        if limit:
            notice_ids = notice_ids[:limit]

        already_fetched = self._get_fetched_ids()
        to_fetch = [nid for nid in notice_ids if nid not in already_fetched]

        logger.info(f"Total in index: {len(notice_ids)}")
        logger.info(f"Already fetched: {len(already_fetched)}")
        logger.info(f"To fetch: {len(to_fetch)}")

        success_count = 0
        for i, notice_id in enumerate(to_fetch):
            raw_detail = self.client.get_notice_detail(notice_id)

            if raw_detail:
                detail = self._normalize_notice(raw_detail, notice_id)
                self._save_detail(notice_id, detail)
                success_count += 1
            else:
                logger.warning(f"Failed to fetch {notice_id}")
                self._save_detail(notice_id, {
                    "tender_id": notice_id,
                    "_fetch_failed": True,
                    "_error": "API returned no data"
                })

            if (i + 1) % 25 == 0:
                logger.info(
                    f"Progress: {i+1}/{len(to_fetch)} "
                    f"({success_count} successful)"
                )

        logger.info(f"Detail fetch complete: {success_count}/{len(to_fetch)} successful")
        return success_count

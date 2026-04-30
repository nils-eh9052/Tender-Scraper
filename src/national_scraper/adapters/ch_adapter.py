"""
Switzerland Adapter - simap.ch (Schweizerisches Interoperables Meldewesen
fuer das Oeffentliche Beschaffungswesen / Systeme d'information sur les marches
publics en Suisse)

Discovered structure (2026-04-30):
  REST API: https://www.simap.ch/api/publications/v2/project/project-search
  No authentication required for public search.
  Technology: React SPA (DarvinSSR by Unic AG) with backend REST API.

Key API parameters:
  search           : free-text keyword search
  lang             : de | fr | it | en
  cpvCodes         : CPV code filter (comma-separated)
  newestPubTypes   : tender | award | advance_notice | request_for_information
  newestPublicationFrom / newestPublicationUntil : YYYY-MM-DD
  itemsPerPage     : page size (max ~100)
  lastItem         : cursor pagination (YYYYMMDD|projectNumber)

Detail endpoints:
  GET /api/publications/v2/project/{projectId}/project-header?lang=en
  GET /api/publications/v1/project/{projectId}/publication-details/{pubId}?lang=en

Note: Switzerland is not EU/EWR, so NO overlap with TED. All findings are new.

Defence procurement authorities:
  armasuisse (Bundesamt fuer Ruestung / Office federal de l'armement)
  Logistikbasis der Armee (LBA / Base logistique de l'armee)
  VBS/DDPS (Eidg. Departement fuer Verteidigung)
  Schweizer Armee

Trailer CPV codes (same international standard):
  34223000 Trailers and semi-trailers
  34223300 Trailers (general)
  34223100 Semi-trailers
  34221000 Special-purpose mobile containers
  35000000 Security/defence/police equipment (broad)
"""

import re
import time
import logging
import os
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

SIMAP_BASE = "https://www.simap.ch"
SIMAP_API_SEARCH = f"{SIMAP_BASE}/api/publications/v2/project/project-search"
SIMAP_API_HEADER = f"{SIMAP_BASE}/api/publications/v2/project/{{project_id}}/project-header"
SIMAP_API_DETAIL = f"{SIMAP_BASE}/api/publications/v1/project/{{project_id}}/publication-details/{{pub_id}}"
SIMAP_NOTICE_URL = f"{SIMAP_BASE}/en/project-detail/{{project_id}}"

# Defence keyword substrings for filtering nomacheteur/authority
CH_DEFENCE_PATTERNS = [
    "armasuisse", "bundesamt fur rustung", "office federal de l'armement",
    "ufficio federale dell'armamento", "logistikbasis der armee",
    "base logistique de l'armee", "base logistica dell'esercito",
    "vbs", "ddps", "schweizer armee", "armee suisse",
    "armée suisse", "schweizerische armee",
]

# CPV codes for trailers (simap uses full 8-digit CPV)
TRAILER_CPV_CODES = [
    "34223000", "34223100", "34223200", "34223300",
    "34221000", "34224100",
]

# Defence CPV codes
DEFENCE_CPV_CODES = [
    "35000000", "35600000", "35610000", "35400000",
]


def create_ch_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Switzerland",
        country_code="CH",
        source_code="CH-SI",
        base_url=SIMAP_BASE,
        search_url=SIMAP_API_SEARCH,
        language="de",
        trailer_keywords=[
            # German (proper umlauts — simap.ch full-text search requires them)
            "Anhänger",
            "Sattelanhänger",
            "Tieflader",
            "Tankanhänger",
            "Feldküche",
            "Wechselaufbau",
            "Shelter",
            # French
            "remorque",
            "semi-remorque",
            "cuisine roulante",
            # Italian
            "rimorchio",
            "semirimorchio",
        ],
        defence_authorities=[
            "armasuisse",
            "Bundesamt fuer Ruestung",
            "Office federal de l'armement",
            "Logistikbasis der Armee",
            "Base logistique de l'armee",
            "VBS", "DDPS",
            "Schweizer Armee",
        ],
        min_interval_seconds=1.0,
    )


class CHAdapter(BaseAdapter):
    """
    Switzerland adapter - simap.ch REST API (requests-based, no browser needed).

    Search strategy:
    1. Keyword searches (trailer vocabulary in DE/FR/IT)
    2. CPV-based search (34223xxx trailer codes)
    3. armasuisse authority sweep (all recent tenders)

    All three deduplicated by projectId.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    def _build_session(self):
        try:
            import requests
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            logger.error("CH: 'requests' not installed")
            return None

        import requests as rl
        session = rl.Session()
        session.verify = not (
            os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
            in ("1", "true", "yes")
        )
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, */*",
            "Referer": SIMAP_BASE,
        })
        return session

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Keyword search via simap.ch API."""
        return self._api_search({"search": keyword}, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Three-phase search:
        1. Keyword searches (trailer vocabulary)
        2. CPV-based search for trailer codes
        3. armasuisse full sweep (all recent tenders)
        """
        if not self._session:
            return []

        all_results: dict = {}  # key = project_id

        # Phase 1: Keyword searches
        kw_list = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords
        for kw in kw_list:
            for r in self._api_search({"search": kw}, max_results_per_keyword):
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # Phase 2: Trailer CPV codes (skip in test mode)
        if not test_mode:
            logger.info("CH: searching by trailer CPV codes")
            cpv_str = ",".join(TRAILER_CPV_CODES)
            for r in self._api_search({"cpvCodes": cpv_str}, 200):
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # Phase 3: armasuisse authority sweep (always — most reliable source)
        logger.info("CH: armasuisse authority sweep")
        limit_arm = 30 if test_mode else 500
        for r in self._api_search({"search": "armasuisse"}, limit_arm):
            key = r.reference_id or r.url or r.title[:50]
            if key and key not in all_results:
                all_results[key] = r

        logger.info("CH: search_all_keywords -> %d unique results", len(all_results))
        return list(all_results.values())

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch notice detail from simap.ch API."""
        project_id = result.reference_id
        if not project_id or not self._session:
            return self._detail_from_result(result)

        logger.info("CH: fetching detail for project %s", project_id)

        # Get project header
        try:
            header_url = SIMAP_API_HEADER.format(project_id=project_id)
            resp = self._session.get(header_url, params={"lang": "en"}, timeout=15)
            if resp.status_code != 200:
                logger.warning("CH: header %s -> %s", project_id, resp.status_code)
                return self._detail_from_result(result)
            header = resp.json()
        except Exception as exc:
            logger.error("CH: header fetch error: %s", exc)
            return self._detail_from_result(result)

        # Get publication details (for description, CPV, winner)
        pub_details = {}
        pub_id = self._pick_publication_id(header)
        if pub_id:
            try:
                det_url = SIMAP_API_DETAIL.format(project_id=project_id, pub_id=pub_id)
                resp2 = self._session.get(det_url, params={"lang": "en"}, timeout=15)
                if resp2.status_code == 200:
                    pub_details = resp2.json()
            except Exception as exc:
                logger.debug("CH: pub detail error %s: %s", project_id, exc)

        return self._build_detail(project_id, header, pub_details)

    def filter_defence(self, results: list) -> list:
        """Keep only results from Swiss defence authorities."""
        kept = []
        for r in results:
            all_text = " ".join([
                (r.authority or "").lower(),
                (r.title or "").lower(),
                (r.snippet or "").lower(),
            ])
            is_defence = any(p in all_text for p in CH_DEFENCE_PATTERNS) or any(
                pat.lower() in all_text for pat in self.config.defence_authorities
            )
            if is_defence:
                kept.append(r)
        logger.info("CH: filter_defence: %d -> %d", len(results), len(kept))
        return kept

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _api_search(self, params: dict, max_results: int = 100) -> list:
        """
        Paginate through simap.ch project-search API.

        Pagination: cursor-based via pagination.lastItem (format "YYYYMMDD|projectNumber").
        NOTE: Do NOT send newestPubTypes or newestPublicationFrom — they cause HTTP 400.
        """
        if not self._session:
            return []

        base_params = {
            "lang": "en",
            "itemsPerPage": min(100, max_results),
        }
        base_params.update(params)

        all_results: dict = {}
        last_item = None

        while len(all_results) < max_results:
            page_params = dict(base_params)
            if last_item:
                page_params["lastItem"] = last_item

            try:
                resp = self._session.get(SIMAP_API_SEARCH, params=page_params, timeout=20)
                if resp.status_code != 200:
                    logger.warning("CH API: %s %s", resp.status_code, resp.text[:200])
                    break
                data = resp.json()
            except Exception as exc:
                logger.error("CH API error: %s", exc)
                break

            items = data.get("projects") or []
            if not items:
                break

            for item in items:
                sr = self._item_to_search_result(item)
                if sr and sr.reference_id and sr.reference_id not in all_results:
                    all_results[sr.reference_id] = sr

            # Cursor pagination: pagination.lastItem
            pagination = data.get("pagination") or {}
            last_item = pagination.get("lastItem")
            if not last_item or len(all_results) >= max_results:
                break
            time.sleep(0.3)

        return list(all_results.values())[:max_results]

    def _item_to_search_result(self, item: dict) -> Optional[SearchResult]:
        """Convert simap.ch project item to SearchResult.

        Actual API field names (confirmed 2026-04-30):
          id               = UUID used in detail URLs
          projectNumber    = numeric project ID
          title            = multilingual dict {de, en, fr, it}
          procOfficeName   = multilingual dict for authority name
          publicationDate  = YYYY-MM-DD
          pubType          = tender | award | advance_notice
        """
        # Use UUID as reference_id (for detail API calls)
        project_id = str(item.get("id") or item.get("projectId") or "")
        project_number = str(item.get("projectNumber") or "")
        if not project_id:
            return None

        # Title
        title_raw = item.get("title") or {}
        if isinstance(title_raw, dict):
            title = (title_raw.get("en") or title_raw.get("de") or
                     title_raw.get("fr") or next(iter(title_raw.values()), ""))
        else:
            title = str(title_raw)
        title = str(title).strip()

        # Authority
        auth_raw = item.get("procOfficeName") or {}
        if isinstance(auth_raw, dict):
            authority = (auth_raw.get("en") or auth_raw.get("de") or
                         auth_raw.get("fr") or next(iter(auth_raw.values()), ""))
        else:
            authority = str(auth_raw)

        pub_date = str(item.get("publicationDate") or "")[:10]
        pub_type = item.get("pubType") or ""
        url = SIMAP_NOTICE_URL.format(project_id=project_id)
        snippet = f"type={pub_type}|num={project_number}"

        return SearchResult(
            title=title[:200],
            url=url,
            authority=str(authority)[:200],
            reference_id=project_id,
            date=pub_date,
            snippet=snippet[:300],
        )

    def _pick_publication_id(self, header: dict) -> Optional[str]:
        """Extract the best publication ID from project header."""
        # Try publications list (prefer award > tender)
        pubs = header.get("publications") or []
        if isinstance(pubs, list) and pubs:
            # Prefer award notices for winner data
            for pub in pubs:
                if "award" in str(pub.get("publicationType", "")).lower():
                    return str(pub.get("id") or pub.get("publicationId") or "")
            # Fallback: first publication
            first = pubs[0]
            return str(first.get("id") or first.get("publicationId") or "")
        return None

    def _build_detail(self, project_id: str, header: dict, pub_details: dict) -> NoticeDetail:
        """Construct NoticeDetail from project header + publication details."""
        title = str(
            header.get("projectTitle") or
            pub_details.get("projectOrderDescription") or
            pub_details.get("orderDescription") or ""
        )
        if not title:
            title = str(header.get("projectOrderDescription") or "")

        authority = str(
            header.get("issuingOrganizationName") or
            pub_details.get("orderAddressName") or ""
        )

        date = str(
            header.get("publicationDate") or
            header.get("newestPublicationDate") or ""
        )[:10]

        # Description
        desc = str(
            pub_details.get("orderDescription") or
            pub_details.get("projectOrderDescription") or
            header.get("projectOrderDescription") or ""
        )
        if isinstance(desc, dict):
            desc = desc.get("de") or desc.get("en") or desc.get("fr") or ""

        # Value
        value, currency = None, "CHF"
        for val_field in ["totalValue", "estimatedValue", "contractValue"]:
            v = pub_details.get(val_field) or header.get(val_field)
            if v:
                if isinstance(v, dict):
                    amount = v.get("amount") or v.get("value")
                    currency = v.get("currency", "CHF")
                else:
                    amount = v
                if amount:
                    try:
                        value = float(str(amount).replace(",", "").replace("'", ""))
                    except ValueError:
                        pass
                break

        # Winner
        winner = ""
        for win_field in ["awardedToName", "winnerName", "contractorName"]:
            w = pub_details.get(win_field) or header.get(win_field)
            if w:
                winner = str(w).strip()
                break
        # Also check lots
        lots = pub_details.get("lots") or []
        if not winner and isinstance(lots, list) and lots:
            for lot in lots[:3]:
                w = lot.get("awardedToName") or lot.get("winnerName")
                if w:
                    winner = str(w).strip()
                    break

        # Build raw text for AI enrichment
        raw_text = (
            f"Title: {title}\n"
            f"Authority: {authority}\n"
            f"Description: {desc[:3000]}\n"
            f"Value: {value} {currency}\n"
            f"Winner: {winner}\n"
        )

        detail = NoticeDetail(
            title=title[:200],
            url=SIMAP_NOTICE_URL.format(project_id=project_id),
            authority=authority[:200],
            date=date,
            reference_id=project_id,
            source_code="CH-SI",
            raw_text=raw_text[:8000],
            currency=currency,
            value=value,
            winner=winner[:200] if winner else "",
        )
        detail.description = desc[:500]
        return detail

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            date=result.date,
            reference_id=result.reference_id,
            source_code="CH-SI",
            raw_text=f"{result.title}\n{result.authority}\n{result.snippet}",
            currency="CHF",
        )

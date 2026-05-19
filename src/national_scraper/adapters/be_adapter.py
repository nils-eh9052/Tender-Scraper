"""
Belgium Adapter — publicprocurement.be (BOSA eProcurement)

Portal:  https://www.publicprocurement.be (Vue.js / Vuetify SPA)
Defence: La Défense / De Defensie, DGMR, Composante Terre
Language: FR + NL (bilingual)

Discovered API (via network interception):
  POST https://www.publicprocurement.be/api/sea/search/publications
  Auth: Keycloak JWT from localStorage['public__confidentialAuth__token']
  Returns: {"publications": [...], "totalCount": N}
  Triggered by: navigating to /bda (Bulletin des Adjudications)

Strategy:
  1. Navigate to /bda — Vue.js app auto-calls the SEA search API on load
  2. Capture the POST /api/sea/search/publications response via capture_response()
  3. Filter results locally for defence authorities + trailer CPV codes
  4. For targeted searches: use page.evaluate() to POST with filter params
     using the captured Keycloak JWT token

Publication structure:
  organisation.organisationNames: [{language, text}]
  cpvMainCode.code, cpvAdditionalCodes[].code
  referenceNumber, publicationDate, dispatchDate
  lots: [{title, description}]
  noticeIds: [TED notice IDs for cross-referencing]
  publicationType, publicationReferenceNumbersBDA / TED

Token acquisition:
  The Keycloak token is stored in localStorage['public__confidentialAuth__token']
  It's auto-refreshed by the Vue.js app, valid for ~3600 seconds.
"""

import re
import time
import json
import logging
import os
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL  = "https://www.publicprocurement.be"
BDA_URL   = "https://www.publicprocurement.be/bda"
SEA_API   = "https://www.publicprocurement.be/api/sea/search/publications"
NOTICE_URL = "https://www.publicprocurement.be/bda/{pub_id}"

TRAILER_KEYWORDS_BE = [
    # French
    "remorque", "semi-remorque", "porte-char", "citerne",
    "remorque militaire",
    # Dutch
    "aanhangwagen", "oplegger", "dieplader", "tankwagen",
    "aanhanger", "veldkeuken",
    # English
    "trailer", "semi-trailer", "low-bed",
]

DEFENCE_ORG_BE = [
    "défense",
    "defensie",
    "dgmr",
    "direction générale material resources",
    "composante terre",
    "landcomponent",
    "composante air",
    "luchtcomponent",
    "composante marine",
    "marinecomponent",
    "ministère de la défense",
    "ministerie van defensie",
    "nato",
]

TRAILER_CPV_PREFIXES = ["34223", "34221", "35400", "35600"]


def create_be_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Belgium",
        country_code="BE",
        source_code="BE-EP",
        base_url=BASE_URL,
        search_url=BDA_URL,
        language="fr",
        trailer_keywords=TRAILER_KEYWORDS_BE,
        defence_authorities=DEFENCE_ORG_BE,
        min_interval_seconds=3.0,
    )


class BEAdapter(BaseAdapter):
    """
    Belgium adapter — BOSA publicprocurement.be via Playwright.

    Navigate to /bda to trigger the SEA publications API call, then
    filter locally for Défense/Defensie authorities with trailer CPVs.
    For targeted searches, use the captured JWT token to POST filter requests.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._token: str = ""
        self._session_ready = False

    # ── Search ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Single keyword — delegates to search_all_keywords."""
        return []

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """
        Search Belgian e-Procurement for defence trailer notices.

        1. Load /bda — Vue.js auto-calls POST /api/sea/search/publications
        2. Capture the initial all-publications response
        3. Filter locally for Défense/Defensie + trailer keywords/CPVs
        4. If token available: also run targeted CPV searches via JS eval
        """
        all_results: dict[str, SearchResult] = {}

        # Step 1: Load /bda and capture initial search results
        initial = self._load_bda_and_capture()
        logger.info(f"BE: /bda initial load → {len(initial)} publications captured")

        for r in initial:
            if self._is_defence(r) and (self._is_trailer_related(r) or
                                         self._has_trailer_cpv(r)):
                key = r.reference_id or r.url
                if key and key not in all_results:
                    all_results[key] = r

        # Step 2: Targeted CPV searches via fetch (if token available)
        if self._token and not test_mode:
            cpv_list = TRAILER_CPV_PREFIXES
            for cpv_prefix in cpv_list:
                logger.info(f"BE: targeted CPV search {cpv_prefix}...")
                hits = self._fetch_cpv_publications(cpv_prefix, max_results=50)
                for r in hits:
                    if self._is_defence(r):
                        key = r.reference_id or r.url
                        if key and key not in all_results:
                            all_results[key] = r
                logger.info(f"BE: CPV {cpv_prefix} → {len(hits)} defence hits, total {len(all_results)}")
                time.sleep(self.config.min_interval_seconds)

        # Step 3: Keyword searches
        kw_list = TRAILER_KEYWORDS_BE[:2] if test_mode else TRAILER_KEYWORDS_BE[:6]
        if self._token:
            for kw in kw_list:
                hits = self._fetch_keyword_publications(kw, max_results=30)
                for r in hits:
                    if self._is_defence(r):
                        key = r.reference_id or r.url
                        if key and key not in all_results:
                            all_results[key] = r
                logger.info(f"BE: kw '{kw}' → {len(hits)} hits, total {len(all_results)}")
                time.sleep(self.config.min_interval_seconds)

        results = list(all_results.values())
        logger.info(f"BE: search_all_keywords → {len(results)} total")
        return results

    def _load_bda_and_capture(self) -> list:
        """
        Navigate to /bda and capture the initial SEA publications API response.
        The Vue.js app calls POST /api/sea/search/publications on page load.
        """
        captured = {"data": None}

        def trigger():
            self.browser.goto(BDA_URL, wait_for="networkidle", timeout=45000)
            time.sleep(3)

        data = self.browser.capture_response(
            url_pattern="/api/sea/search/publications",
            trigger=trigger,
            timeout=20000,
        )

        if data and isinstance(data, dict):
            pubs = data.get("publications") or []
            total = data.get("totalCount", 0)
            logger.info(f"BE: captured {len(pubs)}/{total} publications from /bda")
            # Try to get token
            try:
                self._token = self.browser.page.evaluate(
                    "() => localStorage.getItem('public__confidentialAuth__token') || ''"
                ) or ""
                self._session_ready = bool(self._token)
            except Exception:
                pass
            return [self._pub_to_result(p) for p in pubs]
        else:
            logger.warning("BE: no SEA response captured from /bda — VPN may block")
            # Try to get token anyway
            try:
                self._token = self.browser.page.evaluate(
                    "() => localStorage.getItem('public__confidentialAuth__token') || ''"
                ) or ""
                self._session_ready = bool(self._token)
            except Exception:
                pass
            return []

    def _fetch_cpv_publications(self, cpv_prefix: str, max_results: int = 50) -> list:
        """POST to SEA API with CPV filter using JWT token."""
        return self._sea_post({
            "cpvCodes": [cpv_prefix],
            "page": 0,
            "size": max_results,
        })

    def _fetch_keyword_publications(self, keyword: str, max_results: int = 30) -> list:
        """POST to SEA API with keyword filter."""
        return self._sea_post({
            "shortDescription": keyword,
            "page": 0,
            "size": max_results,
        })

    def _sea_post(self, body: dict) -> list:
        """Call POST /api/sea/search/publications via page.evaluate with JWT token."""
        if not self._token:
            return []
        try:
            result = self.browser.page.evaluate("""
                (args) => {
                    const [token, requestBody] = args;
                    return fetch('https://www.publicprocurement.be/api/sea/search/publications', {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'Authorization': 'Bearer ' + token,
                            'Accept': 'application/json',
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(requestBody)
                    }).then(async r => {
                        if (r.status !== 200) return {error: r.status};
                        const d = await r.json();
                        return {ok: true, total: d.totalCount,
                                publications: d.publications || []};
                    }).catch(e => ({error: e.message}));
                }
            """, [self._token, body])

            if not result or result.get("error"):
                return []
            return [self._pub_to_result(p) for p in result.get("publications", [])]
        except Exception as e:
            logger.error(f"BE: SEA POST error: {e}")
            return []

    def _pub_to_result(self, pub: dict) -> SearchResult:
        """Convert BOSA publication to SearchResult."""
        pub_id = str(pub.get("publicationWorkspaceId") or pub.get("procedureId") or "")
        ref_id = str(pub.get("referenceNumber") or pub_id)

        # Organisation name: prefer FR, then NL, then EN
        org = pub.get("organisation") or {}
        org_names = org.get("organisationNames") or []
        authority = ""
        for lang in ("FR", "NL", "EN"):
            for n in org_names:
                if n.get("language") == lang:
                    authority = n.get("text", "")
                    break
            if authority:
                break
        if not authority and org_names:
            authority = org_names[0].get("text", "") if isinstance(org_names[0], dict) else ""

        # Title from lots
        lots = pub.get("lots") or []
        title = ""
        if lots and isinstance(lots[0], dict):
            title = (lots[0].get("title") or lots[0].get("description") or "")[:200]
        if not title:
            # Try to build from CPV
            cpv_info = pub.get("cpvMainCode") or {}
            cpv_desc = cpv_info.get("descriptions") or []
            for d in cpv_desc:
                if d.get("language") == "EN":
                    title = d.get("text", "")
                    break
            if not title and cpv_desc:
                title = cpv_desc[0].get("text", "")

        cpv_main = (pub.get("cpvMainCode") or {}).get("code", "")
        date_str = (pub.get("publicationDate") or pub.get("dispatchDate") or "")[:10]

        # Check if notice appears in TED (for cross-referencing)
        ted_ids = pub.get("publicationReferenceNumbersTED") or []

        url = NOTICE_URL.format(pub_id=pub_id) if pub_id else BASE_URL
        meta = json.dumps({
            "pubId": pub_id,
            "org": authority,
            "cpv": cpv_main,
            "ted": ted_ids[:2] if ted_ids else [],
        }, ensure_ascii=False)

        return SearchResult(
            title=title,
            url=url,
            authority=authority,
            reference_id=ref_id,
            date=date_str,
            currency="EUR",
            snippet=meta[:500],
        )

    # ── Filter ──

    def filter_defence(self, results: list) -> list:
        return [r for r in results if self._is_defence(r)]

    def _is_defence(self, result: SearchResult) -> bool:
        auth_lower = (result.authority or "").lower()
        title_lower = (result.title or "").lower()
        combined = f"{auth_lower} {title_lower}"
        return any(p in combined for p in self.config.defence_authorities)

    _TRAILER_KW = (
        "remorque", "aanhangwagen", "oplegger", "dieplader",
        "trailer", "semi-trailer", "porte-char", "cisterne",
        "tankwagen", "aanhanger", "semitrailer",
    )

    def _is_trailer_related(self, result: SearchResult) -> bool:
        title_lower = (result.title or "").lower()
        return any(kw in title_lower for kw in self._TRAILER_KW)

    def _has_trailer_cpv(self, result: SearchResult) -> bool:
        try:
            meta = json.loads(result.snippet or "{}")
            cpv = meta.get("cpv", "")
            return any(cpv.startswith(p) for p in TRAILER_CPV_PREFIXES)
        except Exception:
            return False

    # ── Detail ──

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Load detail page and extract fields."""
        if not result.url or result.url == BASE_URL:
            return self._detail_from_result(result)

        ok = self.browser.goto(result.url, wait_for="networkidle", timeout=30000)
        if not ok:
            return self._detail_from_result(result)

        safe = re.sub(r"[^a-zA-Z0-9]", "_", result.reference_id or "be")
        self.browser._screenshot(f"be_detail_{safe}")

        page_text = self.browser.get_page_text()
        if not page_text or len(page_text) < 50:
            return self._detail_from_result(result)

        description = (self._find_field(page_text, [
            r"(?:Objet|Voorwerp|Subject)[:\s]+(.{30,500}?)(?=\n[A-Z]|$)",
            r"(?:Description|Beschrijving)[:\s]+(.{30,400}?)(?=\n|$)",
        ]) or "")[:500]

        value = None
        val_str = self._find_field(page_text, [
            r"(?:Valeur|Waarde|Value)[:\s]+([\d\s,.]+)\s*(?:EUR|€)",
        ])
        if val_str:
            try:
                v = float(val_str.replace(" ", "").replace(",", "."))
                if v > 0:
                    value = v
            except ValueError:
                pass

        winner = self._find_field(page_text, [
            r"(?:Contractant|Titulaire|Opdrachtnemer)[:\s]+([^\n]{5,120})",
        ]) or ""

        date_str = (self._find_field(page_text, [
            r"(?:Date|Datum)[:\s]+(\d{2}[./]\d{2}[./]\d{4})",
        ]) or result.date or "")
        if re.match(r"\d{2}[./]\d{2}[./]\d{4}", date_str):
            m = re.match(r"(\d{2})[./](\d{2})[./](\d{4})", date_str)
            if m:
                date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

        return NoticeDetail(
            title=result.title,
            description=description,
            authority=result.authority,
            date=date_str,
            value=value,
            currency="EUR",
            winner=winner[:120] if winner else "",
            reference_id=result.reference_id,
            url=result.url,
            source_code="BE-EP",
            raw_text=page_text[:10000],
        )

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="EUR",
            reference_id=result.reference_id,
            url=result.url,
            source_code="BE-EP",
            raw_text=result.title or "",
        )

    @staticmethod
    def _find_field(text: str, patterns: list) -> str:
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:300]
        return ""

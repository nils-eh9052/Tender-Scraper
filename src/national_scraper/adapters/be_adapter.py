"""
Belgium Adapter — publicprocurement.be (BOSA eProcurement)

Portal:  https://www.publicprocurement.be (BOSA eProcurement Vue SPA)
Defence: La Défense / De Defensie, DGMR, Composante Terre
Language: FR + NL (bilingual)

Strategy:
  1. Primary: Playwright-based search on the Vue SPA
     - Navigate to the procurement notices search page
     - Intercept the XHR/Fetch API call to /api/sea/... with capture_response()
     - Parse the JSON response for defence trailer notices
  2. Fallback: Parse the HTML page using DOM text extraction

The BOSA eProcurement portal is a Vue.js SPA at:
  https://www.publicprocurement.be
The backend search API requires a session token, obtained automatically
by the browser during the Angular/Vue app initialization.
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

BASE_URL     = "https://www.publicprocurement.be"
SEARCH_URL   = "https://www.publicprocurement.be/en/procurement-projects"
NOTICE_URL   = "https://www.publicprocurement.be/en/procurement-projects/{notice_id}"

TRAILER_KEYWORDS_BE = [
    # French
    "remorque", "semi-remorque", "porte-char", "citerne",
    "remorque militaire",
    # Dutch
    "aanhangwagen", "oplegger", "dieplader", "tankwagen",
    "aanhanger", "veldkeuken",
    # English (used in BE defence tenders)
    "trailer", "semi-trailer", "low-bed",
]

DEFENCE_ORG_BE = [
    "Défense",
    "Defensie",
    "DGMR",
    "Direction Générale Material Resources",
    "Composante Terre",
    "Landcomponent",
    "Composante Air",
    "Luchtcomponent",
    "Composante Marine",
    "Marinecomponent",
    "Ministère de la Défense",
    "Ministerie van Defensie",
    "NATO",
]

TRAILER_CPV_CODES = ["34223300", "34220000", "34223100", "34221000", "35400000"]


def create_be_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Belgium",
        country_code="BE",
        source_code="BE-EP",
        base_url=BASE_URL,
        search_url=SEARCH_URL,
        language="fr",
        trailer_keywords=TRAILER_KEYWORDS_BE,
        defence_authorities=DEFENCE_ORG_BE,
        min_interval_seconds=3.0,
    )


class BEAdapter(BaseAdapter):
    """
    Belgium adapter — BOSA eProcurement via Playwright.

    Search strategy:
    1. Navigate to the BOSA procurement search page with CPV filter
    2. Capture the XHR API call that the Vue app makes
    3. Parse the JSON response for defence trailer notices
    4. Fall back to DOM text parsing if capture fails
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_rest_session()

    def _build_rest_session(self):
        """Optional REST session for API fallback."""
        try:
            import requests, urllib3
            urllib3.disable_warnings()
            ssl_off = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() in ("1", "true", "yes")
            session = __import__("requests").Session()
            session.verify = not ssl_off
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
                "Accept": "application/json",
                "Origin": "https://www.publicprocurement.be",
                "Referer": "https://www.publicprocurement.be/",
            })
            return session
        except ImportError:
            return None

    # ── Search ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search by keyword via Playwright browser."""
        encoded = keyword.replace(" ", "+")
        url = f"{SEARCH_URL}?text={encoded}"
        return self._load_and_capture(url, max_results=max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """Search Belgian defence trailer notices via CPV and keyword filters."""
        all_results: dict[str, SearchResult] = {}

        # Phase 1: CPV searches
        cpv_list = TRAILER_CPV_CODES[:2] if test_mode else TRAILER_CPV_CODES
        for cpv in cpv_list:
            logger.info(f"BE: searching CPV {cpv}")
            url = f"{SEARCH_URL}?cpvCodes={cpv}"
            hits = self._load_and_capture(url, max_results=20 if test_mode else 100)
            hits_def = [h for h in hits if self._is_defence(h)]
            for h in hits_def:
                key = h.reference_id or h.url
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(f"BE: CPV {cpv} → {len(hits)} raw, {len(hits_def)} defence, total {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        # Phase 2: Keyword + defence authority
        kw_list = TRAILER_KEYWORDS_BE[:2] if test_mode else TRAILER_KEYWORDS_BE[:5]
        for kw in kw_list:
            logger.info(f"BE: keyword '{kw}' + Défense filter")
            encoded = kw.replace(" ", "+")
            url = f"{SEARCH_URL}?text={encoded}"
            hits = self._load_and_capture(url, max_results=20 if test_mode else 50)
            hits_def = [h for h in hits if self._is_defence(h)]
            for h in hits_def:
                key = h.reference_id or h.url
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(f"BE: kw '{kw}' → {len(hits)} raw, {len(hits_def)} defence, total {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        results = list(all_results.values())
        logger.info(f"BE: search_all_keywords → {len(results)} total")
        return results

    def _load_and_capture(self, url: str, max_results: int = 50) -> list:
        """Load search page and capture API response or parse DOM."""
        captured_items = []

        def trigger():
            self.browser.goto(url, wait_for="networkidle", timeout=45000)

        # Try to capture the JSON API response from the Vue app
        # The BOSA portal calls /api/sea/... internally with auth headers
        data = self.browser.capture_response(
            url_pattern="/api/sea/",
            trigger=trigger,
            timeout=20000,
        )

        if data and isinstance(data, dict):
            items = (data.get("content") or data.get("items") or
                     data.get("results") or data.get("notices") or [])
            logger.info(f"BE: captured JSON with {len(items)} items from {url}")
            captured_items = [self._item_to_result(i) for i in items[:max_results]]
        elif data and isinstance(data, list):
            logger.info(f"BE: captured JSON list with {len(data)} items")
            captured_items = [self._item_to_result(i) for i in data[:max_results]]
        else:
            logger.info(f"BE: no JSON captured, parsing DOM")
            captured_items = self._parse_dom()

        return captured_items

    def _parse_dom(self) -> list:
        """Parse notice list from rendered Vue.js DOM."""
        results = []
        try:
            text = self.browser.get_page_text()
            if not text:
                return results
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            logger.debug(f"BE DOM: {len(lines)} text lines")
            # Screenshot for debugging
            self.browser._screenshot("be_search_result")
        except Exception as e:
            logger.error(f"BE: DOM parsing error: {e}")
        return results

    def _item_to_result(self, item: dict) -> SearchResult:
        """Convert BOSA API item to SearchResult."""
        notice_id = (item.get("id") or item.get("noticeId") or
                     item.get("publicationId") or "")
        ref_id = str(item.get("referenceNumber") or item.get("fileReference") or
                     item.get("reference") or notice_id)
        # Title: prefer FR first, then NL, then generic
        title = (item.get("title") or item.get("titleFr") or item.get("titleNl") or
                 item.get("subject") or item.get("name") or "")
        if isinstance(title, dict):
            title = title.get("fr") or title.get("nl") or title.get("en") or str(title)
        authority = (item.get("buyerName") or item.get("buyer", {}).get("name", "")
                     if isinstance(item.get("buyer"), dict) else
                     item.get("buyer") or item.get("organisationName") or
                     item.get("contractingAuthority") or "")
        date_str = (item.get("publicationDate") or item.get("datePublication") or
                    item.get("date") or "")[:10]

        value = None
        for vk in ("estimatedValue", "totalValue", "contractValue", "value"):
            v = item.get(vk)
            if isinstance(v, dict):
                v = v.get("amount") or v.get("value")
            try:
                if v and float(str(v).replace(",", ".")) > 0:
                    value = float(str(v).replace(",", "."))
                    break
            except (ValueError, TypeError):
                pass

        url = NOTICE_URL.format(notice_id=notice_id) if notice_id else BASE_URL
        meta = json.dumps({"noticeId": str(notice_id), "org": authority}, ensure_ascii=False)

        return SearchResult(
            title=str(title),
            url=url,
            authority=str(authority),
            reference_id=ref_id,
            date=date_str,
            value=value,
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
        for pattern in self.config.defence_authorities:
            if pattern.lower() in combined:
                return True
        return False

    # ── Detail ──

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch full notice detail via Playwright."""
        if not result.url or result.url == BASE_URL:
            return self._detail_from_result(result)

        ok = self.browser.goto(result.url, wait_for="networkidle", timeout=30000)
        if not ok:
            return self._detail_from_result(result)

        safe_ref = re.sub(r"[^a-zA-Z0-9]", "_", result.reference_id or "unknown")
        self.browser._screenshot(f"be_detail_{safe_ref}")

        page_text = self.browser.get_page_text()
        if not page_text or len(page_text) < 50:
            return self._detail_from_result(result)

        title = (self._find_field(page_text, [
            r"(?:Objet du marché|Voorwerp van de opdracht|Subject)[:\s]+([^\n]{10,200})",
            r"(?:Titre|Titel|Title)[:\s]+([^\n]{10,200})",
        ]) or result.title or "")

        authority = (self._find_field(page_text, [
            r"(?:Pouvoir adjudicateur|Aanbestedende overheid|Buyer)[:\s]+([^\n]{5,150})",
            r"(?:Nom officiel|Officiële naam)[:\s]+([^\n]{5,150})",
        ]) or result.authority or "")

        description = (self._find_field(page_text, [
            r"(?:Description|Beschrijving|Korte beschrijving|Objet)[:\s]+(.{30,500}?)(?=\n[A-Z]|$)",
        ]) or "")[:500]

        date_str = (self._find_field(page_text, [
            r"(?:Date de publication|Publicatiedatum|Publication date)[:\s]+(\d{2}[./]\d{2}[./]\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ]) or result.date or "")
        if date_str:
            date_str = self._normalize_date(date_str)

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

        quantity = None
        m = re.search(r"(\d+)\s*(?:remorque|aanhangwagen|oplegger|trailer|stuks?|pièces?)",
                      page_text, re.IGNORECASE)
        if m:
            try:
                quantity = int(m.group(1))
            except ValueError:
                pass

        return NoticeDetail(
            title=title,
            description=description,
            authority=authority,
            date=date_str,
            value=value,
            currency="EUR",
            quantity=quantity,
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

    # ── Utility ──

    @staticmethod
    def _find_field(text: str, patterns: list) -> str:
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:300]
        return ""

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        m = re.match(r"(\d{2})[./](\d{2})[./](\d{4})", date_str)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        return date_str[:10]

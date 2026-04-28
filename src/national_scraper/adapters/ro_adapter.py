"""
Romania Adapter — SEAP/e-licitatie.ro (Sistemul Electronic de Achiziții Publice)

Portal: https://www.e-licitatie.ro
Defence: Ministerul Apărării Naționale (MApN), Unități Militare (UM XXXXX)
Language: Romanian

Strategy:
  1. Use Playwright to load the Angular SPA at e-licitatie.ro
  2. Intercept XHR/Fetch API responses via capture_response()
     (the Angular app calls an internal backend which returns JSON)
  3. Navigate by CPV code filter URLs (Angular router respects query params)
  4. Fall back to DOM parsing if capture fails

The SEAP portal's Angular frontend makes API calls to its backend at:
  https://www.e-licitatie.ro/ (same-origin, proxied through the web server)
The exact internal API route is discovered at runtime by intercepting all
JSON responses while the page loads.

URL patterns for CPV search:
  https://www.e-licitatie.ro/pub/notices/ca-notices/list/1?cpvCode=34223300
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

BASE_URL   = "https://www.e-licitatie.ro"
LIST_URL   = "https://www.e-licitatie.ro/pub/notices/ca-notices/list/{page}"
DETAIL_URL = "https://www.e-licitatie.ro/pub/notices/ca-notices/notice-details/{notice_id}"

TRAILER_CPV_CODES = [
    "34223300",   # Trailers (remorcă)
    "34220000",   # Trailers, semi-trailers and mobile containers
    "34223100",   # Semi-trailers (semiremorcă)
    "34221000",   # Special-purpose mobile containers
    "35400000",   # Military vehicles + spare parts
]

DEFENCE_ORG_KEYWORDS = [
    "Ministerul Apărării",
    "Apărării Naționale",
    "Statul Major",
    "Unitate Militară",
    "UM 0",
    "Brigada",
    "Batalionul",
    "Forțe Terestre",
    "ROMARM",
    "Arsenalul Armatei",
    "Centrul Militar",
]

TRAILER_KEYWORDS_RO = [
    "remorcă", "semiremorcă", "platformă transport",
    "cisternă", "bucătărie de campanie",
    "container militar", "transport militar",
    "remorcă militară", "dieplader",
]


def create_ro_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Romania",
        country_code="RO",
        source_code="RO-SEAP",
        base_url=BASE_URL,
        search_url=LIST_URL.format(page=1),
        language="ro",
        trailer_keywords=TRAILER_KEYWORDS_RO,
        defence_authorities=DEFENCE_ORG_KEYWORDS,
        min_interval_seconds=3.0,
    )


class ROAdapter(BaseAdapter):
    """
    Romania adapter — SEAP e-licitatie.ro via Playwright.

    Search strategy:
    1. Load CPV-filtered search page (Angular SPA)
    2. Capture JSON API response via response interception
    3. Filter to defence authorities
    4. Load detail pages for full text
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)

    # ── Search ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search by keyword — loads search page and captures results."""
        encoded = keyword.replace(" ", "+")
        url = f"{LIST_URL.format(page=1)}?q={encoded}"
        return self._load_page_and_capture(url, max_results=max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """Combined CPV search for Romanian defence trailer notices."""
        all_results: dict[str, SearchResult] = {}

        # Phase 1: CPV-code searches
        cpv_list = TRAILER_CPV_CODES[:2] if test_mode else TRAILER_CPV_CODES
        for cpv in cpv_list:
            logger.info(f"RO: searching CPV {cpv}")
            url = f"{LIST_URL.format(page=1)}?cpvCode={cpv}"
            hits = self._load_page_and_capture(url, max_results=20 if test_mode else 100)
            for h in hits:
                key = h.reference_id or h.url or h.title[:50]
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(f"RO: CPV {cpv} → {len(hits)} results, total {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        # Phase 2: Keyword searches for trailer + defence terms
        if not test_mode:
            for kw in TRAILER_KEYWORDS_RO[:3]:
                logger.info(f"RO: keyword search '{kw}'")
                encoded = kw.replace(" ", "+")
                url = f"{LIST_URL.format(page=1)}?q={encoded}"
                hits = self._load_page_and_capture(url, max_results=50)
                hits_def = [h for h in hits if self._is_defence(h)]
                for h in hits_def:
                    key = h.reference_id or h.url or h.title[:50]
                    if key and key not in all_results:
                        all_results[key] = h
                logger.info(f"RO: kw '{kw}' → {len(hits)} raw, {len(hits_def)} defence, total {len(all_results)}")
                time.sleep(self.config.min_interval_seconds)

        results = list(all_results.values())
        logger.info(f"RO: search_all_keywords → {len(results)} total")
        return results

    def _load_page_and_capture(self, url: str, max_results: int = 50) -> list:
        """
        Navigate to SEAP search page and capture the Angular API response.

        The SEAP portal at e-licitatie.ro is an Angular SPA. The Angular app
        calls its backend at https://www.e-licitatie.ro/api-pub/...
        We intercept ANY JSON response from that domain and parse notice data.

        Note: On corporate VPN networks the Angular app may not fully bootstrap.
        In that case, we fall back to DOM text parsing.
        """
        captured_items = []
        best_data = {"json": None}

        def trigger():
            # Try multiple URL patterns to find the notice API response
            self.browser.goto(url, wait_for="networkidle", timeout=45000)

        # Intercept JSON from the e-licitatie.ro API-PUB backend
        # The Angular SPA makes calls to https://www.e-licitatie.ro/api-pub/...
        for pattern in ["CaNotice", "Notice", "Acquisition", "api-pub"]:
            data = self.browser.capture_response(
                url_pattern=pattern,
                trigger=trigger if not best_data["json"] else (lambda: None),
                timeout=10000,
            )
            if data and isinstance(data, (dict, list)):
                best_data["json"] = data
                break

        data = best_data["json"]
        if data and isinstance(data, dict):
            items = (data.get("items") or data.get("data") or
                     data.get("content") or data.get("result") or
                     data.get("notices") or [])
            if items:
                logger.info(f"RO: captured JSON with {len(items)} items from {url}")
                return [self._item_to_result(i) for i in items[:max_results]]
        elif data and isinstance(data, list):
            logger.info(f"RO: captured JSON list with {len(data)} items")
            return [self._item_to_result(i) for i in data[:max_results]]

        logger.info(f"RO: no JSON captured from Angular SPA, falling back to DOM parsing")
        return self._parse_dom()

    def _parse_dom(self) -> list:
        """Parse notice list from rendered Angular DOM as fallback."""
        results = []
        try:
            text = self.browser.get_page_text()
            if not text:
                return results

            # Try to extract notice cards from page text
            # SEAP DOM typically shows: title, authority, date, reference number
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            logger.debug(f"RO DOM: {len(lines)} text lines")

            # Look for notice reference pattern: numbers like "CAN/1234/2024" or "SA000001/2024"
            ref_pattern = re.compile(r"(?:CA[NP]|SA|RC)\s*/?\s*\d+/\d{4}", re.IGNORECASE)

            current_block = []
            for line in lines:
                if ref_pattern.search(line):
                    if current_block:
                        r = self._block_to_result(current_block)
                        if r:
                            results.append(r)
                    current_block = [line]
                elif current_block:
                    current_block.append(line)
                    if len(current_block) > 8:
                        r = self._block_to_result(current_block)
                        if r:
                            results.append(r)
                        current_block = []

            if current_block:
                r = self._block_to_result(current_block)
                if r:
                    results.append(r)

        except Exception as e:
            logger.error(f"RO: DOM parsing error: {e}")

        logger.info(f"RO: DOM parsed {len(results)} notices")
        return results

    def _block_to_result(self, lines: list) -> Optional[SearchResult]:
        """Convert a block of text lines to a SearchResult."""
        if not lines:
            return None
        text = "\n".join(lines)
        ref_m = re.search(r"(?:CA[NP]|SA|RC)\s*/?\s*\d+/\d{4}", text, re.IGNORECASE)
        ref_id = ref_m.group(0) if ref_m else lines[0][:40]
        title = lines[0][:200] if lines else ""
        date_m = re.search(r"\d{2}[./]\d{2}[./]\d{4}", text)
        date_str = date_m.group(0) if date_m else ""
        if date_m:
            date_str = self._normalize_date(date_str)
        authority = ""
        for line in lines[1:]:
            if any(kw.lower() in line.lower() for kw in self.config.defence_authorities):
                authority = line[:100]
                break
        return SearchResult(
            title=title,
            url=BASE_URL,
            authority=authority,
            reference_id=ref_id,
            date=date_str,
            currency="RON",
        )

    def _item_to_result(self, item: dict) -> SearchResult:
        """Convert SEAP API item (from captured response) to SearchResult."""
        notice_id = (item.get("caNoticeId") or item.get("id") or
                     item.get("noticeId") or "")
        ref_id = str(item.get("noticeNo") or item.get("referenceNumber") or notice_id)
        title = (item.get("contractTitle") or item.get("contractObject") or
                 item.get("title") or "")
        authority = (item.get("caName") or item.get("contractingAuthorityName") or
                     item.get("organizationName") or "")
        date_str = (item.get("publicationDate") or item.get("noticePublicationDate") or "")[:10]

        value = None
        for vk in ("contractValue", "estimatedValue", "totalValue"):
            try:
                v = item.get(vk)
                if v and float(v) > 0:
                    value = float(v)
                    break
            except (ValueError, TypeError):
                pass

        url = DETAIL_URL.format(notice_id=notice_id) if notice_id else BASE_URL
        meta = json.dumps({"noticeId": str(notice_id), "org": authority}, ensure_ascii=False)

        return SearchResult(
            title=title,
            url=url,
            authority=authority,
            reference_id=ref_id,
            date=date_str,
            value=value,
            currency="RON",
            snippet=meta[:400],
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
        """Load detail page and extract fields from DOM."""
        if not result.url or result.url == BASE_URL:
            return self._detail_from_result(result)

        ok = self.browser.goto(result.url, wait_for="networkidle", timeout=30000)
        if not ok:
            return self._detail_from_result(result)

        # Take screenshot
        safe_ref = re.sub(r"[^a-zA-Z0-9]", "_", result.reference_id or "unknown")
        self.browser._screenshot(f"ro_detail_{safe_ref}")

        page_text = self.browser.get_page_text()
        if not page_text:
            return self._detail_from_result(result)

        title = (self._find_field(page_text, [
            r"(?:Titlul contractului|Contract title)[:\s]+([^\n]{10,200})",
            r"(?:Obiectul contractului|Contract object)[:\s]+([^\n]{10,200})",
        ]) or result.title or "")

        authority = (self._find_field(page_text, [
            r"(?:Autoritatea contractantă|Contracting authority)[:\s]+([^\n]{5,150})",
            r"(?:Denumirea entității)[:\s]+([^\n]{5,150})",
        ]) or result.authority or "")

        description = (self._find_field(page_text, [
            r"(?:Descrierea achiziției|Short description)[:\s]+(.{30,500}?)(?=\n[A-Z]|$)",
            r"(?:Obiectul[:\s]+)(.{30,400}?)(?=\n|$)",
        ]) or "")[:500]

        date_str = (self._find_field(page_text, [
            r"(?:Data publicării|Publication date)[:\s]+(\d{2}[./]\d{2}[./]\d{4})",
        ]) or result.date or "")
        if date_str:
            date_str = self._normalize_date(date_str)

        value = None
        val_str = self._find_field(page_text, [
            r"(?:Valoarea estimată|Estimated value)[:\s]+([\d\s,.]+)\s*RON",
            r"(?:Valoarea contractului)[:\s]+([\d\s,.]+)",
        ])
        if val_str:
            try:
                v = float(val_str.replace(" ", "").replace(",", "."))
                if v > 0:
                    value = v
            except ValueError:
                pass

        winner = self._find_field(page_text, [
            r"(?:Denumirea câștigătorului|Contractor name)[:\s]+([^\n]{5,120})",
            r"(?:Executant|Contractor)[:\s]+([^\n]{5,120})",
        ]) or ""

        return NoticeDetail(
            title=title,
            description=description,
            authority=authority,
            date=date_str,
            value=value,
            currency="RON",
            winner=winner[:120] if winner else "",
            reference_id=result.reference_id,
            url=result.url,
            source_code="RO-SEAP",
            raw_text=page_text[:10000],
        )

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="RON",
            reference_id=result.reference_id,
            url=result.url,
            source_code="RO-SEAP",
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

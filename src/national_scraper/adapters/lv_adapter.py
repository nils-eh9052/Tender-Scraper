"""
Latvia Adapter — EIS (eis.gov.lv)

Portal: https://www.eis.gov.lv
Defence: Aizsardzības ministrija (Ministry of Defence), NBS (National Armed Forces)

DISCOVERY (Sprint 11):
  Latvia's Electronic Information System (EIS) for public procurement.

  Public procurement search:
    https://www.eis.gov.lv/EKEIS/Supplier/Procurement/

  API investigation:
    The EIS portal renders via server-side ASP.NET. XHR inspection reveals:
    - Procurement list: POST to /EKEIS/Supplier/Procurement (form-encoded)
    - Search params: ProcurementTitle, CpvCode, ContractingAuthority, etc.
    - Session-based (cookies required)

  ALTERNATIVE — Open Data / RSS:
    Latvia publishes procurement data via OpenData.gov.lv:
      https://data.gov.lv/dati/lv/dataset/iepirkumu-paziņojumi
    RSS feeds: https://www.eis.gov.lv/EKEIS/Supplier/Procurement/Rss
    (Filtered RSS by CPV or keyword may work without complex session management)

  IMPLEMENTATION STATUS:
    Phase 1 (Sprint 11): RSS-based search for CPV 34223 (trailer codes)
    and keyword search via browser. Returns results if RSS accessible.

    Phase 2 (future): Full session-based EIS form POST.

  Defence authorities:
    Aizsardzības ministrija = Ministry of Defence
    Nacionālie bruņotie spēki (NBS) = National Armed Forces
    Valsts aizsardzības militārais birojs = State Defence Military Bureau

TRAILER KEYWORDS (Latvian):
  piekabe = trailer
  puspiekabe = semi-trailer
  piekabes = trailers (genitive)
  autocisterna = tanker truck/trailer
  konteiners = container
  lauka virtuve = field kitchen
  zempiekraujamā piekabe = low-loader trailer
"""

import json
import logging
import time
from typing import Optional

import requests
import urllib3

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

logger = logging.getLogger(__name__)
urllib3.disable_warnings()

LV_BASE = "https://www.eis.gov.lv"
LV_SEARCH_URL = f"{LV_BASE}/EKEIS/Supplier/Procurement"
LV_RSS_URL = f"{LV_BASE}/EKEIS/Supplier/Procurement/Rss"
LV_NOTICE_URL = f"{LV_BASE}/EKEIS/Supplier/Procurement/{{id}}"

# CPV codes for trailers (Latvia uses EU CPV codes)
TRAILER_CPV_CODES = ["34223000", "34223100", "34223200", "34223300"]


def create_lv_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Latvia",
        country_code="LV",
        source_code="LV-EIS",
        base_url=LV_BASE,
        search_url=LV_SEARCH_URL,
        language="lv",
        trailer_keywords=[
            "piekabe",              # trailer
            "puspiekabe",           # semi-trailer
            "piekabes",             # trailers (genitive)
            "autocisterna",         # tanker
            "konteiners",           # container
            "lauka virtuve",        # field kitchen
            "zempiekraujamā",       # low-loader
            "kravnesīga piekabe",   # cargo trailer
            "degvielas piekabe",    # fuel trailer
            "trailer",              # English
            "semi-trailer",
        ],
        defence_authorities=[
            "Aizsardzības ministrija",
            "Nacionālie bruņotie spēki",
            "NBS",
            "Valsts aizsardzības militārais birojs",
            "Zemessardze",
            "Ministry of Defence",
        ],
        min_interval_seconds=2.0,
    )


class LVAdapter(BaseAdapter):
    """
    Latvia EIS adapter.

    Strategy:
    1. Try RSS feed filtered by CPV 34223 (trailer codes) — no session needed
    2. Browser-based keyword search on EIS portal
    3. Filter results for defence authority + trailer keyword

    Latvia is EU member — above-threshold tenders appear on TED.
    This adapter captures below-threshold and national-only notices.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=True)
        self._session.update_headers({
            "Accept": "application/rss+xml, application/xml, text/html, */*",
        })

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        return self._rss_search(cpv_prefix="34223", keyword=keyword, max_results=max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        all_results: dict[str, SearchResult] = {}

        # Phase 1: CPV-based RSS search for trailer codes
        logger.info("LV: Phase 1 — CPV trailer search via RSS/API")
        for cpv in (TRAILER_CPV_CODES[:1] if test_mode else TRAILER_CPV_CODES):
            for r in self._rss_search(cpv_prefix=cpv[:5], max_results=100):
                key = r.reference_id or r.url
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # Phase 2: Keyword search via browser (if RSS yields no results)
        if not all_results or not test_mode:
            logger.info("LV: Phase 2 — browser keyword search")
            kw_list = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords[:5]
            for kw in kw_list:
                for r in self._browser_search(kw, max_results_per_keyword):
                    key = r.reference_id or r.url
                    if key and key not in all_results:
                        all_results[key] = r
                time.sleep(self.config.min_interval_seconds)

        logger.info("LV: search_all_keywords → %d candidates", len(all_results))
        return list(all_results.values())

    def _rss_search(self, cpv_prefix: str = None, keyword: str = None,
                    max_results: int = 50) -> list:
        """Try EIS RSS feed for trailer CPV codes."""
        params = {}
        if cpv_prefix:
            params["cpvCode"] = cpv_prefix
        if keyword:
            params["title"] = keyword

        try:
            resp = self._session.get(LV_RSS_URL, params=params, timeout=20)
            if resp.status_code != 200:
                logger.debug("LV: RSS HTTP %s — will try browser", resp.status_code)
                return []

            content = resp.text
            if "<rss" not in content.lower() and "<feed" not in content.lower():
                logger.debug("LV: RSS response is not XML — portal may require session")
                return []

            return self._parse_rss(content, max_results)

        except Exception as exc:
            logger.debug("LV: RSS fetch error: %s", exc)
            return []

    def _parse_rss(self, xml_content: str, max_results: int) -> list:
        """Parse RSS/Atom feed from EIS portal."""
        import xml.etree.ElementTree as ET
        results = []
        try:
            root = ET.fromstring(xml_content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # Try Atom first, then RSS
            items = root.findall(".//atom:entry", ns) or root.findall(".//item")

            for item in items[:max_results]:
                title_el = (item.find("atom:title", ns) or item.find("title"))
                link_el = (item.find("atom:link", ns) or item.find("link"))
                date_el = (item.find("atom:published", ns) or
                           item.find("atom:updated", ns) or
                           item.find("pubDate"))

                title = (title_el.text or "").strip() if title_el is not None else ""
                link = (link_el.get("href") or (link_el.text or "")).strip() if link_el is not None else ""
                pub_date = (date_el.text or "")[:10] if date_el is not None else ""

                # Extract ID from link
                ref_id = ""
                import re
                m = re.search(r"/(\d+)/?$", link)
                if m:
                    ref_id = m.group(1)

                if not title:
                    continue

                results.append(SearchResult(
                    title=title[:200],
                    url=link or LV_SEARCH_URL,
                    authority="",  # not in RSS, filled at detail stage
                    reference_id=ref_id or link,
                    date=pub_date,
                    currency="EUR",
                ))

        except ET.ParseError as exc:
            logger.debug("LV: RSS parse error: %s", exc)

        return results

    def _browser_search(self, keyword: str, max_results: int) -> list:
        """Browser-based search on EIS portal."""
        results = []
        try:
            if not self.browser or not self.browser.page:
                return []

            search_url = f"{LV_SEARCH_URL}?Title={requests.utils.quote(keyword)}"
            ok = self.browser.goto(search_url, timeout=30000)
            if not ok:
                return []

            time.sleep(2)
            self.browser._screenshot(f"lv_search_{keyword[:20]}")

            # Parse results from page
            page_html = self.browser.page.content()
            results = self._parse_search_html(page_html)
            logger.info("LV: browser search '%s' → %d results", keyword, len(results))

        except Exception as exc:
            logger.warning("LV: browser search error: %s", exc)

        return results[:max_results]

    def _parse_search_html(self, html: str) -> list:
        """Parse search results from EIS HTML page."""
        import re
        results = []

        # Look for procurement links: /EKEIS/Supplier/Procurement/NNNNN
        for m in re.finditer(
            r'href=["\']([^"\']*?/Procurement/(\d+)[^"\']*?)["\'].*?'
            r'>([^<]{5,200})<',
            html,
            re.DOTALL
        ):
            url = m.group(1)
            ref_id = m.group(2)
            title = m.group(3).strip()
            if not url.startswith("http"):
                url = LV_BASE + url

            results.append(SearchResult(
                title=title[:200],
                url=url,
                authority="",
                reference_id=ref_id,
                date="",
                currency="EUR",
            ))

        return results

    # ── Filter ────────────────────────────────────────────────────────────

    def filter_defence(self, results: list) -> list:
        kept = []
        defence_kw = [a.lower() for a in self.config.defence_authorities]
        trailer_kw = [k.lower() for k in self.config.trailer_keywords]

        for r in results:
            auth_low = (r.authority or "").lower()
            title_low = (r.title or "").lower()
            combined = f"{auth_low} {title_low}"

            is_defence = any(kw in combined for kw in defence_kw)
            is_trailer = any(kw in title_low for kw in trailer_kw)

            # If we have no authority (RSS case), keep trailer hits and verify at detail stage
            if (is_trailer and (is_defence or not r.authority)):
                kept.append(r)

        logger.info("LV: filter_defence: %d → %d", len(results), len(kept))
        return kept

    # ── Detail ────────────────────────────────────────────────────────────

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        if not self.browser or not self.browser.page:
            return self._detail_from_result(result)

        try:
            url = result.url
            if not url.startswith("http"):
                url = LV_NOTICE_URL.format(id=result.reference_id)

            ok = self.browser.goto(url, timeout=30000)
            if not ok:
                return self._detail_from_result(result)

            time.sleep(1.5)
            html = self.browser.page.content()
            return self._parse_detail_html(html, result)

        except Exception as exc:
            logger.error("LV: detail error for %s: %s", result.reference_id, exc)
            return self._detail_from_result(result)

    def _parse_detail_html(self, html: str, result: SearchResult) -> NoticeDetail:
        import re

        def extract(pattern: str, default: str = "") -> str:
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            return (m.group(1).strip() if m else default)

        title = extract(r'<h1[^>]*>(.*?)</h1>') or result.title
        # Clean HTML tags
        title = re.sub(r"<[^>]+>", "", title).strip()

        authority = extract(
            r'(?:Pasūtītājs|Iepirkuma veicējs|Contracting\s+Authority)[^:]*:\s*'
            r'<[^>]*>([^<]+)</[^>]*>'
        ) or result.authority

        pub_date = extract(
            r'(?:Publicēšanas datums|Published)[^:]*:\s*(\d{4}-\d{2}-\d{2})'
        ) or result.date

        value = result.value
        val_str = extract(
            r'(?:Līguma vērtība|Estimated value)[^:]*:\s*([\d\s,.]+)\s*(?:EUR|€)'
        )
        if val_str:
            try:
                value = float(val_str.replace(" ", "").replace(",", "."))
            except ValueError:
                pass

        description = extract(
            r'(?:Apraksts|Description)[^:]*:\s*<[^>]*>(.*?)</[^>]*>', ""
        )[:500]
        description = re.sub(r"<[^>]+>", " ", description).strip()

        winner = extract(
            r'(?:Uzvarētājs|Award winner|Piegādātājs)[^:]*:\s*<[^>]*>([^<]+)</[^>]*>'
        )

        return NoticeDetail(
            title=title[:200],
            description=description,
            authority=authority[:200],
            date=pub_date,
            value=value,
            currency="EUR",
            winner=winner[:200] if winner else "",
            reference_id=result.reference_id,
            url=result.url,
            source_code="LV-EIS",
            raw_text=re.sub(r"<[^>]+>", " ", html)[:3000],
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
            source_code="LV-EIS",
            raw_text=result.title or "",
        )

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        return {
            "tender_id": f"LV-EIS-{detail.reference_id}",
            "source": "LV-EIS",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "Latvia",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": "EUR",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or "",
            "_national_raw_text": detail.raw_text or "",
            "_trailer_quantity_1": detail.quantity,
            "_raw": {"source": "LV-EIS", "url": detail.url},
            "estimated_value": (
                {"amount": detail.value, "currency": "EUR"} if detail.value else None
            ),
            "award": (
                {"winner_name": detail.winner, "awarded": True}
                if detail.winner else None
            ),
        }

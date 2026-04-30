"""
Italy Adapter — ANAC (Autorità Nazionale Anticorruzione)
Portal: https://www.anticorruzione.it

Strategy:
Two-track approach:
  Track A — REST API (fast path):
    The ANAC portal runs Liferay CMS which has headless REST APIs.
    Try /o/headless-delivery/v1.0 or direct search endpoints.
    Also checks Ministero della Difesa website for procurement listings.

  Track B — Playwright (fallback):
    Navigate the ANAC portal and use its search form.
    Search for trailer + defence keywords in Italian.

Coverage: IT has 27 TED notices — 2nd highest country after CZ.
National portal expected to have additional below-threshold tenders.

Defence authorities:
  Ministero della Difesa, Direzione degli Armamenti Terrestri (DAT),
  Segretariato Generale della Difesa (SGD-DNA),
  Armaereo, 1° Reparto Genio
"""

import re
import time
import logging
import os
import json
from typing import Optional

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.anticorruzione.it"
DIFESA_URL = "https://www.difesa.it"

# ANAC portal search URL
ANAC_SEARCH = f"{BASE_URL}/risultati-ricerca"


def _fix_anac_url(href: str) -> str:
    """
    Fix malformed ANAC portal URLs — the Liferay CMS sometimes emits hrefs
    where the slash between domain and path is missing, e.g.:
      https://www.anticorruzione.itrisultati-ricerca  (missing /)
      https://www.anticorruzione.it-/cerca-il-bando  (leading hyphen from path)
    Normalise to absolute https://www.anticorruzione.it/... form.
    """
    if not href:
        return href
    if href.startswith("http"):
        # Already absolute — fix missing slash: "anticorruzione.it<path>" → "anticorruzione.it/<path>"
        for domain in (BASE_URL, DIFESA_URL):
            if href.startswith(domain) and len(href) > len(domain):
                rest = href[len(domain):]
                if rest and not rest.startswith("/"):
                    href = domain + "/" + rest.lstrip("-")
                    break
        return href
    # Relative URL — build absolute
    return BASE_URL.rstrip("/") + "/" + href.lstrip("/-")
# ANAC advanced CIG search
ANAC_CIG_SEARCH = f"{BASE_URL}/-/cerca-il-bando"

# Liferay headless API (available on ANAC Liferay instance)
ANAC_HEADLESS = f"{BASE_URL}/o/headless-delivery/v1.0"

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")


def create_it_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Italy",
        country_code="IT",
        source_code="IT-AN",
        base_url=BASE_URL,
        search_url=ANAC_SEARCH,
        language="it",
        trailer_keywords=[
            "rimorchio",
            "semirimorchio",
            "carrellone",
            "cisterna",
            "cucina da campo",
            "container militare",
            "shelter",
            "pianale",
            "ribaltabile",
            "trasporto militare",
            "rimorchio militare",
            "veicolo rimorchiabile",
        ],
        defence_authorities=[
            "Ministero della Difesa",
            "Direzione degli Armamenti Terrestri",
            "Armamenti Terrestri",
            "Segretariato Generale della Difesa",
            "SGD",
            "Armaereo",
            "Reparto Genio",
            "Stato Maggiore",
            "Marina Militare",
            "Aeronautica Militare",
            "Esercito",
            "Difesa Servizi",
            "Difesa Servizi S.p.A.",
        ],
        min_interval_seconds=2.0,
    )


class ITAdapter(BaseAdapter):
    """
    Italy adapter — ANAC portal (anticorruzione.it).

    Uses a two-track approach:
    1. REST API via Liferay headless API (fast, when accessible)
    2. Playwright scraping of the ANAC search (fallback)

    The ANAC portal uses Liferay 7 CMS with standard REST capabilities.
    Defence notices are published through ANAC as all Italian public contracts
    must be registered (CIG — Codice Identificativo Gara).
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    def _build_session(self):
        """Create a requests Session with browser-like headers."""
        s = requests.Session()
        s.verify = _SSL_VERIFY
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        })
        return s

    # ── Main search ──

    def search(self, keyword: str, max_results: int = 30) -> list:
        """Search ANAC for a trailer keyword. Tries REST first, then Playwright."""
        results = self._rest_search(keyword, max_results)
        if not results:
            logger.info(f"IT: REST search empty for '{keyword}', trying Playwright")
            results = self._playwright_search(keyword, max_results)
        return results

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Run all keywords, deduplicate results.
        Also searches combined 'keyword difesa' queries to find defence-specific notices.
        """
        all_results: dict = {}

        keywords = self.config.trailer_keywords
        if test_mode:
            keywords = keywords[:2]

        # Primary keyword searches (general trailers)
        for keyword in keywords:
            logger.info(f"IT: searching '{keyword}'")
            hits = self.search(keyword, max_results=max_results_per_keyword)
            for h in hits:
                key = h.url or h.reference_id or h.title[:50]
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(f"IT: '{keyword}' → {len(hits)} hits, total {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        # Also search with "difesa" modifier for the top keywords
        if not test_mode:
            defence_queries = [
                f"{kw} difesa"
                for kw in ["rimorchio", "semirimorchio", "carrellone", "cisterna"]
            ]
            for query in defence_queries:
                logger.info(f"IT: searching combined '{query}'")
                hits = self._rest_search(query, max_results=max_results_per_keyword)
                if not hits:
                    hits = self._playwright_search(query, max_results=max_results_per_keyword)
                for h in hits:
                    key = h.url or h.reference_id or h.title[:50]
                    if key and key not in all_results:
                        all_results[key] = h
                time.sleep(self.config.min_interval_seconds)

        return list(all_results.values())

    def filter_defence(self, results: list) -> list:
        """
        Filter results to defence-relevant notices.

        For ANAC results: the search result listing doesn't carry authority data.
        All results from our trailer keyword searches are trailer-relevant;
        defence authority filtering happens at the AI classify step.

        We pass through results that:
        a) Have a detected defence authority (if available), OR
        b) Have a trailer keyword in any available field, OR
        c) Are from a keyword search (snippet = searched keyword)
        """
        defence = []
        for r in results:
            authority = (r.authority or "").lower()
            title = (r.title or "").lower()
            snippet = (r.snippet or "").lower()
            combined = authority + " " + title + " " + snippet

            is_defence = any(pat.lower() in combined for pat in self.config.defence_authorities)
            is_trailer = any(kw.lower() in combined for kw in self.config.trailer_keywords)

            if is_defence or is_trailer:
                defence.append(r)

        # If rich-filter found nothing but we have results from keyword searches,
        # pass them all through (ANAC result metadata is minimal — AI handles auth check)
        if not defence and results:
            return results

        return defence

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch full detail for a notice — tries REST then Playwright."""
        detail = self._rest_detail(result)
        if not detail:
            detail = self._playwright_detail(result)
        return detail or self._detail_from_search_result(result)

    # ── REST API (Track A) ──

    def _rest_search(self, keyword: str, max_results: int = 30) -> list:
        """
        Try ANAC REST API for keyword search.
        The Liferay headless API at /o/headless-delivery/v1.0 handles searches.
        Returns empty list if the REST API is not accessible (falls back to Playwright).
        """
        results = []

        # Try the Liferay search REST API
        endpoints_to_try = [
            # Liferay standard search
            f"{ANAC_HEADLESS}/sites/anticorruzione/search",
            # Direct search page with JSON accept
            f"{BASE_URL}/o/portal-search-rest/v1.0/search",
        ]

        for endpoint in endpoints_to_try:
            try:
                resp = self._session.get(
                    endpoint,
                    params={"q": keyword, "scope": "everything", "page": 1, "pageSize": max_results},
                    timeout=10,
                )
                if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("application/json"):
                    data = resp.json()
                    items = data.get("items", data.get("results", []))
                    for item in items:
                        result = self._liferay_item_to_search_result(item)
                        if result:
                            results.append(result)
                    if results:
                        logger.info(f"IT REST: '{keyword}' → {len(results)} results via {endpoint}")
                        return results
            except Exception as e:
                logger.debug(f"IT REST endpoint {endpoint} failed: {e}")

        # Try the ANAC tender search (simpler HTML-response endpoint)
        try:
            resp = self._session.get(
                ANAC_SEARCH,
                params={"q": keyword},
                timeout=15,
            )
            if resp.status_code == 200 and len(resp.content) > 5000:
                results = self._parse_search_html(resp.text, keyword)
                if results:
                    logger.info(f"IT REST HTML: '{keyword}' → {len(results)} results")
                    return results
        except Exception as e:
            logger.debug(f"IT REST HTML search failed: {e}")

        return []

    def _liferay_item_to_search_result(self, item: dict) -> Optional[SearchResult]:
        """Convert a Liferay search API item to SearchResult."""
        title = item.get("title", item.get("headline", ""))
        url = item.get("contentUrl", item.get("friendlyUrlPath", ""))
        url = _fix_anac_url(url)

        if not title or len(title) < 5:
            return None

        return SearchResult(
            title=title[:200],
            url=url,
            authority=item.get("taxonomyCategoryBriefs", [{}])[0].get("name", "") if item.get("taxonomyCategoryBriefs") else "",
            date=item.get("datePublished", item.get("dateCreated", ""))[:10] if item.get("datePublished") else "",
            snippet=item.get("description", "")[:300],
        )

    # Known noise patterns in ANAC search results (pagination, UI controls)
    _NOISE_PATTERNS = [
        "entries per page", "per page", "pagina", "ordina per",
        "sort by", "filtro", "next", "previous", "cookie",
        "accetta", "registrati", "accedi", "menu",
    ]

    def _parse_search_html(self, html: str, keyword: str) -> list:
        """
        Parse ANAC search results from the HTML response (Liferay portal).
        Filters out pagination controls and navigation links.
        """
        results = []
        link_pattern = re.compile(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*(.{5,300}?)\s*</a>',
            re.DOTALL,
        )
        keyword_lower = keyword.lower()
        seen_urls: set = set()

        for m in link_pattern.finditer(html):
            href = m.group(1)
            raw_text = m.group(2)
            text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', raw_text)).strip()

            if len(text) < 8:
                continue

            # Skip pagination / UI noise
            text_lower = text.lower()
            if any(noise in text_lower for noise in self._NOISE_PATTERNS):
                continue

            # Must contain keyword somewhere (in URL or text)
            if keyword_lower not in text_lower and keyword_lower not in href.lower():
                continue

            # Skip purely numeric link texts (page numbers)
            if re.match(r"^\d+$", text.strip()):
                continue

            # Skip very short generic link texts
            if text_lower in ("dettaglio", "vedi", "apri", "leggi", "scheda"):
                continue

            href = _fix_anac_url(href)

            # Deduplicate by URL
            if href in seen_urls:
                continue
            seen_urls.add(href)

            results.append(SearchResult(
                title=text[:200],
                url=href,
                snippet=keyword,
            ))

        return results

    def _rest_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Try to get notice detail via REST API."""
        if not result.url:
            return None
        try:
            resp = self._session.get(result.url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 2000:
                raw = self._html_to_text(resp.text)
                if len(raw) < 100:
                    return None
                return self._build_detail_from_text(result, raw)
        except Exception as e:
            logger.debug(f"IT: REST detail fetch failed for {result.url}: {e}")
        return None

    # ── Playwright (Track B) ──

    def _playwright_search(self, keyword: str, max_results: int = 30) -> list:
        """Use Playwright to search the ANAC portal."""
        results = []
        try:
            # Navigate to the search URL
            search_url = f"{ANAC_SEARCH}?q={keyword.replace(' ', '+')}"
            logger.info(f"IT Playwright: navigating to {search_url}")
            self.browser.goto(search_url)
            time.sleep(3)

            raw_text = self.browser.get_page_text()
            html = self.browser.get_page_html()

            # Parse links from the rendered page
            results = self._parse_search_html(html, keyword)
            if not results:
                # Try navigating to the CIG search page
                self.browser.goto(ANAC_CIG_SEARCH)
                time.sleep(2)
                # Try filling search input
                search_selectors = [
                    'input[placeholder*="ricerca"]',
                    'input[placeholder*="Cerca"]',
                    'input[type="search"]',
                    'input[name*="keywords"]',
                    'input.lfr-search-combobox-field',
                ]
                for sel in search_selectors:
                    try:
                        self.browser.fill(sel, keyword)
                        self.browser.press_key("Enter")
                        time.sleep(3)
                        html = self.browser.get_page_html()
                        results = self._parse_search_html(html, keyword)
                        if results:
                            break
                    except Exception:
                        continue

            logger.info(f"IT Playwright: '{keyword}' → {len(results)} results")

        except Exception as e:
            logger.error(f"IT: Playwright search failed for '{keyword}': {e}")

        return results[:max_results]

    def _playwright_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch notice detail via Playwright."""
        if not result.url:
            return None
        try:
            self.browser.goto(result.url)
            time.sleep(2)
            raw_text = self.browser.get_page_text()
            if raw_text and len(raw_text) > 100:
                return self._build_detail_from_text(result, raw_text)
        except Exception as e:
            logger.debug(f"IT: Playwright detail failed for {result.url}: {e}")
        return None

    # ── Detail extraction ──

    def _build_detail_from_text(self, result: SearchResult, raw_text: str) -> NoticeDetail:
        """Build a NoticeDetail from plain text extracted from a notice page."""
        detail = NoticeDetail(
            title=result.title or self._find_title(raw_text),
            url=result.url,
            authority=result.authority or self._find_authority(raw_text),
            reference_id=result.reference_id or self._find_cig(raw_text),
            source_code="IT-AN",
            raw_text=raw_text[:15000],
            currency="EUR",
        )
        detail.date = result.date or self._find_date(raw_text)
        detail.description = self._find_description(raw_text)
        detail.value = result.value or self._find_value(raw_text)
        detail.quantity = self._find_quantity(raw_text)
        detail.winner = self._find_winner(raw_text)
        detail.duration = self._find_duration(raw_text)
        detail.deadline = self._find_deadline(raw_text)
        return detail

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags to plain text."""
        import html as _html_module
        text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<(h[1-6]|p|div|li|br|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = _html_module.unescape(text)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)

    def _find_title(self, text: str) -> str:
        patterns = [
            r"(?:Oggetto|Descrizione gara|Denominazione)[:\s]+([^\n]{10,200})",
            r"(?:Titolo|Oggetto del contratto)[:\s]+([^\n]{10,200})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:200]
        return ""

    def _find_authority(self, text: str) -> str:
        patterns = [
            r"(?:Stazione appaltante|Ente appaltante|Amministrazione aggiudicatrice)[:\s]+([^\n]{5,150})",
            r"(?:Denominazione dell'ente|Acquirente)[:\s]+([^\n]{5,150})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:150]
        return ""

    def _find_cig(self, text: str) -> str:
        """Extract the CIG (Codice Identificativo Gara) — Italian procurement ID."""
        m = re.search(r"CIG[:\s]+([A-Z0-9]{8,10})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"(?:Numero|N\.)[:\s]*([A-Z0-9]{8,12})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    def _find_date(self, text: str) -> str:
        patterns = [
            r"(?:Data di pubblicazione|Pubblicato il|Data)[:\s]+(\d{2}/\d{2}/\d{4})",
            r"(\d{2}/\d{2}/\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parts = m.group(1).split("/")
                if len(parts) == 3:
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if m:
            return m.group(1)
        return ""

    def _find_description(self, text: str) -> str:
        patterns = [
            r"(?:Oggetto del contratto|Descrizione|Oggetto della gara)[:\s]+(.{30,500}?)(?:\n\n|\n\d|\Z)",
            r"(?:Oggetto|Object)[:\s]+(.{30,500}?)(?:\n\n|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                desc = m.group(1).strip()
                lines = [l for l in desc.split("\n") if l.strip()][:3]
                return " ".join(lines)[:500]
        return ""

    def _find_value(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:Importo|Valore stimato|Importo a base d'asta)[^\d]{0,30}([\d\.,]+)\s*(?:€|EUR|euro)",
            r"(?:Importo complessivo)[^\d]{0,20}([\d\.,]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val_str = m.group(1).replace(".", "").replace(",", ".")
                try:
                    v = float(val_str)
                    if v > 100:
                        return v
                except ValueError:
                    pass
        return None

    def _find_quantity(self, text: str) -> Optional[int]:
        patterns = [
            r"(\d+)\s*(?:unità|rimorchi|veicoli|sistemi)",
            r"(?:Quantità|Numero di unità)[:\s]+(\d+)",
            r"n\.\s*(\d+)\s*(?:rimorchi|veicoli)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1))
                    if 1 <= v <= 5000:
                        return v
                except ValueError:
                    pass
        return None

    def _find_winner(self, text: str) -> str:
        patterns = [
            r"(?:Aggiudicatario|Impresa aggiudicataria|Appaltatore)[:\s]+([^\n]{5,120})",
            r"(?:Contraente|Fornitore selezionato)[:\s]+([^\n]{5,120})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if not re.match(r"^[\d\s,.\+€]+$", name):
                    return name[:120]
        return ""

    def _find_duration(self, text: str) -> str:
        patterns = [
            r"(?:Durata del contratto|Durata|Periodo di esecuzione)[:\s]+([^\n]{3,80})",
            r"(\d+)\s*(?:mesi|settimane|anni|giorni)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:80]
        return ""

    def _find_deadline(self, text: str) -> str:
        patterns = [
            r"(?:Termine per la presentazione|Scadenza|Data di scadenza)[:\s]+(\d{2}/\d{2}/\d{4})",
            r"(?:Termine|Deadline)[:\s]+(\d{2}/\d{2}/\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parts = m.group(1).split("/")
                if len(parts) == 3:
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return ""

    def _detail_from_search_result(self, result: SearchResult) -> NoticeDetail:
        """Build minimal NoticeDetail from SearchResult when detail fetch fails."""
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            reference_id=result.reference_id,
            date=result.date,
            source_code="IT-AN",
            currency="EUR",
            raw_text=result.snippet or result.title,
        )

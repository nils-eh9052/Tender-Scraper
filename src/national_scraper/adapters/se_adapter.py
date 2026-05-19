"""
Sweden Adapter — Kommersannons.se (Antirio Supplier Hub)

Sweden's official national procurement portal. The platform is server-rendered
HTML (ASP.NET Razor Pages), NOT a React SPA — so simple GET requests work.

Discovered structure (2026-04-28):
  Search URL:   GET https://www.kommersannons.se/Notices/TenderNotices
  Search field: SearchString={keyword}
  Entity filter: SelectedProcuringEntity={entity_name_verbatim}
  Notice detail: /Notices/TenderNotice/{numeric_id}
  Notice reference format in link text: "{REF-ID} - {Title}"

FMV entity name in Kommersannons: "Försvarets materielverk"
(verified by inspecting the SelectedProcuringEntity dropdown; 37 notices present)

Defence procurement authorities:
  FMV (Försvarets materielverk) — primary defence procurement agency
  Försvarsmakten — Swedish Armed Forces
  Fortifikationsverket — Defence Estates Agency

Sweden already has 13 TED notices in relevant.json.
This adapter:
1. ENRICHMENT: matches national notices to existing TED entries via dedup key
2. DISCOVERY: notices that appear only on Kommersannons (e.g. 25FMVU2821)

Swedish trailer vocabulary:
  släpvagn=trailer, påhängsvagn=semitrailer, låglastare=low-bed,
  tanktrailer=tank trailer, fältkök=field kitchen, lastväxlare=hook-lift,
  drivmedelsekipage=fuel transport combination, transportekipage=transport combo
"""

import re
import time
import html as html_module
import logging
import os
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

KOMMERS_BASE = "https://www.kommersannons.se"
KOMMERS_SEARCH_URL = f"{KOMMERS_BASE}/Notices/TenderNotices"
KOMMERS_DETAIL_URL = f"{KOMMERS_BASE}/Notices/TenderNotice"

# FMV entity name as it appears in the SelectedProcuringEntity dropdown
# (verified 2026-04-28 by inspecting the <select> options)
FMV_ENTITY_NAME = "Försvarets materielverk"

# Other defence entities to search for
DEFENCE_ENTITY_NAMES = [
    "Försvarets materielverk",
    "Försvarsmakten",
    "Fortifikationsverket",
]


def create_se_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Sweden",
        country_code="SE",
        source_code="SE-KA",
        base_url=KOMMERS_BASE,
        search_url=KOMMERS_SEARCH_URL,
        language="sv",
        trailer_keywords=[
            "släpvagn",              # trailer
            "påhängsvagn",           # semitrailer
            "semitrailer",           # semitrailer (loanword)
            "låglastare",            # low-bed trailer
            "tanktrailer",           # tank trailer
            "fältkök",               # field kitchen
            "lastväxlare",           # hook-lift system
            "containervagn",         # container trailer
            "transportekipage",      # transport combination
            "drivmedelsekipage",     # fuel transport combination
        ],
        defence_authorities=[
            "Försvarets materielverk",
            "FMV",
            "Försvarsmakten",
            "Fortifikationsverket",
            "Totalförsvarets forskningsinstitut",
        ],
        min_interval_seconds=1.5,
    )


class SEAdapter(BaseAdapter):
    """
    Sweden adapter — Kommersannons.se (requests-based, no browser needed for search).

    Search strategy:
    1. Per-keyword GET search via SearchString parameter
    2. FMV authority search via SelectedProcuringEntity=Försvarets materielverk
    3. Other defence entity searches (Försvarsmakten, Fortifikationsverket)

    Detail pages require browser (JavaScript-rendered, but raw HTML also parseable).
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    # ── Session ──────────────────────────────────────────────────────────────

    def _build_session(self):
        try:
            import requests
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            logger.error("SE: 'requests' not installed")
            return None

        import requests as req_lib
        session = req_lib.Session()
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
            "Accept": "text/html, */*",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "Referer": KOMMERS_BASE,
        })
        return session

    # ── Public interface ──────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Keyword search via GET request to Kommersannons."""
        if not self._session:
            return []
        return self._get_search_results(
            params={"SearchString": keyword},
            max_results=max_results,
        )

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Keyword search + FMV authority search + other defence entities.

        Entity searches return ALL notices by that buyer (incl. non-trailer ones).
        filter_defence() keeps only defence-buyer results; AI classifier downstream
        determines trailer relevance.
        """
        if not self._session:
            logger.warning("SE: no session — cannot search")
            return []

        all_results: dict = {}

        # ── Per-keyword searches ──
        keywords = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords
        for kw in keywords:
            for r in self.search(kw, max_results=max_results_per_keyword):
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # ── Defence authority searches ──
        entities = DEFENCE_ENTITY_NAMES[:1] if test_mode else DEFENCE_ENTITY_NAMES
        for entity in entities:
            logger.info(f"SE: entity search for '{entity}'")
            new_count = 0
            for r in self._get_entity_results(entity, max_results=200):
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
                    new_count += 1
            logger.info(f"SE: entity='{entity}' → {new_count} new results")
            time.sleep(self.config.min_interval_seconds)

        logger.info(f"SE: search_all_keywords → {len(all_results)} unique results")
        return list(all_results.values())

    def _get_entity_results(self, entity: str, max_results: int = 200) -> list:
        """
        Fetch all notices for a specific procuring entity.
        Sets authority=entity on every result so filter_defence() keeps them.
        """
        raw = self._get_search_results(
            params={"SelectedProcuringEntity": entity},
            max_results=max_results,
        )
        for r in raw:
            if not r.authority:
                r.authority = entity
        return raw

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """
        Fetch notice detail.
        Strategy:
        1. GET the HTML detail page (requests — fast, works for most pages)
        2. Fall back to browser if requests fails or returns sparse content
        """
        if not result.url:
            return None

        logger.info(f"SE: fetching detail: {result.url[:80]}")

        # Try requests first (faster)
        raw_text = self._get_detail_html(result.url)

        # Fall back to browser if content is sparse
        if len(raw_text) < 200:
            raw_text = self._get_detail_browser(result)

        detail = NoticeDetail(
            title=result.title or self._find_title(raw_text),
            url=result.url,
            authority=result.authority or self._find_authority(raw_text),
            date=result.date or self._find_date(raw_text),
            reference_id=result.reference_id or self._find_ref_id(raw_text),
            source_code="SE-KA",
            raw_text=raw_text[:15000],
            currency="SEK",
        )
        detail.description = self._find_description(raw_text)
        detail.quantity = self._find_quantity(raw_text)
        detail.value = self._find_value(raw_text)
        detail.winner = self._find_winner(raw_text)
        detail.duration = self._find_duration(raw_text)
        return detail

    def filter_defence(self, results: list) -> list:
        """Keep only results from Swedish defence authorities."""
        kept = []
        se_patterns = [
            "fmv", "försvarets materielverk", "försvarsmakten",
            "fortifikationsverket", "totalförsvarets", "försvarets radio",
        ]
        for r in results:
            all_text = " ".join([
                (r.authority or "").lower(),
                (r.title or "").lower(),
                (r.snippet or "").lower(),
            ])
            is_defence = (
                any(pat.lower() in all_text for pat in self.config.defence_authorities)
                or any(p in all_text for p in se_patterns)
            )
            if is_defence:
                kept.append(r)
        logger.info(f"SE: filter_defence: {len(results)} → {len(kept)}")
        return kept

    # ── HTTP search helpers ───────────────────────────────────────────────────

    def _get_csrf_token(self) -> str:
        """Fetch a fresh CSRF token by loading the search page."""
        if not self._session:
            return ""
        try:
            resp = self._session.get(KOMMERS_SEARCH_URL, timeout=15)
            m = re.search(r'__RequestVerificationToken[^>]*value="([^"]+)"', resp.text)
            token = m.group(1) if m else ""
            if token:
                logger.debug(f"SE: CSRF token obtained ({token[:20]}...)")
            else:
                logger.warning("SE: CSRF token not found")
            return token
        except Exception as e:
            logger.debug(f"SE: CSRF fetch error: {e}")
            return ""

    def _get_search_results(self, params: dict, max_results: int = 100) -> list:
        """
        Execute a search on Kommersannons and parse the HTML result list.

        For entity-filtered searches, uses POST with CSRF token (required by the
        ASP.NET anti-forgery mechanism). For plain keyword searches, GET works.
        Paginates using PageIndex. Each page has ~25 notices.
        """
        if not self._session:
            return []

        # Determine whether this is an entity-filtered search (needs POST)
        needs_post = "SelectedProcuringEntity" in params

        # For POST: fetch CSRF token first
        csrf_token = ""
        if needs_post:
            csrf_token = self._get_csrf_token()
            if not csrf_token:
                logger.warning("SE: no CSRF token — falling back to GET (may miss entity filter)")

        all_results: dict = {}
        page = 1
        page_size = 25

        while len(all_results) < max_results:
            page_data = {**params, "PageIndex": page}

            try:
                if needs_post and csrf_token:
                    page_data["__RequestVerificationToken"] = csrf_token
                    resp = self._session.post(KOMMERS_SEARCH_URL, data=page_data, timeout=20)
                else:
                    resp = self._session.get(KOMMERS_SEARCH_URL, params=page_data, timeout=20)

                if resp.status_code != 200:
                    logger.warning(f"SE: HTTP {resp.status_code} on page {page}")
                    break

                page_results = self._parse_html_results(resp.text)
                if not page_results:
                    break
                new_on_page = 0
                for r in page_results:
                    key = r.url or r.reference_id or r.title[:50]
                    if key and key not in all_results:
                        all_results[key] = r
                        new_on_page += 1
                logger.debug(
                    f"SE: page {page}: {len(page_results)} results, {new_on_page} new"
                )
                if len(page_results) < page_size:
                    break
                page += 1
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"SE: search error page {page}: {e}")
                break

        return list(all_results.values())

    def _parse_html_results(self, html_text: str) -> list:
        """
        Parse notice links from the Kommersannons search results HTML.

        Notice links follow the pattern:
          <a href="/Notices/TenderNotice/{id}">  {ref} - {title}  </a>
        """
        results = []
        # Find all notice links: /Notices/TenderNotice/{numeric_id}
        pattern = re.compile(
            r'<a\s+href="(/Notices/TenderNotice/(\d+))"[^>]*>\s*(.*?)\s*</a>',
            re.DOTALL
        )
        for m in pattern.finditer(html_text):
            path = m.group(1)
            notice_id = m.group(2)
            raw_title = html_module.unescape(m.group(3)).strip()
            # Normalize whitespace (link text often has \r\n and indentation)
            raw_title = re.sub(r'\s+', ' ', raw_title).strip()
            if not raw_title or len(raw_title) < 5:
                continue
            url = KOMMERS_BASE + path

            # Reference number and title: "{REF} - {Title}" or just "{Title}"
            ref_id = ""
            title = raw_title
            ref_m = re.match(r'^([A-Z0-9][A-Z0-9/\-]{2,30})\s+-\s+(.+)$', raw_title)
            if ref_m:
                ref_id = ref_m.group(1)
                title = ref_m.group(2).strip()

            results.append(SearchResult(
                title=title[:200],
                url=url,
                reference_id=ref_id or notice_id,
                snippet=f"id={notice_id}",
            ))

        return results

    # ── Detail page helpers ───────────────────────────────────────────────────

    def _get_detail_html(self, url: str) -> str:
        """Fetch and convert detail page HTML to plain text via requests."""
        if not self._session:
            return ""
        try:
            resp = self._session.get(url, timeout=20)
            if resp.status_code != 200:
                return ""
            return self._html_to_text(resp.text)
        except Exception as e:
            logger.error(f"SE: detail fetch error: {e}")
            return ""

    @staticmethod
    def _html_to_text(html_text: str) -> str:
        """Convert HTML to readable plain text."""
        # Remove scripts, styles
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html_text,
                      flags=re.DOTALL | re.IGNORECASE)
        # Block elements → newlines
        text = re.sub(r'<(h[1-6]|p|div|li|br|tr|td|th)[^>]*>', '\n', text,
                      flags=re.IGNORECASE)
        # Remove remaining tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decode entities
        text = html_module.unescape(text)
        # Normalize
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines)

    def _get_detail_browser(self, result: SearchResult) -> str:
        """Fallback: use browser to fetch detail page."""
        if not self.browser.goto(result.url, wait_for="networkidle", timeout=30000):
            return ""
        self.browser.wait_seconds(2)
        safe_id = re.sub(r'[^a-z0-9]', '_', (result.reference_id or result.title[:15]).lower())
        self.browser._screenshot(f"se_detail_{safe_id}")
        return self.browser.get_page_text()

    # ── Text extraction helpers ───────────────────────────────────────────────

    def _find_title(self, text: str) -> str:
        for pat in [
            r'(?:Rubrik|Upphandlingsföremål|Titel)[:\s]+([^\n]{5,150})',
            r'(?:Subject|Title)[:\s]+([^\n]{5,150})',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:150]
        return ""

    def _find_authority(self, text: str) -> str:
        for pat in [
            r'(?:Upphandlande myndighet|Organisation|Myndighet)[:\s]+([^\n]{5,120})',
            r'(?:Contracting authority|Buyer)[:\s]+([^\n]{5,120})',
            r'(?:Köpare|Beställare)[:\s]+([^\n]{5,120})',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        for auth in self.config.defence_authorities:
            if auth.lower() in text.lower():
                return auth
        return ""

    def _find_date(self, text: str) -> str:
        for pat in [
            r'(?:Publiceringsdatum|Publicerad)[:\s]+(\d{4}-\d{2}-\d{2})',
            r'(\d{4}-\d{2}-\d{2})',
        ]:
            m = re.search(pat, text)
            if m:
                return m.group(1)[:10]
        m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        return ""

    def _find_description(self, text: str) -> str:
        for pat in [
            r'(?:Kort beskrivning|Beskrivning|Föremål)[:\s]+(.{30,500}?)(?:\n\n|$)',
            r'(?:Description|Short description)[:\s]+(.{30,500}?)(?:\n\n|$)',
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:400]
        return ""

    def _find_quantity(self, text: str) -> Optional[int]:
        for pat in [
            r'(\d+)\s*(?:stycken|st\.?|fordon|ekipage|släpvagn)',
            r'(?:Antal|Kvantitet)[:\s]+(\d+)',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1))
                    if 1 <= v <= 10000:
                        return v
                except ValueError:
                    pass
        return None

    def _find_value(self, text: str) -> Optional[float]:
        for pat in [
            r'(?:Uppskattad value|Kontraktsvärde|Värde)[:\s]+([\d\s]+)\s*(?:SEK|kr)',
            r'([\d\s]{5,})\s*(?:SEK|kronor)',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val_str = m.group(1).replace(' ', '').replace(',', '.')
                try:
                    v = float(val_str)
                    if v > 100:
                        return v
                except ValueError:
                    pass
        return None

    def _find_winner(self, text: str) -> str:
        for pat in [
            r'(?:Leverantör|Tilldelad|Vinnande)[:\s]+([^\n]{5,120})',
            r'(?:Winner|Awarded to|Contractor)[:\s]+([^\n]{5,120})',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        return ""

    def _find_duration(self, text: str) -> str:
        for pat in [
            r'(?:Kontraktslängd|Avtalstid|Löptid)[:\s]+([^\n]{3,60})',
            r'(\d+)\s*(?:månader|veckor|år|dagar)',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:60]
        return ""

    def _find_ref_id(self, text: str) -> str:
        for pat in [
            r'\b(\d{2}FMV[A-Z0-9]+)\b',       # FMV internal: 25FMVU2821
            r'\b(\d{6}-\d{4})\b',              # TED/OJEU: 182178-2026
            r'(?:Referensnummer|Diarienummer|Dnr)[:\s]+([A-Z0-9/\-_.]{4,40})',
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

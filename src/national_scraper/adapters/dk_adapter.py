"""
Denmark Adapter - Udbud.dk

Udbud.dk is the official Danish national procurement portal.
It is a Vue.js SPA (902-char shell for all paths). Results are rendered
client-side from pre-loaded data — no XHR is fired during search.

Discovered structure (2026-04-28):
  - Production URL: https://udbud.dk (no www — www redirects to no-www)
  - Search form: input[name="search-query"] on the homepage
  - Search trigger: Enter key or search button click
  - Results in DOM: links to /detaljevisning?noticeId={UUID}&noticeVersion=...
  - Notice URL: https://udbud.dk/detaljevisning?noticeId={UUID}&...
  - Publication number format: 00253032-2026 (matches TED OJEU number)

Defence procurement authorities:
  FMI (Forsvarsministeriets Materiel- og Indkobsstyrelse)
  Forsvaret (Danish Armed Forces)
  Forsvarets Materieltjeneste (Defence Material Service)

Danish trailer vocabulary (correct characters):
  anhaenger=anhænger, saettevogn=sættevogn, blokvogn, tanktrailer,
  feltkokken=feltkøkken, containervogn, specialtrailer
"""

import re
import time
import logging
import os
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

# No-www hostname is the production URL
UDBUD_BASE = "https://udbud.dk"
UDBUD_HOME = f"{UDBUD_BASE}/"
UDBUD_DETAIL_URL = f"{UDBUD_BASE}/detaljevisning"

DK_DEFENCE_PATTERNS = [
    "fmi",
    "forsvarsministeriets",
    "forsvaret",
    "forsvarets materieltjeneste",
    "forsvarsakademi",
    "forsvarscenter",
]

# Search terms — must use correct Danish characters (æ, ø, å)
DK_TRAILER_KEYWORDS = [
    "anhænger",        # trailer (with ae ligature)
    "sættevogn",       # semitrailer
    "blokvogn",        # low-bed transporter
    "tanktrailer",     # tank trailer
    "feltkøkken",      # field kitchen
    "containervogn",   # container trailer
    "specialtrailer",  # special purpose trailer
    "transporttrailer", # transport trailer
]


def create_dk_config():
    return AdapterConfig(
        country_name="Denmark",
        country_code="DK",
        source_code="DK-UD",
        base_url=UDBUD_BASE,
        search_url=UDBUD_HOME,
        language="da",
        trailer_keywords=DK_TRAILER_KEYWORDS,
        defence_authorities=[
            "Forsvarsministeriets Materiel- og Indkobsstyrelse",
            "FMI",
            "Forsvaret",
            "Forsvarets Materieltjeneste",
        ],
        min_interval_seconds=2.0,
    )


class DKAdapter(BaseAdapter):
    """
    Denmark adapter - Udbud.dk (Vue.js SPA, browser + DOM parsing).

    Udbud.dk renders results entirely client-side without firing network
    requests during search. The search fills the Vue reactive store.

    Search flow:
    1. Navigate to https://udbud.dk/ (homepage)
    2. Fill input[name="search-query"] with keyword
    3. Press Enter — Vue re-renders results in DOM
    4. Wait 4 seconds for rendering
    5. Extract /detaljevisning?noticeId= links from DOM
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search Udbud.dk for a keyword."""
        return self._search_browser(keyword, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Keyword search + FMI/Forsvaret authority search.
        """
        all_results: dict = {}

        keywords = (
            self.config.trailer_keywords[:2]
            if test_mode
            else self.config.trailer_keywords
        )
        for kw in keywords:
            for r in self._search_browser(kw, max_results=max_results_per_keyword):
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # FMI authority search (always run)
        logger.info("DK: running FMI/Forsvaret authority search")
        for fmi_kw in ["FMI Forsvaret", "Forsvarsministeriets Materiel"]:
            for r in self._search_browser(fmi_kw, max_results=30):
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)
            if test_mode:
                break

        logger.info(f"DK: search_all_keywords -> {len(all_results)} unique results")
        return list(all_results.values())

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch notice detail via browser navigation."""
        if not result.url:
            return None

        logger.info(f"DK: fetching detail: {result.url[:80]}")
        if not self.browser.goto(result.url, wait_for="networkidle", timeout=30000):
            return None

        self.browser.wait_seconds(4)
        safe_id = re.sub(
            r"[^a-z0-9]", "_",
            (result.reference_id or result.title[:15]).lower()
        )
        self.browser._screenshot(f"dk_detail_{safe_id}")
        raw_text = self.browser.get_page_text()

        detail = NoticeDetail(
            title=result.title or self._find_title(raw_text),
            url=result.url,
            authority=result.authority or self._find_authority(raw_text),
            date=result.date or self._find_date(raw_text),
            reference_id=result.reference_id or self._find_ref_id(raw_text),
            source_code="DK-UD",
            raw_text=raw_text[:15000],
            currency="DKK",
        )
        detail.description = self._find_description(raw_text)
        detail.quantity = self._find_quantity(raw_text)
        detail.value = self._find_value(raw_text)
        detail.winner = self._find_winner(raw_text)
        detail.duration = self._find_duration(raw_text)
        return detail

    def filter_defence(self, results: list) -> list:
        """Keep only results from Danish defence authorities."""
        kept = []
        for r in results:
            all_text = " ".join([
                (r.authority or "").lower(),
                (r.title or "").lower(),
                (r.snippet or "").lower(),
            ])
            is_defence = any(p in all_text for p in DK_DEFENCE_PATTERNS) or any(
                pat.lower() in all_text for pat in self.config.defence_authorities
            )
            if is_defence:
                kept.append(r)
        logger.info(f"DK: filter_defence: {len(results)} -> {len(kept)}")
        return kept

    # ------------------------------------------------------------------
    # Browser search helpers
    # ------------------------------------------------------------------

    def _search_browser(self, keyword: str, max_results: int = 50) -> list:
        """
        Fill the Udbud.dk search form and extract results from the rendered DOM.
        """
        logger.info(f"DK: searching for {keyword!r}")

        # Navigate to homepage (search form is here)
        ok = self.browser.goto(UDBUD_HOME, wait_for="networkidle", timeout=30000)
        if not ok:
            logger.warning("DK: could not load homepage")
            return []
        self.browser.wait_seconds(2)

        # Fill search form
        filled = self.browser.fill('input[name="search-query"]', keyword)
        if not filled:
            logger.warning("DK: could not fill search form")
            return []

        self.browser.wait_seconds(0.5)
        self.browser.press_key("Enter")
        self.browser.wait_seconds(5)  # Vue.js needs time to re-render

        safe_kw = re.sub(r"[^a-z0-9]", "_", keyword.lower()[:15])
        self.browser._screenshot(f"dk_search_{safe_kw}")
        self.browser.save_page_text(f"dk_search_{safe_kw}.txt")

        return self._extract_results_from_dom(max_results)

    def _extract_results_from_dom(self, max_results: int) -> list:
        """
        Extract notice links and metadata from the current Udbud.dk results DOM.

        Notice links follow the pattern:
          /detaljevisning?noticeId={UUID}&noticeVersion={N}&noticePublicationNumber={N}
        """
        results = []
        try:
            raw = self.browser.page.evaluate("""
                () => {
                    const items = [];
                    const seen = new Set();
                    // Collect all detaljevisning links with their surrounding context
                    const links = document.querySelectorAll(
                        'a[href*="detaljevisning"][href*="noticeId"]'
                    );
                    for (const link of links) {
                        const href = link.href;
                        if (seen.has(href)) continue;
                        seen.add(href);
                        // Walk up to find the card container
                        const card = link.closest(
                            '[class*="card"], [class*="result"], [class*="list"], article, li, div'
                        ) || link.parentElement;
                        const text = (card ? card.innerText : link.innerText || '').trim();
                        const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                        // Try to find organisation name (usually after notice type badge)
                        let org = '', title = '';
                        for (let i = 0; i < lines.length; i++) {
                            const l = lines[i];
                            if (/^[A-ZÀ-ÖØ-Þ]{3,}$/.test(l)) continue; // skip badge
                            if (!org && l.length > 3) { org = l; }
                            else if (!title && l.length > 5) { title = l; break; }
                        }
                        // Extract noticeId from URL
                        const idMatch = href.match(/noticeId=([a-f0-9-]+)/i);
                        const pubMatch = href.match(/noticePublicationNumber=([^&]+)/);
                        items.push({
                            href,
                            org,
                            title: title || lines[0] || '',
                            noticeId: idMatch ? idMatch[1] : '',
                            pubNumber: pubMatch ? pubMatch[1] : '',
                            snippet: lines.slice(0, 4).join(' '),
                        });
                    }
                    return items;
                }
            """) or []

        except Exception as e:
            logger.debug(f"DK DOM JS extraction: {e}")
            raw = []

        for item in raw[:max_results]:
            href = item.get("href", "")
            title = item.get("title") or item.get("org") or ""
            authority = item.get("org", "")
            notice_id = item.get("pubNumber") or item.get("noticeId") or ""

            if not href:
                continue

            results.append(SearchResult(
                title=title.strip()[:200],
                url=href,
                authority=authority.strip()[:200],
                reference_id=notice_id,
                snippet=item.get("snippet", "")[:300],
            ))

        logger.info(f"DK DOM: extracted {len(results)} results")

        # Fallback: if DOM extraction fails, parse page text
        if not results:
            results = self._parse_page_text_fallback(max_results)

        return results

    def _parse_page_text_fallback(self, max_results: int) -> list:
        """Last resort: parse visible page text for notice information."""
        page_text = self.browser.get_page_text()
        lines = [l.strip() for l in page_text.split("\n")
                 if len(l.strip()) > 15 and not any(
                     skip in l.lower() for skip in
                     ["cookie", "log ind", "menu", "søg", "filter", "kontakt", "hjaelp"]
                 )]

        results = []
        for line in lines[:max_results]:
            results.append(SearchResult(
                title=line[:200],
                url="",
                snippet=line[:300],
            ))

        logger.info(f"DK page text fallback: {len(results)} results")
        return results[:max_results]

    # ------------------------------------------------------------------
    # Text extraction helpers
    # ------------------------------------------------------------------

    def _find_title(self, text: str) -> str:
        for pat in [
            r"(?:Titel|Overskrift|Udbudsbekendtgoerelse)[:\s]+([^\n]{5,150})",
            r"(?:Title|Subject)[:\s]+([^\n]{5,150})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:150]
        return ""

    def _find_authority(self, text: str) -> str:
        for pat in [
            r"(?:Ordregiver|Myndighed|Organisation)[:\s]+([^\n]{5,120})",
            r"(?:Contracting authority|Buyer)[:\s]+([^\n]{5,120})",
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
            r"(?:Offentliggorelsesdato|Dato|Publiceret)[:\s]+(\d{4}-\d{2}-\d{2})",
            r"(\d{2})-(\d{2})-(\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ]:
            m = re.search(pat, text)
            if m:
                if m.lastindex == 3 and len(m.group(1)) == 2:
                    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                return m.group(1)[:10]
        return ""

    def _find_description(self, text: str) -> str:
        for pat in [
            r"(?:Beskrivelse|Kort beskrivelse|Resume)[:\s]+(.{30,500}?)(?:\n\n|$)",
            r"(?:Description)[:\s]+(.{30,500}?)(?:\n\n|$)",
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:400]
        return ""

    def _find_quantity(self, text: str) -> Optional[int]:
        for pat in [
            r"(\d+)\s*(?:stk\.?|enheder|anhænger|sættevogn|blokvogn)",
            r"(?:Antal|Maengde)[:\s]+(\d+)",
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
            r"(?:Anslaaet vaerdi|Kontraktvaerdi|Vaerdi)[:\s]+([\d\s,.]+)\s*(?:DKK|kr\.?|EUR)",
            r"([\d\s]{5,})\s*(?:DKK|kroner)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val_str = m.group(1).replace(" ", "").replace(",", ".")
                try:
                    v = float(val_str)
                    if v > 100:
                        return v
                except ValueError:
                    pass
        return None

    def _find_winner(self, text: str) -> str:
        for pat in [
            r"(?:Tilbudsgiver|Leverandoer|Tildelingsmodtager)[:\s]+([^\n]{5,120})",
            r"(?:Winner|Awarded to)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        return ""

    def _find_duration(self, text: str) -> str:
        for pat in [
            r"(?:Kontraktens varighed|Varighed)[:\s]+([^\n]{3,60})",
            r"(\d+)\s*(?:maaneder|uger|aar|dage)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:60]
        return ""

    def _find_ref_id(self, text: str) -> str:
        for pat in [
            r"\b(\d{8}-\d{4})\b",            # TED format: 00253032-2026
            r"(?:Referencenummer|ID)[:\s]+([A-Z0-9/\-_.]{4,40})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

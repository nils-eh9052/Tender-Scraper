"""
Spain Adapter — PLACE (Plataforma de Contratación del Sector Público)
URL: https://contrataciondelestado.es

Strategy:
  Playwright navigates the IBM WebSphere Portal SPA (JSF-based).
  The portal's Atom/syndication feeds require a client certificate
  (error: "Su certificado no está autorizado"), so browser navigation is used.

  Search flow:
  1. Navigate to the "Búsqueda avanzada de licitaciones" form
  2. Enter each trailer keyword and wait for results
  3. Parse result links and details from rendered HTML
  4. Filter by Ministerio de Defensa authority

  Note: The PLACE search page uses dynamically generated IBM Portal URLs
  and JSF component IDs. The selectors below use wildcard patterns robust
  to namespace changes.

Defence authorities:
  Ministerio de Defensa, DGAM, Ejército de Tierra, Armada Española,
  Ejército del Aire, JALE, Parque y Centro de Mantenimiento

Coverage: ES has 11 TED entries; national portal expected to contain
          additional below-EU-threshold tenders not published on TED.
"""

import re
import time
import logging
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://contrataciondelestado.es"
# The licitaciones search page — navigated to from the buscadores menu
SEARCH_PAGE = f"{BASE_URL}/wps/portal/plataforma/buscadores"
# Advanced licitaciones search URL pattern (contains obfuscated IBM Portal tokens)
ADVANCED_SEARCH_PARTIAL = "buscadores/busqueda"


def create_es_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Spain",
        country_code="ES",
        source_code="ES-PL",
        base_url=BASE_URL,
        search_url=SEARCH_PAGE,
        language="es",
        trailer_keywords=[
            "remolque",
            "semirremolque",
            "góndola",
            "cisterna",
            "cocina de campaña",
            "contenedor militar",
            "plataforma de transporte",
            "remolque militar",
            "plataforma baja",
            "portacontenedores",
        ],
        defence_authorities=[
            "Ministerio de Defensa",
            "Dirección General de Armamento",
            "DGAM",
            "Ejército de Tierra",
            "Armada Española",
            "Ejército del Aire",
            "Apoyo Logístico",
            "JALE",
            "Estado Mayor",
            "Secretaría de Estado de Defensa",
            "Parque y Centro de Mantenimiento",
            "Dirección General de Infraestructura",
        ],
        min_interval_seconds=2.0,
    )


class ESAdapter(BaseAdapter):
    """
    Spain adapter — PLACE (contrataciondelestado.es).

    IBM WebSphere Portal (JSF) — Playwright-based scraping.
    Each search keyword triggers a separate form submission and result parse.
    """

    # Input selector for the licitaciones keyword search
    # PLACE uses IBM Portal JSF namespace prefixes in IDs — we match by name-substring
    _SEARCH_INPUT_SEL = 'input[type="text"]'
    _SEARCH_SUBMIT_SEL = 'input[type="submit"], button[type="submit"]'
    # Tender result links in PLACE contain these path segments
    _RESULT_LINK_PATTERNS = [
        "buscadores/detalle",   # PLACE standard result URL pattern
        "licitacion",
        "expediente",
        "detalleLicitacion",
        "detalleContrato",
        "/detalle/",
    ]
    # Max pages to scrape per keyword (safety cap)
    MAX_PAGES = 5

    def search(self, keyword: str, max_results: int = 30) -> list:
        return self._playwright_search(keyword, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """Search all trailer keywords, deduplicate by URL/reference_id."""
        all_results: dict = {}

        keywords = self.config.trailer_keywords
        if test_mode:
            keywords = keywords[:2]

        # Navigate once to the search page before looping keywords
        search_nav_ok = self._navigate_to_licitaciones_search()
        if not search_nav_ok:
            logger.warning("ES: could not navigate to PLACE licitaciones search")

        for keyword in keywords:
            logger.info(f"ES: searching '{keyword}'")
            hits = self._playwright_search(keyword, max_results=max_results_per_keyword)
            for h in hits:
                key = h.url or h.reference_id or h.title[:50]
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(f"ES: '{keyword}' → {len(hits)} hits, total {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        return list(all_results.values())

    def filter_defence(self, results: list) -> list:
        """
        For PLACE, return all results from trailer keyword searches.

        PLACE search results have very sparse metadata (the listing page only
        shows a "Detalle" link per result, with no title or authority text).
        All metadata is on the individual detail pages.

        Since our search_all_keywords() uses trailer-specific keywords
        (remolque, semirremolque, etc.), all returned results are already
        trailer-relevant. Defence filtering happens later at the AI classify
        stage after get_detail() enriches each result.
        """
        if not results:
            return results

        # If results have authority/title data, apply standard filter
        results_with_data = [
            r for r in results
            if (r.authority and len(r.authority) > 3) or (r.title and len(r.title) > 10)
        ]
        if results_with_data:
            # Rich data available — apply standard authority/keyword filter
            return super().filter_defence(results_with_data) or results_with_data

        # No rich data — pass all detalle links through for detail-page enrichment
        return [r for r in results if r.url and "detalle" in r.url.lower()]

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Navigate to a PLACE notice and extract full details."""
        if not result.url:
            return self._detail_from_search_result(result)
        try:
            self.browser.goto(result.url)
            time.sleep(2)
            raw_text = self.browser.get_page_text()
            if raw_text and len(raw_text) > 100:
                detail = NoticeDetail(
                    title=result.title or self._find_title(raw_text),
                    url=result.url,
                    authority=result.authority or self._find_authority(raw_text),
                    reference_id=result.reference_id or self._find_ref(raw_text),
                    source_code="ES-PL",
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
        except Exception as e:
            logger.error(f"ES: get_detail failed for {result.url}: {e}")
        return self._detail_from_search_result(result)

    # ── Playwright helpers ──

    def _navigate_to_licitaciones_search(self) -> bool:
        """
        Navigate to the PLACE licitaciones advanced search form.
        Uses JavaScript click to bypass IBM Portal's visibility constraints.
        """
        try:
            self.browser.goto(SEARCH_PAGE)
            time.sleep(3)

            # Use JavaScript to find and click the licitaciones search link
            # — needed because IBM Portal often renders links with visibility:hidden
            clicked = self.browser.page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const target = links.find(a => a.href && a.href.includes('busqueda'));
                    if (target) { target.click(); return target.href; }
                    return null;
                }
            """)
            if clicked:
                logger.info(f"ES: JS-clicked licitaciones link: {str(clicked)[:60]}")
                time.sleep(4)
                return True

            logger.warning("ES: licitaciones search link not found via JS — staying on buscadores")
            return True
        except Exception as e:
            logger.error(f"ES: navigation to search failed: {e}")
            return False

    def _playwright_search(self, keyword: str, max_results: int = 30) -> list:
        """Fill the search form with keyword and parse results."""
        results = []
        try:
            # Ensure we're on the search page
            current_url = self.browser.page.url if self.browser.page else ""
            if ADVANCED_SEARCH_PARTIAL not in current_url and "buscadores" not in current_url:
                self._navigate_to_licitaciones_search()

            # Fill the keyword search input — use JS to bypass visibility constraints
            filled = self.browser.page.evaluate(f"""
                () => {{
                    const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
                    const inp = inputs.find(i => i.offsetParent !== null || true);
                    if (!inp) return false;
                    inp.value = {repr(keyword)};
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
            """)
            if not filled:
                logger.warning(f"ES: could not fill search input for '{keyword}'")
                return []
            time.sleep(0.5)

            # Capture the search API response if the portal uses XHR
            def submit_search():
                # Use JS to click the submit button (bypass visibility)
                self.browser.page.evaluate("""
                    () => {
                        const btn = document.querySelector('input[type="submit"], button[type="submit"]');
                        if (btn) { btn.click(); return true; }
                        const form = document.querySelector('form');
                        if (form) { form.submit(); return true; }
                        return false;
                    }
                """)
            search_input = None  # No longer needed directly

            captured = self.browser.capture_response(
                url_pattern="/busqueda",
                trigger=submit_search,
                timeout=8000,
            )

            if captured and isinstance(captured, dict):
                # Parse JSON response from IBM Portal search API
                results = self._parse_json_response(captured)
            else:
                # Wait for PLACE SPA to render results (IBM Portal is slow)
                time.sleep(6)
                results = self._parse_result_links(current_keyword=keyword)

        except Exception as e:
            logger.error(f"ES: Playwright search failed for '{keyword}': {e}")

        return results[:max_results]

    def _parse_result_links(self, current_keyword: str = "") -> list:
        """
        Parse tender result links from the current PLACE search results page.

        PLACE renders each result as a row with a "Detalle" link — the surrounding
        context has sparse text. We capture the detail link URL and use the
        searched keyword as the snippet (for downstream filter_defence).
        """
        results = []
        try:
            page = self.browser.page
            links = page.query_selector_all("a[href]")

            for link in links:
                href = link.get_attribute("href") or ""
                text = (link.inner_text() or "").strip()

                if not any(pat in href.lower() for pat in self._RESULT_LINK_PATTERNS):
                    continue

                # Make absolute URL
                if href.startswith("/"):
                    href = BASE_URL + href
                elif not href.startswith("http"):
                    continue

                # Try to get surrounding row/cell context
                try:
                    ctx = link.evaluate(
                        "el => {"
                        "  const p = el.closest('tr,li,article,section');"
                        "  return p ? p.innerText.slice(0,600) : '';"
                        "}"
                    ) or ""
                except Exception:
                    ctx = ""

                # Use keyword as snippet so filter_defence can identify trailer results
                snippet = current_keyword or ctx[:300]

                result = SearchResult(
                    title=ctx[:200] if len(ctx) > 15 else text[:200],
                    url=href,
                    authority=self._extract_authority_from_context(ctx),
                    date=self._extract_date_from_context(ctx),
                    snippet=snippet,
                )
                results.append(result)

        except Exception as e:
            logger.warning(f"ES: _parse_result_links error: {e}")

        return results

    def _parse_json_response(self, data: dict) -> list:
        """Parse search results from a JSON API response (if captured via XHR)."""
        results = []
        items = data.get("licitaciones", data.get("results", data.get("items", [])))
        for item in items:
            url = item.get("url", item.get("enlace", ""))
            if url and not url.startswith("http"):
                url = BASE_URL + url
            results.append(SearchResult(
                title=item.get("titulo", item.get("nombre", ""))[:200],
                url=url,
                authority=item.get("organo", item.get("organismo", ""))[:150],
                date=item.get("fecha", item.get("fechaPublicacion", ""))[:10],
                reference_id=item.get("expediente", item.get("numero", ""))[:50],
            ))
        return results

    def _extract_authority_from_context(self, context: str) -> str:
        """Try to extract the contracting authority from surrounding text."""
        for auth in self.config.defence_authorities:
            if auth.lower() in context.lower():
                return auth
        return ""

    def _extract_date_from_context(self, context: str) -> str:
        """Extract a date (DD/MM/YYYY) from surrounding text."""
        m = re.search(r"(\d{2}/\d{2}/\d{4})", context)
        if m:
            d, mo, yr = m.group(1).split("/")
            return f"{yr}-{mo}-{d}"
        m = re.search(r"(\d{4}-\d{2}-\d{2})", context)
        return m.group(1) if m else ""

    # ── Detail field extraction from page text ──

    def _find_title(self, text: str) -> str:
        for pat in [
            r"(?:Objeto del contrato|Nombre del contrato|Denominación)[:\s]+([^\n]{10,200})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:200]
        return ""

    def _find_authority(self, text: str) -> str:
        for pat in [
            r"(?:Órgano de contratación|Poder adjudicador|Entidad contratante)[:\s]+([^\n]{5,150})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:150]
        return ""

    def _find_ref(self, text: str) -> str:
        for pat in [
            r"(?:Expediente|Número de expediente)[:\s]+([A-Z0-9/\-\.]{4,40})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _find_date(self, text: str) -> str:
        m = re.search(r"(?:Fecha de publicación|Fecha)[:\s]+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if m:
            d, mo, yr = m.group(1).split("/")
            return f"{yr}-{mo}-{d}"
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        return m.group(1) if m else ""

    def _find_description(self, text: str) -> str:
        for pat in [
            r"(?:Objeto del contrato|Descripción)[:\s]+(.{30,500}?)(?:\n\n|\n\d|$)",
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                lines = [l for l in m.group(1).strip().split("\n") if l.strip()][:3]
                return " ".join(lines)[:500]
        return ""

    def _find_value(self, text: str) -> Optional[float]:
        m = re.search(
            r"(?:Valor estimado|Importe estimado|Presupuesto base)[^\d]{0,30}([\d\.,]+)\s*€",
            text, re.IGNORECASE,
        )
        if m:
            try:
                return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
        return None

    def _find_quantity(self, text: str) -> Optional[int]:
        m = re.search(r"(\d+)\s*(?:unidades?|remolques?|vehículo)", text, re.IGNORECASE)
        if m:
            try:
                v = int(m.group(1))
                if 1 <= v <= 5000:
                    return v
            except ValueError:
                pass
        return None

    def _find_winner(self, text: str) -> str:
        m = re.search(r"(?:Adjudicatario|Empresa adjudicataria)[:\s]+([^\n]{5,120})", text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if not re.match(r"^[\d\s,.\+]+$", name):
                return name[:120]
        return ""

    def _find_duration(self, text: str) -> str:
        m = re.search(r"(?:Plazo de ejecución|Duración)[:\s]+([^\n]{3,80})", text, re.IGNORECASE)
        return m.group(1).strip()[:80] if m else ""

    def _find_deadline(self, text: str) -> str:
        m = re.search(r"(?:Plazo de presentación|Fecha límite)[:\s]+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if m:
            d, mo, yr = m.group(1).split("/")
            return f"{yr}-{mo}-{d}"
        return ""

    def _detail_from_search_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            reference_id=result.reference_id,
            date=result.date,
            source_code="ES-PL",
            currency="EUR",
            raw_text=result.snippet or result.title,
        )

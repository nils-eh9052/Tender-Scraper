"""
Germany Adapter — service.bund.de (Bundesvergabeportal)

Discovered form structure (2026-04-26):
- URL: https://www.service.bund.de/Content/DE/Ausschreibungen/Suche/Formular.html?nn=4641514
- Filters (JS-triggered checkboxes):
    VSVgV  (id=f-ausschreibungsart-vsvgv, name=cl2Categories_AllocationType)
           → "Vergabeverordnung Verteidigung und Sicherheit" = 35 defence items
    KFZ    (id=f-leistung-kraftfahrwesen, name=cl2Categories_LeistungenErzeugnisse)
           → "Kraftfahrwesen" = 71 vehicle items
- Submit: button text 'Finden' (must scroll-click via JS)
- Pagination: 15 items/page, button text "eine Seite weiter" (JS-driven, no href)

Strategy: run BOTH filters independently → merge results → filter by defence keywords.
"""

import re
import logging
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.service.bund.de"
SEARCH_URL = "https://www.service.bund.de/Content/DE/Ausschreibungen/Suche/Formular.html?nn=4641514"

# Filter IDs (discovered via DOM inspection)
FILTER_VSSVGV = "f-ausschreibungsart-vsvgv"     # Verteidigung & Sicherheit (35)
FILTER_KFZ = "f-leistung-kraftfahrwesen"          # Kraftfahrwesen (71)

MAX_PAGES = 10  # Safety limit for pagination


def create_de_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Germany",
        country_code="DE",
        source_code="DE-SB",
        base_url=BASE_URL,
        search_url=SEARCH_URL,
        language="de",
        # These keywords are used for detail-page filtering after collecting all links
        trailer_keywords=[
            "Anhänger",
            "Sattelanhänger",
            "Tieflader",
            "Tankanhänger",
            "Feldküche",
            "Wechsellader",
            "Transportanhänger",
            "Shelter",
            "Hakenladegerät",
            "Schwerlastanhänger",
            "Sattelzug",
            "Kastenanhänger",
        ],
        defence_authorities=[
            "BAAINBw",
            "Bundesamt für Ausrüstung",
            "Bundeswehr",
            "HIL Heeresinstandsetzungslogistik",
            "BWI GmbH",
            "Bundesministerium der Verteidigung",
            "Wehrbereichsverwaltung",
            "Bundeswehrverwaltung",
            "Marine",
            "Kaserne",
            "Streitkräfte",
        ],
        min_interval_seconds=2.0,
    )


class DEAdapter(BaseAdapter):
    """Germany adapter — service.bund.de with VSVgV + Kraftfahrwesen filters."""

    # ── Public interface ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """
        Not used directly — we override search_all_keywords() instead.
        This runs a VSVgV or KFZ filter-based search.
        """
        # For the keyword-based search, delegate to filter-based collection
        return self._collect_with_filter(FILTER_VSSVGV, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """
        Run both VSVgV and Kraftfahrwesen filters and merge results.
        Ignores keyword list — uses server-side category filters instead.
        """
        all_results: dict = {}

        # ── VSVgV: Verteidigung & Sicherheit (35 items) ──
        logger.info("DE: collecting VSVgV (Verteidigung/Sicherheit) filter...")
        vsv_results = self._collect_with_filter(
            FILTER_VSSVGV,
            max_results=10 if test_mode else 500,
        )
        logger.info(f"DE: VSVgV → {len(vsv_results)} results")
        for r in vsv_results:
            key = r.url or r.title[:50]
            if key:
                all_results[key] = r

        if not test_mode:
            # ── Kraftfahrwesen: Vehicle category (71 items) ──
            logger.info("DE: collecting Kraftfahrwesen filter...")
            kfz_results = self._collect_with_filter(
                FILTER_KFZ,
                max_results=500,
            )
            logger.info(f"DE: KFZ → {len(kfz_results)} results")
            for r in kfz_results:
                key = r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r

        total = list(all_results.values())
        logger.info(f"DE: {len(total)} unique results after merging filters")
        return total

    def filter_defence(self, results: list) -> list:
        """
        For DE: most results are already defence/vehicle-related due to filters.
        Apply a light filter: keep VSVgV items always; filter KFZ by defence authority.
        """
        kept = []
        for r in results:
            # VSVgV items: keep all (already defence-specific)
            if r.snippet and "vsv" in r.snippet.lower():
                kept.append(r)
                continue

            # Authority check
            auth = (r.authority or "").lower()
            title = (r.title or "").lower()
            snippet = (r.snippet or "").lower()
            combined = auth + " " + title + " " + snippet

            is_defence = any(
                pat.lower() in combined
                for pat in self.config.defence_authorities
            )

            if is_defence:
                kept.append(r)
            else:
                # Keep anyway — we'll check detail pages for defence keywords
                kept.append(r)

        return results  # Return all; let detail extraction do the real filtering

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch the notice detail page."""
        if not result.url:
            return None

        logger.info(f"DE: fetching detail: {result.url[:80]}")
        if not self.browser.goto(result.url, wait_for="body", timeout=20000):
            return None

        self.browser.wait_seconds(2)

        safe_id = re.sub(r"[^a-z0-9]", "_", result.title[:15].lower())
        self.browser._screenshot(f"de_detail_{safe_id}")

        raw_text = self.browser.get_page_text()

        detail = NoticeDetail(
            title=self._clean_title(result.title),
            url=result.url,
            authority=result.authority or self._find_authority_in_text(raw_text),
            date=result.date or self._find_date_in_text(raw_text),
            source_code="DE-SB",
            raw_text=raw_text,
            currency="EUR",
        )

        detail.description = self._find_description(raw_text)
        detail.quantity = self._find_quantity(raw_text)
        detail.value = self._find_value(raw_text)
        detail.winner = self._find_winner(raw_text)
        detail.duration = self._find_duration(raw_text)
        detail.reference_id = self._find_ref_id(raw_text) or result.reference_id

        return detail

    # ── Filter-based collection ──

    def _collect_with_filter(self, filter_id: str, max_results: int = 200) -> list:
        """
        Apply one checkbox filter, submit, then collect all pages of results.
        """
        results = []

        logger.info(f"DE: loading search form for filter '{filter_id}'")
        if not self.browser.goto(SEARCH_URL, wait_for="networkidle", timeout=25000):
            logger.error("DE: cannot load search form")
            return []

        self.browser.wait_seconds(2)

        # ── Check the filter checkbox ──
        checked = self.browser.page.evaluate(f"""
            () => {{
                const cb = document.getElementById('{filter_id}');
                if (!cb) return false;
                cb.click();
                return cb.checked;
            }}
        """)
        if not checked:
            logger.warning(f"DE: could not check filter '{filter_id}'")
            return []

        logger.info(f"DE: checked filter '{filter_id}'")
        self.browser.wait_seconds(1.5)  # Let the checkbox JS event propagate

        # ── Submit (Finden button) ──
        # Use the first <button> in the DOM — proven to be Finden in standalone tests.
        # Note: locator('button:has-text(Finden)') may time out after checkbox AJAX.
        # Note: form.submit() is shadowed by a child input[name=submit].
        self.browser.page.evaluate(
            "() => { const b = document.querySelector('button'); if (b) b.click(); }"
        )
        logger.info("DE: clicked Finden (first button in DOM)")

        self.browser.wait_seconds(6)
        self.browser.wait_networkidle(timeout=12000)

        # ── Verify count ──
        text = self.browser.get_page_text()
        count_m = re.search(r"(\d+)\s*Ausschreibungen", text)
        total_expected = int(count_m.group(1)) if count_m else "?"
        logger.info(f"DE: filter '{filter_id}' → {total_expected} Ausschreibungen")
        self.browser._screenshot(f"de_filter_{filter_id}")

        # ── Paginate and collect ──
        page_num = 0
        while len(results) < max_results:
            page_num += 1
            if page_num > MAX_PAGES:
                logger.warning(f"DE: reached page limit ({MAX_PAGES})")
                break

            # Extract links on this page
            page_results = self._extract_page_links()
            if not page_results:
                logger.info(f"DE: no results on page {page_num}")
                break

            results.extend(page_results)
            logger.info(f"DE: page {page_num}: {len(page_results)} links "
                        f"(total so far: {len(results)})")

            # Check for next page
            if not self._click_next_page():
                logger.info(f"DE: no more pages after page {page_num}")
                break

            self.browser.wait_seconds(3)
            self.browser.wait_networkidle(timeout=8000)

        return results

    def _extract_page_links(self) -> list:
        """Extract SearchResult objects from the current results page."""
        link_elements = self.browser.page.query_selector_all("a[href*='IMPORTE']")
        results = []

        for el in link_elements:
            try:
                href = el.get_attribute("href") or ""
                if not href.startswith("http"):
                    href = BASE_URL + ("" if href.startswith("/") else "/") + href

                # Clean soft hyphens + extra whitespace from title
                raw_title = el.inner_text() or el.text_content() or ""
                title = self._clean_title(raw_title)

                if not title:
                    continue

                # Extract date if visible in surrounding context
                parent = el.evaluate_handle("el => el.closest('li, article, div.item, tr') || el.parentElement")
                parent_text = ""
                try:
                    parent_text = (parent.as_element().inner_text() or "") if parent else ""
                    parent_text = self._clean_title(parent_text)
                except Exception:
                    pass

                date_str = self._find_date_in_text(parent_text)

                # Extract authority from title/snippet
                authority = self._extract_authority_from_text(title + " " + parent_text)

                # Folder name from URL (eVergabe = military, etc.)
                folder_m = re.search(r"IMPORTE/Ausschreibungen/([^/;]+)/", href)
                folder = folder_m.group(1) if folder_m else ""

                results.append(SearchResult(
                    title=title,
                    url=href,
                    authority=authority,
                    date=date_str,
                    snippet=f"folder={folder}",  # Track source folder
                    reference_id=folder,
                ))
            except Exception as e:
                logger.debug(f"DE link extract error: {e}")

        return results

    def _click_next_page(self) -> bool:
        """
        Click the 'eine Seite weiter' pagination button.
        Returns True if successfully clicked.
        """
        # The button has no href, it's JS-driven
        clicked = self.browser.page.evaluate("""
            () => {
                // Find 'eine Seite weiter' link/button
                const links = Array.from(document.querySelectorAll('a, button'));
                const nxt = links.find(el =>
                    el.textContent.trim().toLowerCase().includes('eine seite weiter') ||
                    el.textContent.trim().toLowerCase() === 'weiter'
                );
                if (nxt && !nxt.disabled) {
                    nxt.click();
                    return true;
                }
                return false;
            }
        """)
        return bool(clicked)

    # ── Text helpers ──

    @staticmethod
    def _clean_title(text: str) -> str:
        """Remove soft hyphens, zero-width chars, and normalize whitespace."""
        # Remove soft hyphens (U+00AD), zero-width chars, STX (U+0002)
        text = re.sub(r"[\u00ad\u0002\u200b\u200c\u200d\ufeff]", "", text)
        # Remove "Ausschreibung" prefix that appears on every link
        text = re.sub(r"^Ausschreibung\s*", "", text, flags=re.IGNORECASE)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_authority_from_text(self, text: str) -> str:
        """Check for known defence authority names in text."""
        for auth in self.config.defence_authorities:
            if auth.lower() in text.lower():
                return auth
        # Also look for "Vergabestelle ..." pattern
        m = re.search(r"Vergabestelle\s+([^\n\|]{4,60})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    def _find_authority_in_text(self, text: str) -> str:
        patterns = [r"(?:Vergabestelle|Auftraggeber)[:\s]+([^\n]{5,80})"]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return self._extract_authority_from_text(text)

    def _find_date_in_text(self, text: str) -> str:
        m = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
        if m:
            p = m.group(1).split(".")
            return f"{p[2]}-{p[1]}-{p[0]}"
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        return m2.group(1) if m2 else ""

    def _find_description(self, text: str) -> str:
        patterns = [
            r"(?:Beschreibung|Leistung|Gegenstand|Auftragsgegenstand)[:\s]+(.{50,500}?)(?:\n\n|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:500]
        return ""

    def _find_quantity(self, text: str) -> Optional[int]:
        patterns = [
            r"(\d[\d.]*)\s*(?:Stück|Stk\.?|Einheiten|Fahrzeuge|Anhänger)",
            r"(?:Menge|Anzahl)[:\s]+(\d[\d.]*)",
            r"(\d+)\s*x\s*(?:Anhänger|Fahrzeug|Sattelzug)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1).replace(".", ""))
                except ValueError:
                    continue
        return None

    def _find_value(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:Auftragswert|Schätzwert|Gesamtwert)[^\d]{0,20}(\d[\d.,]+)\s*(?:EUR|€)",
            r"(\d[\d.,]+)\s*EUR\b",
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
                    continue
        return None

    def _find_winner(self, text: str) -> str:
        patterns = [
            r"(?:Auftragnehmer|Zuschlag erteilt|Zuschlag an)[:\s]+([^\n]{5,100})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:100]
        return ""

    def _find_duration(self, text: str) -> str:
        patterns = [
            r"(?:Laufzeit|Vertragsdauer)[:\s]+([^\n]{3,60})",
            r"(\d+)\s*(?:Monate?|Wochen|Jahre?)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:60]
        return ""

    def _find_ref_id(self, text: str) -> str:
        patterns = [
            r"(?:Aktenzeichen|Vergabenummer|Referenznummer)[:\s]+([A-Z0-9/\-_.]{4,40})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

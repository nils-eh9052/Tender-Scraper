"""
Germany evergabe-online.de Adapter

The official federal e-procurement platform used by BAAINBw (Bundesamt für
Ausrüstung, Informationstechnik und Nutzung der Bundeswehr) and other German
defence authorities.  Superior to service.bund.de for BW procurement.

Portal:  https://www.evergabe-online.de/search.html
Engine:  Apache Wicket (SPA-like server-rendered, no REST API)
Access:  Public search visible without login; full documents may need login.

Search strategy:
  1. Fill #keywordString with trailer terms
  2. Expand advanced search section
  3. Check VSVGV checkbox (Vergabeverordnung Verteidigung und Sicherheit)
  4. Click SUCHEN button
  5. Parse #datatable rows (Bezeichnung | Geschäftszeichen | Vergabestelle | Ort)

Also searches by authority name ("BAAINBw", "Bundeswehr") without keyword filter
to catch procurement not using standard terminology.

Login: Optional — set DE_EVERGABE_USERNAME + DE_EVERGABE_PASSWORD in .env for
access to restricted documents.
"""

import logging
import re
import time
from typing import Optional

from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ...credentials import CredentialManager

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.evergabe-online.de/search.html"


def create_de_evergabe_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Germany",
        country_code="DE",
        source_code="DE-EV",
        base_url="https://www.evergabe-online.de",
        search_url=SEARCH_URL,
        language="de",
        trailer_keywords=[
            "Anhänger",
            "Sattelanhänger",
            "Auflieger",
            "Tieflader",
            "Tankanhänger",
            "Feldküche",
            "Wechsellader",
            "Hakenladegerät",
            "Transportanhänger",
            "Schwerlastanhänger",
            "Shelter",
            "Bergeanhänger",
            "Fahrzeugbeschaffung",
            "Logistikfahrzeug",
        ],
        defence_authorities=[
            "BAAINBw",
            "Bundesamt für Ausrüstung",
            "HIL",
            "Heeresinstandsetzungslogistik",
            "BWI",
            "Bundeswehr",
            "Bundesministerium der Verteidigung",
            "Streitkräftebasis",
        ],
        min_interval_seconds=3.0,
    )


class DEEvergabeAdapter(BaseAdapter):
    """
    Germany evergabe-online.de adapter (Wicket-based portal).

    Uses VSVgV (defence/security procurement regulation) checkbox filter
    to restrict results to defence procurement from the start.
    """

    def __init__(self, browser, config: AdapterConfig):
        super().__init__(browser, config)
        self._page_loaded = False
        self._search_page_ready = False

    def _load_search_page(self):
        """Navigate to search.html and optionally log in."""
        logger.info("DE-EV: loading search page")
        self.browser.goto(SEARCH_URL)
        time.sleep(2)

        creds = CredentialManager.get("DE_EVERGABE")
        if creds:
            logger.info("DE-EV: logging in with credentials")
            try:
                self.browser.fill("#id1", creds["username"])
                self.browser.fill("#id2", creds["password"])
                login_btn = self.browser.page.query_selector("button#loginButton, button[name*='login']")
                if login_btn:
                    login_btn.click()
                    time.sleep(3)
                    logger.info("DE-EV: login submitted")
            except Exception as exc:
                logger.warning(f"DE-EV: login failed: {exc}")
        else:
            logger.info("DE-EV: no credentials — public access")

        # Expand advanced search to reveal VSVgV checkbox
        self.browser.page.evaluate('''() => {
            const links = [...document.querySelectorAll("a")];
            const adv = links.find(a => a.textContent.includes("Erweiterte"));
            if (adv) adv.click();
        }''')
        time.sleep(1.5)
        self._search_page_ready = True

    def _do_search(self, keyword: str, vsvgv_only: bool = False):
        """Fill form and submit, return (rows, total_count)."""
        if not self._search_page_ready:
            self._load_search_page()

        # Clear and fill keyword
        try:
            kw_field = self.browser.page.query_selector("#keywordString")
            if kw_field:
                kw_field.triple_click()
                kw_field.type(keyword)
        except Exception:
            self.browser.fill("#keywordString", keyword)
        time.sleep(0.3)

        # VSVgV (defence/security) checkbox:
        # Enable only for authority-name searches to avoid missing keyword hits
        # (BAAINBw often uses procurement codes, not keywords like "Anhänger").
        try:
            vsvgv = self.browser.page.query_selector('input[value="VSVGV"]')
            if vsvgv:
                checked = vsvgv.is_checked()
                if vsvgv_only and not checked:
                    vsvgv.click()
                elif not vsvgv_only and checked:
                    vsvgv.click()  # uncheck for keyword searches
        except Exception as exc:
            logger.debug(f"DE-EV: VSVgV checkbox: {exc}")

        # Submit
        try:
            btn = self.browser.page.query_selector('button[value="suchen"]')
            if btn:
                btn.click()
            else:
                self.browser.page.locator("#keywordString").press("Enter")
        except Exception:
            try:
                self.browser.page.locator("#keywordString").press("Enter")
            except Exception:
                pass

        time.sleep(5)
        return self._parse_results_page()

    def _parse_results_page(self) -> tuple[list, int]:
        """Parse the current results page. Returns (rows, total_count)."""
        text = self.browser.page.inner_text("body")

        # Total count
        m = re.search(r"Zeige\s+\d+\s+bis\s+\d+\s+von\s+(\d+)", text)
        total = int(m.group(1)) if m else 0

        # Table rows
        rows_data = self.browser.page.evaluate('''() => {
            const rows = [];
            document.querySelectorAll("#datatable tr").forEach((tr, idx) => {
                if (idx === 0) return;  // skip header
                const cells = tr.querySelectorAll("td");
                const link = tr.querySelector("a");
                if (cells.length >= 3 && cells[0].innerText.trim()) {
                    rows.push({
                        title:     cells[0].innerText.trim(),
                        ref_id:    cells[1] ? cells[1].innerText.trim() : "",
                        authority: cells[2] ? cells[2].innerText.trim() : "",
                        place:     cells[3] ? cells[3].innerText.trim() : "",
                        url:       link ? link.href : ""
                    });
                }
            });
            return rows;
        }''')

        return rows_data, total

    def _next_page(self) -> bool:
        """Click the 'next page' link if available. Returns True if navigated."""
        try:
            next_btn = self.browser.page.query_selector(
                'a[title="Nächste Seite"], a.next, .pagination a[rel="next"]'
            )
            if not next_btn:
                # Look for >> or → button
                next_btn = self.browser.page.evaluate('''() => {
                    const links = [...document.querySelectorAll(".pagination a, .pager a")];
                    return links.find(a => a.textContent.includes(">>") || a.textContent.includes("Nächste"));
                }''')
            if next_btn:
                self.browser.page.evaluate("el => el.click()", next_btn)
                time.sleep(3)
                return True
        except Exception:
            pass
        return False

    def search(self, keyword: str, max_results: int = 50) -> list[SearchResult]:
        """Search evergabe for one keyword under VSVgV filter."""
        if not self._search_page_ready:
            self._load_search_page()

        rows_data, total = self._do_search(keyword)
        logger.info(f"DE-EV: '{keyword}' → {total} total, {len(rows_data)} on page")

        results = []
        for r in rows_data:
            if not r.get("title"):
                continue
            results.append(SearchResult(
                title=r["title"],
                url=r.get("url", ""),
                authority=r.get("authority", ""),
                date="",
                reference_id=r.get("ref_id", ""),
                snippet=r.get("place", ""),
            ))
        return results

    def search_all_keywords(
        self,
        max_results_per_keyword: int = 50,
        test_mode: bool = False,
    ) -> list[SearchResult]:
        """
        Search for all trailer keywords + defence authority names under VSVgV.
        Deduplicates by reference_id (Geschäftszeichen).
        """
        self._load_search_page()

        all_results: dict[str, SearchResult] = {}
        keywords = self.config.trailer_keywords
        authorities = self.config.defence_authorities

        if test_mode:
            keywords = keywords[:3]
            authorities = authorities[:2]

        for kw in keywords:
            try:
                rows, total = self._do_search(kw)
                for r in rows:
                    key = r.get("ref_id") or r.get("title", "")[:60]
                    if key and key not in all_results:
                        all_results[key] = SearchResult(
                            title=r["title"],
                            url=r.get("url", ""),
                            authority=r.get("authority", ""),
                            date="",
                            reference_id=r.get("ref_id", ""),
                            snippet=r.get("place", ""),
                        )
                logger.info(
                    f"DE-EV: kw='{kw}' → {total} total, "
                    f"{len(rows)} on page, {len(all_results)} unique so far"
                )
            except Exception as exc:
                logger.error(f"DE-EV: search '{kw}' failed: {exc}")
            time.sleep(self.config.min_interval_seconds)

        # Authority-only search (no keyword, just BAAINBw etc. in authority field)
        for auth in authorities:
            try:
                rows, total = self._do_search(auth, vsvgv_only=True)
                for r in rows:
                    key = r.get("ref_id") or r.get("title", "")[:60]
                    if key and key not in all_results:
                        all_results[key] = SearchResult(
                            title=r["title"],
                            url=r.get("url", ""),
                            authority=r.get("authority", ""),
                            date="",
                            reference_id=r.get("ref_id", ""),
                            snippet=r.get("place", ""),
                        )
                logger.info(
                    f"DE-EV: auth='{auth}' → {total} total, "
                    f"{len(rows)} on page, {len(all_results)} unique so far"
                )
            except Exception as exc:
                logger.error(f"DE-EV: auth search '{auth}' failed: {exc}")
            time.sleep(self.config.min_interval_seconds)

        logger.info(f"DE-EV: total unique results: {len(all_results)}")
        return list(all_results.values())

    def filter_defence(self, results: list[SearchResult]) -> list[SearchResult]:
        """
        Keep notice if:
          (a) trailer keyword in title, OR
          (b) defence authority in authority field (from VSVgV authority search)
              — these go to AI classification which will decide relevance.
        """
        kept = []
        all_kw = {kw.lower() for kw in self.config.trailer_keywords}
        all_auth = {a.lower() for a in self.config.defence_authorities}

        for r in results:
            title_low = r.title.lower()
            auth_low  = r.authority.lower()
            has_trailer_kw = any(kw in title_low for kw in all_kw)
            has_defence_auth = any(a in auth_low for a in all_auth)
            if has_trailer_kw or has_defence_auth:
                kept.append(r)

        logger.info(f"DE-EV: filter_defence: {len(results)} → {len(kept)}")
        return kept

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Navigate to the notice detail page and extract information."""
        if not result.url:
            return NoticeDetail(
                title=result.title,
                authority=result.authority,
                reference_id=result.reference_id,
                url=result.url,
                source_code="DE-EV",
            )

        try:
            self.browser.goto(result.url)
            time.sleep(3)
            self.browser._screenshot(f"de_evergabe_detail_{result.reference_id[:20]}")

            text = self.browser.page.inner_text("body")

            # Extract structured fields
            def extract_field(label: str) -> str:
                m = re.search(
                    re.escape(label) + r"[:\s]*\n([^\n]{1,200})", text, re.IGNORECASE
                )
                return m.group(1).strip() if m else ""

            value = None
            value_str = extract_field("Geschätzter Auftragswert") or extract_field("Estimated value")
            if value_str:
                m = re.search(r"([\d.,]+)", value_str.replace(" ", ""))
                if m:
                    try:
                        value = float(m.group(1).replace(".", "").replace(",", "."))
                    except ValueError:
                        pass

            date_str = extract_field("Bekanntmachungsdatum") or extract_field("Datum der Absendung")
            deadline_str = extract_field("Angebotsfrist") or extract_field("Schlusstermin")

            return NoticeDetail(
                title=result.title,
                description=text[:500],
                authority=result.authority,
                date=self._parse_de_date(date_str),
                value=value,
                currency="EUR",
                deadline=self._parse_de_date(deadline_str),
                reference_id=result.reference_id,
                url=result.url,
                source_code="DE-EV",
                raw_text=text[:3000],
            )

        except Exception as exc:
            logger.error(f"DE-EV: detail error for {result.reference_id}: {exc}")
            return NoticeDetail(
                title=result.title,
                authority=result.authority,
                reference_id=result.reference_id,
                url=result.url,
                source_code="DE-EV",
            )

    @staticmethod
    def _parse_de_date(s: str) -> str:
        """DD.MM.YYYY → YYYY-MM-DD."""
        if not s:
            return ""
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}" if m else ""

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        safe_id = re.sub(r"[^\w\-]", "_", detail.reference_id or detail.title[:20])
        return {
            "tender_id": f"DE-EV-{safe_id}",
            "source": "DE-EV",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "Germany",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": "EUR",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or detail.raw_text[:500],
            "_national_raw_text": detail.raw_text,
            "_raw": {"source": "DE-EV", "url": detail.url},
            "estimated_value": (
                {"amount": detail.value, "currency": "EUR"} if detail.value else None
            ),
            "award": (
                {"winner_name": detail.winner, "awarded": True}
                if detail.winner else None
            ),
        }

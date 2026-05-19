"""
Czech Republic Adapter — NEN/NIPEZ (nen.nipez.cz)
Národní elektronický nástroj — National Electronic Tool

Discovered via browser investigation (2026-04-28):
  Search page URL: https://nen.nipez.cz/verejne-zakazky
  Search input:    #verejne-zakazky-seznam-filter__fast-search (name="query")
  Search button:   button:has-text("HLEDAT")
  Results URL:     https://nen.nipez.cz/verejne-zakazky/p:vz:query={keyword}
  Results table:   tbody tr (class: gov-table gov-table--tablet-block gov-sortable-table)
  Row columns:     [Detail link] | System# | Title | Status | Authority | Deadline
  Detail URL:      https://nen.nipez.cz/verejne-zakazky/p:vz:query={q}/detail-zakazky/{id}

The NEN system is a React SPA with server-side rendered search results. The tender
list is rendered in the server HTML after navigating to the search URL. JavaScript
loads filter dropdown data (CPV codes, NUTS codes) via XHR, but the tender table
itself is server-rendered HTML — no separate API for the tender list.

Wait time: 10-12 seconds after clicking HLEDAT for results to render.

Czech Republic has 15 defence trailer TED notices — the primary value of this adapter
is ENRICHMENT (quantity, specs from the full notice text). Secondary: new notices
only visible on NEN (not cross-published to TED).

Dedup: 15 existing TED notices matched via authority + title fragment + year.
PDF attachments: downloaded to data/raw/cz/ if found; text extracted for AI.
"""

import re
import time
import logging
from pathlib import Path
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL   = "https://nen.nipez.cz"
SEARCH_URL = "https://nen.nipez.cz/verejne-zakazky"
SEARCH_INPUT_ID = "#verejne-zakazky-seznam-filter__fast-search"
SEARCH_BUTTON   = "HLEDAT"

PDF_DIR = Path("data/raw/cz")

# NEN status → pipeline vocabulary
_CZ_STATUS_MAP: dict[str, str] = {
    "probíhající":             "Open",
    "vyhlášený":               "Open",
    "neukončen":               "Open",    # "Not terminated" (search table label)
    "not terminated":          "Open",
    "ukončený":                "Closed",
    "termination of performance": "Closed",
    "zadán":                   "Awarded",
    "awarded":                 "Awarded",
    "zrušen":                  "Cancelled",
    "cancelled":               "Cancelled",
}


def _map_cz_status(raw: str) -> str:
    """Map a raw NEN status string to pipeline vocabulary."""
    key = raw.strip().lower()
    for pattern, mapped in _CZ_STATUS_MAP.items():
        if pattern in key:
            return mapped
    return ""


# Known defence-related Czech keywords in the combined text
_DEFENCE_KW = (
    "obrany", "vojenský", "vojenská", "vojenské", "vojensk",
    "vop cz", "armáda", "armády", "ministerstvo obrany",
    "vojenský technický",
)


def create_cz_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Czech Republic",
        country_code="CZ",
        source_code="CZ-NEN",
        base_url=BASE_URL,
        search_url=SEARCH_URL,
        language="cs",
        trailer_keywords=[
            "přívěs",             # trailer
            "návěs",              # semi-trailer
            "podvalník",          # low-bed
            "cisterna",           # tanker
            "polní kuchyně",      # field kitchen
            "nosič kontejnerů",   # container carrier
            "transportní přívěs", # transport trailer
            "těžký přívěs",       # heavy trailer
            "nízkoložný",         # low-loading
            "nákladní přívěs",    # cargo trailer
            "vojenský přívěs",    # military trailer
            "přívěsný",           # trailer-based
        ],
        defence_authorities=[
            "Ministerstvo obrany",
            "VOP CZ",
            "Vojenský technický ústav",
            "Sekce vyzbrojování",
            "Agentura hospodaření s nemovitým majetkem",
            "Armáda České republiky",
        ],
        min_interval_seconds=2.0,
    )


class CZAdapter(BaseAdapter):
    """
    Czech Republic adapter — NEN/NIPEZ (nen.nipez.cz).

    Browser-based search: fill form, click HLEDAT, wait 12s, parse tbody rows.
    PDF attachments are downloaded to data/raw/cz/ for later AI processing.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        self._search_page_loaded = False

    # ── Session ──

    def _build_session(self):
        try:
            import requests, urllib3
            urllib3.disable_warnings()
        except ImportError:
            return None
        import os
        session = __import__("requests").Session()
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
            "Accept": "*/*",
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
        })
        return session

    # ── Public interface ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search NEN for a keyword via browser form interaction."""
        logger.info(f"CZ: searching for '{keyword}'")
        return self._browser_search(keyword, max_results=max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Search for all trailer keywords + all defence authority names.
        Deduplicates by NEN system number or URL.
        """
        all_results: dict = {}

        keywords    = self.config.trailer_keywords
        authorities = self.config.defence_authorities
        if test_mode:
            keywords    = keywords[:3]
            authorities = authorities[:2]

        for kw in keywords:
            hits = self._browser_search(kw, max_results=max_results_per_keyword)
            for r in hits:
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            logger.info(f"CZ: kw='{kw}' → {len(hits)} hits (total {len(all_results)})")
            time.sleep(self.config.min_interval_seconds)

        for auth in authorities:
            hits = self._browser_search(auth, max_results=max_results_per_keyword)
            for r in hits:
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            logger.info(f"CZ: auth='{auth}' → {len(hits)} hits (total {len(all_results)})")
            time.sleep(self.config.min_interval_seconds)

        total = list(all_results.values())
        logger.info(f"CZ: search_all_keywords → {len(total)} results")
        return total

    def filter_defence(self, results: list) -> list:
        """Keep notices from Czech defence authorities OR with trailer keywords."""
        kept = []
        for r in results:
            combined = " ".join([
                (r.title or "").lower(),
                (r.authority or "").lower(),
                (r.snippet or "").lower(),
            ])

            has_defence_auth = any(
                auth.lower() in combined
                for auth in self.config.defence_authorities
            ) or any(kw in combined for kw in _DEFENCE_KW)

            has_trailer_kw = any(
                kw.lower() in combined
                for kw in self.config.trailer_keywords
            )

            if has_defence_auth or has_trailer_kw:
                kept.append(r)

        logger.info(f"CZ: filter_defence: {len(results)} → {len(kept)}")
        return kept

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch NEN notice detail page. Downloads PDF attachments if found."""
        if not result.url:
            return self._detail_from_search_result(result)

        logger.info(f"CZ: fetching detail: {result.url[:80]}")
        if not self.browser.goto(result.url, wait_for="networkidle", timeout=30000):
            logger.warning("CZ: detail page load failed")
            return self._detail_from_search_result(result)

        self.browser.wait_seconds(5)  # Angular/server-side render time
        safe_id = re.sub(r"[^a-z0-9]", "_", (result.reference_id or "cz")[:15].lower())
        self.browser._screenshot(f"cz_detail_{safe_id}")

        raw_text = self.browser.get_page_text()

        # Download PDF attachments and extract text
        pdf_text = self._extract_and_download_pdfs(result)
        if pdf_text:
            raw_text = raw_text + "\n\n--- PDF CONTENT ---\n" + pdf_text

        status = self._find_status(raw_text)
        cpv    = self._find_cpv(raw_text)

        # Prepend structured meta so AI classifier sees it even if truncated
        meta_prefix = ""
        if cpv:
            meta_prefix += f"CPV: {cpv}\n"
        if status:
            meta_prefix += f"STATUS: {status}\n"
        if meta_prefix:
            raw_text = meta_prefix + raw_text

        detail = NoticeDetail(
            title=result.title or self._find_title(raw_text),
            url=result.url,
            authority=result.authority or self._find_authority(raw_text),
            date=result.date or self._find_date(raw_text),
            source_code="CZ-NEN",
            raw_text=raw_text[:15000],
            currency="CZK",
            status=status,
        )
        detail.reference_id = result.reference_id or self._find_ref_id(raw_text)
        detail.description  = self._find_description(raw_text)
        detail.quantity     = self._find_quantity(raw_text)
        detail.value        = self._find_value(raw_text)
        detail.winner       = self._find_winner(raw_text)
        detail.duration     = self._find_duration(raw_text)

        # If awarded, try fetching the result sub-page for winner name
        if status == "Awarded" and not detail.winner:
            winner_from_result = self._try_result_page(result)
            if winner_from_result:
                detail.winner = winner_from_result
                logger.info(f"CZ: winner from result page: {winner_from_result[:60]}")

        return detail

    # ── Browser search ──

    def _browser_search(self, keyword: str, max_results: int = 50) -> list:
        """
        Fill the NEN search form, submit, wait for results, parse table rows.

        The results table (tbody tr) has columns:
          [0] "Detail" text / link anchor
          [1] System number (e.g. N006/26/V00011038)
          [2] Title / procedure name
          [3] Status (Neukončen, Zadán, Zrušen, ...)
          [4] Authority name
          [5] Deadline

        Detail URL pattern:
          /verejne-zakazky/p:vz:query={query}/detail-zakazky/{id_with_dashes}
        """
        # Load the search page if needed (reuse across keywords)
        try:
            current = self.browser.current_url()
            if SEARCH_URL not in current:
                if not self.browser.goto(SEARCH_URL, wait_for="domcontentloaded", timeout=45000):
                    logger.error("CZ: cannot load search page")
                    return []
                self.browser.wait_seconds(6)
        except Exception as e:
            logger.error(f"CZ: navigation error: {e}")
            return []

        # Fill the fast-search input
        try:
            self.browser.page.fill(SEARCH_INPUT_ID, "", timeout=5000)
            self.browser.page.fill(SEARCH_INPUT_ID, keyword, timeout=5000)
        except Exception as e:
            logger.warning(f"CZ: could not fill search input: {e}")
            return []

        time.sleep(0.5)

        # Click the HLEDAT (Search) button
        try:
            self.browser.page.click(f"button:has-text('{SEARCH_BUTTON}')", timeout=5000)
        except Exception:
            try:
                self.browser.page.keyboard.press("Enter")
            except Exception as e:
                logger.warning(f"CZ: could not submit search: {e}")
                return []

        # Wait for results to render (server renders the table).
        # Reduced from 12s to 6s in sprint6/performance — results arrive in 3-4s.
        self.browser.wait_seconds(6)

        safe_kw = re.sub(r"[^a-z0-9]", "_", keyword[:15].lower())
        self.browser._screenshot(f"cz_search_{safe_kw}")

        # Parse tbody rows from the rendered page
        try:
            rows = self.browser.page.evaluate("""
                () => {
                    const rows = document.querySelectorAll("tbody tr");
                    const results = [];
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll("td"));
                        const link = row.querySelector("a[href]");
                        if (cells.length >= 4) {
                            results.push({
                                href: link ? link.href : "",
                                sysnum: cells[1] ? cells[1].innerText.trim() : "",
                                title:  cells[2] ? cells[2].innerText.trim() : "",
                                status: cells[3] ? cells[3].innerText.trim() : "",
                                auth:   cells[4] ? cells[4].innerText.trim() : "",
                                deadline: cells[5] ? cells[5].innerText.trim() : ""
                            });
                        }
                    }
                    return results;
                }
            """) or []
        except Exception as e:
            logger.error(f"CZ: row extraction error: {e}")
            return []

        results = []
        for row in rows[:max_results]:
            title   = row.get("title", "").strip()
            href    = row.get("href", "").strip()
            sys_num = row.get("sysnum", "").strip()
            auth    = row.get("auth", "").strip()
            status  = row.get("status", "").strip()
            dl      = row.get("deadline", "").strip()

            if not title and not sys_num:
                continue

            url = href or (
                f"{BASE_URL}/verejne-zakazky/p:vz:query={keyword}/detail-zakazky/"
                + sys_num.replace("/", "-")
                if sys_num else ""
            )

            snippet = f"status={status} deadline={dl} kw={keyword}"
            results.append(SearchResult(
                title=title[:200],
                url=url,
                authority=auth[:150],
                date=self._parse_czech_date(dl),
                reference_id=sys_num[:60],
                snippet=snippet[:400],
            ))

        logger.info(f"CZ: '{keyword}' → {len(results)} rows parsed")

        # Navigate back to search URL for next keyword search
        try:
            if not self.browser.goto(SEARCH_URL, wait_for="domcontentloaded", timeout=30000):
                pass
            self.browser.wait_seconds(4)
        except Exception:
            pass

        return results

    # ── PDF extraction ──

    def _extract_and_download_pdfs(self, result: SearchResult) -> str:
        """Find PDF attachments on detail page, download them, extract text."""
        try:
            pdf_links = self.browser.page.evaluate("""
                () => Array.from(document.querySelectorAll("a[href]"))
                    .filter(a => a.href.toLowerCase().includes(".pdf") ||
                                 a.href.toLowerCase().includes("download") ||
                                 (a.innerText||"").toLowerCase().includes("pdf"))
                    .map(a => ({href: a.href, text: (a.innerText||"").trim()}))
                    .slice(0, 5)
            """) or []
        except Exception:
            return ""

        if not pdf_links:
            return ""

        logger.info(f"CZ: found {len(pdf_links)} PDF links")
        texts = []
        for item in pdf_links[:3]:
            href = item.get("href", "")
            ltext = item.get("text", "unknown")
            if not href:
                continue
            if not href.startswith("http"):
                href = BASE_URL + ("" if href.startswith("/") else "/") + href

            safe = re.sub(r"[^a-z0-9_.-]", "_", href.split("/")[-1][:60].lower())
            if not safe.endswith(".pdf"):
                safe += ".pdf"
            # Sanitize reference_id (N006/25/V00008153 → N006_25_V00008153)
            ref = re.sub(r"[/\\:]", "_", result.reference_id or "unknown")
            dest = PDF_DIR / f"{ref}_{safe}"

            try:
                if self._session:
                    resp = self._session.get(href, timeout=30, stream=True)
                    if resp.status_code == 200:
                        dest.write_bytes(resp.content)
                        logger.info(f"CZ: PDF saved: {dest.name} ({len(resp.content)//1024} KB)")
                        txt = self._extract_pdf_text(dest)
                        if txt:
                            texts.append(f"[PDF: {ltext}]\n{txt}")
            except Exception as e:
                logger.warning(f"CZ: PDF error ({href}): {e}")

        return "\n".join(texts)[:5000]

    @staticmethod
    def _extract_pdf_text(pdf_path: Path) -> str:
        """Extract text from PDF using pypdf or pdfplumber (both optional)."""
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            pages_text = [p.extract_text() or "" for p in reader.pages[:5]]
            return "\n".join(t.strip() for t in pages_text if t.strip())[:3000]
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"CZ: pypdf error: {e}")
        try:
            import pdfplumber
            with pdfplumber.open(str(pdf_path)) as pdf:
                texts = [p.extract_text() or "" for p in pdf.pages[:5]]
                return "\n".join(t for t in texts if t.strip())[:3000]
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"CZ: pdfplumber error: {e}")
        return ""

    def _detail_from_search_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            date=result.date,
            reference_id=result.reference_id,
            source_code="CZ-NEN",
            currency="CZK",
            raw_text=result.snippet or "",
        )

    # ── Text / date helpers ──

    @staticmethod
    def _parse_czech_date(text: str) -> str:
        """Parse Czech/NEN date formats → YYYY-MM-DD.

        Handles:
          dd. mm. yyyy  (Czech locale)
          dd.mm.yyyy    (Czech compact)
          dd/mm/yyyy    (NEN portal — DATE OF PUBLICATION ON PROFILE)
          dd/mm/yyyy, HH:MM  (NEN with time component)
          YYYY-MM-DD    (ISO)
        """
        # dd/mm/yyyy with optional time suffix (NEN format)
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if m:
            return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
        # dd. mm. yyyy or dd.mm.yyyy
        m = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})", text)
        if m:
            return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
        # ISO YYYY-MM-DD
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        return m.group(1) if m else ""

    def _find_title(self, text: str) -> str:
        m = re.search(r"(?:Název|Předmět|Name|Title)[:\s]+([^\n]{10,200})", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _find_authority(self, text: str) -> str:
        for pat in [
            r"(?:Zadavatel|Objednatel|Contracting authority)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        for auth in self.config.defence_authorities:
            if auth.lower() in text.lower():
                return auth
        return ""

    def _find_date(self, text: str) -> str:
        return self._parse_czech_date(text)

    def _find_ref_id(self, text: str) -> str:
        for pat in [
            r"(?:Evidenční číslo|Systémové číslo|Č\. j\.)[:\s]+([A-Z0-9/\-_.]{4,40})",
            r"\b(N\d{3}[/\-]\d{2,4}[/\-][A-Z0-9]+)\b",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _find_description(self, text: str) -> str:
        for pat in [
            r"(?:Popis|Předmět zakázky|Description|Stručný popis)[:\s]+(.{30,500}?)(?:\n\n|$)",
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                lines = [l.strip() for l in m.group(1).split("\n") if l.strip()]
                return " ".join(lines[:3])[:400]
        return ""

    def _find_quantity(self, text: str) -> Optional[int]:
        for pat in [
            r"(\d[\d\s]*)\s*(?:ks|kusů|kus|přívěsů|návěsů|vozidel)",
            r"(?:Počet|Množství|Quantity)[:\s]+(\d[\d\s]*)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1).replace(" ", ""))
                    if 1 <= v <= 9999:
                        return v
                except ValueError:
                    pass
        return None

    def _find_value(self, text: str) -> Optional[float]:
        # NEN English interface: "ESTIMATED VALUE (EXCL. VAT)\n153,107.43"
        m = re.search(r"ESTIMATED VALUE \(EXCL\. VAT\)\n([\d,. ]+)", text)
        if m:
            raw = m.group(1).strip().replace(" ", "").replace(",", "")
            try:
                v = float(raw)
                if v > 0:
                    return v
            except ValueError:
                pass

        for pat in [
            r"(?:Předpokládaná hodnota|Odhadovaná hodnota)[^\d]{0,20}([\d\s,.]+)\s*(?:CZK|Kč|KČ)",
            r"([\d\s,.]+)\s*(?:CZK|Kč|KČ)\b",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                raw = m.group(1).strip().replace(" ", "")
                if "," in raw and "." not in raw:
                    raw = raw.replace(",", ".")
                elif raw.count(".") > 1:
                    raw = raw.replace(".", "", raw.count(".") - 1)
                try:
                    v = float(raw)
                    if v > 100:
                        return v
                except ValueError:
                    pass
        return None

    def _find_winner(self, text: str) -> str:
        # Same-line patterns: "Label: Value"
        for pat in [
            r"(?:Vítěz|Dodavatel|Vybraný dodavatel|Winner|Jméno dodavatele)[:\s]+([^\n]{5,120})",
            r"(?:Supplier|Selected supplier|Selected tenderer|Contractor)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if not re.match(r"^[\d\s,.]+$", name):
                    return name[:120]
        # Next-line patterns: "LABEL\nValue" — NEN English/Czech result-tab format
        for heading in (
            "SUPPLIER", "SELECTED SUPPLIER", "SELECTED TENDERER",
            "DODAVATEL", "VYBRANÝ DODAVATEL", "VÍTĚZ",
            "NAME OF SUPPLIER", "JMÉNO DODAVATELE",
        ):
            m = re.search(
                rf"{re.escape(heading)}\s*\n\s*([^\n]{{5,120}})",
                text, re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip()
                if not re.match(r"^[\d\s,.]+$", name):
                    return name[:120]
        return ""

    def _find_status(self, text: str) -> str:
        """Extract and map NEN procurement status to pipeline vocabulary.

        NEN English UI shows: "CURRENT STATUS OF THE PROCUREMENT PROCEDURE"
        Czech status values: Probíhající / Vyhlášený → Open
                             Ukončený → Closed
                             Zadán → Awarded
                             Zrušen → Cancelled
        """
        # NEN English heading (all-caps label followed by newline + value)
        m = re.search(
            r"CURRENT STATUS OF THE PROCUREMENT PROCEDURE\s*\n\s*([^\n]+)",
            text, re.IGNORECASE,
        )
        if not m:
            # Czech fallback label
            m = re.search(
                r"STAV ZADÁVACÍHO ŘÍZENÍ\s*\n\s*([^\n]+)",
                text, re.IGNORECASE,
            )
        if not m:
            return ""
        raw = m.group(1).strip()
        return _map_cz_status(raw)

    def _find_cpv(self, text: str) -> str:
        """Extract CPV code from NEN detail page text.

        NEN English UI shows: "CODE FROM THE CPV CODE LIST"
        followed on the next line by the code (e.g. "34223300-9").
        """
        m = re.search(
            r"CODE FROM THE CPV CODE LIST\s*\n\s*([\d]{8}-[\d])",
            text, re.IGNORECASE,
        )
        if not m:
            # Looser pattern: any 8-digit + check-digit code in that section
            m = re.search(
                r"CODE FROM THE CPV CODE LIST\s*\n\s*([\d\-]{9,12})",
                text, re.IGNORECASE,
            )
        return m.group(1).strip() if m else ""

    def _try_result_page(self, result: SearchResult) -> str:
        """Navigate to the NEN result/vysledek sub-page and extract winner name.

        NEN result tab URL patterns tried in order:
          1. Replace detail-zakazky with vysledek-zakazky in the search-context URL
          2. English clean URL: /en/verejne-zakazky/vysledek-zakazky/{dashed_id}
          3. Czech clean URL:   /verejne-zakazky/vysledek-zakazky/{dashed_id}
          4. Append /vysledek to current URL
        Returns winner name or "" on any failure.
        """
        base_url = result.url or ""
        if not base_url:
            return ""

        ref_id = result.reference_id or ""
        dashed_id = ref_id.replace("/", "-")

        candidates: list[str] = []

        # Pattern 1: replace detail-zakazky with vysledek-zakazky (preserves lang+query)
        if "detail-zakazky" in base_url:
            candidates.append(base_url.replace("detail-zakazky", "vysledek-zakazky"))

        if dashed_id:
            # Pattern 2: English clean URL (most reliable — no search-context noise)
            candidates.append(
                f"{BASE_URL}/en/verejne-zakazky/vysledek-zakazky/{dashed_id}"
            )
            # Pattern 3: Czech clean URL (fallback — Dodavatel appears in Czech text)
            candidates.append(
                f"{BASE_URL}/verejne-zakazky/vysledek-zakazky/{dashed_id}"
            )

        # Pattern 4: append /vysledek sub-path to current URL
        candidates.append(base_url.rstrip("/") + "/vysledek")

        _RESULT_KW = (
            "dodavatel", "vítěz", "winner", "vysledek", "výsledek",
            "contractor", "supplier", "selected tenderer",
        )

        for url in candidates:
            try:
                logger.info(f"CZ: trying result page: {url[:80]}")
                ok = self.browser.goto(url, wait_for="networkidle", timeout=15000)
                if not ok:
                    continue
                self.browser.wait_seconds(3)
                page_text = self.browser.get_page_text()
                if not any(kw in page_text.lower() for kw in _RESULT_KW):
                    logger.debug(f"CZ: result page has no winner keywords: {url[:60]}")
                    continue
                winner = self._find_winner(page_text)
                if winner:
                    return winner
                logger.debug(f"CZ: result page keyword hit but no name extracted: {url[:60]}")
            except Exception as exc:
                logger.debug(f"CZ: result page error ({url[:60]}): {exc}")

        return ""

    def _find_duration(self, text: str) -> str:
        for pat in [
            r"(?:Doba trvání|Délka smlouvy|Duration)[:\s]+([^\n]{3,80})",
            r"(\d+)\s*(?:měsíců|měsíce|měsíc|týdnů|let|dní)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:80]
        return ""

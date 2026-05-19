"""
Turkey Adapter — EKAP (Kamu İhale Kurumu / Public Procurement Authority)

Portal:   https://ekap.kik.gov.tr/EKAP/
Defence:  Milli Savunma Bakanlığı (MSB), Kara/Hava/Deniz Kuvvetleri,
          Jandarma Genel Komutanlığı, Savunma Sanayii Başkanlığı (SSB)
Language: Turkish
Currency: TRY (Turkish Lira)

BPW use-case: Turkish Armed Forces actively procure Trailers and HETs
(Heavy Equipment Transporters) for armoured vehicle transportation.
These tenders are published on EKAP alongside all other public procurement.

Search strategy (Playwright-primary):
  EKAP is an ASP.NET portal with ViewState — no clean public REST API confirmed.
  1. Navigate to EKAP search page with Playwright (handles ViewState/SSL).
  2. Fill keyword field, submit form.
  3. Intercept XHR response via capture_response() to auto-discover REST endpoint.
     If captured, cache URL and use direct REST calls for subsequent keywords.
  4. Fall back to HTML result-list parsing if XHR not captured.

  For each defence-matched result: load detail page, extract fields via regex.

Defence authority filter:
  Turkish military/defence organisation name patterns (Turkish, case-insensitive).

MSB Tedarik note (Sprint 14d):
  tedarik.msb.gov.tr is a separate MoD portal for direct defence orders outside
  EKAP. Requires registration — not covered here.
  Planned as TrMsbAdapter in a future sprint.

Known limitations (Sprint 14d):
  - EKAP HTML/XHR structure not confirmed from live testing; selectors may need
    tuning after first real run (screenshots saved to data/raw/screenshots/).
  - Corporate VPN may cause TLS issues; BrowserCore uses ignore_https_errors=True.
  - Classified/black defence procurement not published on any public portal.
"""

import json
import logging
import re
import time
from typing import Optional

from ..base_adapter import AdapterConfig, BaseAdapter, NoticeDetail, SearchResult
from ..core import BrowserCore
from ..resilience import RetrySession

logger = logging.getLogger(__name__)

EKAP_BASE = "https://ekap.kik.gov.tr"
EKAP_SEARCH_PAGE = f"{EKAP_BASE}/EKAP/Ortak/IhaleAra/index.html"
EKAP_DETAIL_TEMPLATE = (
    f"{EKAP_BASE}/EKAP/Ortak/IhaleDuyuruDetay/index.html?ihaleKayitNo={{notice_id}}"
)

# XHR URL fragments to listen for while the browser submits the search form.
# The first matching response is treated as the API response.
_XHR_PATTERNS = [
    "ihaleleriGetir",
    "ihaleListesi",
    "getIhaleList",
    "IhaleAra",
    "/api/ihale",
    "GetList",
    "getList",
]

TRAILER_CPV_PREFIXES = [
    "34223",  # Trailers and semi-trailers
    "34221",  # Special-purpose mobile containers
    "35400",  # Military vehicles and parts
    "35600",  # Military vehicles
    "34140",  # Heavy goods vehicles
]

DEFENCE_AUTHORITIES_TR = [
    "milli savunma bakanlığı",
    "msb",
    "kara kuvvetleri",
    "hava kuvvetleri",
    "deniz kuvvetleri",
    "silahlı kuvvetler",
    "savunma sanayii başkanlığı",
    "savunma sanayii",
    "jandarma genel komutanlığı",
    "jandarma",
    "sahil güvenlik",
    "kuvvet komutanlığı",
    "lojistik komutanlığı",
    "ikmal merkezi",
    "ordu komutanlığı",
    "genelkurmay",
    "harekât dairesi",
    "mekanik ikmal",
    "kara kuvvetleri lojistik",
]

TRAILER_KEYWORDS_TR = [
    "römork",
    "yarı römork",
    "treyler",
    "platform römork",
    "alçak yataklı",
    "tank taşıyıcı",
    "askeri taşıma",
    "çekici",
    "lowbed",
    "semitrailer",
    "platform araç",
    "ağır yük taşıma",
    "düşük tabanlı araç",
]


def create_tr_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Turkey",
        country_code="TR",
        source_code="TR-EKAP",
        base_url=EKAP_BASE,
        search_url=EKAP_SEARCH_PAGE,
        language="tr",
        trailer_keywords=TRAILER_KEYWORDS_TR,
        defence_authorities=DEFENCE_AUTHORITIES_TR,
        min_interval_seconds=2.5,
    )


class TrAdapter(BaseAdapter):
    """
    Turkey EKAP adapter — Kamu İhale Kurumu public procurement portal.

    Playwright-primary with XHR auto-discovery:
      1. Load EKAP search page (Playwright handles ASP.NET ViewState / SSL).
      2. Fill keyword, submit form, intercept XHR to discover REST endpoint.
      3. If XHR captured → parse JSON response, cache REST URL for future keywords.
      4. If no XHR → parse HTML result list from page text.
      5. For each result → load detail page, extract structured fields.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0)
        self._session.update_headers({
            "Accept": "application/json, text/html, */*",
            "Origin": EKAP_BASE,
            "Referer": EKAP_SEARCH_PAGE,
        })
        self._discovered_api_url: Optional[str] = None
        self._session_ready: bool = False

    # ── Search ──────────────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Single keyword search — called by search_all_keywords."""
        if self._discovered_api_url:
            results = self._rest_search(keyword, max_results)
            if results:
                return results
        return self._browser_search(keyword, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Search EKAP for Turkish defence trailer tenders.

        Iterates over configured trailer keywords (Turkish), deduplicates by
        reference_id / URL / title. filter_defence() applied separately by
        the pipeline (main.py) after this returns.
        """
        all_results: dict[str, SearchResult] = {}
        keywords = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords

        logger.info(f"TR: searching {len(keywords)} keywords on EKAP...")

        for keyword in keywords:
            results = self.search(keyword, max_results=max_results_per_keyword)
            for r in results:
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            logger.info(f"TR: '{keyword}' → {len(results)} results, "
                        f"total deduplicated: {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        results_list = list(all_results.values())
        logger.info(f"TR: search_all_keywords → {len(results_list)} total")
        return results_list

    # ── Browser search ───────────────────────────────────────────────────────

    def _browser_search(self, keyword: str, max_results: int) -> list:
        """
        Playwright-based EKAP search with XHR interception.

        On first call: loads EKAP search page, fills keyword field, submits.
        Tries each XHR pattern to capture the underlying JSON API response.
        Falls back to HTML result-list parsing if no XHR is captured.
        """
        try:
            if not self._session_ready:
                ok = self.browser.goto(
                    EKAP_SEARCH_PAGE,
                    wait_for="networkidle",
                    timeout=30000,
                )
                if not ok:
                    logger.warning("TR: EKAP page load failed — VPN / geo-block?")
                    return []
                self._session_ready = True
                time.sleep(2)

            # Try each XHR pattern; use the first that returns JSON
            for pattern in _XHR_PATTERNS:
                captured = self.browser.capture_response(
                    url_pattern=pattern,
                    trigger=lambda kw=keyword: self._fill_and_submit(kw),
                    timeout=8000,
                )
                if captured and isinstance(captured, dict) and "_text" not in captured:
                    logger.info(f"TR: XHR captured (pattern='{pattern}') "
                                f"for keyword '{keyword}'")
                    results = self._parse_api_response(captured)
                    return results[:max_results]

            # No useful XHR captured — parse rendered HTML
            time.sleep(3)
            page_text = self.browser.get_page_text()
            if not page_text or len(page_text) < 50:
                return []
            results = self._parse_html_results(page_text)
            logger.info(f"TR: HTML parse for '{keyword}' → {len(results)} results")
            return results[:max_results]

        except Exception as e:
            logger.error(f"TR: browser_search error for '{keyword}': {e}")
            return []

    def _fill_and_submit(self, keyword: str):
        """Fill EKAP keyword field and submit the search form."""
        search_selectors = [
            'input[name="ihaleAdi"]',
            '#txtIhaleAdi',
            '#ihaleAdi',
            'input[placeholder*="ara"]',
            'input[placeholder*="ihale"]',
            'input[type="text"]',
        ]
        filled = False
        for sel in search_selectors:
            if self.browser.fill(sel, keyword, timeout=2000):
                filled = True
                logger.debug(f"TR: filled '{keyword}' in {sel}")
                break

        if not filled:
            logger.warning(f"TR: no keyword input found for '{keyword}'")
            return

        self.browser.press_key("Return")
        time.sleep(0.5)
        for btn_sel in [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Ara")',
            '#btnAra',
            '.btn-search',
        ]:
            if self.browser.click(btn_sel, timeout=1500):
                break

    # ── REST fallback ────────────────────────────────────────────────────────

    def _rest_search(self, keyword: str, max_results: int) -> list:
        """Direct REST call to EKAP (only used after XHR endpoint is discovered)."""
        if not self._discovered_api_url:
            return []
        try:
            resp = self._session.post(
                self._discovered_api_url,
                json={"keyword": keyword, "pageSize": max_results, "pageIndex": 0},
                timeout=15,
            )
            if resp.status_code == 200:
                return self._parse_api_response(resp.json())[:max_results]
        except Exception as e:
            logger.debug(f"TR: REST search failed: {e}")
        return []

    # ── Response parsing ─────────────────────────────────────────────────────

    def _parse_api_response(self, data: object) -> list:
        """Parse EKAP JSON API response into SearchResult list."""
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("data", "ihaleler", "ihaleList", "items", "result", "list"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        return [r for item in items for r in [self._item_to_result(item)] if r]

    def _parse_html_results(self, page_text: str) -> list:
        """
        Parse EKAP result list from Playwright page text (innerText).

        EKAP results typically show:
          İhale Kayıt No   2026/XXXXXX
          Kurum Adı        Kara Kuvvetleri Komutanlığı
          İhale Adı        Platform Römork Alımı
          İhale Tarihi     15.03.2026
          Tahmini Bedel    4.500.000,00 TL
        """
        results: list[SearchResult] = []
        current: dict = {}

        date_re = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
        ref_re = re.compile(r"\b(\d{4}/\d{4,8})\b")
        value_re = re.compile(
            r"([\d]{1,3}(?:[.,][\d]{3})*(?:[.,]\d{2})?)\s*(?:TL|TRY)\b",
            re.IGNORECASE,
        )

        for raw_line in page_text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            ref_m = ref_re.search(line)
            if ref_m:
                if current.get("reference_id"):
                    r = self._dict_to_result(current)
                    if r:
                        results.append(r)
                current = {"reference_id": ref_m.group(1)}
                continue

            if not current:
                continue

            llow = line.lower()
            if any(kw in llow for kw in ("kurum", "idare", "makam")):
                val = line.split(":", 1)[-1].strip() if ":" in line else line
                if val and len(val) > 3:
                    current.setdefault("authority", val[:150])
            elif not current.get("title") and len(line) > 5:
                current["title"] = line[:200]

            dm = date_re.search(line)
            if dm and not current.get("date"):
                current["date"] = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"

            vm = value_re.search(line)
            if vm and not current.get("value"):
                raw_val = vm.group(1).replace(".", "").replace(",", ".")
                try:
                    v = float(raw_val)
                    if v > 100:
                        current["value"] = v
                except ValueError:
                    pass

        if current.get("reference_id"):
            r = self._dict_to_result(current)
            if r:
                results.append(r)

        return results

    def _item_to_result(self, item: dict) -> Optional[SearchResult]:
        """Convert EKAP API JSON dict to SearchResult."""
        ref_id = str(
            item.get("ihaleKayitNo") or item.get("kayitNo") or
            item.get("IhaleKayitNo") or item.get("id") or ""
        )
        title = str(
            item.get("ihaleAdi") or item.get("IhaleAdi") or
            item.get("adi") or item.get("title") or ""
        )
        authority = str(
            item.get("ihaleMakamAdi") or item.get("kurumAdi") or
            item.get("IdareAdi") or item.get("authority") or ""
        )
        date_raw = str(
            item.get("ihaleBaslangicTarihi") or item.get("ilanTarihi") or
            item.get("publicationDate") or item.get("tarih") or ""
        )
        value_raw = item.get("tahminiMaliyet") or item.get("bedel")

        if not (ref_id or title):
            return None

        value: Optional[float] = None
        if value_raw is not None:
            try:
                v = float(str(value_raw).replace(".", "").replace(",", "."))
                if v > 0:
                    value = v
            except (ValueError, TypeError):
                pass

        url = (
            EKAP_DETAIL_TEMPLATE.format(notice_id=ref_id)
            if ref_id else EKAP_SEARCH_PAGE
        )
        meta = json.dumps({"kayitNo": ref_id, "source": "ekap"}, ensure_ascii=False)

        return SearchResult(
            title=title[:200],
            url=url,
            authority=authority[:150],
            reference_id=ref_id,
            date=self._parse_tr_date(date_raw),
            value=value,
            currency="TRY",
            snippet=meta[:300],
        )

    def _dict_to_result(self, d: dict) -> Optional[SearchResult]:
        """Build SearchResult from internal HTML-parse dict."""
        ref_id = d.get("reference_id", "")
        title = d.get("title", "")
        if not (ref_id or title):
            return None
        url = (
            EKAP_DETAIL_TEMPLATE.format(notice_id=ref_id)
            if ref_id else EKAP_SEARCH_PAGE
        )
        return SearchResult(
            title=title,
            url=url,
            authority=d.get("authority", ""),
            reference_id=ref_id,
            date=d.get("date", ""),
            value=d.get("value"),
            currency="TRY",
        )

    # ── Detail ───────────────────────────────────────────────────────────────

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Load EKAP notice detail page and extract structured fields."""
        if not result.url or result.url == EKAP_SEARCH_PAGE:
            return self._detail_from_result(result)

        ok = self.browser.goto(result.url, wait_for="networkidle", timeout=30000)
        if not ok:
            logger.warning(f"TR: detail load failed for {result.reference_id!r}")
            return self._detail_from_result(result)

        safe_id = re.sub(r"[^a-zA-Z0-9]", "_", result.reference_id or "tr")[:30]
        self.browser._screenshot(f"tr_detail_{safe_id}")

        page_text = self.browser.get_page_text()
        if not page_text or len(page_text) < 30:
            return self._detail_from_result(result)

        description = self._find_field(page_text, [
            r"(?:İhale Konusu|Konu|Kısa Açıklama)[:\s]+(.{30,500}?)"
            r"(?=\n[A-Zİ-ş]|\Z)",
            r"(?:İşin Adı)[:\s]+(.{20,300}?)(?=\n|\Z)",
        ]) or ""

        authority = (
            self._find_field(page_text, [
                r"(?:Kurum Adı|İhale Makamı|İdare Adı)[:\s]+([^\n]{5,150})",
            ]) or result.authority
        )

        deadline = self._find_field(page_text, [
            r"(?:Son Teklif|Teklif Verme Son|Başvuru Son)[:\s]+"
            r"(\d{2}\.\d{2}\.\d{4}[^\n]{0,30})",
        ]) or ""

        duration = self._find_field(page_text, [
            r"(?:Sözleşme Süresi|İşin Süresi|Süre)[:\s]+([^\n]{3,60})",
        ]) or ""

        winner = self._find_field(page_text, [
            r"(?:Yüklenici|İhaleyi Kazanan|Sözleşme İmzalayan)[:\s]+([^\n]{5,120})",
        ]) or ""

        value = result.value
        val_str = self._find_field(page_text, [
            r"(?:Tahmini Bedel|Yaklaşık Maliyet|Sözleşme Bedeli)[:\s]+"
            r"([\d.,]+)\s*(?:TL|TRY)",
        ])
        if val_str:
            try:
                v = float(val_str.replace(".", "").replace(",", "."))
                if v > 0:
                    value = v
            except ValueError:
                pass

        quantity: Optional[int] = None
        qty_str = self._find_field(page_text, [
            r"(\d+)\s*(?:adet|set|takım|parça)\b",
        ])
        if qty_str:
            try:
                q = int(qty_str)
                if 1 <= q <= 10000:
                    quantity = q
            except ValueError:
                pass

        return NoticeDetail(
            title=result.title,
            description=description[:500],
            authority=authority[:150] if authority else "",
            date=result.date,
            value=value,
            currency="TRY",
            quantity=quantity,
            winner=winner[:120] if winner else "",
            deadline=deadline[:80] if deadline else "",
            duration=duration[:80] if duration else "",
            reference_id=result.reference_id,
            url=result.url,
            source_code="TR-EKAP",
            raw_text=page_text[:10000],
        )

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="TRY",
            reference_id=result.reference_id,
            url=result.url,
            source_code="TR-EKAP",
            raw_text=result.title or "",
        )

    # ── Filter ───────────────────────────────────────────────────────────────

    def filter_defence(self, results: list) -> list:
        return [r for r in results if self._is_defence(r)]

    def _is_defence(self, result: SearchResult) -> bool:
        combined = (
            f"{(result.authority or '').lower()} {(result.title or '').lower()}"
        )
        return any(p in combined for p in self.config.defence_authorities)

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_tr_date(raw: str) -> str:
        """Normalise Turkish date formats → YYYY-MM-DD."""
        if not raw:
            return ""
        m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
        if m:
            return m.group(1)
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})T", raw)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return ""

    @staticmethod
    def _find_field(text: str, patterns: list) -> str:
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:300]
        return ""

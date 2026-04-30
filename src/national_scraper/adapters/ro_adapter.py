"""
Romania Adapter — SEAP/e-licitatie.ro (Sistemul Electronic de Achiziții Publice)

Portal: https://www.e-licitatie.ro  (AngularJS 1.4.4 SPA)
Defence: Ministerul Apărării Naționale (MApN), Unități Militare (UM XXXXX)
Language: Romanian

Discovered API (via AngularJS $location routing + response interception):
  POST-like: /api-pub/NoticeCommon/GetCNoticeList/
  Returns: {"total": N, "items": [...], "searchTooLong": false}
  Triggered when AngularJS router activates /pub/notices/contract-notices/list/1/1

Strategy:
  1. Load e-licitatie.ro with Playwright (Chromium bypasses VPN SSL issues)
  2. Navigate using AngularJS $location.path() to activate the notice list route
  3. Wait for GetCNoticeList API call and capture it via capture_response()
  4. Filter results for defence authorities + trailer CPVs
  5. For each relevant hit: load the detail page and extract text

VPN note: Direct Python requests to e-licitatie.ro time out from corporate VPN.
  Playwright (Chromium) works because it uses browser SSL/cert handling.
  If neither works, adapter returns empty list (fail-safe).

Item structure from GetCNoticeList:
  cNoticeId, noticeId, noticeNo (CN/SCN format), contractTitle,
  contractingAuthorityNameAndFN (includes fiscal code),
  cpvCodeAndName, estimatedValueRon, tenderReceiptDeadlineExport,
  sysNoticeState {"text": "Publicat/Atribuita"}, sysNoticeTypeId
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
# Route that triggers the GetCNoticeList API call
NOTICES_ROUTE = "/pub/notices/contract-notices/list/1/1"
DETAIL_URL = "https://www.e-licitatie.ro/pub/notices/ca-notices/notice-details/{notice_id}"

TRAILER_CPV_PREFIXES = ["34223", "34221", "35600", "35610", "35400"]

DEFENCE_AUTHORITIES_RO = [
    "ministerul apărării",
    "ministerul apararii",
    "mapn",
    "unitate militară",
    "unitate militara",
    "um 0",
    "brigada",
    "batalionul",
    "forțe terestre",
    "forte terestre",
    "romarm",
    "arsenalul armatei",
    "centrul militar",
    "statul major",
]

TRAILER_KEYWORDS_RO = [
    "remorcă", "remorci", "remorca",
    "semiremorcă", "semiremorca",
    "platformă", "platforma",
    "cisternă", "cisterna",
    "bucătărie de campanie", "bucatarie de campanie",
    "container militar",
    "transport militar",
    "hakenarm", "trailer", "semitrailer",
]


def create_ro_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Romania",
        country_code="RO",
        source_code="RO-SEAP",
        base_url=BASE_URL,
        search_url=BASE_URL + NOTICES_ROUTE,
        language="ro",
        trailer_keywords=TRAILER_KEYWORDS_RO,
        defence_authorities=DEFENCE_AUTHORITIES_RO,
        min_interval_seconds=3.0,
    )


class ROAdapter(BaseAdapter):
    """
    Romania adapter — SEAP e-licitatie.ro via Playwright + AngularJS API.

    Uses the AngularJS 1.4 app's $location service to navigate to the
    contract notice list, which triggers the /api-pub/NoticeCommon/GetCNoticeList/
    API call. Results are filtered for defence authorities and trailer CPVs.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session_ready = False

    # ── Search ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Single keyword search — delegates to search_all_keywords."""
        return []

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """
        Search SEAP for Romanian defence trailer notices.

        Note: SEAP GetCNoticeList does NOT support server-side filtering
        (all filter params are ignored, returns most-recent notices).
        Strategy: scan recent notices and filter locally for defence authorities
        with trailer keywords/CPVs.

        Scan depth: 200 in test mode, 2000 in full mode.
        """
        all_results: dict[str, SearchResult] = {}

        # Load SEAP and activate AngularJS
        if not self._init_seap_session():
            logger.warning("RO: SEAP session init failed — VPN may be blocking")
            return []

        max_scan = 200 if test_mode else 2000
        page_size = 50
        logger.info(f"RO: scanning {max_scan} recent notices (local filter)...")

        scanned = 0
        page_idx = 1
        while scanned < max_scan:
            items = self._get_page(page_idx, page_size)
            if not items:
                break
            for item in items:
                r = self._item_to_result(item)
                if r and self._is_defence(r):
                    # Additional trailer CPV/keyword filter
                    cpv = (item.get("cpvCodeAndName") or "")
                    title_lower = (r.title or "").lower()
                    auth_lower = (r.authority or "").lower()
                    is_trailer_cpv = any(cpv.startswith(p) for p in TRAILER_CPV_PREFIXES)
                    is_trailer_kw = any(kw in title_lower or kw in auth_lower
                                        for kw in self.config.trailer_keywords)
                    if is_trailer_cpv or is_trailer_kw:
                        key = r.reference_id or r.url
                        if key and key not in all_results:
                            all_results[key] = r
            scanned += len(items)
            if len(items) < page_size:
                break
            page_idx += 1
            if page_idx % 5 == 0:
                logger.info(f"RO: scanned {scanned}, defence+trailer found: {len(all_results)}")
            time.sleep(0.3)

        results = list(all_results.values())
        logger.info(f"RO: search_all_keywords → {len(results)} defence+trailer notices "
                    f"(scanned {scanned})")
        return results

    def _get_page(self, page_idx: int, page_size: int) -> list:
        """Fetch one page of notices from GetCNoticeList."""
        try:
            result = self.browser.page.evaluate("""
                (args) => new Promise((resolve) => {
                    var [pageIdx, pageSize] = args;
                    var injector = angular.element(document.body).injector();
                    var $http = injector.get('$http');
                    $http.post('/api-pub/NoticeCommon/GetCNoticeList/', {
                        pageIndex: pageIdx, pageSize: pageSize, noticeTypeId: 1
                    }).then(
                        r => resolve(r.data.items || []),
                        e => resolve([])
                    );
                })
            """, [page_idx, page_size])
            return result or []
        except Exception as e:
            logger.error(f"RO: _get_page error: {e}")
            return []

    def _init_seap_session(self) -> bool:
        """Load SEAP and verify AngularJS is available."""
        if self._session_ready:
            return True
        try:
            # Use domcontentloaded (not networkidle — e-licitatie.ro never reaches networkidle)
            ok = self.browser.goto(
                "https://www.e-licitatie.ro/pub/#/ca-notices",
                wait_for="domcontentloaded", timeout=30000
            )
            if not ok:
                logger.warning("RO: SEAP page load failed")
                return False

            # Wait for AngularJS to bootstrap (the app needs a few seconds)
            time.sleep(5)

            # Check AngularJS is running
            try:
                ng_check = self.browser.page.evaluate("""
                    () => ({
                        exists: typeof window.angular !== 'undefined',
                        version: window.angular ? (window.angular.version && window.angular.version.full) : null,
                        injector: typeof window.angular !== 'undefined' ?
                            !!angular.element(document.body).injector() : false,
                    })
                """)
            except Exception as e:
                logger.warning(f"RO: AngularJS eval error: {e}")
                return False

            if not ng_check.get("injector"):
                logger.warning(f"RO: AngularJS not ready: {ng_check} "
                               f"(VPN may block CDN resources)")
                return False

            logger.info(f"RO: AngularJS {ng_check.get('version','?')} initialized")

            # Navigate to notice list route using $location
            self.browser.page.evaluate("""
                () => {
                    var injector = angular.element(document.body).injector();
                    var $location = injector.get('$location');
                    var $rootScope = injector.get('$rootScope');
                    $location.path('/pub/notices/contract-notices/list/1/1');
                    $rootScope.$apply();
                }
            """)
            time.sleep(3)
            self._session_ready = True
            logger.info("RO: SEAP session initialized successfully")
            return True
        except Exception as e:
            logger.error(f"RO: SEAP init error: {e}")
            return False

    def _item_to_result(self, item: dict) -> Optional[SearchResult]:
        """Convert SEAP GetCNoticeList item to SearchResult."""
        notice_id = str(item.get("cNoticeId") or item.get("noticeId") or "")
        ref_id = str(item.get("noticeNo") or notice_id)
        title = item.get("contractTitle") or ""
        authority = item.get("contractingAuthorityNameAndFN") or ""
        # Strip fiscal code (format "RO XXXXXXX - Name")
        if " - " in authority:
            authority = authority.split(" - ", 1)[-1].strip()
        date_str = (item.get("noticeStateDate") or
                    item.get("tenderReceiptDeadlineExport") or "")[:10]
        cpv = str(item.get("cpvCodeAndName") or "")[:20]

        value = None
        try:
            v = item.get("estimatedValueRon")
            if v and float(v) > 0:
                value = float(v)
        except (ValueError, TypeError):
            pass

        url = DETAIL_URL.format(notice_id=notice_id) if notice_id else BASE_URL
        meta = json.dumps({"noticeId": notice_id, "cpv": cpv}, ensure_ascii=False)

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
        return any(p in combined for p in self.config.defence_authorities)

    # ── Detail ──

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Load detail page and extract text."""
        if not result.url or result.url == BASE_URL:
            return self._detail_from_result(result)

        ok = self.browser.goto(result.url, wait_for="networkidle", timeout=30000)
        if not ok:
            return self._detail_from_result(result)

        safe = re.sub(r"[^a-zA-Z0-9]", "_", result.reference_id or "ro")
        self.browser._screenshot(f"ro_detail_{safe}")

        page_text = self.browser.get_page_text()
        if not page_text or len(page_text) < 50:
            return self._detail_from_result(result)

        description = (self._find_field(page_text, [
            r"(?:Descrierea|Obiectul|Description)[:\s]+(.{30,500}?)(?=\n[A-Z]|$)",
        ]) or "")[:500]

        value = None
        val_str = self._find_field(page_text, [
            r"(?:Valoarea|Valeur|Value)[:\s]+([\d\s,.]+)\s*(?:RON|€|EUR)",
        ])
        if val_str:
            try:
                v = float(val_str.replace(" ", "").replace(",", "."))
                if v > 0:
                    value = v
            except ValueError:
                pass

        winner = self._find_field(page_text, [
            r"(?:Câștigător|Adjudicataire|Winner)[:\s]+([^\n]{5,120})",
        ]) or ""

        return NoticeDetail(
            title=result.title,
            description=description,
            authority=result.authority,
            date=result.date,
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

    @staticmethod
    def _find_field(text: str, patterns: list) -> str:
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:300]
        return ""

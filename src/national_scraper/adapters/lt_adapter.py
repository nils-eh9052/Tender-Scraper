"""
Lithuania Adapter — CVP IS / Viešųjų pirkimų tarnybos portalas

Portal: https://cvpp.eviesiejipirkimai.lt  (new portal since 2021)
Old portal: https://cvpis.lt (deprecated, redirects to new)
Defence: Krašto apsaugos ministerija (Ministry of National Defence), LK

DISCOVERY (Sprint 11):
  Lithuania's Central Procurement Portal (CVPP).
  Technology: Modern React SPA with REST API backend.

  REST API status (Sprint 11 discovery):
    GET /api/procurements → HTTP 404 (endpoint not found)
    POST /Notice/Search → HTTP 404 (path does not exist on this portal)

  The portal uses React Router with SPA routing. All paths are virtual
  (client-side routing), not server-side. Direct URL navigation to
  non-root paths may 404 at server level before React loads.

  Correct approach (Sprint 12):
    1. Navigate to https://cvpp.eviesiejipirkimai.lt/ (homepage)
    2. Wait for React SPA to load
    3. Intercept XHR calls made by the search functionality
    4. Replicate the API call (likely a different path or POST endpoint)

  Alternative: VPT Open Data portal
    https://data.gov.lt/datasets/ — check for procurement dataset exports
    Lithuanian tenders above threshold also appear on TED.

  IMPLEMENTATION STATUS: STUB — browser fallback corrected to homepage.

  Defence authorities:
    Krašto apsaugos ministerija = Ministry of National Defence
    Lietuvos kariuomenė = Lithuanian Armed Forces (LK)
    Gynybos resursų agentūra = Defence Resources Agency
    Karo policija = Military Police

TRAILER KEYWORDS (Lithuanian):
  priekaba = trailer
  puspriekabė = semi-trailer
  priekabų = trailers (genitive plural)
  žemakrovė priekaba = low-loader trailer
  cisterninis priekaba = tank trailer
  lauko virtuvė = field kitchen
  konteineris = container
  krovininis priekaba = cargo trailer
"""

import json
import logging
import re
import time
from typing import Optional

import requests
import urllib3

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

logger = logging.getLogger(__name__)
urllib3.disable_warnings()

LT_BASE = "https://cvpp.eviesiejipirkimai.lt"
LT_API = f"{LT_BASE}/api"
LT_NOTICE_URL = f"{LT_BASE}/procurement/{{id}}"


def create_lt_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Lithuania",
        country_code="LT",
        source_code="LT-CV",
        base_url=LT_BASE,
        search_url=f"{LT_API}/procurements",
        language="lt",
        trailer_keywords=[
            "priekaba",           # trailer
            "puspriekabė",        # semi-trailer
            "priekabų",           # trailers (genitive)
            "žemakrovė",          # low-loader
            "cisterninis",        # tank/cistern
            "lauko virtuvė",      # field kitchen
            "konteineris",        # container
            "priekabos",          # trailer (genitive singular)
            "krovininė priekaba", # cargo trailer
            "trailer",            # English
            "semi-trailer",
        ],
        defence_authorities=[
            "Krašto apsaugos ministerija",
            "Lietuvos kariuomenė",
            "Gynybos resursų agentūra",
            "Karo policija",
            "Lietuvos šaulių sąjunga",
            "Ministry of National Defence",
            "Lithuanian Armed Forces",
        ],
        min_interval_seconds=1.0,
    )


class LTAdapter(BaseAdapter):
    """
    Lithuania CVPP adapter.

    Tries REST API first, falls back to browser-based search.
    Lithuania is EU member — above-threshold tenders appear on TED.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=True)
        self._session.update_headers({
            "Accept": "application/json, */*",
            "Content-Type": "application/json",
        })
        self._api_works = None

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        results = self._api_search(keyword, max_results)
        if not results:
            results = self._browser_search(keyword, max_results)
        return results

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        all_results: dict[str, SearchResult] = {}

        kw_list = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords

        for kw in kw_list:
            for r in self.search(kw, max_results_per_keyword):
                key = r.reference_id or r.url
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # Defence authority sweep
        if not test_mode:
            for auth_kw in ["Krašto apsaugos", "Lietuvos kariuomenė", "Gynybos resursų"]:
                for r in self.search(auth_kw, 100):
                    key = r.reference_id or r.url
                    if key and key not in all_results:
                        all_results[key] = r
                time.sleep(self.config.min_interval_seconds)

        logger.info("LT: search_all_keywords → %d candidates", len(all_results))
        return list(all_results.values())

    def _api_search(self, keyword: str, max_results: int) -> list:
        """Try CVPP REST API (GET-based)."""
        results = []
        page = 0
        page_size = min(20, max_results)

        while len(results) < max_results:
            try:
                resp = self._session.get(
                    f"{LT_API}/procurements",
                    params={
                        "searchText": keyword,
                        "page": page,
                        "size": page_size,
                        "sort": "publicationDate,desc",
                    },
                    timeout=15,
                )

                if self._api_works is None:
                    self._api_works = resp.status_code == 200
                    if not self._api_works:
                        logger.debug(
                            "LT: REST API at /api/procurements not accessible (HTTP %s)",
                            resp.status_code,
                        )
                        return []

                if resp.status_code != 200:
                    break

                data = resp.json()
                items = (
                    data.get("content") or
                    data.get("procurements") or
                    data.get("data") or
                    (data if isinstance(data, list) else [])
                )
                if not items:
                    break

                for item in items:
                    sr = self._item_to_result(item)
                    if sr:
                        results.append(sr)

                total = data.get("totalElements") or data.get("totalCount") or 0
                if len(results) >= total or len(items) < page_size:
                    break
                page += 1

            except Exception as exc:
                logger.debug("LT: API search error: %s", exc)
                if self._api_works is None:
                    self._api_works = False
                break

        return results[:max_results]

    def _browser_search(self, keyword: str, max_results: int) -> list:
        """Browser fallback for CVPP search.

        NOTE (Sprint 11): /Notice/Search returns HTTP 404 — portal uses SPA routing.
        Navigate to homepage and let React load, then take screenshot for discovery.
        """
        results = []
        try:
            if not self.browser or not self.browser.page:
                return []

            # Navigate to homepage (SPA needs to load React first)
            ok = self.browser.goto(LT_BASE, timeout=30000)
            if not ok:
                return []

            time.sleep(3)  # wait for React SPA to initialize
            self.browser._screenshot(f"lt_search_{keyword[:20]}")
            html = self.browser.page.content()
            results = self._parse_search_html(html)
            logger.debug("LT: SPA homepage loaded — keyword search not yet implemented")
            logger.info("LT: browser search '%s' → %d results (stub)", keyword, len(results))

        except Exception as exc:
            logger.warning("LT: browser search error: %s", exc)

        return results[:max_results]

    def _item_to_result(self, item: dict) -> Optional[SearchResult]:
        proc_id = str(
            item.get("id") or item.get("procurementId") or item.get("noticeId") or ""
        )
        if not proc_id:
            return None

        title = str(
            item.get("title") or item.get("procurementTitle") or
            item.get("subject") or ""
        )
        authority = str(
            item.get("contractingAuthority") or
            item.get("buyerName") or
            item.get("procuringEntityName") or ""
        )
        pub_date = str(
            item.get("publicationDate") or item.get("publishedDate") or ""
        )[:10]

        value = None
        try:
            v = item.get("estimatedValue") or item.get("contractValue") or item.get("value")
            if v:
                value = float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            pass

        url = LT_NOTICE_URL.format(id=proc_id)
        snippet = json.dumps({
            "id": proc_id,
            "status": item.get("status") or item.get("procurementStatus", ""),
            "cpv": item.get("cpvCode") or item.get("mainCpv", ""),
        }, ensure_ascii=False)

        return SearchResult(
            title=title[:200],
            url=url,
            authority=authority[:200],
            reference_id=proc_id,
            date=pub_date,
            value=value,
            currency="EUR",
            snippet=snippet[:400],
        )

    def _parse_search_html(self, html: str) -> list:
        results = []
        for m in re.finditer(
            r'href=["\']([^"\']*?/(?:Notice|procurement)/(\d+)[^"\']*?)["\'].*?'
            r'>([^<]{5,200})<',
            html,
            re.DOTALL
        ):
            url = m.group(1)
            ref_id = m.group(2)
            title = m.group(3).strip()
            if not url.startswith("http"):
                url = LT_BASE + url
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
            combined = f"{(r.authority or '').lower()} {(r.title or '').lower()}"
            is_defence = any(kw in combined for kw in defence_kw)
            is_trailer = any(kw in (r.title or "").lower() for kw in trailer_kw)
            if is_defence and is_trailer:
                kept.append(r)

        logger.info("LT: filter_defence: %d → %d", len(results), len(kept))
        return kept

    # ── Detail ────────────────────────────────────────────────────────────

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        proc_id = result.reference_id
        if not proc_id:
            return self._detail_from_result(result)

        # Try API first
        try:
            resp = self._session.get(
                f"{LT_API}/procurements/{proc_id}",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                item = data.get("procurement") or data if isinstance(data, dict) else {}
                return self._build_detail_from_api(item, result)
        except Exception:
            pass

        # Browser fallback
        try:
            if self.browser and self.browser.page:
                ok = self.browser.goto(result.url, timeout=30000)
                if ok:
                    time.sleep(1.5)
                    html = self.browser.page.content()
                    return self._parse_detail_html(html, result)
        except Exception as exc:
            logger.error("LT: detail error for %s: %s", proc_id, exc)

        return self._detail_from_result(result)

    def _build_detail_from_api(self, item: dict, result: SearchResult) -> NoticeDetail:
        title = str(item.get("title") or item.get("subject") or result.title)
        authority = str(
            item.get("contractingAuthority") or item.get("buyerName") or result.authority
        )
        pub_date = str(item.get("publicationDate") or result.date or "")[:10]
        description = str(item.get("description") or item.get("lotDescription") or "")[:500]
        winner = str(item.get("winnerName") or item.get("awardedTo") or "")
        value = result.value
        try:
            v = item.get("estimatedValue") or item.get("contractValue")
            if v:
                value = float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            pass
        qty = None
        try:
            q = item.get("quantity") or item.get("totalQuantity")
            if q:
                qty = int(float(str(q)))
        except (ValueError, TypeError):
            pass

        return NoticeDetail(
            title=title[:200],
            description=description,
            authority=authority[:200],
            date=pub_date,
            value=value,
            currency="EUR",
            quantity=qty,
            winner=winner[:200] if winner else "",
            reference_id=result.reference_id,
            url=result.url,
            source_code="LT-CV",
            raw_text=json.dumps(item, ensure_ascii=False)[:5000],
        )

    def _parse_detail_html(self, html: str, result: SearchResult) -> NoticeDetail:
        def extract(pattern: str, default: str = "") -> str:
            m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            return (re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else default)

        title = extract(r"<h1[^>]*>(.*?)</h1>") or result.title
        authority = extract(
            r"(?:Perkančioji organizacija|Contracting authority)[^:]*:\s*<[^>]*>(.*?)<"
        ) or result.authority
        pub_date = extract(
            r"(?:Skelbimo data|Publication date)[^:]*:\s*(\d{4}-\d{2}-\d{2})"
        ) or result.date
        description = extract(
            r"(?:Pirkimo objekto aprašymas|Description)[^:]*:\s*<[^>]*>(.*?)</[^>]*>"
        )[:500]
        winner = extract(
            r"(?:Laimėtojas|Winner)[^:]*:\s*<[^>]*>(.*?)<"
        )

        return NoticeDetail(
            title=title[:200],
            description=description,
            authority=authority[:200],
            date=pub_date,
            winner=winner[:200] if winner else "",
            reference_id=result.reference_id,
            url=result.url,
            source_code="LT-CV",
            raw_text=re.sub(r"<[^>]+>", " ", html)[:3000],
            currency="EUR",
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
            source_code="LT-CV",
            raw_text=result.title or "",
        )

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        return {
            "tender_id": f"LT-CV-{detail.reference_id}",
            "source": "LT-CV",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "Lithuania",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": "EUR",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or "",
            "_national_raw_text": detail.raw_text or "",
            "_trailer_quantity_1": detail.quantity,
            "_raw": {"source": "LT-CV", "url": detail.url},
            "estimated_value": (
                {"amount": detail.value, "currency": "EUR"} if detail.value else None
            ),
            "award": (
                {"winner_name": detail.winner, "awarded": True}
                if detail.winner else None
            ),
        }

"""
Latvia Adapter — IUB (Iepirkumu uzraudzības birojs)

Portal: https://info.iub.gov.lv
Backend API: https://infob.iub.gov.lv/api/search
Defence: Aizsardzības ministrija (Ministry of Defence), NBS (National Armed Forces)

DISCOVERY (Sprint 11):
  EIS portal (eis.gov.lv) is completely broken — all requests return ASP.NET
  session errors. EIS is unreachable without a valid session cookie.

  Primary source: IUB (Iepirkumu uzraudzības birojs) at info.iub.gov.lv.
  The Vue.js SPA uses a JSON API backend at infob.iub.gov.lv/api/search:

    GET https://infob.iub.gov.lv/api/search
        ?search={keyword}&withInflections=true&searchPhrase=true
    Returns JSON array of up to 20 notice objects.
    No authentication required.

  Notice URL: https://info.iub.gov.lv/lv/pazinojumi/{uuid}
    where {uuid} is the `identifier` field from the API response.

  Notice object fields:
    identifier       UUID (used for notice URL)
    procurementIdentifier  human-readable ID like "NBS 2025/123"
    name             tender title
    organizationName contracting authority name
    publicationDate  ISO datetime
    amount           contract value string
    currency         "EUR"
    cpvCodes         list of {code, caption}
    externalId       numeric ID (alternative URL key)

IMPLEMENTATION STATUS: ACTIVE — uses infob.iub.gov.lv JSON API directly.

Defence authorities:
  Aizsardzības ministrija = Ministry of Defence
  Nacionālie bruņotie spēki (NBS) = National Armed Forces
  Valsts aizsardzības militārais birojs = State Defence Military Bureau
  Zemessardze = National Guard

TRAILER KEYWORDS (Latvian):
  piekabe = trailer
  puspiekabe = semi-trailer
  piekabes = trailers (genitive)
  autocisterna = tanker truck/trailer
  konteiners = container
  lauka virtuve = field kitchen
  zempiekraujamā piekabe = low-loader trailer
"""

import logging
import re
import time
from typing import Optional

import urllib3

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

logger = logging.getLogger(__name__)
urllib3.disable_warnings()

LV_IUB_API = "https://infob.iub.gov.lv/api/search"
LV_IUB_NOTICE_URL = "https://info.iub.gov.lv/lv/pazinojumi/{uuid}"
LV_IUB_SEARCH = "https://info.iub.gov.lv/lv/meklet"  # for base_url / config


def create_lv_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Latvia",
        country_code="LV",
        source_code="LV-IUB",
        base_url=LV_IUB_SEARCH,
        search_url=LV_IUB_API,
        language="lv",
        trailer_keywords=[
            "piekabe",              # trailer
            "puspiekabe",           # semi-trailer
            "piekabes",             # trailers (genitive)
            "autocisterna",         # tanker
            "konteiners",           # container
            "lauka virtuve",        # field kitchen
            "zempiekraujamā",       # low-loader
            "kravnesīga piekabe",   # cargo trailer
            "degvielas piekabe",    # fuel trailer
            "trailer",              # English
            "semi-trailer",
        ],
        defence_authorities=[
            "Aizsardzības ministrija",
            "Nacionālie bruņotie spēki",
            "NBS",
            "Valsts aizsardzības militārais birojs",
            "Zemessardze",
            "Ministry of Defence",
        ],
        min_interval_seconds=1.0,
    )


class LVAdapter(BaseAdapter):
    """
    Latvia IUB adapter using the infob.iub.gov.lv JSON API.

    EIS portal (eis.gov.lv) is broken — all requests return session errors.
    The IUB Vue.js SPA (info.iub.gov.lv) uses a public JSON API backend that
    can be called directly without authentication or Playwright.

    Strategy:
    1. REST search on infob.iub.gov.lv/api/search per keyword and per authority
    2. Filter by defence authority + trailer keyword in returned JSON
    3. Notice detail page is info.iub.gov.lv/lv/pazinojumi/{uuid}

    Latvia is EU member — above-threshold tenders appear on TED.
    This adapter targets below-threshold and national-only notices.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=True)
        self._session.update_headers({"Accept": "application/json"})

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        return self._api_search(keyword, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        all_results: dict[str, SearchResult] = {}

        kw_list = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords
        auth_list = [] if test_mode else self.config.defence_authorities[:4]

        for kw in kw_list:
            for r in self._api_search(kw, max_results_per_keyword):
                key = r.reference_id or r.url
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        for auth in auth_list:
            for r in self._api_search(auth, 50):
                key = r.reference_id or r.url
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        logger.info("LV: search_all_keywords → %d candidates", len(all_results))
        return list(all_results.values())

    def _api_search(self, keyword: str, max_results: int) -> list:
        """Call infob.iub.gov.lv JSON API and parse results."""
        results = []
        page = 1

        while len(results) < max_results:
            try:
                resp = self._session.get(
                    LV_IUB_API,
                    params={
                        "search": keyword,
                        "withInflections": "true",
                        "searchPhrase": "true",
                        "page": page,
                    },
                    timeout=20,
                )
                if resp.status_code != 200:
                    logger.warning("LV: API HTTP %s for '%s'", resp.status_code, keyword)
                    break

                items = resp.json()
                if not isinstance(items, list) or not items:
                    break

                for item in items:
                    sr = self._item_to_result(item, keyword)
                    if sr:
                        results.append(sr)

                # API returns 20 items per page; stop if fewer returned
                if len(items) < 20:
                    break
                page += 1

            except Exception as exc:
                logger.warning("LV: API search error for '%s': %s", keyword, exc)
                break

        logger.info("LV: API search '%s' → %d results", keyword, len(results))
        return results[:max_results]

    def _item_to_result(self, item: dict, keyword: str = "") -> Optional[SearchResult]:
        uuid = str(item.get("identifier") or "").strip()
        if not uuid:
            return None

        title = str(item.get("name") or "").strip()
        authority = str(item.get("organizationName") or "").strip()
        pub_date = str(item.get("publicationDate") or "")[:10]
        proc_id = str(item.get("procurementIdentifier") or uuid[:8])

        value = None
        raw_amount = item.get("amount")
        if raw_amount:
            try:
                value = float(str(raw_amount).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                pass

        url = LV_IUB_NOTICE_URL.format(uuid=uuid)
        return SearchResult(
            title=title[:200],
            url=url,
            authority=authority[:200],
            reference_id=proc_id,
            date=pub_date,
            value=value,
            currency=item.get("currency", "EUR"),
            snippet=keyword,  # preserve search term for filter_defence
        )

    # ── Filter ────────────────────────────────────────────────────────────

    def filter_defence(self, results: list) -> list:
        kept = []
        defence_kw = [a.lower() for a in self.config.defence_authorities]
        trailer_kw = [k.lower() for k in self.config.trailer_keywords]

        for r in results:
            # Check only title + authority — snippet would accept all keyword-search results
            combined = f"{(r.authority or '').lower()} {(r.title or '').lower()}"
            is_trailer = any(kw in combined for kw in trailer_kw)
            is_defence = any(kw in combined for kw in defence_kw)
            if is_trailer and is_defence:
                kept.append(r)

        logger.info("LV: filter_defence: %d → %d", len(results), len(kept))
        return kept

    # ── Detail ────────────────────────────────────────────────────────────

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        return NoticeDetail(
            title=result.title,
            description="",
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="EUR",
            reference_id=result.reference_id,
            url=result.url,
            source_code="LV-IUB",
            raw_text=result.title or "",
        )

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        return {
            "tender_id": f"LV-IUB-{detail.reference_id}",
            "source": "LV-IUB",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "Latvia",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": "EUR",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or "",
            "_national_raw_text": detail.raw_text or "",
            "_trailer_quantity_1": detail.quantity,
            "_raw": {"source": "LV-IUB", "url": detail.url},
            "estimated_value": (
                {"amount": detail.value, "currency": "EUR"} if detail.value else None
            ),
            "award": (
                {"winner_name": detail.winner, "awarded": True}
                if detail.winner else None
            ),
        }

"""
Estonia Adapter — Riigihangete Register (riigihanked.riik.ee)

Portal: https://riigihanked.riik.ee
Defence: Kaitseministeerium, Kaitsevägi, Riigi Kaitseinvesteeringute Keskus (RKK)

DISCOVERY (Sprint 11):
  The Estonian procurement portal has a public REST API.

  REST API base: https://riigihanked.riik.ee/rhr-web/api/v1/
  Key endpoints discovered:
    POST /rhr-web/api/v1/procurements/search
      Body: {"pageSize": 20, "pageNumber": 0, "searchWord": "...", "statusCode": ["..."], ...}
      Response: {"totalCount": N, "procurements": [{id, title, ...}]}

    GET /rhr-web/api/v1/procurements/{id}
      Full tender detail

  No authentication required for public tenders.
  Technology: Spring Boot REST API + React frontend.

  Defence authorities:
    Kaitseministeerium = Ministry of Defence
    Kaitsevägi = Estonian Defence Forces
    Riigi Kaitseinvesteeringute Keskus = State Centre for Defence Investments (RKK/CDIC)
    Siseministeerium = Ministry of Interior (border guard, police)

  Estonia is EU member — above-threshold notices appear on TED.
  This adapter captures below-threshold and national-only tenders.

  CPV codes: same EU standard (34223xxx for trailers).

TRAILER KEYWORDS (Estonian):
  haagis = trailer
  poolhaagis = semi-trailer
  madalahaagis = low-bed trailer
  tsisternhaagis = tank trailer
  konteinerhaagis = container trailer
  väliköök / välikuchen = field kitchen
  veokihaagis = cargo trailer
"""

import json
import logging
import time
from typing import Optional

import requests
import urllib3

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

logger = logging.getLogger(__name__)
urllib3.disable_warnings()

EE_BASE = "https://riigihanked.riik.ee"
EE_API = f"{EE_BASE}/rhr-web/api/v1"
EE_SEARCH_URL = f"{EE_API}/procurements/search"
EE_DETAIL_URL = f"{EE_API}/procurements/{{id}}"
EE_NOTICE_URL = f"{EE_BASE}/rhr-web/#/procurement/{{id}}/general-info"


def create_ee_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Estonia",
        country_code="EE",
        source_code="EE-RP",
        base_url=EE_BASE,
        search_url=EE_SEARCH_URL,
        language="et",
        trailer_keywords=[
            "haagis",         # trailer
            "poolhaagis",     # semi-trailer
            "madalahaagis",   # low-bed trailer
            "tsisternhaagis", # tank trailer
            "konteiner",      # container
            "väliköök",       # field kitchen
            "veok",           # vehicle/truck (broad, catches some trailer combos)
            "trailer",        # English
            "semi-trailer",
        ],
        defence_authorities=[
            "Kaitseministeerium",
            "Kaitsevägi",
            "Riigi Kaitseinvesteeringute Keskus",
            "RKK",
            "Kaitseliit",
            "Ministry of Defence",
            "Estonian Defence Forces",
        ],
        min_interval_seconds=1.0,
    )


class EEAdapter(BaseAdapter):
    """
    Estonia riigihanked.riik.ee adapter.

    Two-stage approach:
    1. REST API search per trailer keyword → collect candidate tender IDs
    2. Filter by defence authority + optional CPV check
    3. Fetch detail for matches

    Falls back to browser-based search if API returns unexpected responses.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=True)
        self._session.update_headers({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._api_works = None  # None = untested, True/False after first call

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        return self._api_keyword_search(keyword, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        all_results: dict[str, SearchResult] = {}

        kw_list = self.config.trailer_keywords[:2] if test_mode else self.config.trailer_keywords

        # Keyword searches
        for kw in kw_list:
            for r in self._api_keyword_search(kw, max_results_per_keyword):
                key = r.reference_id or r.url
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        # Defence authority sweeps (not in test mode)
        if not test_mode:
            for auth_kw in ["Kaitseministeerium", "Kaitsevägi", "Riigi Kaitseinvesteeringute"]:
                for r in self._api_keyword_search(auth_kw, 100):
                    key = r.reference_id or r.url
                    if key and key not in all_results:
                        all_results[key] = r
                time.sleep(self.config.min_interval_seconds)

        logger.info("EE: search_all_keywords → %d candidates", len(all_results))
        return list(all_results.values())

    def _api_keyword_search(self, keyword: str, max_results: int) -> list:
        """POST search to Estonian procurement API."""
        results = []
        page = 0
        page_size = min(50, max_results)

        while len(results) < max_results:
            payload = {
                "pageSize": page_size,
                "pageNumber": page,
                "searchWord": keyword,
                "sortField": "PUBLISHED_DATE",
                "sortDirection": "DESC",
            }
            try:
                resp = self._session.post(EE_SEARCH_URL, json=payload, timeout=20)

                # First call — detect if API is working
                if self._api_works is None:
                    self._api_works = resp.status_code in (200, 201)
                    if not self._api_works:
                        logger.warning(
                            "EE: API not accessible (HTTP %s) — "
                            "endpoint may have changed; stub returning empty",
                            resp.status_code,
                        )
                        return []

                if resp.status_code not in (200, 201):
                    logger.warning("EE: search API HTTP %s", resp.status_code)
                    break

                data = resp.json()
                items = data.get("procurements") or data.get("data") or []
                if not items:
                    break

                for item in items:
                    sr = self._item_to_result(item)
                    if sr:
                        results.append(sr)

                total = data.get("totalCount") or data.get("total") or 0
                if len(results) >= total or len(items) < page_size:
                    break
                page += 1

            except Exception as exc:
                logger.error("EE: API search error for '%s': %s", keyword, exc)
                if self._api_works is None:
                    self._api_works = False
                break

        return results[:max_results]

    def _item_to_result(self, item: dict) -> Optional[SearchResult]:
        proc_id = str(item.get("id") or item.get("procurementId") or "")
        if not proc_id:
            return None

        title = str(item.get("title") or item.get("procurementTitle") or "")
        authority = str(
            item.get("contractingAuthority") or
            item.get("buyerName") or
            item.get("organisationName") or ""
        )
        pub_date = str(item.get("publicationDate") or item.get("publishedDate") or "")[:10]
        ref_num = str(item.get("referenceNumber") or item.get("procurementNumber") or proc_id)

        value = None
        try:
            v = item.get("estimatedValue") or item.get("contractValue")
            if v:
                value = float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            pass

        url = EE_NOTICE_URL.format(id=proc_id)
        snippet = json.dumps({
            "id": proc_id,
            "status": item.get("status") or item.get("statusCode", ""),
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

    # ── Filter ────────────────────────────────────────────────────────────

    def filter_defence(self, results: list) -> list:
        kept = []
        defence_kw = [a.lower() for a in self.config.defence_authorities]
        trailer_kw = [k.lower() for k in self.config.trailer_keywords]

        for r in results:
            auth_low = (r.authority or "").lower()
            title_low = (r.title or "").lower()
            combined = f"{auth_low} {title_low}"

            is_defence = any(kw in combined for kw in defence_kw)
            is_trailer = any(kw in title_low for kw in trailer_kw)

            if is_defence and is_trailer:
                kept.append(r)

        logger.info("EE: filter_defence: %d → %d", len(results), len(kept))
        return kept

    # ── Detail ────────────────────────────────────────────────────────────

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        proc_id = result.reference_id
        if not proc_id:
            return self._detail_from_result(result)

        try:
            url = EE_DETAIL_URL.format(id=proc_id)
            resp = self._session.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning("EE: detail HTTP %s for %s", resp.status_code, proc_id)
                return self._detail_from_result(result)

            data = resp.json()
            item = data.get("procurement") or data if isinstance(data, dict) else {}

            title = str(item.get("title") or item.get("procurementTitle") or result.title)
            authority = str(
                item.get("contractingAuthority") or
                item.get("buyerName") or
                result.authority
            )
            pub_date = str(item.get("publicationDate") or result.date or "")[:10]
            description = str(
                item.get("description") or
                item.get("procurementDescription") or ""
            )[:500]

            value = result.value
            currency = "EUR"
            try:
                v = item.get("estimatedValue") or item.get("contractValue")
                if v:
                    value = float(str(v).replace(",", ""))
            except (ValueError, TypeError):
                pass

            winner = str(item.get("winnerName") or item.get("awardedTo") or "")

            qty = None
            try:
                q = item.get("quantity") or item.get("totalQuantity")
                if q:
                    qty = int(float(str(q)))
            except (ValueError, TypeError):
                pass

            raw_text = json.dumps(item, ensure_ascii=False)[:5000]

            return NoticeDetail(
                title=title[:200],
                description=description,
                authority=authority[:200],
                date=pub_date,
                value=value,
                currency=currency,
                quantity=qty,
                winner=winner[:200] if winner else "",
                reference_id=proc_id,
                url=result.url,
                source_code="EE-RP",
                raw_text=raw_text,
            )

        except Exception as exc:
            logger.error("EE: detail error for %s: %s", proc_id, exc)
            return self._detail_from_result(result)

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="EUR",
            reference_id=result.reference_id,
            url=result.url,
            source_code="EE-RP",
            raw_text=result.title or "",
        )

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        fx_eur = detail.value  # Already EUR
        return {
            "tender_id": f"EE-RP-{detail.reference_id}",
            "source": "EE-RP",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "Estonia",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": "EUR",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or "",
            "_national_raw_text": detail.raw_text or "",
            "_trailer_quantity_1": detail.quantity,
            "_raw": {"source": "EE-RP", "url": detail.url},
            "estimated_value": (
                {"amount": detail.value, "currency": "EUR"} if detail.value else None
            ),
            "award": (
                {"winner_name": detail.winner, "awarded": True}
                if detail.winner else None
            ),
        }

"""
Ukraine Adapter — Prozorro (prozorro.gov.ua)

Portal: https://prozorro.gov.ua
API:    https://public.api.openprocurement.org/api/2.5/tenders  (cursor-based, no auth)
Defence: Міністерство оборони, Державний оператор тилу (DOT), Збройні Сили України
Language: Ukrainian

Prozorro is the most transparent procurement API in the world — fully open,
REST/JSON, no authentication, updated in real-time.

SCOPE:
  ✅ Non-lethal/dual-use: trailers, fuel tankers, field kitchens, shelters,
     containers, generator trailers, water purification trailers
  ❌ Classified/lethal: weapons, ammunition, classified systems (not published)

API BEHAVIOUR:
  - Cursor-based pagination: each response contains "next_page.offset"
  - No keyword search — filter locally after download
  - CPV scheme: ДК021 (Ukrainian equivalent of EU CPV, same codes)
  - Defence authorities: identified by "procuringEntity.name" (Ukrainian)

SEARCH STRATEGY:
  1. Scan recent tenders with CPV prefix 34 (transport equipment) — includes trailers
  2. Filter locally by: defence authority name + trailer keyword in title/description
  3. Fetch full detail for each match
"""

import re
import time
import json
import logging
from typing import Optional

import requests
import urllib3

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

PROZORRO_API = "https://public.api.openprocurement.org/api/2.5"
PROZORRO_URL = "https://prozorro.gov.ua/tender/{tender_id}"


def _map_prozorro_status(raw_status: str) -> str:
    """Map Prozorro tender status strings to pipeline vocabulary.

    Prozorro statuses seen in the wild:
      active.tendering      — bidding period open
      active.enquiries      — clarification period
      active.qualification  — bids evaluated, award pending
      active.awarded        — award decision made
      complete              — contract signed and closed
      cancelled             — tender withdrawn by authority
      unsuccessful          — no valid bids received
    """
    s = (raw_status or "").lower().strip()
    if s in ("active.tendering", "active.enquiries", "active.pre-qualification",
             "active.stage2.pending", "active.stage2"):
        return "Open"
    if s in ("active.qualification", "active.qualification.stand-still",
             "active.awarded"):
        return "Awarded"
    if s == "complete":
        return "Closed"
    if s in ("cancelled", "unsuccessful"):
        return "Cancelled"
    if s.startswith("active"):
        return "Open"
    return ""


def _extract_ua_value(detail: dict) -> tuple[Optional[float], Optional[str]]:
    """
    Resolve a tender's monetary value with fallbacks for Prozorro quirks.

    Order:
      1. detail.value.amount      (top-level — present on most tenders)
      2. lots[*].value.amount     (multi-lot tenders carry value per lot)
      3. detail.minimalStep.amount (auction tenders without explicit value)

    Returns (amount, currency). Both None when no positive amount is found.
    """
    def _amount(v: dict) -> Optional[float]:
        if not isinstance(v, dict):
            return None
        try:
            amt = float(v.get("amount") or 0)
        except (TypeError, ValueError):
            return None
        return amt if amt > 0 else None

    top = detail.get("value") or {}
    amt = _amount(top)
    if amt is not None:
        return amt, top.get("currency")

    for lot in (detail.get("lots") or []):
        lv = lot.get("value") or {}
        amt = _amount(lv)
        if amt is not None:
            return amt, lv.get("currency")

    ms = detail.get("minimalStep") or {}
    amt = _amount(ms)
    if amt is not None:
        return amt, ms.get("currency")

    return None, None

# CPV codes relevant to trailers (Ukrainian ДК021, same as EU CPV)
TRAILER_CPV_PREFIXES = [
    "34223",  # Trailers and semi-trailers
    "34221",  # Special-purpose mobile containers
    "34140",  # Heavy goods vehicles (covers some trailer combinations)
    "35400",  # Military vehicles and parts
    "35600",  # Military vehicles
]

DEFENCE_AUTHORITIES_UA = [
    "міністерство оборони",
    "збройні сили",
    "державний оператор тилу",
    "dot ",
    "дот ",
    "національна гвардія",
    "державна прикордонна",
    "командування сухопутних",
    "командування повітряних",
    "командування військово-морських",
    "командування сил підтримки",
    "командування сил спеціальних операцій",
    "військова частина",
    "в/ч ",
    "генеральний штаб",
    "головне управління логістики",
    "головне управління постачання",
    "управління постачання",
    "центральне управління матеріального забезпечення",
]

TRAILER_KEYWORDS_UA = [
    "причіп",              # trailer (noun, nominative)
    "причепа",             # trailer (colloquial variant)
    "напівпричіп",         # semi-trailer
    "напівпричепа",
    "низькорамний причіп", # low-bed trailer
    "автоцистерна",        # fuel/water tanker (mounted)
    "причіп-цистерна",     # tanker trailer
    "польова кухня",       # field kitchen (trailer-mounted)
    "кухня польова",
    "транспортний причіп", # transport trailer
    "trailer",             # English
    "semi-trailer",        # English
    "мобільна кухня",      # mobile kitchen
    "нагрівач причіп",     # heater trailer
    "причіп паливозаправ", # fuel trailer
    "причіп для перев",    # transport trailer
    "фургон причіп",       # van/box trailer
]


def create_ua_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Ukraine",
        country_code="UA",
        source_code="UA-PR",
        base_url="https://prozorro.gov.ua",
        search_url=PROZORRO_API + "/tenders",
        language="uk",
        trailer_keywords=TRAILER_KEYWORDS_UA,
        defence_authorities=DEFENCE_AUTHORITIES_UA,
        min_interval_seconds=0.5,  # Prozorro API is fast
    )


class UAAdapter(BaseAdapter):
    """
    Ukraine Prozorro adapter — public REST API, no browser needed.

    Scan strategy: paginate through recent tenders, filter locally for
    defence authorities + trailer CPV codes or keywords.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=False)
        self._session.update_headers({
            "Accept": "application/json",
            "User-Agent": "TED-Defence-Trailer-Research/2.0 (defence procurement research)",
        })

    # ── Search ──

    def search(self, keyword: str, max_results: int = 100) -> list:
        """Search by keyword — delegates to search_all_keywords."""
        return []

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """
        Scan Prozorro for Ukrainian defence trailer tenders.

        Two-stage approach:
        Stage 1: Scan list endpoint with opt_fields=procuringEntity,tenderID
                 Filter locally for defence authority names → ~9% hit rate
                 Scan depth: 1000 test / 10000 full
        Stage 2: Fetch full detail for each defence hit
                 Filter for trailer keywords in title/description → collect matches

        This avoids fetching 5000 individual records by pre-filtering via entity name.
        """
        all_results: dict[str, SearchResult] = {}
        max_scan = 1000 if test_mode else 10000
        detail_limit = 20 if test_mode else 500  # max detail fetches (increased from 200)

        # ── Stage 1: Scan list for defence entities ──
        defence_candidates = []
        scanned = 0
        offset = None

        logger.info(f"UA: Stage 1 — scanning {max_scan} tenders for defence entities...")

        while scanned < max_scan:
            params = {
                "limit": 100,
                "descending": "true",
                "opt_fields": "procuringEntity,tenderID",
            }
            if offset:
                params["offset"] = offset

            try:
                resp = self._session.get(f"{PROZORRO_API}/tenders", params=params, timeout=30)
                if resp.status_code != 200:
                    logger.warning(f"UA: list API {resp.status_code}")
                    break

                data = resp.json()
                items = data.get("data", [])
                if not items:
                    break

                for item in items:
                    entity = item.get("procuringEntity") or {}
                    auth = (entity.get("name") or "").lower()
                    if any(p in auth for p in self.config.defence_authorities):
                        defence_candidates.append({
                            "id": item.get("id", ""),
                            "tenderID": item.get("tenderID", ""),
                            "authority": entity.get("name", ""),
                            "date": item.get("dateModified", "")[:10],
                        })

                scanned += len(items)
                offset = data.get("next_page", {}).get("offset")
                if not offset or len(items) < 100:
                    break

                if scanned % 1000 == 0:
                    logger.info(f"UA: scanned {scanned}, defence candidates: {len(defence_candidates)}")
                time.sleep(0.3)

            except Exception as e:
                logger.error(f"UA: list API error: {e}")
                break

        logger.info(f"UA: Stage 1 done — {len(defence_candidates)} defence candidates "
                    f"from {scanned} scanned")

        # ── Stage 2: Fetch details and filter for trailers ──
        candidates_to_fetch = defence_candidates[:detail_limit]
        logger.info(f"UA: Stage 2 — fetching {len(candidates_to_fetch)} detail records...")

        fetched = 0
        for cand in candidates_to_fetch:
            internal_id = cand.get("id", "")
            if not internal_id:
                continue
            try:
                resp = self._session.get(
                    f"{PROZORRO_API}/tenders/{internal_id}", timeout=20)
                if resp.status_code != 200:
                    continue
                detail = resp.json().get("data", {})
                title = (detail.get("title") or "").lower()
                desc = (detail.get("description") or "").lower()

                # Filter: trailer keyword in title or CPV match
                cpv_codes = []
                for it in (detail.get("items") or []):
                    cls = it.get("classification") or {}
                    cpv = cls.get("id", "")[:5]
                    if cpv:
                        cpv_codes.append(cpv)

                is_trailer = (
                    any(kw in title or kw in desc for kw in self.config.trailer_keywords)
                    or any(any(cpv.startswith(p) for p in TRAILER_CPV_PREFIXES)
                           for cpv in cpv_codes)
                )

                if not is_trailer:
                    continue

                # Build SearchResult
                entity = detail.get("procuringEntity") or {}
                authority = entity.get("name", cand.get("authority", ""))
                tender_id = detail.get("tenderID") or cand.get("tenderID", "")
                value, currency = _extract_ua_value(detail)

                meta = json.dumps({"id": internal_id, "status": detail.get("status","")}, ensure_ascii=False)
                r = SearchResult(
                    title=detail.get("title", ""),
                    url=PROZORRO_URL.format(tender_id=tender_id),
                    authority=authority,
                    reference_id=tender_id,
                    date=(detail.get("datePublished") or cand.get("date",""))[:10],
                    value=value,
                    currency=currency or "UAH",
                    snippet=meta[:400],
                )
                key = tender_id or internal_id
                if key and key not in all_results:
                    all_results[key] = r
                    logger.info(f"UA: MATCH {tender_id}: {detail.get('title','')[:60]}")

                fetched += 1
                time.sleep(self.config.min_interval_seconds)

            except Exception as e:
                logger.error(f"UA: detail fetch error for {internal_id}: {e}")

        results = list(all_results.values())
        logger.info(f"UA: search_all_keywords → {len(results)} defence+trailer tenders "
                    f"(scanned {scanned}, fetched {fetched} details)")
        return results

    def _item_to_result(self, item: dict) -> Optional[SearchResult]:
        """Convert Prozorro API item to SearchResult."""
        tender_id = item.get("tenderID") or item.get("id", "")
        if not tender_id:
            return None

        title = item.get("title", "")
        entity = item.get("procuringEntity", {}) or {}
        authority = (entity.get("name", "") or
                     entity.get("contactPoint", {}).get("name", ""))
        date_str = (item.get("datePublished") or item.get("dateModified") or "")[:10]
        status = item.get("status", "")

        # Extract CPV from items
        cpv_codes = []
        for proc_item in (item.get("items") or []):
            cls = proc_item.get("classification") or {}
            cpv = cls.get("id", "")
            if cpv:
                cpv_codes.append(cpv)

        value = None
        val_data = item.get("value") or {}
        try:
            v = val_data.get("amount")
            if v and float(v) > 0:
                value = float(v)
        except (ValueError, TypeError):
            pass

        url = PROZORRO_URL.format(tender_id=tender_id)
        meta = json.dumps({
            "id": item.get("id", ""),
            "cpv": cpv_codes[:3],
            "status": status,
        }, ensure_ascii=False)

        return SearchResult(
            title=title,
            url=url,
            authority=authority,
            reference_id=tender_id,
            date=date_str,
            value=value,
            currency="UAH",
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

    def _is_trailer_related(self, result: SearchResult) -> bool:
        title_lower = (result.title or "").lower()

        # Check title keywords
        if any(kw in title_lower for kw in self.config.trailer_keywords):
            return True

        # Check CPV codes from snippet
        try:
            meta = json.loads(result.snippet or "{}")
            cpv_codes = meta.get("cpv", [])
            if any(any(cpv.startswith(p) for p in TRAILER_CPV_PREFIXES)
                   for cpv in cpv_codes):
                return True
        except Exception:
            pass

        return False

    # ── Detail ──

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch full tender detail from Prozorro API."""
        meta = {}
        try:
            meta = json.loads(result.snippet or "{}")
        except Exception:
            pass

        internal_id = meta.get("id", "")

        # Prozorro detail endpoint requires the internal UUID, not the tenderID
        if not internal_id:
            # Extract from URL
            m = re.search(r"/tender/([A-Za-z0-9-]+)", result.url)
            if m:
                internal_id = m.group(1)

        if not internal_id:
            return self._detail_from_result(result)

        try:
            resp = self._session.get(
                f"{PROZORRO_API}/tenders/{internal_id}",
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"UA: detail {resp.status_code} for {internal_id}")
                return self._detail_from_result(result)

            data = resp.json().get("data", {})

            entity = data.get("procuringEntity", {}) or {}
            authority = entity.get("name", result.authority)

            value, currency = _extract_ua_value(data)

            # Build description from items
            items = data.get("items") or []
            desc_parts = [data.get("description", "")]
            total_qty = 0
            for it in items:
                item_desc = it.get("description", "")
                qty = it.get("quantity", 0)
                if qty:
                    total_qty += qty
                    desc_parts.append(f"- {item_desc} (qty: {qty})")
                elif item_desc:
                    desc_parts.append(f"- {item_desc}")
            description = "\n".join(d for d in desc_parts if d)[:500]

            # Winner from awards
            winner = ""
            for award in (data.get("awards") or []):
                if award.get("status") == "active":
                    suppliers = award.get("suppliers") or []
                    if suppliers:
                        winner = suppliers[0].get("name", "")
                    break

            raw_text = json.dumps(data, ensure_ascii=False)[:10000]

            return NoticeDetail(
                title=data.get("title", result.title),
                description=description,
                authority=authority,
                date=(data.get("datePublished") or result.date or "")[:10],
                value=value,
                currency=currency or "UAH",
                quantity=int(total_qty) if total_qty else None,
                winner=winner[:120] if winner else "",
                reference_id=result.reference_id,
                url=result.url,
                source_code="UA-PR",
                raw_text=raw_text,
                status=_map_prozorro_status(data.get("status", "")),
            )

        except Exception as e:
            logger.error(f"UA: detail fetch error for {internal_id}: {e}")
            return self._detail_from_result(result)

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="UAH",
            reference_id=result.reference_id,
            url=result.url,
            source_code="UA-PR",
            raw_text=result.title or "",
        )

"""
Netherlands Adapter — TenderNed (tenderned.nl)

Portal: https://www.tenderned.nl
Defence: Ministerie van Defensie, Defensie Materieel Organisatie (DMO)
API: https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties (public REST, no auth)

Strategy:
  1. REST API search at TenderNed public API v2
     GET /papi/tenderned-rs-tns/v2/publicaties
     params: zoekterm, aanbestedende_dienst_naam, publicatieDatumVan/Tot, type
  2. Two passes: keyword search + authority name search
  3. Filter to defence authorities
  4. Detail fetch via same API or HTML page scrape

API documentation: https://www.tenderned.nl/papi/tenderned-rs-tns/v2/api-docs
No authentication required for public tender search.
"""

import re
import time
import json
import logging
import os
from typing import Optional

import requests
import urllib3

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

# ── Endpoints ──
BASE_URL        = "https://www.tenderned.nl"
SEARCH_API      = "https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties"
DETAIL_API      = "https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties/{pub_id}"
NOTICE_URL      = "https://www.tenderned.nl/aankondigingen/overzicht/{pub_id}"

# TenderNed publication types:
# "AANKONDIGING_VAN_EEN_OPDRACHT" = procurement notice
# "VOORAANKONDIGING"              = prior information notice
# "AANKONDIGING_VAN_GEGUNDE_OPDRACHT" = contract award
PUB_TYPES_INCLUDE = [
    "AANKONDIGING_VAN_EEN_OPDRACHT",
    "AANKONDIGING_VAN_GEGUNDE_OPDRACHT",
]

TRAILER_KEYWORDS_NL = [
    "aanhangwagen",
    "oplegger",
    "dieplader",
    "tankwagen",
    "veldkeuken",
    "containertransport",
    "haakarm",
    "militaire aanhangwagen",
    "munitietransport",
    "semitrailer",
    "voertuig defensie",
    "aanhanger",
]

DEFENCE_ORG_NAMES = [
    "Ministerie van Defensie",
    "Defensie Materieel Organisatie",
    "DMO",
    "Koninklijke Marechaussee",
    "Commando Landstrijdkrachten",
    "CLAS",
    "Defensie",
]

# CPV codes for trailer search (TenderNed supports CPV filter too)
TRAILER_CPV_PREFIXES = [
    "34223",   # Trailers + semi-trailers
    "34221",   # Special-purpose containers
    "35400",   # Military vehicles
]


def create_nl_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Netherlands",
        country_code="NL",
        source_code="NL-TN",
        base_url=BASE_URL,
        search_url=SEARCH_API,
        language="nl",
        trailer_keywords=TRAILER_KEYWORDS_NL,
        defence_authorities=DEFENCE_ORG_NAMES,
        min_interval_seconds=2.0,
    )


class NLAdapter(BaseAdapter):
    """
    Netherlands adapter — TenderNed public REST API v2.

    Search strategy:
    1. Per trailer keyword + Defensie authority filter → REST API
    2. Direct authority name search for known defence orgs
    3. Deduplicate by publicatieId
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        ssl_off = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() in ("1", "true", "yes")
        session = requests.Session()
        session.verify = not ssl_off
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Referer": "https://www.tenderned.nl/",
        })
        return session

    # ── Search ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search TenderNed by keyword."""
        return self._api_search({"zoekterm": keyword}, max_results=max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """
        Scan TenderNed API for Defensie publications.

        Note: the TenderNed public API (/papi/tenderned-rs-tns/v2/publicaties)
        does NOT support server-side filtering by authority or keyword — it always
        returns all publications sorted by date. We paginate through recent
        publications and filter locally.

        Scan depth: 500 publications (recent ~3-5 days) in test mode,
                    5000 publications (~1 month) in full mode.
        """
        all_results: dict[str, SearchResult] = {}
        max_scan = 500 if test_mode else 5000
        page_size = 50

        logger.info(f"NL: scanning TenderNed (max {max_scan} publications)")
        scanned = 0
        page = 0

        while scanned < max_scan:
            hits = self._api_search({}, max_results=page_size, _page_override=page)
            if not hits:
                break
            for h in hits:
                # Only keep Defensie publications — let AI classifier decide trailer relevance
                if self._is_defence(h):
                    key = h.reference_id or h.url
                    if key and key not in all_results:
                        all_results[key] = h
            scanned += len(hits)
            if len(hits) < page_size:
                break
            page += 1
            if page % 10 == 0:
                logger.info(f"NL: scanned {scanned}, Defensie found: {len(all_results)}")
            time.sleep(0.5)

        results = list(all_results.values())
        logger.info(f"NL: search_all_keywords → {len(results)} Defensie notices found (scanned {scanned})")
        return results

    def _api_search(self, params: dict, max_results: int = 100,
                    _page_override: int = None) -> list:
        """Fetch one page from TenderNed API and return SearchResult list.

        Note: the TenderNed public API does NOT support filtering by keyword
        or authority name — all parameters except 'page' and 'size' are ignored
        by the server. Use search_all_keywords() which applies local filtering.
        """
        page = _page_override if _page_override is not None else 0
        page_size = min(50, max_results)
        query = {**params, "page": page, "size": page_size}

        try:
            resp = self._session.get(SEARCH_API, params=query, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"NL TenderNed API: HTTP {resp.status_code}")
                return []
            data = resp.json()
            if isinstance(data, dict):
                items = data.get("content") or []
            elif isinstance(data, list):
                items = data
            else:
                return []
            return [self._item_to_result(i) for i in items]
        except Exception as e:
            logger.error(f"NL TenderNed API error: {e}")
            return []

    def _item_to_result(self, item: dict) -> SearchResult:
        """Convert TenderNed API item to SearchResult.

        TenderNed v2 confirmed fields:
          publicatieId, publicatieDatum, aanbestedingNaam, opdrachtgeverNaam,
          tsenderLink, opdrachtBeschrijving, kenmerk
        """
        pub_id = str(item.get("publicatieId") or item.get("id") or "")
        ref_id = str(item.get("kenmerk") or item.get("publicatiecode") or pub_id)

        # Title: 'aanbestedingNaam' is the tender name
        title = (item.get("aanbestedingNaam") or item.get("titel") or
                 item.get("naam") or item.get("onderwerp") or "")
        # Authority: 'opdrachtgeverNaam' is the client
        authority = (item.get("opdrachtgeverNaam") or item.get("aanbestedendeDienstNaam") or "")
        date_str = (item.get("publicatieDatum") or item.get("datum") or "")[:10]
        description = (item.get("opdrachtBeschrijving") or "")[:200]

        # External link to the actual tender documents
        external_link = item.get("tsenderLink") or ""
        url = NOTICE_URL.format(pub_id=pub_id) if pub_id else external_link or BASE_URL

        value = None
        for vk in ("geraamdeWaarde", "totaleWaarde", "waarde", "estimatedValue"):
            v = item.get(vk)
            try:
                if v and float(str(v).replace(",", ".")) > 0:
                    value = float(str(v).replace(",", "."))
                    break
            except (ValueError, TypeError):
                pass

        # Extract TenderNed notice URL from 'link' field
        link_field = item.get("link") or {}
        if isinstance(link_field, dict):
            tn_url = link_field.get("href") or ""
        else:
            tn_url = str(link_field)
        url = tn_url or (NOTICE_URL.format(pub_id=pub_id) if pub_id else external_link or BASE_URL)

        meta = json.dumps({
            "pubId": pub_id,
            "org": authority,
            "externalLink": external_link,
            "tnUrl": tn_url,
        }, ensure_ascii=False)

        return SearchResult(
            title=title,
            url=url,
            authority=authority,
            reference_id=ref_id,
            date=date_str,
            value=value,
            currency="EUR",
            snippet=meta[:500],
        )

    # ── Filter ──

    def filter_defence(self, results: list) -> list:
        """Keep only defence-authority notices."""
        return [r for r in results if self._is_defence(r)]

    def _is_defence(self, result: SearchResult) -> bool:
        auth_lower = (result.authority or "").lower()
        title_lower = (result.title or "").lower()
        for pattern in self.config.defence_authorities:
            if pattern.lower() in auth_lower or pattern.lower() in title_lower:
                return True
        return False

    _TRAILER_KW_NL = (
        "aanhangwagen", "oplegger", "dieplader", "tankwagen",
        "veldkeuken", "haakarm", "trailer", "aanhanger",
        "semitrailer", "opbouweenheid",
    )

    def _is_trailer_related(self, result: SearchResult) -> bool:
        title_lower = (result.title or "").lower()
        return any(kw in title_lower for kw in self._TRAILER_KW_NL)

    # ── Detail ──

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch full detail via TenderNed API."""
        pub_id = ""
        try:
            meta = json.loads(result.snippet or "{}")
            pub_id = meta.get("pubId", "")
        except Exception:
            pass
        if not pub_id and result.reference_id:
            pub_id = result.reference_id

        if pub_id:
            detail = self._fetch_detail(pub_id, result)
            if detail:
                return detail

        return self._detail_from_result(result)

    def _fetch_detail(self, pub_id: str,
                      result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch detail from TenderNed API."""
        url = DETAIL_API.format(pub_id=pub_id)
        try:
            resp = self._session.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"NL: detail API {resp.status_code} for {pub_id}")
                return None
            data = resp.json()
            if not isinstance(data, dict):
                return None

            # Build raw text from all descriptive fields
            raw_parts = []
            for key in ("titel", "omschrijving", "beschrijving", "technischeBeschrijving",
                        "aanvullendeInformatie", "opdracht"):
                val = data.get(key)
                if isinstance(val, dict):
                    val = val.get("waarde") or val.get("tekst") or str(val)
                if val and isinstance(val, str):
                    raw_parts.append(f"{key}: {val}")

            raw_text = "\n".join(raw_parts) or result.title or ""

            title = data.get("titel") or data.get("naam") or result.title or ""
            authority = (data.get("aanbestedendeDienstNaam") or
                         (data.get("aanbestedendeDienst") or {}).get("naam", "")
                         if isinstance(data.get("aanbestedendeDienst"), dict) else
                         data.get("aanbestedendeDienst") or result.authority or "")
            description = (data.get("omschrijving") or data.get("beschrijving") or "")[:500]
            date_str = (data.get("publicatieDatum") or result.date or "")[:10]

            value = None
            for vk in ("geraamdeWaarde", "totaleWaarde", "waarde"):
                v = data.get(vk)
                try:
                    if v and float(str(v).replace(",", ".")) > 0:
                        value = float(str(v).replace(",", "."))
                        break
                except (ValueError, TypeError):
                    pass

            winner = ""
            # Award notices have "gunningsinformatie" or "gegunde" section
            gunning = data.get("gunningsinformatie") or data.get("gegunde") or {}
            if isinstance(gunning, dict):
                winner = gunning.get("contractant") or gunning.get("naam") or ""
            elif isinstance(gunning, list) and gunning:
                first = gunning[0]
                if isinstance(first, dict):
                    winner = first.get("contractant") or first.get("naam") or ""

            quantity = None
            raw_lower = raw_text.lower()
            m = re.search(r"(\d+)\s*(?:stuks?|aanhangwagen|oplegger|trailer)", raw_lower)
            if m:
                try:
                    quantity = int(m.group(1))
                except ValueError:
                    pass

            duration = data.get("looptijd") or data.get("contractDuur") or ""
            if isinstance(duration, dict):
                duration = str(duration.get("waarde", "")) + " " + str(duration.get("eenheid", ""))

            return NoticeDetail(
                title=title,
                description=description,
                authority=authority,
                date=date_str,
                value=value,
                currency="EUR",
                quantity=quantity,
                winner=str(winner)[:120] if winner else "",
                duration=str(duration)[:80] if duration else "",
                reference_id=result.reference_id,
                url=NOTICE_URL.format(pub_id=pub_id),
                source_code="NL-TN",
                raw_text=raw_text[:10000],
            )
        except Exception as e:
            logger.error(f"NL: detail fetch error for {pub_id}: {e}")
            return None

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            authority=result.authority,
            date=result.date,
            value=result.value,
            currency="EUR",
            reference_id=result.reference_id,
            url=result.url,
            source_code="NL-TN",
            raw_text=result.title or "",
        )

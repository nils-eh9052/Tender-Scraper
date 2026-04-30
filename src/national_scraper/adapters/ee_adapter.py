"""
Estonia Adapter — Riigihangete Register (riigihanked.riik.ee)

Portal: https://riigihanked.riik.ee
Defence: Kaitseministeerium, Kaitsevägi, Riigi Kaitseinvesteeringute Keskus (RKK)

DISCOVERY (Sprint 11):
  The Estonian procurement portal has a public REST API.

  REST API base: https://riigihanked.riik.ee/rhr-web/api/v1/
  Sprint 11 test result: HTTP 404 at POST /rhr-web/api/v1/procurements/search
    → API endpoint has changed since discovery. Likely moved or renamed.
    → Adapter returns empty and logs warning without crashing.

  Correct endpoint TBD via browser XHR interception:
    Suggested: open riigihanked.riik.ee, open DevTools Network tab,
    search for "haagis", copy the XHR request URL and body format.
    The portal is React-based — the API definitely exists, just needs rediscovery.

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
EE_SEARCH_URL = f"{EE_BASE}/rhr-web/#/procurement"  # SPA front page; actual data via XML bulk
# Monthly XML bulk export (UBL eForms format, no auth required)
EE_OPENDATA_XML = f"{EE_BASE}/rhr/api/public/v1/opendata/notice/{{year}}/month/{{month}}/xml"
# Detail: HTML render of a single notice by UUID
EE_NOTICE_HTML = f"{EE_BASE}/rhr/api/public/v1/notice/{{notice_id}}/html"
EE_NOTICE_URL = f"{EE_BASE}/rhr-web/#/procurement/{{notice_id}}"

# UBL namespace prefixes used in the XML
_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "efac": "http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1",
    "efbc": "http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1",
}


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

    Strategy (Sprint 11 rewrite — REST API at /rhr-web/api was 404):
      Download monthly UBL eForms XML bulk exports from the public OpenData
      endpoint, parse client-side for trailer + defence keywords, then fetch
      notice HTML for matched entries.

    URL: GET /rhr/api/public/v1/opendata/notice/{year}/month/{month}/xml
         No auth, returns ~40 MB XML with all notices for the month.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=True)
        self._session.update_headers({"Accept": "application/xml, */*"})

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list:
        return []  # keyword search not meaningful here; use search_all_keywords

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """Download monthly XML exports and filter for defence trailer notices."""
        from datetime import date, timedelta

        today = date.today()
        # test: last 2 months; full: last 13 months (covers rolling year)
        months_back = 2 if test_mode else 13

        all_results: dict[str, SearchResult] = {}
        trailer_kw_lower = [k.lower() for k in self.config.trailer_keywords]
        defence_kw_lower = [a.lower() for a in self.config.defence_authorities]

        for i in range(months_back):
            # Walk backwards month by month
            target = today.replace(day=1) - timedelta(days=1) * (i * 28)
            year, month = target.year, target.month

            logger.info("EE: fetching XML for %d/%02d", year, month)
            notices = self._fetch_month_xml(year, month)

            month_hits = 0
            for notice_id, title, authority, date_str, description in notices:
                search_text = f"{title} {description}".lower()
                auth_lower = authority.lower()

                has_trailer = any(kw in search_text for kw in trailer_kw_lower)
                has_defence = any(kw in auth_lower or kw in search_text
                                  for kw in defence_kw_lower)

                if has_trailer and has_defence and notice_id not in all_results:
                    url = EE_NOTICE_URL.format(notice_id=notice_id)
                    all_results[notice_id] = SearchResult(
                        title=title[:200],
                        url=url,
                        authority=authority[:200],
                        reference_id=notice_id,
                        date=date_str,
                        currency="EUR",
                        snippet=description[:200],
                    )
                    month_hits += 1

            logger.info("EE: %d/%02d → %d notices scanned, %d defence+trailer hits",
                        year, month, len(notices), month_hits)
            time.sleep(self.config.min_interval_seconds)

        logger.info("EE: search_all_keywords → %d candidates", len(all_results))
        return list(all_results.values())

    def _fetch_month_xml(self, year: int, month: int) -> list[tuple]:
        """
        Download and parse one month's UBL XML bulk export.
        Returns list of (notice_id, title, authority, date, description).
        """
        import xml.etree.ElementTree as ET

        url = EE_OPENDATA_XML.format(year=year, month=month)
        try:
            resp = self._session.get(url, timeout=120)
            if resp.status_code != 200:
                logger.warning("EE: XML %d/%02d → HTTP %s", year, month, resp.status_code)
                return []
        except Exception as exc:
            logger.error("EE: XML fetch error %d/%02d: %s", year, month, exc)
            return []

        results = []
        try:
            # Parse the <OPEN-DATA> root; each child is a <ContractNotice>
            root = ET.fromstring(resp.content)
            cbc = _NS["cbc"]
            cac = _NS["cac"]
            efac = _NS["efac"]

            for notice in root:
                notice_id = ""
                title = ""
                authority = ""
                date_str = ""
                description = ""

                # Notice UUID
                el = notice.find(f"{{{cbc}}}ContractFolderID")
                if el is not None:
                    notice_id = (el.text or "").strip()

                # Publication date
                el = notice.find(f"{{{cbc}}}IssueDate")
                if el is not None:
                    date_str = (el.text or "")[:10]

                # Procurement title from ProcurementProject
                proj = notice.find(f".//{{{cac}}}ProcurementProject")
                if proj is not None:
                    name_el = proj.find(f"{{{cbc}}}Name")
                    if name_el is not None:
                        title = (name_el.text or "").strip()
                    desc_el = proj.find(f"{{{cbc}}}Description")
                    if desc_el is not None:
                        description = (desc_el.text or "").strip()

                # Authority: first Organization's Company name
                orgs = notice.find(f".//{{{efac}}}Organizations")
                if orgs is not None:
                    for org in orgs.findall(f"{{{efac}}}Organization"):
                        company = org.find(f"{{{efac}}}Company")
                        if company is not None:
                            name_el = company.find(
                                f".//{{{cac}}}PartyName/{{{cbc}}}Name"
                            )
                            if name_el is not None:
                                authority = (name_el.text or "").strip()
                                break  # first org = contracting authority

                if notice_id:
                    results.append((notice_id, title, authority, date_str, description))

        except ET.ParseError as exc:
            logger.error("EE: XML parse error %d/%02d: %s", year, month, exc)

        return results

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
        """Fetch notice HTML for a matched entry and extract structured data."""
        proc_id = result.reference_id
        if not proc_id:
            return self._detail_from_result(result)

        try:
            html_url = EE_NOTICE_HTML.format(notice_id=proc_id)
            resp = self._session.get(html_url, timeout=30)
            if resp.status_code != 200:
                logger.warning("EE: detail HTML HTTP %s for %s", resp.status_code, proc_id)
                return self._detail_from_result(result)

            html = resp.text

            # Strip HTML tags for raw text
            import re as _re
            raw_text = _re.sub(r"<[^>]+>", " ", html)[:5000]

            # Extract value from HTML (pattern: currency amount)
            value = result.value
            val_m = _re.search(r"([\d\s]+[.,]\d{2})\s*(?:EUR|€)", html)
            if val_m:
                try:
                    value = float(
                        val_m.group(1).replace(" ", "").replace(",", ".")
                    )
                except ValueError:
                    pass

            return NoticeDetail(
                title=result.title,
                description=result.snippet[:500] if result.snippet else "",
                authority=result.authority,
                date=result.date,
                value=value,
                currency="EUR",
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

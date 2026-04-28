"""
Norway Adapter — Doffin (doffin.no)
REST API: POST https://api.doffin.no/webclient/api/v2/search-api/search

Discovered via browser XHR interception (2026-04-28):
  Endpoint: POST https://api.doffin.no/webclient/api/v2/search-api/search
  Body: {"numHitsPerPage": N, "page": P, "searchString": "...", "sortBy": "RELEVANCE",
         "facets": {"cpvCodesLabel": {"checkedItems": []}, ...}}
  Response: {"numHitsTotal": N, "hits": [{id, buyer, heading, description, type, status,
             publicationDate, deadline, estimatedValue, ...}]}

No browser needed for search — pure REST API.
Browser only used for detail page (to get full notice text).

Norway is NOT in the EU — some tenders appear ONLY on Doffin, not on TED.
This makes the adapter particularly valuable for capturing Norwegian-only
defence trailer procurement from Forsvarsmateriell and related agencies.

Validated TED notices to find on Doffin (4 known):
  477617-2024, 694394-2023, 195799-2021, + 1 more (from force_include.json)
  These may appear as historical/expired notices on Doffin.
"""

import re
import time
import logging
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL     = "https://doffin.no"
SEARCH_URL   = "https://doffin.no/search"
API_ENDPOINT = "https://api.doffin.no/webclient/api/v2/search-api/search"
NOTICE_URL   = "https://doffin.no/notices/{notice_id}"

# Default search payload template (facets empty = no filters)
_FACETS_EMPTY = {
    "cpvCodesLabel":             {"checkedItems": []},
    "cpvCodesId":                {"checkedItems": []},
    "type":                      {"checkedItems": []},
    "status":                    {"checkedItems": []},
    "contractNature":            {"checkedItems": []},
    "procurementStrategicLabels":{"checkedItems": []},
    "publicationDate":           {"from": None, "to": None},
    "location":                  {"checkedItems": []},
    "buyer":                     {"checkedItems": []},
}


def create_no_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Norway",
        country_code="NO",
        source_code="NO-DF",
        base_url=BASE_URL,
        search_url=SEARCH_URL,
        language="no",
        trailer_keywords=[
            "tilhenger",          # trailer (generic)
            "semitrailer",        # semi-trailer
            "påhengsvogn",        # tow trailer
            "lastetrailer",       # cargo trailer
            "tanktrailer",        # tank trailer
            "feltkjøkken",        # field kitchen
            "lasteveksler",       # hook-lift
            "containervogn",      # container trailer
            "lavlaster",          # low-bed
            "tungtransport",      # heavy haulage
            "drivstofftilhenger", # fuel trailer
            "tilhengervogn",      # trailer wagon
            "semihenger",         # semi-trailer (informal)
        ],
        defence_authorities=[
            "Forsvarsmateriell",
            "Forsvarsdepartementet",
            "Forsvaret",
            "Forsvarets logistikkorganisasjon",
            "Forsvarets logistikk",
            "Hæren",
            "Sjøforsvaret",
            "Luftforsvaret",
            "Cyberforsvaret",
            "Heimevernet",
        ],
        min_interval_seconds=1.5,
    )


class NOAdapter(BaseAdapter):
    """
    Norway adapter — Doffin REST API (no browser needed for search).

    Search flow:
    1. POST to https://api.doffin.no/webclient/api/v2/search-api/search
       with searchString = keyword or authority name
    2. Paginate through hits (numHitsPerPage / page)
    3. filter_defence() keeps defence-authority notices with trailer keywords
    4. get_detail() loads notice URL in browser for full text
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    # ── Session setup ──

    def _build_session(self):
        try:
            import requests, urllib3
            urllib3.disable_warnings()
        except ImportError:
            logger.error("NO: 'requests' not installed")
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
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin":  BASE_URL,
            "Referer": BASE_URL + "/search",
        })
        return session

    # ── Public interface ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search Doffin via REST API for a keyword."""
        logger.info(f"NO: searching for '{keyword}'")
        return self._api_search(keyword, max_results=max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 50,
                            test_mode: bool = False) -> list:
        """
        Search for all trailer keywords + all defence authority names.
        Deduplicates by notice ID.
        """
        all_results: dict = {}

        keywords    = self.config.trailer_keywords
        authorities = self.config.defence_authorities
        if test_mode:
            keywords    = keywords[:2]
            authorities = authorities[:2]

        # 1. Keyword searches (trailer terms)
        for kw in keywords:
            hits = self._api_search(kw, max_results=max_results_per_keyword)
            for r in hits:
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            logger.info(f"NO: kw='{kw}' → {len(hits)} hits (total {len(all_results)})")
            time.sleep(self.config.min_interval_seconds)

        # 2. Authority name searches (catches non-trailer-titled notices)
        for auth in authorities:
            hits = self._api_search(auth, max_results=max_results_per_keyword)
            for r in hits:
                key = r.reference_id or r.url or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            logger.info(f"NO: auth='{auth}' → {len(hits)} hits (total {len(all_results)})")
            time.sleep(self.config.min_interval_seconds)

        total = list(all_results.values())
        logger.info(f"NO: search_all_keywords → {len(total)} total results")
        return total

    def filter_defence(self, results: list) -> list:
        """
        Keep notices from Norwegian defence authorities OR with trailer keywords.
        """
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
            )
            has_trailer_kw = any(
                kw.lower() in combined
                for kw in self.config.trailer_keywords
            )

            if has_defence_auth and has_trailer_kw:
                kept.append(r)

        # If strict intersection yields nothing, fall back to defence-auth only
        if not kept:
            for r in results:
                combined = " ".join([
                    (r.title or "").lower(),
                    (r.authority or "").lower(),
                    (r.snippet or "").lower(),
                ])
                if any(auth.lower() in combined for auth in self.config.defence_authorities):
                    kept.append(r)

        logger.info(f"NO: filter_defence: {len(results)} → {len(kept)}")
        return kept

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """
        Fetch notice detail page via browser (richer text than API).
        Falls back to search result data if browser fails.
        """
        notice_url = result.url
        if not notice_url and result.reference_id:
            notice_url = NOTICE_URL.format(notice_id=result.reference_id)
        if not notice_url:
            return self._detail_from_search_result(result)

        logger.info(f"NO: fetching detail: {notice_url[:80]}")
        if not self.browser.goto(notice_url, wait_for="networkidle", timeout=25000):
            logger.warning(f"NO: could not load detail page")
            return self._detail_from_search_result(result)

        self.browser.wait_seconds(3)
        safe_id = re.sub(r"[^a-z0-9]", "_", (result.reference_id or "no")[:15].lower())
        self.browser._screenshot(f"no_detail_{safe_id}")

        raw_text = self.browser.get_page_text()
        detail = NoticeDetail(
            title=result.title or self._find_title(raw_text),
            url=notice_url,
            authority=result.authority or self._find_authority(raw_text),
            date=result.date or self._find_date(raw_text),
            source_code="NO-DF",
            raw_text=raw_text[:15000],
            currency="NOK",
        )
        detail.reference_id = result.reference_id or self._find_ref_id(raw_text)
        detail.description  = self._find_description(raw_text)
        detail.quantity     = self._find_quantity(raw_text)
        detail.value        = result.value or self._find_value(raw_text)
        detail.winner       = self._find_winner(raw_text)
        detail.duration     = self._find_duration(raw_text)
        return detail

    # ── REST API ──

    def _api_search(self, query: str, max_results: int = 50) -> list:
        """
        POST to the Doffin search API and return SearchResult list.
        Paginates if needed.
        """
        import copy
        if not self._session:
            return []

        page_size = min(max_results, 100)
        all_hits  = []
        page      = 1

        while len(all_hits) < max_results:
            payload = {
                "numHitsPerPage": page_size,
                "page":           page,
                "searchString":   query,
                "sortBy":         "RELEVANCE",
                "facets":         copy.deepcopy(_FACETS_EMPTY),
            }
            try:
                resp = self._session.post(API_ENDPOINT, json=payload, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"NO API: {resp.status_code} for '{query}' (page {page})")
                    break
                data = resp.json()
                hits = data.get("hits", [])
                if not hits:
                    break
                all_hits.extend(hits)
                total = data.get("numHitsTotal", 0)
                logger.debug(f"NO API page {page}: {len(hits)} hits, total={total}")
                if len(all_hits) >= min(max_results, total):
                    break
                page += 1
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"NO API error: {e}")
                break

        return [r for r in (self._hit_to_result(h) for h in all_hits[:max_results]) if r]

    def _hit_to_result(self, hit: dict) -> Optional[SearchResult]:
        """Convert a raw Doffin API hit to SearchResult."""
        if not hit or not isinstance(hit, dict):
            return None

        notice_id = hit.get("id", "")
        title     = hit.get("heading", "") or hit.get("title", "")
        if not title:
            return None

        # Authority
        buyers = hit.get("buyer", [])
        authority = ""
        if isinstance(buyers, list) and buyers:
            authority = buyers[0].get("name", "")
        elif isinstance(buyers, dict):
            authority = buyers.get("name", "")

        # URL
        url = NOTICE_URL.format(notice_id=notice_id) if notice_id else ""

        # Date
        date = hit.get("publicationDate", "") or hit.get("issueDate", "")
        if date and "T" in date:
            date = date[:10]

        # Value
        value = hit.get("estimatedValue")
        if isinstance(value, dict):
            value = value.get("amount") or value.get("value")
        try:
            value = float(value) if value else None
        except (TypeError, ValueError):
            value = None

        # Snippet with key metadata for filtering
        status = hit.get("status", "")
        notice_type = hit.get("type", "")
        desc = (hit.get("description") or "")[:200]
        snippet = f"type={notice_type} status={status} auth={authority}\n{desc}"

        return SearchResult(
            title=str(title)[:200],
            url=url,
            authority=str(authority)[:150],
            date=str(date)[:10] if date else "",
            value=value,
            currency="NOK",
            reference_id=str(notice_id)[:60],
            snippet=snippet[:400],
        )

    def _detail_from_search_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            date=result.date,
            value=result.value,
            reference_id=result.reference_id,
            source_code="NO-DF",
            currency="NOK",
            raw_text=result.snippet or "",
        )

    # ── Text extraction helpers ──

    def _find_title(self, text: str) -> str:
        m = re.search(r"(?:Tittel|Subject|Title|Heading)[:\s]+([^\n]{10,200})", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _find_authority(self, text: str) -> str:
        for pat in [
            r"(?:Oppdragsgiver|Kjøper|Contracting authority)[:\s]+([^\n]{5,120})",
            r"(?:Organisasjon|Organisation|Buyer)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        for auth in self.config.defence_authorities:
            if auth.lower() in text.lower():
                return auth
        return ""

    def _find_date(self, text: str) -> str:
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        return m2.group(1) if m2 else ""

    def _find_ref_id(self, text: str) -> str:
        for pat in [
            r"(?:Doffin|Referanse|Reference)[:\s\-#]+([A-Z0-9\-/]{4,40})",
            r"(\d{4}-\d+)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _find_description(self, text: str) -> str:
        for pat in [
            r"(?:Beskrivelse|Kontraktsbeskrivelse|Description)[:\s]+(.{30,500}?)(?:\n\n|$)",
            r"(?:Kort beskrivelse)[:\s]+(.{30,400}?)(?:\n\n|$)",
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                lines = [l.strip() for l in m.group(1).split("\n") if l.strip()]
                return " ".join(lines[:3])[:400]
        return ""

    def _find_quantity(self, text: str) -> Optional[int]:
        for pat in [
            r"(\d[\d\s]*)\s*(?:stk|stykk|enheter|tilhengere|kjøretøy)",
            r"(?:Antall|Mengde|Quantity)[:\s]+(\d[\d\s]*)",
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
        for pat in [
            r"(?:Estimert verdi|Kontraktsverdi|Estimated value)[^\d]{0,20}([\d\s.,]+)\s*(?:NOK|kr\.?)",
            r"NOK\s+([\d\s.,]+)",
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
        for pat in [
            r"(?:Tildelt|Vinner|Leverandør|Winner|Award)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if not re.match(r"^[\d\s.,]+$", name):
                    return name[:120]
        return ""

    def _find_duration(self, text: str) -> str:
        for pat in [
            r"(?:Varighet|Kontraktslengde|Duration)[:\s]+([^\n]{3,80})",
            r"(\d+)\s*(?:måneder|uker|år|dager)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:80]
        return ""

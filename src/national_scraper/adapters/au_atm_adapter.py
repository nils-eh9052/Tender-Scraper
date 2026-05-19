"""
Australia Adapter — AusTender Approaches to Market (ATM, pre-award only)

Portal: https://www.tenders.gov.au
RSS:    https://www.tenders.gov.au/public_data/rss/rss.xml  (~500 current ATMs)
Detail: https://www.tenders.gov.au/Atm/Show/{uuid}

NOT covered:
  - Post-award Contract Notices (api.tenders.gov.au OCDS — separate adapter)
  - Closed / awarded ATMs (historical search requires session auth)

AusTender is ASP.NET server-rendered HTML — no JS execution needed.
Uses requests.Session with SSL verification controlled by SSL_VERIFY_DISABLE env.

Validated 2026-05-10:
  RSS 200 OK, 56 KB, "AusTender Current ATM List", ~500 items
  Detail 200 OK, 90 KB, all field labels present as flat text after tag-stripping
  OCDS API (api.tenders.gov.au): post-award Contract Notices only — not used here

Field extraction after HTML tag-stripping (single-line space-separated text):
  ATM ID      : GA2026/564
  Agency      : Geoscience Australia
  Category    : 81150000 - Earth science services   ← UNSPSC segment 25 = vehicles/military
  Close Date & Time : 11-May-2026 10:00 am (ACT Local Time)
  Publish Date: 1-Apr-2026
  Description : <free text>
"""

from __future__ import annotations

import html as _html
import logging
import os
import re
import time
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BASE_URL   = "https://www.tenders.gov.au"
RSS_URL    = "https://www.tenders.gov.au/public_data/rss/rss.xml"
DETAIL_URL = "https://www.tenders.gov.au/Atm/Show/{atm_uuid}"

# Australian Defence buyers — agency name substrings that signal defence procurement
DEFENCE_BUYERS: list[str] = [
    "Department of Defence",
    "Dept of Defence",
    "CASG",
    "Capability Acquisition and Sustainment Group",
    "Australian Signals Directorate",
    "ASD",
    "Joint Logistics Command",
    "JLC",
    "Royal Australian Air Force",
    "RAAF",
    "Royal Australian Navy",
    "RAN",
    "Australian Army",
    "Australian Defence Force",
    "ADF",
    "Defence Housing Australia",
    "Defence Science and Technology Group",
    "DST Group",
    "Defence Materiel Organisation",
]

# UNSPSC segment codes that indicate relevance to BPW
# Segment 25 = Vehicles/Military Equipment/Weapons; 20 = Mining/Logistics
DEFENCE_UNSPSC_SEGMENTS: set[str] = {"25", "20"}

# Trailer and related vehicle keywords for pre-filter and filter_defence
TRAILER_KEYWORDS: list[str] = [
    "trailer",
    "semi-trailer",
    "semitrailer",
    "semi trailer",
    "flatbed",
    "flat bed",
    "flat-bed",
    "low loader",
    "low-loader",
    "lowloader",
    "low bed",
    "low-bed",
    "lowbed",
    "cargo trailer",
    "tank trailer",
    "fuel trailer",
    "ammunition trailer",
    "field kitchen",
    "prime mover",
    "LAND 121",
    "LAND121",
    "army trailer",
    "defence trailer",
    "towed vehicle",
    "towed equipment",
    "logistics vehicle",
    "logistic vehicle",
    "military trailer",
    "military vehicle",
    "load carrier",
]


def create_au_atm_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Australia",
        country_code="AU",
        source_code="AU-AT",
        base_url=BASE_URL,
        search_url=RSS_URL,
        language="en",
        trailer_keywords=TRAILER_KEYWORDS,
        defence_authorities=DEFENCE_BUYERS,
        min_interval_seconds=1.0,
    )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _parse_rfc2822_date(date_str: str) -> str:
    """Convert RFC 2822 → ISO YYYY-MM-DD: 'Wed, 01 Apr 2026 00:00:00 GMT' → '2026-04-01'."""
    try:
        import email.utils
        parsed = email.utils.parsedate(date_str)
        if parsed:
            return f"{parsed[0]:04d}-{parsed[1]:02d}-{parsed[2]:02d}"
    except Exception:
        pass
    return ""


_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _parse_austender_date(date_str: str) -> str:
    """Convert AusTender date formats to ISO YYYY-MM-DD.

    Handles:
      '11-May-2026 10:00 am'   → '2026-05-11'
      '1-Apr-2026'             → '2026-04-01'
      '01 Apr 2026'            → '2026-04-01'
    """
    s = date_str.strip()
    # Take just the date portion (before any space with a time-like segment)
    date_part = s.split()[0] if s else ""

    # "11-May-2026" or "1-Apr-2026"
    m = re.match(r'^(\d{1,2})-([A-Za-z]{3})-(\d{4})$', date_part)
    if m:
        d, mon, y = m.groups()
        return f"{y}-{_MONTHS.get(mon.lower(), '00')}-{d.zfill(2)}"

    # "01 Apr 2026" or "1 Apr 2026" (space-separated in full string)
    m2 = re.match(r'^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$', s)
    if m2:
        d, mon, y = m2.groups()
        return f"{y}-{_MONTHS.get(mon.lower(), '00')}-{d.zfill(2)}"

    return ""


def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities; collapse whitespace."""
    raw = _html.unescape(raw)
    raw = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
    raw = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL)
    raw = re.sub(r'<[^>]+>', ' ', raw)
    return re.sub(r'\s+', ' ', raw).strip()


def _extract_field(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_unspsc(text: str) -> str:
    """Return first 8-digit UNSPSC code found after a 'Category' label."""
    m = re.search(r'Category\s*:\s*(\d{8})', text, re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_description(text: str) -> str:
    """Extract the Description block from stripped ATM detail text."""
    m = re.search(
        r'Description\s*:\s*(.+?)(?=Other Instructions|Conditions for Participation'
        r'|Timeframe for Delivery|Address for Lodgement|Addenda Available'
        r'|Contact Details|Return to top|$)',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return re.sub(r'\s+', ' ', m.group(1)).strip()[:500]
    return ""


# ── Adapter ────────────────────────────────────────────────────────────────────

class AuAtmAdapter(BaseAdapter):
    """
    Australia adapter — AusTender Approaches to Market (pre-award only).

    Search strategy:
      1. Fetch RSS feed once for all currently open ATMs (~500 items)
      2. Pre-filter by any trailer/defence keyword in title + RSS description
      3. Fetch detail pages for matched items (agency, UNSPSC, deadline, raw_text)

    Defence filter (OR logic):
      - Agency name matches DEFENCE_BUYERS whitelist
      - UNSPSC category segment = 25 (vehicles/military equipment)
      - Title/description contains a TRAILER_KEYWORDS match
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()
        self._rss_cache: Optional[list[SearchResult]] = None

    # ── Session ──────────────────────────────────────────────────────────────

    def _build_session(self):
        try:
            import requests
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            logger.error("AU: 'requests' not installed")
            return None

        import requests as req_mod
        session = req_mod.Session()
        session.verify = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in (
            "1", "true", "yes"
        )
        # CloudFront in front of tenders.gov.au returns 403 for non-browser UAs
        # (verified 2026-05-18: bot-style UAs blocked, Mozilla UAs pass).
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-AU,en;q=0.9",
        })
        return session

    # ── RSS ──────────────────────────────────────────────────────────────────

    def _fetch_rss(self) -> list[SearchResult]:
        """Fetch and parse the AusTender RSS feed; result is cached per instance."""
        if self._rss_cache is not None:
            return self._rss_cache

        if not self._session:
            return []

        try:
            resp = self._session.get(RSS_URL, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"AU RSS: HTTP {resp.status_code}")
                return []
            xml_text = resp.text
        except Exception as e:
            logger.error(f"AU RSS fetch error: {e}")
            return []

        results: list[SearchResult] = []
        for m in re.finditer(r'<item>(.*?)</item>', xml_text, re.DOTALL):
            r = self._parse_rss_item(m.group(1))
            if r:
                results.append(r)

        logger.info(f"AU RSS: parsed {len(results)} ATM items")
        self._rss_cache = results
        return results

    def _parse_rss_item(self, item_xml: str) -> Optional[SearchResult]:
        """Convert a raw RSS <item> block to SearchResult."""
        title_m = re.search(r'<title>(.*?)</title>', item_xml, re.DOTALL)
        link_m  = re.search(r'<link>(.*?)</link>',   item_xml, re.DOTALL)
        desc_m  = re.search(r'<description>(.*?)</description>', item_xml, re.DOTALL)
        date_m  = re.search(r'<pubDate>(.*?)</pubDate>', item_xml, re.DOTALL)

        if not title_m or not link_m:
            return None

        raw_title = _html.unescape(title_m.group(1).strip())
        url = link_m.group(1).strip()

        # Title format: "GA2026/564: Panel Refresh - Hazard Extent ..."
        ref_id = ""
        title = raw_title
        colon_pos = raw_title.find(': ')
        if colon_pos > 0:
            ref_id = raw_title[:colon_pos].strip()
            title  = raw_title[colon_pos + 2:].strip()

        snippet = ""
        if desc_m:
            snippet = _strip_html(desc_m.group(1).strip())[:400]

        date = _parse_rfc2822_date(date_m.group(1).strip()) if date_m else ""

        return SearchResult(
            title=title[:200],
            url=url,
            authority="",       # populated in get_detail()
            date=date,
            reference_id=ref_id[:60],
            snippet=snippet,
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list[SearchResult]:
        """Fetch RSS and pre-filter by keyword in title + RSS description."""
        logger.info(f"AU: search '{keyword}'")
        items = self._fetch_rss()
        kw = keyword.lower()
        matched = [
            r for r in items
            if kw in r.title.lower() or kw in r.snippet.lower()
        ]
        logger.info(f"AU: '{keyword}' → {len(matched)} of {len(items)} RSS items")
        return matched[:max_results]

    def search_all_keywords(
        self,
        max_results_per_keyword: int = 100,
        test_mode: bool = False,
    ) -> list[SearchResult]:
        """
        Fetch all current ATMs from RSS, pre-filter by any keyword or defence
        authority name, then enrich each match via detail page (agency, UNSPSC).

        Returns deduplicated SearchResult list with authority populated.
        """
        items = self._fetch_rss()

        keywords    = self.config.trailer_keywords
        authorities = self.config.defence_authorities
        if test_mode:
            keywords    = keywords[:3]
            authorities = authorities[:3]

        matched_keys: dict[str, SearchResult] = {}

        for r in items:
            combined = f"{r.title} {r.snippet}".lower()
            # Require a trailer keyword — authority-only matches lead to irrelevant records
            is_kw_match = any(kw.lower() in combined for kw in keywords)
            if is_kw_match:
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in matched_keys:
                    matched_keys[key] = r

        pre_filtered = list(matched_keys.values())
        logger.info(
            f"AU: RSS pre-filter: {len(items)} items → {len(pre_filtered)} matched"
        )

        limit = min(len(pre_filtered), max_results_per_keyword)
        enriched: list[SearchResult] = []

        for i, r in enumerate(pre_filtered[:limit]):
            detail = self.get_detail(r)
            if detail:
                r.authority = detail.authority or r.authority
                unspsc = _extract_unspsc(detail.raw_text or "")
                if unspsc:
                    r.snippet = f"unspsc={unspsc} {r.snippet}"
            enriched.append(r)
            if i < limit - 1:
                time.sleep(self.config.min_interval_seconds)

        logger.info(f"AU: search_all_keywords → {len(enriched)} enriched results")
        return enriched

    def filter_defence(self, results: list) -> list:
        """
        Keep a result only when it has an explicit trailer/vehicle keyword match
        AND at least one of: defence authority, UNSPSC segment 25, or trailer keyword
        in title+description.

        Trailer keyword is REQUIRED — a defence agency buying building services
        or IT panels is not relevant to BPW.
        """
        kept = []
        for r in results:
            combined = " ".join([
                (r.authority or "").lower(),
                (r.title    or "").lower(),
                (r.snippet  or "").lower(),
            ])

            has_trailer_kw = any(kw.lower() in combined for kw in self.config.trailer_keywords)

            # Gate: trailer keyword is mandatory — no trailer mention, no relevance
            if not has_trailer_kw:
                continue

            kept.append(r)

        logger.info(f"AU: filter_defence: {len(results)} → {len(kept)}")
        return kept

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch ATM detail page and extract all structured fields."""
        if not result.url or not self._session:
            return None

        logger.info(f"AU: detail fetch: {result.url[:80]}")

        try:
            resp = self._session.get(result.url, timeout=25)
            if resp.status_code != 200:
                logger.warning(f"AU detail: HTTP {resp.status_code}")
                return None
            raw_html = resp.text
        except Exception as e:
            logger.warning(f"AU detail fetch error: {e}")
            return None

        page_text = _strip_html(raw_html)

        atm_id   = _extract_field(page_text, r'ATM\s+ID\s*:\s*(\S+)')
        agency   = _extract_field(page_text, r'Agency\s*:\s*(.*?)\s*(?=Category\s*:)')
        unspsc   = _extract_unspsc(page_text)
        close_raw = _extract_field(page_text, r'Close Date\s*(?:&amp;|&)?\s*Time\s*:\s*(\d+\-[A-Za-z]+\-\d+)')
        pub_raw  = _extract_field(page_text, r'Publish Date\s*:\s*(\d+\-[A-Za-z]+\-\d+)')
        desc     = _extract_description(page_text)

        deadline = _parse_austender_date(close_raw) if close_raw else ""
        pub_iso  = _parse_austender_date(pub_raw)   if pub_raw   else ""

        raw_text = page_text[:15000]
        if unspsc:
            raw_text = f"UNSPSC: {unspsc}\n" + raw_text

        return NoticeDetail(
            title=result.title,
            description=desc,
            authority=agency[:150] if agency else "",
            date=pub_iso or result.date,
            deadline=deadline,
            reference_id=atm_id or result.reference_id or "",
            url=result.url,
            source_code="AU-AT",
            raw_text=raw_text,
            currency="AUD",
            status="Open",  # RSS only surfaces currently open ATMs
        )

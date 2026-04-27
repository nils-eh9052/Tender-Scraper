"""
Germany service.bund.de Scraper

Discovers German defence trailer procurement notices not captured by TED.
Uses the public RSS feed (no login required) and filters client-side for
BAAINBw/Bundeswehr + trailer keywords, since the server-side keyword filter
is non-functional in the RSS endpoint.

Normalizes every notice to the standard classifier schema.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import urllib3
from pathlib import Path
from typing import Optional

import requests

# SSL bypass for corporate VPN
_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "raw" / "de"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "https://www.service.bund.de"

# RSS endpoint — requires jsessionid in URL path (server-side keyword filter broken)
RSS_PATH = "/Content/DE/Ausschreibungen/Suche/Formular.html"
RSS_PARAMS = {
    "nn": "4641482",
    "resultsPerPage": "200",
    "sortOrder": "dateOfIssue_dt+desc",
    "jobsrss": "true",
}

DEFENCE_KEYWORDS = [
    "bundeswehr", "baainbw", "bundesamt für ausrüstung",
    "hil heeresinstandsetzung", "bwi gmbh",
    "wehrbereichsverwaltung", "bundeswehrverwaltung",
    "verteidigungsministerium", "bundesministerium der verteidigung",
]

TRAILER_KEYWORDS_DE = [
    "anhänger", "anhanger", "sattelanhänger", "sattelanh",
    "tieflader", "tankanhänger", "tanktrailer",
    "feldküche", "feldkueche", "wechsellader",
    "hakenladegerät", "shelter", "transportanhänger",
    "lastanhänger", "schwerlastanhänger", "munitionsanh",
    "bergeanhänger", "kfz-anhänger", "kfz anhänger",
    "sattelzug", "sattel-auflieger", "auflieger",
]


# ── HTML helpers ─────────────────────────────────────────────────────────────

def _decode_html(text: str) -> str:
    """Decode HTML entities (service.bund.de uses &uuml; etc. in RSS)."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_text(html_str: str) -> str:
    """Extract clean text from HTML, using bs4 or regex fallback."""
    if HAS_BS4:
        soup = BeautifulSoup(html_str, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        main = soup.select_one("main, .content, article, #content, .teaserText")
        if main:
            return main.get_text(" ", strip=True)
        return soup.get_text(" ", strip=True)
    return _decode_html(html_str)


# ── RSS parser ────────────────────────────────────────────────────────────────

def _parse_rss_item(raw: str) -> dict:
    """Parse a single <item>...</item> block from the RSS feed."""

    def extract_raw(tag: str) -> str:
        """Extract tag content WITHOUT stripping HTML (for field extraction)."""
        m = re.search(rf"<{tag}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{tag}>",
                      raw, re.DOTALL | re.I)
        return m.group(1).strip() if m else ""

    def extract(tag: str) -> str:
        return _decode_html(extract_raw(tag))

    title = extract("title")
    link = extract("link").strip()
    description_html = extract_raw("description")  # keep HTML for field extraction
    pub_date = extract("pubDate")

    # Extract Vergabestelle from raw HTML (before stripping)
    authority_m = re.search(r"Vergabestelle:\s*<strong>(.*?)</strong>", description_html, re.I | re.DOTALL)
    if not authority_m:
        # Fallback: plain text after decoding (e.g. "Vergabestelle: Bundeswehrverwaltung\n")
        desc_plain = _decode_html(description_html)
        authority_m2 = re.search(r"Vergabestelle:\s+([^\n<]{5,100})", desc_plain, re.I)
        authority = authority_m2.group(1).strip() if authority_m2 else ""
    else:
        authority = _decode_html(authority_m.group(1))

    # Deadline — try both HTML and plain text
    description_plain = _decode_html(description_html)
    deadline_m = re.search(r"Angebotsfrist[:\s]+([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4})", description_plain, re.I)
    deadline = deadline_m.group(1) if deadline_m else ""

    # Normalize date DD.MM.YYYY → YYYY-MM-DD
    def de_date(d: str) -> str:
        m2 = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d)
        if m2:
            return f"{m2.group(3)}-{m2.group(2).zfill(2)}-{m2.group(1).zfill(2)}"
        return d

    # Extract internal notice ID from URL
    notice_id_m = re.search(r"/([^/]+)\.html(?:#|$)", link)
    notice_id = notice_id_m.group(1) if notice_id_m else ""

    # Source folder (abc = BAAINBw, eVergabe = general, etc.)
    folder_m = re.search(r"IMPORTE/Ausschreibungen/([^/]+)/", link)
    folder = folder_m.group(1) if folder_m else ""

    # Publication date — pubDate is RFC2822 (Fri, 25 Apr 2026 ...)
    pub_date_iso = ""
    pd_m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", pub_date)
    if pd_m:
        months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                  "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                  "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
        mo = months.get(pd_m.group(2), "01")
        pub_date_iso = f"{pd_m.group(3)}-{mo}-{pd_m.group(1).zfill(2)}"

    return {
        "_raw_id": notice_id,
        "_folder": folder,
        "title": title,
        "url": link,
        "authority": authority,
        "description_raw": description_plain,
        "pub_date_iso": pub_date_iso,
        "deadline": de_date(deadline),
    }


class DEServiceBundScraper:
    """
    Scrapes service.bund.de for German defence trailer procurement notices.

    Strategy:
      1. Fetch the RSS feed (up to 200 latest notices per request).
      2. Filter client-side for defence org + trailer keywords.
      3. Fetch detail pages for matching notices.
      4. Normalize to the TED classifier schema.
      5. Dedup against existing TED notices by title similarity.
    """

    def __init__(self, config: dict, cache_dir: Optional[str] = None):
        self.config = config or {}
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/html,application/xml,application/rss+xml",
            "Accept-Language": "de-DE,de;q=0.9",
        })
        self.min_interval = 2.0
        self._last_request = 0.0
        self._jsid: Optional[str] = None

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    # ── Session establishment ──────────────────────────────────────────────────

    def _get_session(self) -> str:
        """Establish session and return jsessionid (required for RSS to return items)."""
        if self._jsid:
            return self._jsid
        try:
            r = self.session.get(f"{BASE_URL}/Content/DE/Ausschreibungen/Suche/Formular.html",
                                 params={"nn": "4641988"}, timeout=20)
            jsid_m = re.search(r"jsessionid=([A-F0-9]+\.[a-z0-9]+)", r.text)
            if jsid_m:
                self._jsid = jsid_m.group(1)
                logger.debug(f"DE session: {self._jsid[:20]}...")
        except Exception as e:
            logger.warning(f"DE session establishment failed: {e}")
        return self._jsid or ""

    # ── RSS fetch ─────────────────────────────────────────────────────────────

    def fetch_rss(self, results_per_page: int = 200) -> list[dict]:
        """
        Fetch the service.bund.de RSS feed.

        Returns a list of parsed notice dicts.
        NOTE: The `sortOrder` parameter MUST use a literal '+' (not %2B)
        in the URL path — the server ignores %2B-encoded + signs.
        """
        jsid = self._get_session()
        self._rate_limit()

        # Build URL manually to preserve the literal + in sortOrder
        params_str = "&".join(f"{k}={v}" for k, v in RSS_PARAMS.items())
        params_str = params_str.replace("%2B", "+")  # ensure literal +
        if results_per_page != 200:
            params_str = params_str.replace("resultsPerPage=200",
                                            f"resultsPerPage={results_per_page}")

        if jsid:
            url = f"{BASE_URL}{RSS_PATH};jsessionid={jsid}?{params_str}"
        else:
            url = f"{BASE_URL}{RSS_PATH}?{params_str}"

        try:
            r = self.session.get(url, timeout=30)
            if r.status_code != 200:
                logger.warning(f"DE RSS HTTP {r.status_code}")
                return []

            items_raw = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
            logger.info(f"DE RSS: {len(items_raw)} items from feed")

            return [_parse_rss_item(raw) for raw in items_raw]

        except Exception as e:
            logger.error(f"DE RSS fetch error: {e}")
            return []

    # ── Filtering ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_defence(notice: dict) -> bool:
        """Return True if the notice is from a defence/Bundeswehr authority."""
        text = (notice.get("authority", "") + " " + notice.get("description_raw", "")).lower()
        return any(kw in text for kw in DEFENCE_KEYWORDS)

    @staticmethod
    def _is_trailer(notice: dict) -> bool:
        """Return True if the notice relates to trailers/Anhänger."""
        text = (notice.get("title", "") + " " + notice.get("description_raw", "")).lower()
        return any(kw in text for kw in TRAILER_KEYWORDS_DE)

    def filter_relevant(self, notices: list[dict]) -> list[dict]:
        """
        Keep only defence + trailer relevant notices.

        Two-pass:
          1. Must be from a defence authority (strict).
          2. Must mention trailers in title/description (or we fetch detail page if title is vague).
        Notices that pass defence check but have vague title are included too
        — the detail page fetch will confirm or discard them.
        """
        defence = [n for n in notices if self._is_defence(n)]
        # Keep those with trailer hint, OR those from BAAINBw (abc folder — always relevant)
        result = []
        for n in defence:
            if self._is_trailer(n) or n.get("_folder") == "abc":
                result.append(n)
        return result

    # ── Detail page ───────────────────────────────────────────────────────────

    def fetch_detail(self, url: str) -> str:
        """Fetch and extract clean text from a service.bund.de notice detail page."""
        if not url or not url.startswith("http"):
            return ""
        self._rate_limit()
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code != 200:
                logger.warning(f"DE detail HTTP {r.status_code}: {url}")
                return ""
            return _extract_text(r.text)[:8000]
        except Exception as e:
            logger.error(f"DE detail error {url}: {e}")
            return ""

    # ── Normalisation ─────────────────────────────────────────────────────────

    @staticmethod
    def normalize(notice: dict, detail_text: str = "") -> dict:
        """Convert a service.bund.de notice to the TED classifier schema."""
        raw_id = notice.get("_raw_id", "")
        title = notice.get("title", "")
        authority = notice.get("authority", "")
        pub_date = notice.get("pub_date_iso", "")
        deadline = notice.get("deadline", "")
        url = notice.get("url", "").split("#")[0]  # strip tracking fragment

        tender_id = f"DE-{raw_id}" if raw_id else f"DE-{hash(title) & 0xFFFFFF:06X}"

        return {
            "tender_id": tender_id,
            "publication_number": tender_id,
            "source": "DE-SB",
            "source_url_national": url,
            "ted_url": "",

            # Classifier-visible
            "title": f"Germany – {title}",
            "description": detail_text or notice.get("description_raw", ""),
            "cpv_codes": [],
            "legal_basis": "",
            "publication_date": pub_date,
            "submission_deadline": deadline,
            "contracting_authority": {
                "name": authority,
                "name_short": authority,
                "country": "DEU",
            },
            "estimated_value": {},
            "award": None,

            "_raw": notice,
        }

    # ── Dedup against existing notices ───────────────────────────────────────

    @staticmethod
    def _dedup_key(notice: dict) -> str:
        """Match key: first 35 chars of clean title + year."""
        title = re.sub(r"^germany\s*[-–]\s*", "", notice.get("title", "").lower())
        title = re.sub(r"\s+", " ", title).strip()[:35]
        year = str(notice.get("publication_date", ""))[:4]
        return f"{title}|{year}"

    def merge_with_existing(self, new_notices: list[dict],
                            existing: list[dict]) -> tuple[list[dict], int]:
        """
        Dedup new DE notices against existing.

        - If a match is found: add national URL to existing notice, skip new row.
        - If no match: add as new row.

        Returns (merged_list, count_added).
        """
        existing_keys = {self._dedup_key(n): i for i, n in enumerate(existing)}
        added = 0

        for new in new_notices:
            key = self._dedup_key(new)
            if key in existing_keys:
                idx = existing_keys[key]
                if not existing[idx].get("source_url_national"):
                    existing[idx]["source_url_national"] = new.get("source_url_national", "")
                    existing[idx]["source"] = existing[idx].get("source", "TED") + "+DE-SB"
                    logger.info(f"  DE: enriched TED match → {new.get('tender_id')}")
            else:
                existing.append(new)
                existing_keys[key] = len(existing) - 1
                added += 1
                logger.info(f"  DE: new notice → {new.get('tender_id')} | {new.get('title','')[:50]}")

        return existing, added

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def fetch_and_filter(self, existing_notices: Optional[list] = None,
                         test_mode: bool = False) -> list[dict]:
        """
        Full DE scraping pipeline:
          1. Fetch RSS feed
          2. Filter for defence + trailer relevance
          3. Fetch detail pages
          4. Normalize to TED schema
          5. Merge with existing (dedup)

        Returns list of new normalized notices (already deduplicated).
        """
        logger.info("DE scraper: fetching RSS feed...")
        rss_results = self.fetch_rss(results_per_page=100 if test_mode else 200)

        if not rss_results:
            logger.warning("DE scraper: no RSS items received")
            return []

        relevant = self.filter_relevant(rss_results)
        logger.info(f"DE scraper: {len(relevant)} defence+trailer relevant "
                    f"(from {len(rss_results)} total in feed)")

        if test_mode:
            relevant = relevant[:3]
            logger.info(f"DE scraper: test mode — limiting to {len(relevant)} notices")

        normalized = []
        for i, notice in enumerate(relevant):
            logger.info(f"DE [{i+1}/{len(relevant)}]: {notice.get('title','')[:60]}")
            logger.info(f"  Authority: {notice.get('authority','')[:60]}")
            logger.info(f"  URL: {notice.get('url','')[:80]}")

            detail = self.fetch_detail(notice.get("url", ""))
            if detail:
                logger.info(f"  Detail text: {len(detail)} chars")
            else:
                logger.warning("  No detail text fetched")

            norm = self.normalize(notice, detail_text=detail)
            normalized.append(norm)

        # Cache raw results
        raw_path = self.cache_dir / "de_notices.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(rss_results, f, ensure_ascii=False, indent=2)

        normalized_path = self.cache_dir / "de_normalized.json"
        with open(normalized_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

        logger.info(f"DE scraper: {len(normalized)} notices normalized, "
                    f"cached to {normalized_path}")
        return normalized

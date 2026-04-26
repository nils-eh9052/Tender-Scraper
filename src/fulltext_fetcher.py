"""
Phase 3c (Stufe 1): Fulltext Fetcher

Downloads the full HTML text of TED notices for notices that need enrichment
(missing value, quantity, or winner). Caches results in data/raw/fulltext/.

Prefer English HTML, fallback to German/French.
Extract clean text with BeautifulSoup (or regex fallback).
Truncate at 15000 chars.
Rate-limit: respect config's requests_per_second.
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

# Corporate VPN / self-signed proxy: set SSL_VERIFY_DISABLE=1 in .env to bypass
_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

FULLTEXT_DIR = Path(__file__).parent.parent / "data" / "raw" / "fulltext"
FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)

MAX_CHARS = 15000
LANG_PRIORITY = ["ENG", "eng", "en", "DEU", "deu", "de", "FRA", "fra", "fr"]

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.warning("BeautifulSoup not installed – using regex HTML stripping fallback")


def _strip_html_regex(html: str) -> str:
    """Fallback: strip HTML tags with regex."""
    # Remove script/style blocks
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    html = re.sub(r'<[^>]+>', ' ', html)
    # Collapse whitespace
    html = re.sub(r'\s+', ' ', html)
    return html.strip()


def _extract_clean_text(html: str) -> str:
    """Extract clean text from HTML, stripping nav/header/footer/script/style."""
    if HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        # Remove noise elements
        for tag in soup.find_all(["nav", "header", "footer", "script", "style",
                                   "noscript", "aside", "form", "button"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
    else:
        text = _strip_html_regex(html)
    # Collapse excess whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:MAX_CHARS]


class FulltextFetcher:
    """Downloads and caches full notice text from TED website."""

    TED_NOTICE_URL = "https://ted.europa.eu/en/notice/{notice_id}/texts"

    def __init__(self, config: dict):
        self.config = config
        api_cfg = config.get("api", {})
        self.min_interval = 1.0 / api_cfg.get("requests_per_second", 1)
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            "User-Agent": "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)"
        })

    def _rate_limit(self):
        now = time.time()
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    def _get_cache_path(self, notice_id: str) -> Path:
        safe_id = notice_id.replace("/", "_").replace("\\", "_")
        return FULLTEXT_DIR / f"{safe_id}.txt"

    def is_cached(self, notice_id: str) -> bool:
        return self._get_cache_path(notice_id).exists()

    def load_cached(self, notice_id: str) -> Optional[str]:
        path = self._get_cache_path(notice_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _save_cache(self, notice_id: str, text: str):
        path = self._get_cache_path(notice_id)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _pick_url(link_value) -> Optional[str]:
        """Extract a usable URL from a TED link field.

        TED v3 stores links as language-keyed dicts:
            {"ENG": "https://...", "DEU": "https://...", ...}
        Prefer ENG, then DEU/FRA, else take first available.
        """
        if isinstance(link_value, str) and link_value.startswith("http"):
            return link_value
        if isinstance(link_value, dict):
            for lang in LANG_PRIORITY:
                if link_value.get(lang, "").startswith("http"):
                    return link_value[lang]
            # Fallback: first value
            for v in link_value.values():
                if isinstance(v, str) and v.startswith("http"):
                    return v
        return None

    def fetch(self, notice_id: str, links: Optional[dict] = None) -> Optional[str]:
        """Fetch fulltext for a notice. Returns cached version if available.

        Strategy (in order):
          1. Return cached text if already on disk.
          2. Use `links["htmlDirect"]` from the notice detail (if provided) — ENG preferred.
          3. Fall back to constructed URL: TED_NOTICE_URL.format(notice_id=notice_id).

        HTTP 202 from /texts endpoint = async rendering (old endpoint), skip.
        """
        cached = self.load_cached(notice_id)
        if cached is not None:
            return cached

        self._rate_limit()

        # Build URL candidate list
        url_candidates: list[str] = []
        if links:
            for link_key in ("htmlDirect", "html"):
                url = self._pick_url(links.get(link_key))
                if url:
                    url_candidates.append(url)
        # Always add constructed fallback
        url_candidates.append(self.TED_NOTICE_URL.format(notice_id=notice_id))

        for url in url_candidates:
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    text = _extract_clean_text(resp.text)
                    if len(text) > 100:
                        self._save_cache(notice_id, text)
                        logger.debug(f"Fetched fulltext for {notice_id}: {len(text)} chars via {url}")
                        return text
                    logger.warning(f"Fulltext for {notice_id} too short ({len(text)} chars)")
                elif resp.status_code == 202:
                    # Async rendering — skip this URL, try next
                    logger.debug(f"Fulltext {notice_id}: HTTP 202 (async), trying next URL")
                else:
                    logger.warning(f"Fulltext fetch failed for {notice_id}: HTTP {resp.status_code}")
            except requests.RequestException as e:
                logger.error(f"Fulltext fetch error for {notice_id}: {e}")

        return None

    @staticmethod
    def needs_enrichment(notice: dict) -> bool:
        """
        Returns True if the notice is missing value, quantity, or winner.
        These are candidates for fulltext enrichment.
        """
        # Missing winner
        award = notice.get("award") or {}
        if not award.get("winner_name"):
            return True

        # Missing value
        val = notice.get("estimated_value") or {}
        amount = val.get("amount")
        if not amount or float(str(amount).replace(",", "") or 0) <= 0.01:
            return True

        # Missing AI quantity
        if notice.get("_trailer_quantity_ai") is None:
            return True

        return False

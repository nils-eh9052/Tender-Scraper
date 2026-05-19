"""
Document downloader — fetches a DocumentRef URL and caches the file locally.

Cache layout: data/documents/{safe_tender_id}/{sha1}.{ext}

Features:
- SHA1-based dedup: same content is stored once regardless of URL
- Rate-limiting: min 1s between requests
- SSL_VERIFY_DISABLE support
- Retries (3×) with exponential backoff
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

from .discovery import DocumentRef

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")

DOCS_DIR = Path(__file__).parent.parent.parent / "data" / "documents"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*",
}

_MIN_INTERVAL = 1.0  # seconds between requests
_last_request: float = 0.0


def _rate_limit() -> None:
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = time.time()


def _safe_name(tender_id: str) -> str:
    """Make tender_id safe for use as a directory name."""
    return re.sub(r"[^\w\-]", "_", tender_id)[:80]


def download_document(ref: DocumentRef, force: bool = False) -> Optional[Path]:
    """Download a document and return its local cache path.

    Returns None if download fails or content is too small (e.g. auth redirect).
    """
    safe_dir = DOCS_DIR / _safe_name(ref.tender_id)
    safe_dir.mkdir(parents=True, exist_ok=True)

    # Check if we already have a file for this URL (URL-hash pointer file)
    url_hash = hashlib.sha1(ref.url.encode()).hexdigest()[:12]
    pointer_path = safe_dir / f".ptr_{url_hash}"
    if not force and pointer_path.exists():
        cached_path = Path(pointer_path.read_text().strip())
        if cached_path.exists():
            logger.debug(f"Downloader: cache hit for {ref.tender_id} / {url_hash}")
            return cached_path

    _rate_limit()

    content: Optional[bytes] = None
    for attempt in range(3):
        try:
            resp = requests.get(
                ref.url,
                headers=_HEADERS,
                timeout=60,
                verify=_SSL_VERIFY,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning(f"Downloader: HTTP {resp.status_code} for {ref.url[:80]}")
                return None
            content = resp.content
            break
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"Downloader: attempt {attempt+1} failed ({e}), retry in {wait}s")
            time.sleep(wait)

    if not content:
        return None

    # Reject suspiciously small responses (auth-redirect HTML, error pages)
    if len(content) < 2048:
        snippet = content[:200].decode("utf-8", errors="replace")
        logger.warning(f"Downloader: response too small ({len(content)}B) for {ref.url[:60]} — likely auth block. Snippet: {snippet[:80]}")
        return None

    # SHA1 of content for dedup
    sha1 = hashlib.sha1(content).hexdigest()[:16]
    file_path = safe_dir / f"{sha1}.{ref.format}"

    if not file_path.exists():
        file_path.write_bytes(content)
        logger.info(f"Downloader: saved {file_path.name} ({len(content)//1024}KB) for {ref.tender_id}")

    # Write pointer
    pointer_path.write_text(str(file_path))
    return file_path

"""
Resilience utilities for national scraper HTTP requests.

Provides:
  - ROTATING_USER_AGENTS: pool of desktop browser UAs
  - RetrySession: requests.Session with automatic exponential-backoff retry
  - retry_request: standalone helper for one-off resilient GET calls
"""

import logging
import os
import random
import time
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

ROTATING_USER_AGENTS = [
    # Chrome/Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36",
    # Firefox/Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Chrome/macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari/macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Edge/Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class RetrySession:
    """
    requests.Session wrapper with automatic exponential-backoff retry.

    Retries on:
      - Connection errors / timeouts
      - HTTP status codes in _RETRY_STATUS_CODES (429, 5xx)

    Usage:
        session = RetrySession(max_retries=3, backoff_base=2.0)
        resp = session.get(url, params=..., timeout=30)
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        rotate_ua: bool = True,
        verify_ssl: Optional[bool] = None,
    ):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.rotate_ua = rotate_ua

        if verify_ssl is None:
            ssl_env = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
            verify_ssl = ssl_env not in ("1", "true", "yes")
        self._verify = verify_ssl

        self._session = requests.Session()
        self._session.verify = self._verify
        self._set_ua()

    def _set_ua(self):
        ua = random.choice(ROTATING_USER_AGENTS) if self.rotate_ua else ROTATING_USER_AGENTS[0]
        self._session.headers.update({"User-Agent": ua})

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = self.backoff_base ** attempt + random.uniform(0, 1)
                logger.info(f"Retry {attempt}/{self.max_retries} for {url} in {delay:.1f}s")
                time.sleep(delay)
                if self.rotate_ua:
                    self._set_ua()

            try:
                resp = self._session.request(method, url, **kwargs)
                if resp.status_code in _RETRY_STATUS_CODES and attempt < self.max_retries:
                    logger.warning(
                        f"HTTP {resp.status_code} on {url} — will retry "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    last_exc = requests.HTTPError(
                        f"HTTP {resp.status_code}", response=resp
                    )
                    continue
                return resp
            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                logger.warning(
                    f"Request error on {url}: {exc} "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )

        # All retries exhausted — raise last exception
        if last_exc:
            raise last_exc
        raise requests.exceptions.RequestException(f"All retries failed for {url}")

    def update_headers(self, headers: dict):
        self._session.headers.update(headers)

    def close(self):
        self._session.close()

    # Context manager support
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def retry_request(
    url: str,
    params: Optional[dict] = None,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    session: Optional[requests.Session] = None,
) -> Optional[requests.Response]:
    """
    One-off resilient GET with exponential backoff.

    Returns the Response on success, None on permanent failure (all retries exhausted).
    Caller is responsible for checking resp.status_code.
    """
    _session = session or requests.Session()
    ssl_env = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
    _session.verify = ssl_env not in ("1", "true", "yes")

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            delay = backoff_base ** attempt + random.uniform(0, 0.5)
            logger.info(f"retry_request attempt {attempt}/{max_retries} for {url} in {delay:.1f}s")
            time.sleep(delay)

        try:
            resp = _session.get(url, params=params, timeout=timeout)
            if resp.status_code in _RETRY_STATUS_CODES and attempt < max_retries:
                last_exc = requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                continue
            return resp
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            logger.warning(f"retry_request error on {url}: {exc}")

    logger.error(f"retry_request: all {max_retries} retries failed for {url}: {last_exc}")
    return None

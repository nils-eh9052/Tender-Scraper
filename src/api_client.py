"""
TED API Client – Handles all communication with the TED Europa API.

Uses the public Search API at api.ted.europa.eu/v3 (no API key required).
The Search API returns structured notice data directly when fields are specified.

Supports:
- Expert search queries with classification-cpv, legal-basis, date ranges
- Automatic pagination (PAGE_NUMBER mode, max 15k results)
- Iteration mode for unlimited results (via iterationNextToken)
- Rate limiting & exponential backoff
"""

import time
import json
import logging
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# All fields we request — used for both index and detail phases (merged).
# No need for separate index/detail requests: the search API returns
# everything in one go, making Phase 2 unnecessary.
ALL_FIELDS = [
    "notice-identifier",
    "publication-number",
    "notice-title",
    "publication-date",
    "buyer-name",
    "organisation-country-buyer",
    "classification-cpv",
    "legal-basis",
    "total-value",
    "total-value-cur",
    "description-lot",
    "description-proc",
    "description-part",
    "title-lot",
    "title-proc",
    "contract-title",
    "winner-name",
    "winner-country",
    "winner-identifier",
    "winner-decision-date",
    "winner-size",
    "deadline-receipt-tender-date-lot",
    "legal-basis-proc",
    "legal-basis-notice",
    "place-of-performance-post-code-part",
    "identifier-part",
    "announcement-title",
    # Sprint 14b: notice lifecycle fields — enables Tier-1b status resolution
    "notice-type",
    "form-type",
    "procedure-type",
    # Sprint 2026-05-09 (TED-XML §B): cross-reference + lot breakdown.
    # Discovered empirically via scripts/_probe_ted_fields_v2.py. See
    # docs/TED_FIELDS_DISCOVERED.md.
    "buyer-internet-address",            # Foreign-key to buyer's procurement portal
    "estimated-value-lot",               # Per-lot value breakdown (closes total-value aggregation gap)
    "quantity-lot",                      # Per-lot quantity — direct source for _trailer_quantity_*_ai
    "procedure-features",                # Multilingual procedure description
    "place-of-performance-city-part",
    "place-of-performance-country-part",
    "deadline-receipt-tender-time-lot",  # Time-component for deadline (pairs with date-lot)
    "internal-identifier-part",          # Internal organisation reference
    # Sprint 2026-05-18 (TED Quick-Wins): structured eForms fields validated by
    # scripts/_probe_ted_fields_v3.py. See docs/TED_DEEP_RESEARCH_260517.md §2.2.
    "framework-agreement-lot",           # eForms code: fa-wo-rc / fa-w-rc / fa-mix / none.
                                         # Direct source for contract_type (100% coverage in eForms,
                                         # replaces fragile regex on description text).
    "contract-conclusion-date",          # Real award/signature date (≠ publication-date of the CAN).
                                         # Populated on CAN-standard notices; ~17% coverage in probe,
                                         # expected to grow as award-matching catches up.
    "organisation-name-buyer",           # Multilingual dict of buyer names — richer than the legacy
                                         # buyer-name field (which is a flat string).
    "organisation-identifier-buyer",     # Buyer registration identifier (e.g. DE "991-19518-88").
                                         # Stable foreign-key for buyer-profile aggregation across
                                         # multiple notices from the same authority.
]

# Backwards compatibility aliases
INDEX_FIELDS = ALL_FIELDS
DETAIL_FIELDS = ALL_FIELDS


class TedApiClient:
    """Client for the TED (Tenders Electronic Daily) Search API."""

    SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"

    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)"
        })

        # Rate limiting
        api_cfg = config.get("api", {})
        self.min_interval = 1.0 / api_cfg.get("requests_per_second", 2)
        self.max_retries = api_cfg.get("max_retries", 3)
        self.backoff_factor = api_cfg.get("retry_backoff_factor", 2)
        self.timeout = api_cfg.get("timeout_seconds", 30)
        self.page_size = min(api_cfg.get("page_size", 100), 250)  # API max is 250
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce minimum interval between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_time = time.time()

    def _request_with_retry(self, method: str, url: str,
                            params: Optional[dict] = None,
                            json_body: Optional[dict] = None) -> Optional[dict]:
        """Make HTTP request with rate limiting and exponential backoff."""
        for attempt in range(self.max_retries + 1):
            self._rate_limit()
            try:
                if method == "GET":
                    resp = self.session.get(url, params=params, timeout=self.timeout)
                elif method == "POST":
                    resp = self.session.post(url, json=json_body, timeout=self.timeout)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    wait = self.backoff_factor ** (attempt + 1)
                    logger.warning(f"Rate limited (429). Waiting {wait}s... (attempt {attempt+1})")
                    time.sleep(wait)
                    continue
                elif resp.status_code == 400:
                    # Bad request – log the error detail and don't retry
                    try:
                        err = resp.json()
                        logger.error(f"Bad request (400): {err.get('message', resp.text[:300])}")
                    except Exception:
                        logger.error(f"Bad request (400): {resp.text[:300]}")
                    return None
                elif resp.status_code == 404:
                    logger.warning(f"Not found (404): {url}")
                    return None
                else:
                    logger.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    if attempt < self.max_retries:
                        wait = self.backoff_factor ** attempt
                        time.sleep(wait)
                    continue

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout for {url} (attempt {attempt+1})")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** attempt)
            except requests.exceptions.ConnectionError as e:
                logger.error(f"Connection error: {e}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor ** (attempt + 1))

        logger.error(f"All {self.max_retries + 1} attempts failed for {url}")
        return None

    # ──────────────────────────────────────────────
    # Query Builder
    # ──────────────────────────────────────────────

    def build_query(self, cpv_codes: list[str] = None,
                    legal_basis: Optional[str] = None,
                    date_from: Optional[str] = None,
                    date_to: Optional[str] = None,
                    text_query: Optional[str] = None,
                    fields: Optional[list[str]] = None) -> dict:
        """
        Build a search query payload for the TED Search API.

        Uses the TED expert query syntax:
        - classification-cpv="34223000"
        - legal-basis="32009L0081"
        - publication-date>=2024-01-01
        """
        query_parts = []

        # CPV code filter
        if cpv_codes:
            cpv_filter = " OR ".join([f'classification-cpv="{code}"' for code in cpv_codes])
            query_parts.append(f"({cpv_filter})")

        # Legal basis filter
        if legal_basis:
            query_parts.append(f'legal-basis="{legal_basis}"')

        # Date range – API requires YYYYMMDD format (no dashes)
        if date_from:
            d = date_from.replace("-", "")
            query_parts.append(f"publication-date>={d}")
        if date_to:
            d = date_to.replace("-", "")
            query_parts.append(f"publication-date<={d}")

        # Free text
        if text_query:
            query_parts.append(f"({text_query})")

        full_query = " AND ".join(query_parts) if query_parts else "*"

        return {
            "query": full_query,
            "fields": fields or ALL_FIELDS,
            "page": 1,
            "limit": self.page_size,
            "paginationMode": "PAGE_NUMBER",
        }

    # ──────────────────────────────────────────────
    # Search Methods
    # ──────────────────────────────────────────────

    def search(self, query_payload: dict, page: int = 1) -> Optional[dict]:
        """
        Execute a search query against TED.

        Returns raw API response with notices and totalNoticeCount.
        """
        payload = query_payload.copy()
        payload["page"] = page

        logger.info(f"Searching TED: page {page}, query: {payload.get('query', '')[:100]}...")
        return self._request_with_retry("POST", self.SEARCH_URL, json_body=payload)

    def search_all_pages(self, query_payload: dict,
                         max_pages: Optional[int] = None,
                         checkpoint_callback=None) -> list[dict]:
        """
        Fetch ALL results for a query, handling pagination.

        Uses PAGE_NUMBER mode (max 15,000 results).
        For larger datasets, use search_with_iteration().

        Args:
            query_payload: The search query
            max_pages: Optional limit on pages to fetch
            checkpoint_callback: Called with (page, results) after each page

        Returns:
            List of all notice objects
        """
        all_results = []
        page = 1
        total_pages = None

        while True:
            response = self.search(query_payload, page=page)
            if not response:
                logger.error(f"Search failed at page {page}")
                break

            notices = response.get("notices", [])
            total = response.get("totalNoticeCount", 0)

            if total_pages is None:
                total_pages = (total + self.page_size - 1) // self.page_size
                logger.info(f"Total results: {total}, pages: {total_pages}")

            all_results.extend(notices)

            if checkpoint_callback:
                checkpoint_callback(page, all_results)

            logger.info(f"Page {page}/{total_pages}: fetched {len(notices)} "
                        f"(total so far: {len(all_results)})")

            # Check if we're done
            if len(notices) < self.page_size:
                break
            if max_pages and page >= max_pages:
                logger.info(f"Reached max_pages limit ({max_pages})")
                break
            if total_pages and page >= total_pages:
                break

            page += 1

        return all_results

    def search_with_iteration(self, query_payload: dict,
                              max_iterations: Optional[int] = None,
                              checkpoint_callback=None) -> list[dict]:
        """
        Fetch results using ITERATION mode (unlimited, uses tokens).

        Use this when PAGE_NUMBER mode's 15k limit is not enough.
        """
        payload = query_payload.copy()
        payload["paginationMode"] = "ITERATION"
        payload.pop("page", None)  # not used in iteration mode

        all_results = []
        iteration = 0
        next_token = None

        while True:
            if next_token:
                payload["iterationNextToken"] = next_token

            response = self._request_with_retry("POST", self.SEARCH_URL, json_body=payload)
            if not response:
                logger.error(f"Iteration search failed at step {iteration}")
                break

            notices = response.get("notices", [])
            total = response.get("totalNoticeCount", 0)
            next_token = response.get("iterationNextToken")

            all_results.extend(notices)
            iteration += 1

            if iteration == 1:
                logger.info(f"Total matching notices: {total}")

            logger.info(f"Iteration {iteration}: fetched {len(notices)} "
                        f"(total so far: {len(all_results)})")

            if checkpoint_callback:
                checkpoint_callback(iteration, all_results)

            # Check if we're done
            if not notices or not next_token:
                break
            if max_iterations and iteration >= max_iterations:
                logger.info(f"Reached max_iterations limit ({max_iterations})")
                break

        return all_results

    # ──────────────────────────────────────────────
    # Detail Methods
    # ──────────────────────────────────────────────

    def get_notice_detail(self, publication_number: str) -> Optional[dict]:
        """
        Fetch full detail for a single notice by re-querying the search API
        with all detail fields.

        The TED detail endpoint (GET /v3/notices/{id}) requires authentication,
        so we use the search API with a specific publication-number query instead.
        """
        payload = {
            "query": f'publication-number="{publication_number}"',
            "fields": DETAIL_FIELDS,
            "page": 1,
            "limit": 1,
            "paginationMode": "PAGE_NUMBER",
        }

        logger.debug(f"Fetching detail: {publication_number}")
        response = self._request_with_retry("POST", self.SEARCH_URL, json_body=payload)

        if response and response.get("notices"):
            return response["notices"][0]
        return None

    def get_notice_details_batch(self, publication_numbers: list[str],
                                  checkpoint_callback=None,
                                  skip_existing: Optional[set] = None) -> dict[str, dict]:
        """
        Fetch details for multiple notices with progress tracking.
        """
        results = {}
        skip = skip_existing or set()
        total = len(publication_numbers)

        for i, pub_num in enumerate(publication_numbers):
            if pub_num in skip:
                logger.debug(f"Skipping {pub_num} (already fetched)")
                continue

            detail = self.get_notice_detail(pub_num)
            if detail:
                results[pub_num] = detail

            if checkpoint_callback:
                checkpoint_callback(i, pub_num, detail)

            if (i + 1) % 50 == 0:
                logger.info(f"Detail progress: {i+1}/{total} "
                            f"({len(results)} successful)")

        return results

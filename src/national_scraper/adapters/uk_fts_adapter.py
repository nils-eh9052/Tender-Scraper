"""
UK Find a Tender Service (FTS) Adapter

OCDS-conformant REST API, free, no authentication required.
Covers UK government contracts above the threshold (≈£139K post-Brexit).
Complements UK Contracts Finder, which focuses on SME-accessible notices.

API: https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages
Pagination: follow links.next URL returned in each response.
No keyword/buyer filter in the API — we paginate and filter client-side.

Strategy:
  Pull notices updated within the configured window (default: last 180 days),
  filter for defence buyers + trailer keywords, cap at max_pages requests.
  Results are cached in data/raw/uk_fts/ to support incremental runs.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

logger = logging.getLogger(__name__)
urllib3.disable_warnings()

FTS_API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
CACHE_DIR = Path("data/raw/uk_fts")

_DEFENCE_BUYER_KW = {
    "ministry of defence",
    "defence equipment and support",
    "de&s",
    "defence infrastructure organisation",
    "dstl",
    "defence science and technology laboratory",
    "royal navy",
    "british army",
    "royal air force",
    "mod ",
    "joint forces command",
    "strategic command",
    "defence nuclear organisation",
    "army headquarters",
    "navy command",
    "air command",
    "submarine delivery agency",
}

_TRAILER_KW = {
    "trailer", "semi-trailer", "semitrailer", "low-bed", "low loader",
    "tank trailer", "fuel tanker", "hook lift", "container trailer",
    "flatbed trailer", "military trailer", "ammunition trailer",
    "field kitchen", "shelter trailer", "epls", "drops",
    "palletised load", "heavy equipment transporter", "het",
    "cargo trailer", "logistics vehicle", "mission module",
    "recovery trailer", "load carrier",
}


def create_uk_fts_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="United Kingdom",
        country_code="GB",
        source_code="UK-FTS",
        base_url="https://www.find-tender.service.gov.uk",
        search_url=FTS_API,
        language="en",
        trailer_keywords=sorted(_TRAILER_KW),
        defence_authorities=[
            "Ministry of Defence",
            "Defence Equipment and Support",
            "DE&S",
            "Defence Infrastructure Organisation",
            "DSTL",
            "Royal Navy",
            "British Army",
            "Royal Air Force",
        ],
        min_interval_seconds=1.5,
    )


def _is_defence_buyer(buyer_name: str) -> bool:
    low = buyer_name.lower()
    return any(kw in low for kw in _DEFENCE_BUYER_KW)


def _has_trailer_kw(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _TRAILER_KW)


class UKFTSAdapter(BaseAdapter):
    """
    UK Find a Tender Service — OCDS REST API.

    The API has no search/filter parameters beyond date ranges; we must
    paginate through all notices and filter for defence + trailer relevance
    client-side.  We cap at max_pages to bound runtime.
    """

    def __init__(self, browser, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=True)
        self._session.update_headers({"Accept": "application/json"})
        self._last_request = 0.0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _wait(self):
        elapsed = time.time() - self._last_request
        gap = self.config.min_interval_seconds
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_request = time.time()

    def search(self, keyword: str, max_results: int = 200) -> list[SearchResult]:
        """
        'keyword' is ignored — FTS API has no keyword filter.
        Instead we paginate through recent defence notices and filter locally.
        Call search_all_keywords() once to get the full set.
        """
        return []  # actual work done in search_all_keywords

    def search_all_keywords(
        self,
        max_results_per_keyword: int = 200,
        test_mode: bool = False,
    ) -> list[SearchResult]:
        """
        Paginate FTS releases updated in the last N days, filter for
        defence + trailer relevance, return deduplicated SearchResults.
        """
        from datetime import datetime, timedelta

        days_back = 7 if test_mode else 365
        since = (datetime.utcnow() - timedelta(days=days_back)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        max_pages = 3 if test_mode else 200
        page_size = 10  # keep small to avoid VPN timeouts

        logger.info(
            f"UK-FTS: fetching notices since {since[:10]}, "
            f"max {max_pages} pages × {page_size}"
        )

        results: dict[str, SearchResult] = {}
        url: Optional[str] = None
        params = {"limit": page_size, "updatedFrom": since}
        pages = 0
        consecutive_errors = 0
        max_consecutive_errors = 5

        while pages < max_pages:
            self._wait()
            try:
                if url:
                    resp = self._session.get(url, timeout=60)
                else:
                    resp = self._session.get(FTS_API, params=params, timeout=60)

                if resp.status_code != 200:
                    logger.warning(f"UK-FTS HTTP {resp.status_code}: {resp.text[:200]}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error("UK-FTS: too many consecutive errors, stopping")
                        break
                    time.sleep(5)
                    continue

                consecutive_errors = 0
                data = resp.json()
                releases = data.get("releases", [])
                if not releases:
                    break

                for r in releases:
                    tender = r.get("tender", {})
                    buyer = r.get("buyer", {})
                    buyer_name = buyer.get("name", "")

                    if not _is_defence_buyer(buyer_name):
                        continue

                    title = tender.get("title", "") or ""
                    desc = tender.get("description", "") or ""

                    if not _has_trailer_kw(title + " " + desc):
                        continue

                    ref_id = r.get("id", "") or r.get("ocid", "")
                    if not ref_id:
                        continue

                    safe_id = re.sub(r"[^\w\-]", "_", ref_id)
                    notice_url = (
                        f"https://www.find-tender.service.gov.uk/Notice/{safe_id}"
                    )
                    val_block = tender.get("value", {}) or {}

                    sr = SearchResult(
                        title=title,
                        url=notice_url,
                        authority=buyer_name,
                        date=(r.get("date", "") or "")[:10],
                        value=val_block.get("amount"),
                        currency=val_block.get("currency", "GBP"),
                        reference_id=ref_id,
                        snippet=desc[:200],
                    )
                    results[ref_id] = sr

                pages += 1
                links = data.get("links", {}) or {}
                url = links.get("next")
                if not url:
                    break

                logger.info(
                    f"UK-FTS page {pages}: {len(releases)} releases scanned, "
                    f"{len(results)} defence+trailer so far"
                )

            except requests.exceptions.Timeout:
                consecutive_errors += 1
                logger.warning(
                    f"UK-FTS timeout on page {pages + 1} "
                    f"(consecutive errors: {consecutive_errors}/{max_consecutive_errors})"
                )
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("UK-FTS: too many consecutive timeouts, stopping")
                    break
                time.sleep(10 * consecutive_errors)
                # Don't advance page counter — retry same page
                continue
            except Exception as exc:
                consecutive_errors += 1
                logger.error(f"UK-FTS error on page {pages + 1}: {exc}")
                if consecutive_errors >= max_consecutive_errors:
                    break
                time.sleep(5)
                continue

        logger.info(f"UK-FTS: {len(results)} defence trailer notices from {pages} pages")
        return list(results.values())

    def filter_defence(self, results: list) -> list:
        """Already filtered during search_all_keywords — pass through."""
        return results

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Fetch full OCDS release for a single notice."""
        if not result.reference_id:
            return None

        # Check cache
        cache_file = CACHE_DIR / f"{re.sub(r'[^\\w\\-]', '_', result.reference_id)}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_bytes())
                return self._parse_release(data, result)
            except Exception:
                pass

        self._wait()
        try:
            # Single-release endpoint: filter by ocid
            resp = self._session.get(
                FTS_API,
                params={"ocid": result.reference_id, "limit": 1},
                timeout=45,
            )
            if resp.status_code != 200:
                logger.warning(f"UK-FTS detail HTTP {resp.status_code} for {result.reference_id}")
                return None

            data = resp.json()
            cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return self._parse_release(data, result)

        except Exception as exc:
            logger.error(f"UK-FTS detail error for {result.reference_id}: {exc}")
            # Return minimal detail from SearchResult
            return NoticeDetail(
                title=result.title,
                authority=result.authority,
                date=result.date,
                value=result.value,
                currency=result.currency,
                reference_id=result.reference_id,
                url=result.url,
                source_code="UK-FTS",
                raw_text=result.snippet,
            )

    def _parse_release(self, data: dict, result: SearchResult) -> NoticeDetail:
        """Extract NoticeDetail from an OCDS release package."""
        releases = data.get("releases", [])
        release = releases[0] if releases else {}

        tender = release.get("tender", {}) or {}
        buyer = release.get("buyer", {}) or {}
        awards = release.get("awards", []) or []

        winner = ""
        for award in awards:
            suppliers = award.get("suppliers", []) or []
            if suppliers:
                winner = suppliers[0].get("name", "")
                break

        val = tender.get("value", {}) or {}
        qty = None
        for item in tender.get("items", []) or []:
            if item.get("quantity"):
                try:
                    qty = int(item["quantity"])
                except (ValueError, TypeError):
                    pass
                break

        raw_text = tender.get("description", "") or ""
        for item in tender.get("items", []) or []:
            raw_text += "\n" + (item.get("description", "") or "")

        return NoticeDetail(
            title=tender.get("title", result.title) or result.title,
            description=(tender.get("description", "") or "")[:500],
            authority=buyer.get("name", result.authority) or result.authority,
            date=(release.get("date", result.date) or result.date)[:10],
            value=val.get("amount", result.value),
            currency=val.get("currency", result.currency) or "GBP",
            quantity=qty,
            winner=winner,
            reference_id=result.reference_id,
            url=result.url,
            source_code="UK-FTS",
            raw_text=raw_text[:2000],
        )

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        """Convert NoticeDetail to the pipeline's standard notice dict."""
        safe_id = re.sub(r"[^\w\-]", "_", detail.reference_id or "")
        fx = {"GBP": 1.17, "EUR": 1.0, "USD": 0.93}
        eur = None
        if detail.value:
            rate = fx.get(detail.currency or "GBP", 1.17)
            eur = round(detail.value * rate, 2)

        return {
            "tender_id": f"UK-FTS-{safe_id}",
            "source": "UK-FTS",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "United Kingdom",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": detail.currency or "GBP",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or detail.raw_text[:500],
            "_national_raw_text": detail.raw_text,
            "_trailer_quantity_1": detail.quantity,
            "_raw": {"source": "UK-FTS", "url": detail.url},
            "estimated_value": (
                {"amount": detail.value, "currency": detail.currency or "GBP"}
                if detail.value else None
            ),
            "award": (
                {"winner_name": detail.winner, "awarded": True}
                if detail.winner else None
            ),
        }

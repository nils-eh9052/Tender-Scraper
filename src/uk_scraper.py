"""
UK Contracts Finder Scraper

Public API, no authentication required.
Searches for defence trailer tenders from UK MoD and related organizations.

Normalizes every notice to the SAME schema the TED classifier expects
(title, description, contracting_authority, cpv_codes, estimated_value,
award, publication_date, submission_deadline, ted_url, _raw) so that
`src.classifier.AiClassifier.classify_batch()` can process UK and TED
notices in a single pass without modification.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib3
from pathlib import Path
from typing import Optional

import requests

# Corporate VPN / self-signed proxy: set SSL_VERIFY_DISABLE=1 in .env to bypass
_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class UKContractsFinderScraper:
    """Scrapes UK Contracts Finder API for defence trailer tenders."""

    # REST search endpoint — POST with {searchCriteria: {keyword, dateFromPublished}}
    # The OCDS "/Published/Notices/OCDS/Search" endpoint is a paginated feed that
    # IGNORES keyword params; REST is the only way to do server-side keyword search.
    SEARCH_URL = "https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices/json"

    # UK Defence organizations — a notice must mention one of these in buyer/party
    DEFENCE_ORGS = [
        "ministry of defence",
        "defence equipment and support",
        "defence infrastructure organisation",
        "defence science and technology laboratory",
        "de&s",
        "dstl",
        "royal navy",
        "british army",
        "royal air force",
        "raf ",
        "mod ",
        "uk hydrographic office",
    ]

    # Trailer-related search terms
    SEARCH_TERMS = [
        "trailer",
        "semi-trailer",
        "semitrailer",
        "low-bed",
        "low loader",
        "tank trailer",
        "fuel tanker trailer",
        "hook lift",
        "container trailer",
        "flatbed trailer",
        "military trailer",
        "ammunition trailer",
        "field kitchen",
        "shelter trailer",
        "mission module",
    ]

    def __init__(self, config: dict, cache_dir: str = "data/raw/uk"):
        self.config = config or {}
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TED-Defence-Trailer-Research/1.0",
        })
        self.min_interval = 1.0  # 1 req/sec to be polite
        self._last_request = 0.0

    # ------------------------------------------------------------------ #
    # HTTP plumbing                                                      #
    # ------------------------------------------------------------------ #

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    def _post(self, body: dict) -> Optional[dict]:
        """Single POST with simple retry/backoff."""
        self._rate_limit()
        for attempt in range(3):
            try:
                resp = self.session.post(self.SEARCH_URL, json=body, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 503):
                    wait = 2 * (attempt + 1)
                    logger.warning(f"Contracts Finder {resp.status_code}, waiting {wait}s")
                    time.sleep(wait)
                    continue
                logger.warning(f"Contracts Finder HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            except Exception as e:
                logger.error(f"Contracts Finder request failed (attempt {attempt+1}): {e}")
                time.sleep(2 * (attempt + 1))
        return None

    # ------------------------------------------------------------------ #
    # Search                                                             #
    # ------------------------------------------------------------------ #

    def search(self, query: str, published_from: str = "2015-01-01",
               published_to: Optional[str] = None,
               max_results: int = 500) -> list[dict]:
        """Search Contracts Finder for notices matching query.

        Returns a list of flat notice dicts (the `item` payload inside
        each `noticeList` entry, with a `_score` field added from the wrapper).
        """
        all_results: list[dict] = []
        page = 1
        page_size = 100

        while len(all_results) < max_results:
            body = {
                "searchCriteria": {
                    "keyword": query,
                    "dateFromPublished": published_from,
                },
                "size": min(page_size, max_results - len(all_results)),
                "page": page,
            }
            if published_to:
                body["searchCriteria"]["dateToPublished"] = published_to

            data = self._post(body)
            if not data:
                break

            # REST format: {"hitCount": N, "noticeList": [{"score": ..., "item": {...}}]}
            raw_list = data.get("noticeList") or data.get("results") or []
            if not raw_list:
                break

            page_items: list[dict] = []
            for entry in raw_list:
                if isinstance(entry, dict) and isinstance(entry.get("item"), dict):
                    it = dict(entry["item"])
                    it["_score"] = entry.get("score")
                    page_items.append(it)
                elif isinstance(entry, dict):
                    page_items.append(entry)

            all_results.extend(page_items)
            logger.info(f"UK search '{query}' page {page}: {len(page_items)} "
                        f"results (hitCount={data.get('hitCount', '?')})")

            if len(page_items) < body["size"]:
                break
            page += 1

        return all_results

    def search_all_terms(self, published_from: str = "2015-01-01",
                         max_terms: Optional[int] = None,
                         max_per_term: int = 500) -> list[dict]:
        """Run all search terms and deduplicate results."""
        all_notices: dict[str, dict] = {}
        terms = self.SEARCH_TERMS[:max_terms] if max_terms else self.SEARCH_TERMS

        for term in terms:
            results = self.search(term, published_from=published_from,
                                   max_results=max_per_term)
            for notice in results:
                notice_id = self._extract_id(notice)
                if notice_id and notice_id not in all_notices:
                    all_notices[notice_id] = notice
            logger.info(f"After '{term}': {len(all_notices)} unique notices total")

        logger.info(f"UK search complete: {len(all_notices)} unique notices")
        return list(all_notices.values())

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_id(notice: dict) -> Optional[str]:
        """Extract unique notice ID (REST flat or OCDS nested)."""
        if not isinstance(notice, dict):
            return None
        # REST flat: noticeIdentifier / id ; OCDS nested: tender.id / ocid
        tender = notice.get("tender") or {}
        tid = (
            notice.get("noticeIdentifier")
            or notice.get("id")
            or notice.get("ocid")
            or tender.get("id")
            or notice.get("noticeId")
        )
        if tid is None:
            tags = notice.get("tag")
            if isinstance(tags, list) and tags:
                tid = tags[0]
        return str(tid) if tid else None

    @staticmethod
    def _extract_buyer_names(notice: dict) -> list[str]:
        """All organisation names that could represent the buyer."""
        names: list[str] = []
        # REST flat schema
        for k in ("organisationName", "issuedBy", "contractingAuthority"):
            v = notice.get(k)
            if isinstance(v, str) and v:
                names.append(v)
            elif isinstance(v, dict) and v.get("name"):
                names.append(v["name"])
        # OCDS nested schema
        buyer = notice.get("buyer") or {}
        if isinstance(buyer, dict) and buyer.get("name"):
            names.append(buyer["name"])
        for p in notice.get("parties") or []:
            if not isinstance(p, dict):
                continue
            roles = [str(r).lower() for r in (p.get("roles") or [])]
            if "buyer" in roles or "procuringEntity" in roles:
                if p.get("name"):
                    names.append(p["name"])
        return names

    # Title/description patterns that indicate non-operational trailer use
    # (sport/training/university — pass defence org filter but irrelevant for market intel)
    UK_TITLE_BLACKLIST = [
        "paddle sport", "canoe", "kayak",               # Sports equipment trailers
        "cadet force", "combined cadet",                 # Cadet units (not operational)
        "university air squadron",                        # University units
        "driver training", "driving training",            # Driving school trailers
        "defence school of transport",                    # DST training fleet
        "draw-bar trailer.*contract hire",                # Hire trailers for training
        "lawn mower", "grounds maintenance",              # Groundskeeping
        "bicycle", "cycling",                             # Cycle transport
    ]

    def is_defence_relevant(self, notice: dict) -> bool:
        """Check if notice is from a defence organization."""
        for name in self._extract_buyer_names(notice):
            name_lower = str(name).lower()
            for defence_org in self.DEFENCE_ORGS:
                if defence_org in name_lower:
                    return True
        return False

    def is_relevant_trailer(self, notice: dict) -> bool:
        """Additional filter: reject training/sports/university trailer notices.

        Called after is_defence_relevant() to remove notices that pass the
        defence-org check but are not relevant for defence trailer market intel.
        """
        import re
        title = str(notice.get("title") or "").lower()
        description = str(notice.get("description") or "").lower()
        combined = f"{title} {description}"
        for pattern in self.UK_TITLE_BLACKLIST:
            if re.search(pattern, combined):
                return False
        return True

    # ------------------------------------------------------------------ #
    # Normalisation to TED-classifier schema                             #
    # ------------------------------------------------------------------ #

    # Hard-coded FX → EUR (matches exporter's FX_RATES_TO_EUR)
    _GBP_TO_EUR = 1.17

    def normalize_to_ted_format(self, notice: dict) -> dict:
        """
        Convert UK Contracts Finder notice to the schema that
        src/classifier.py and src/exporter.py expect.

        The classifier reads:
          - title (str or {lang: str})
          - description (str or {lang: str})
          - cpv_codes (list)
          - contracting_authority: {name, country, name_short}
          - estimated_value: {amount, currency}
          - award: {winner_name} or None
          - publication_date, submission_deadline, tender_id, ted_url
        """
        tender = notice.get("tender") or {}
        buyer_names = self._extract_buyer_names(notice)
        primary_buyer = buyer_names[0] if buyer_names else ""

        notice_id = self._extract_id(notice) or ""

        # REST flat schema keys first, then OCDS nested fallback
        title = (
            notice.get("title")
            or tender.get("title")
            or notice.get("noticeTitle")
            or ""
        )
        description = (
            notice.get("description")
            or tender.get("description")
            or notice.get("summary")
            or ""
        )

        # Value — REST uses valueLow/valueHigh/awardedValue; OCDS uses tender.value
        ocds_value = tender.get("value") or notice.get("value") or {}
        raw_amount = (
            ocds_value.get("amount")
            if isinstance(ocds_value, dict) else None
        )
        if raw_amount in (None, "", 0):
            # Prefer awardedValue, else valueHigh, else valueLow
            raw_amount = (
                notice.get("awardedValue")
                or notice.get("valueHigh")
                or notice.get("valueLow")
            )
        currency = (ocds_value.get("currency") if isinstance(ocds_value, dict) else None) or "GBP"
        try:
            amount = float(raw_amount) if raw_amount not in (None, "", 0) else None
        except (TypeError, ValueError):
            amount = None

        # Dates
        pub_date = (
            notice.get("publishedDate")
            or notice.get("date")
            or notice.get("publicationDate")
            or ""
        )
        deadline = (
            notice.get("deadlineDate")
            or (tender.get("tenderPeriod") or {}).get("endDate", "")
            or ""
        )

        # Award / winner — REST has awardedSupplier (string), OCDS has awards[].suppliers[].name
        winner_name = notice.get("awardedSupplier") or None
        if not winner_name:
            for a in notice.get("awards") or []:
                for s in a.get("suppliers") or []:
                    if s.get("name"):
                        winner_name = s["name"]
                        break
                if winner_name:
                    break

        # CPV — REST gives `cpvCodes` (space-separated); OCDS uses tender.items[].classification
        cpv_codes: list[str] = []
        cpv_raw = notice.get("cpvCodes")
        if isinstance(cpv_raw, str) and cpv_raw.strip():
            cpv_codes.extend([c for c in cpv_raw.split() if c])
        cpv_ext = notice.get("cpvCodesExtended")
        if isinstance(cpv_ext, str) and cpv_ext.strip():
            for c in cpv_ext.split():
                if c and c not in cpv_codes:
                    cpv_codes.append(c)
        for cls in tender.get("items", []) or []:
            c = cls.get("classification") or {}
            if c.get("scheme", "").upper() == "CPV" and c.get("id"):
                cpv_codes.append(str(c["id"]))
            for add in cls.get("additionalClassifications", []) or []:
                if add.get("scheme", "").upper() == "CPV" and add.get("id"):
                    cpv_codes.append(str(add["id"]))

        # URL: REST provides GUID in `id` (good for /Notice/<guid>),
        # noticeIdentifier is the human-readable reference. Prefer GUID for URL.
        guid = notice.get("id") or notice_id
        normalized: dict = {
            "tender_id": f"UK-{notice_id}" if notice_id else "",
            "publication_number": f"UK-{notice_id}" if notice_id else "",
            "ted_url": "",  # no TED URL for UK-only tenders
            "source": "UK-CF",
            "source_url_national": (
                f"https://www.contractsfinder.service.gov.uk/Notice/{guid}"
                if guid else ""
            ),

            # Classifier-visible fields
            "title": title,
            "description": description,
            "cpv_codes": cpv_codes,
            "legal_basis": "",
            "publication_date": pub_date,
            "submission_deadline": deadline,
            "contracting_authority": {
                "name": primary_buyer,
                "name_short": primary_buyer,
                "country": "GBR",
            },
            "estimated_value": (
                {"amount": amount, "currency": currency} if amount is not None
                else {}
            ),
            "award": ({"winner_name": winner_name} if winner_name else None),

            # Keep the full OCDS payload for debugging / future re-parse
            "_raw": notice,
        }
        return normalized

    # ------------------------------------------------------------------ #
    # Full pipeline                                                      #
    # ------------------------------------------------------------------ #

    def fetch_and_filter(self, published_from: str = "2015-01-01",
                         test_mode: bool = False) -> list[dict]:
        """
        Full UK scraping pipeline:
          1. Search all terms
          2. Filter for defence relevance
          3. Normalize to TED classifier schema
          4. Cache raw + normalized outputs
        """
        if test_mode:
            # In test mode: only first 2 terms, 20 results each -> <=40 candidates
            raw_results = self.search_all_terms(
                published_from=published_from,
                max_terms=2,
                max_per_term=20,
            )
        else:
            raw_results = self.search_all_terms(published_from=published_from)

        logger.info(f"UK raw results: {len(raw_results)}")

        # Cache raw
        raw_path = self.cache_dir / "uk_raw.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw_results, f, ensure_ascii=False, indent=2)

        # Filter: defence org AND relevant trailer (not training/sports/university)
        defence = [
            n for n in raw_results
            if self.is_defence_relevant(n) and self.is_relevant_trailer(n)
        ]
        logger.info(f"UK defence-relevant (after org + relevance filter): {len(defence)}")

        # Normalize
        normalized = [self.normalize_to_ted_format(n) for n in defence]

        # Cache normalized
        norm_path = self.cache_dir / "uk_notices.json"
        with open(norm_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

        logger.info(f"UK pipeline complete: {len(normalized)} normalized "
                    f"notices saved to {norm_path}")
        return normalized

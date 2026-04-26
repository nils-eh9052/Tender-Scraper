"""
Poland Adapter — eZamowienia REST API (mo-board/api/v1/Board/Search)

Strategy:
1. Call the public REST API at ezamowienia.gov.pl (no auth required, no CAPTCHA)
2. Filter by trailer-related CPV codes (34223300, 34220000, etc.)
   AND by defence/military organisation name keywords
3. Combine, deduplicate, return SearchResult objects
4. For detail pages: use the Angular SPA notice URL + browser rendering

Why this instead of searchbzp.uzp.gov.pl (the old DevExpress portal):
- Old BZP portal triggers CAPTCHA (WAF error 426) after repeated headless requests
- eZamowienia API is fully public, JSON-based, fast, no CAPTCHA
- Board/Search supports date range, CPV code, and organisation name filtering
- All data we need is in the search response (no detail page needed for basic search)

Discovered API endpoint (from browser network interception):
  GET https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search
  Query params:
    publicationDateFrom  ISO8601 date (e.g. 2026-01-01T00:00:00Z)
    CpvCode              CPV code prefix (e.g. 34223300)
    OrganizationName     Organisation name substring (e.g. 'wojsk')
    SortingColumnName    PublicationDate
    SortingDirection     DESC
    PageNumber           1-based page number
    PageSize             Items per page (max ~100)
  Response:
    JSON array of notice objects
    X-Pagination header: {"TotalCount":N,"PageSize":N,"CurrentPage":N,...}
"""

import re
import time
import logging
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

# ── Configuration ──

BASE_API = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search"
BASE_URL  = "https://ezamowienia.gov.pl"
# Real Angular route for notice detail (uses objectId UUID from the API response)
NOTICE_URL_TEMPLATE = (
    "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/"
    "{object_id}"
)


def create_pl_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Poland",
        country_code="PL",
        source_code="PL-BZP",
        base_url=BASE_URL,
        search_url=BASE_API,
        language="pl",
        trailer_keywords=[
            "przyczepa",              # trailer
            "naczepa",                # semi-trailer
            "niskopodwoziowa",        # low-bed
            "cysterna",               # tanker
            "kuchnia polowa",         # field kitchen
            "kontener wojskowy",      # military container
            "transporter czołgów",    # tank transporter
            "platforma transportowa", # transport platform
            "przyczepa wojskowa",     # military trailer
        ],
        defence_authorities=[
            "Inspektorat Uzbrojenia",
            "Inspektorat Wsparcia",
            "Agencja Mienia Wojskowego",
            "Ministerstwo Obrony Narodowej",
            "Dowództwo Generalne",
            "Regionalne Szef",
            "Wojskowe Zakłady",
            "Wojskowy Instytut Techniczny",
            "Rejonowy Zarząd Infrastruktury",
            "Centrum Reagowania Operacyjnego",
            "Logistyczny",
            "Wojsk Lądowych",
            "Wojskowy Oddział Gospodarczy",
            "Jednostka Wojskowa",
        ],
        min_interval_seconds=1.0,
    )


# ── CPV codes relevant to trailers / towed equipment ──
# These cover: trailers, semi-trailers, tank trailers, mobile containers,
# low-bed trailers, field kitchens (mounted on trailers), military containers.

TRAILER_CPV_CODES = [
    "34223300",   # Trailers (Przyczepy)                              ~1,600 /yr
    "34220000",   # Trailers, semi-trailers and mobile containers     ~200 /yr
    "34223100",   # Semi-trailers (Naczepy)                           ~50 /yr
    "34223200",   # Tank trailers (Cysterny)                          rare
    "34221000",   # Special-purpose mobile containers                 rare
    "34130000",   # Motor vehicles for transporting goods             broad
]

# ── Defence organisation keywords for OrganizationName filter ──
# Each yields a separate API query, all results are merged.

DEFENCE_ORG_KEYWORDS = [
    "Wojskowy Oddział Gospodarczy",
    "Inspektorat Uzbrojenia",
    "Inspektorat Wsparcia",
    "Agencja Mienia Wojskowego",
    "Centrum Logistyki",
    "Jednostka Wojskowa",
    "Rejonowy Zarząd Infrastruktury",
    "Wojskowe Zakłady",
    "Centrum Reagowania",
]


class PLAdapter(BaseAdapter):
    """
    Poland adapter — eZamowienia.gov.pl REST API (no browser needed for search).

    Search flow:
    1. For each TRAILER_CPV_CODE  → fetch all matching notices (paginated)
    2. For each DEFENCE_ORG_KEYWORD → fetch all notices, keep those with
       trailer-related CPV codes or trailer keyword in orderObject
    3. Deduplicate by noticeNumber, return SearchResult list
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    # ── Session setup ──

    def _build_session(self):
        """Create a requests Session with appropriate headers."""
        try:
            import requests, urllib3
            urllib3.disable_warnings()
        except ImportError:
            logger.error("PL: 'requests' not installed — pip install requests")
            return None

        import os
        session = requests.Session()
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
            "Accept": "application/json",
            "Origin": "https://ezamowienia.gov.pl",
            "Referer": "https://ezamowienia.gov.pl/mo-client-board/bzp/list",
        })
        return session

    # ── Main search (per keyword — delegates to CPV search) ──

    def search(self, keyword: str, max_results: int = 50) -> list:
        """
        Search by keyword.  For the PL-BZP REST API, keywords map to CPV codes
        and organisation name searches rather than free-text.  This method is
        called per keyword by BaseAdapter.search_all_keywords(); we override
        search_all_keywords() to use CPV-based logic directly.
        """
        # Honour calls from the base class but delegate to CPV search
        results = []
        kw_lower = keyword.lower()

        # If keyword looks like a specific CPV, search by CPV
        if re.match(r"^\d{5,8}$", keyword.strip()):
            results = self._fetch_by_cpv(keyword.strip(), max_results=max_results)
        else:
            # Otherwise, search each trailer CPV and filter by keyword in orderObject
            raw = self._fetch_by_cpv("34223300", max_results=200)
            results = [
                r for r in raw
                if kw_lower in (r.title or "").lower()
                or kw_lower in (r.snippet or "").lower()
            ]
        return results[:max_results]

    # ── Override search_all_keywords ──

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Override: instead of iterating keywords, call the REST API with
        CPV codes and defence-org filters.  Returns deduplicated SearchResult list.
        (max_results_per_keyword is accepted for API compatibility but
         the REST adapter uses its own limits per CPV/org query.)
        """
        if self._session is None:
            logger.error("PL: no requests session — cannot search")
            return []

        date_from = "2026-01-01T00:00:00Z"  # align with main --since 2026-01-01
        all_results: dict[str, SearchResult] = {}  # key = noticeNumber

        # ── Phase 1: CPV-code searches ──
        cpv_list = TRAILER_CPV_CODES[:2] if test_mode else TRAILER_CPV_CODES
        for cpv in cpv_list:
            logger.info(f"PL: searching CPV {cpv}")
            max_r = 20 if test_mode else 500
            hits = self._fetch_by_cpv(cpv, date_from=date_from, max_results=max_r)
            for h in hits:
                key = h.reference_id or h.title
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(f"PL: CPV {cpv} → {len(hits)} results, total so far {len(all_results)}")
            time.sleep(self.config.min_interval_seconds)

        # ── Phase 2: Defence-org searches (keep only trailer-related) ──
        org_list = DEFENCE_ORG_KEYWORDS[:2] if test_mode else DEFENCE_ORG_KEYWORDS
        for org_kw in org_list:
            logger.info(f"PL: searching org='{org_kw}'")
            max_r = 30 if test_mode else 500
            hits = self._fetch_by_org(org_kw, date_from=date_from, max_results=max_r)
            # Keep only hits where CPV or orderObject is trailer-related
            hits_filtered = [
                h for h in hits
                if self._is_trailer_related(h)
            ]
            for h in hits_filtered:
                key = h.reference_id or h.title
                if key and key not in all_results:
                    all_results[key] = h
            logger.info(
                f"PL: org '{org_kw}' → {len(hits)} raw, "
                f"{len(hits_filtered)} trailer-related, total {len(all_results)}"
            )
            time.sleep(self.config.min_interval_seconds)

        results = list(all_results.values())
        logger.info(f"PL: search_all_keywords → {len(results)} total notices")
        return results

    # ── REST API helpers ──

    def _api_search(self, params: dict, max_results: int = 200) -> list:
        """
        Paginate through the Board/Search API and return raw notice dicts.
        Respects max_results cap.
        """
        import json as _json

        if self._session is None:
            return []

        base_params = {
            "SortingColumnName": "PublicationDate",
            "SortingDirection": "DESC",
        }

        all_items = []
        page = 1
        page_size = min(100, max_results)

        while len(all_items) < max_results:
            params_page = {**base_params, **params, "PageNumber": page, "PageSize": page_size}
            try:
                resp = self._session.get(BASE_API, params=params_page, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"PL API: {resp.status_code} on page {page}")
                    break
                pagination = _json.loads(resp.headers.get("X-Pagination", "{}"))
                items = resp.json()
                if not items:
                    break
                all_items.extend(items)
                total = pagination.get("TotalCount", 0)
                has_next = pagination.get("HasNext", False)
                logger.debug(
                    f"PL API page {page}: {len(items)} items, "
                    f"total={total}, has_next={has_next}"
                )
                if not has_next or len(all_items) >= max_results:
                    break
                page += 1
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"PL API error (page {page}): {e}")
                break

        return all_items[:max_results]

    def _fetch_by_cpv(self, cpv: str, date_from: str = "",
                      max_results: int = 200) -> list:
        """Fetch notices by CPV code, return SearchResult list."""
        params = {"CpvCode": cpv}
        if date_from:
            params["publicationDateFrom"] = date_from
        items = self._api_search(params, max_results=max_results)
        return [self._item_to_search_result(item) for item in items]

    def _fetch_by_org(self, org_keyword: str, date_from: str = "",
                      max_results: int = 200) -> list:
        """Fetch notices by organisation name keyword, return SearchResult list."""
        params = {"OrganizationName": org_keyword}
        if date_from:
            params["publicationDateFrom"] = date_from
        items = self._api_search(params, max_results=max_results)
        return [self._item_to_search_result(item) for item in items]

    def _item_to_search_result(self, item: dict) -> SearchResult:
        """Convert raw API notice dict to SearchResult."""
        import json as _json

        notice_num = item.get("noticeNumber", "")
        object_id  = item.get("objectId", "")
        mo_id      = item.get("moIdentifier", "")
        # Build notice URL using objectId (the real Angular routing key)
        url = ""
        if object_id:
            url = NOTICE_URL_TEMPLATE.format(object_id=object_id)
        elif notice_num:
            encoded = notice_num.replace("/", "%2F").replace(" ", "%20")
            url = f"{BASE_URL}/mo-client-board/bzp/notice-details/id/{encoded}"

        org = item.get("organizationName", "") or ""
        city = item.get("organizationCity", "") or ""
        cpv_str = (item.get("cpvCode") or "")[:200]

        # Store IDs in snippet as JSON so get_detail() can use REST API
        meta = _json.dumps({
            "objectId": object_id,
            "moId": mo_id,
            "cpv": cpv_str,
            "org": org,
            "city": city,
        }, ensure_ascii=False)

        return SearchResult(
            title=item.get("orderObject", "") or "",
            url=url,
            authority=org,
            reference_id=notice_num,
            date=self._parse_iso_date(item.get("publicationDate", "") or ""),
            snippet=meta[:500],
        )

    # ── Defence / trailer relevance filter ──

    def filter_defence(self, results: list) -> list:
        """
        Override: CPV-based search already guarantees trailer relevance.
        Return all results so the AI classifier can decide military relevance.
        We still apply a soft filter — keep notices from military orgs OR
        from the CPV search (which are all trailer-related by definition).
        """
        # All results from search_all_keywords() are either:
        # a) trailer-CPV matches → already trailer-relevant, pass all to AI
        # b) defence-org matches with trailer CPV → doubly relevant
        # So: return all results, let the AI classifier decide.
        return results

    _TRAILER_CPV_PREFIXES = tuple(cpv[:6] for cpv in TRAILER_CPV_CODES)

    _TRAILER_KW = (
        "przyczepa", "naczepa", "niskopodwoziow", "cystern",
        "kuchnia polowa", "platforma transport", "transporter",
        "kontener", "naczep",
    )

    def _is_trailer_related(self, result: SearchResult) -> bool:
        """Return True if the notice is trailer-related by CPV or title keyword."""
        cpv_part = (result.snippet or "").lower()
        if any(cpv.lower() in cpv_part for cpv in self._TRAILER_CPV_PREFIXES):
            return True
        title_lower = (result.title or "").lower()
        return any(kw in title_lower for kw in self._TRAILER_KW)

    # ── Detail (REST API — no browser needed) ──

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """
        Fetch notice detail via REST API (GetNoticeHtmlBodyById).
        No browser required — much faster and more reliable than SPA rendering.
        Falls back to search result data if REST call fails.
        """
        import json as _json

        if self._session is None:
            return self._detail_from_search_result(result)

        # Extract objectId from snippet metadata (stored by _item_to_search_result)
        object_id = ""
        mo_id = ""
        try:
            meta = _json.loads(result.snippet or "{}")
            object_id = meta.get("objectId", "")
            mo_id = meta.get("moId", "")
        except Exception:
            pass

        # Fallback: extract objectId from URL
        if not object_id and result.url:
            m = re.search(r"/notice-details/id/([0-9a-f\-]+)", result.url)
            if m:
                object_id = m.group(1)

        if not object_id:
            logger.warning(f"PL: no objectId for {result.reference_id!r} — using search data")
            return self._detail_from_search_result(result)

        # Call GetNoticeHtmlBodyById
        logger.info(f"PL: fetching detail for {result.reference_id!r} (objectId={object_id})")
        try:
            resp = self._session.get(
                "https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNoticeHtmlBodyById",
                params={"noticeId": object_id},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning(f"PL: GetNoticeHtmlBodyById → {resp.status_code}")
                return self._detail_from_search_result(result)

            # Response is a JSON string containing HTML
            html_body = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
            if not html_body or len(html_body) < 50:
                return self._detail_from_search_result(result)

            # Strip HTML tags to get plain text
            raw_text = self._html_to_text(html_body if isinstance(html_body, str) else "")
            logger.info(f"PL: detail text {len(raw_text)} chars for {result.reference_id!r}")

        except Exception as e:
            logger.error(f"PL: GetNoticeHtmlBodyById error: {e}")
            return self._detail_from_search_result(result)

        detail = NoticeDetail(
            title=result.title or self._find_description(raw_text)[:100],
            url=result.url,
            authority=result.authority or self._find_authority(raw_text),
            reference_id=result.reference_id or self._find_ref_id(raw_text),
            source_code="PL-BZP",
            raw_text=raw_text[:15000],
            currency="PLN",
        )
        detail.date = result.date or self._find_date(raw_text)
        detail.description = self._find_description(raw_text)
        detail.quantity = self._find_quantity(raw_text)
        detail.value = self._find_value(raw_text)
        detail.winner = self._find_winner(raw_text)
        detail.duration = self._find_duration(raw_text)
        return detail

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags and decode entities to plain text."""
        import html as _html_module
        # Remove style/script blocks
        text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        # Replace block tags with newlines
        text = re.sub(r"<(h[1-6]|p|div|li|br|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode HTML entities
        text = _html_module.unescape(text)
        # Normalise whitespace
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)

    def _detail_from_search_result(self, result: SearchResult) -> NoticeDetail:
        """Build a minimal NoticeDetail from a SearchResult when REST call fails."""
        # Reconstruct a readable snippet from the JSON metadata in result.snippet
        import json as _json
        desc = result.title or ""
        try:
            meta = _json.loads(result.snippet or "{}")
            cpv = meta.get("cpv", "")
            org = meta.get("org", "")
            city = meta.get("city", "")
            desc_extra = f"CPV: {cpv}" if cpv else ""
            raw = f"{desc}\n{desc_extra}\n{org}, {city}"
        except Exception:
            raw = result.snippet or desc
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            reference_id=result.reference_id,
            date=result.date,
            source_code="PL-BZP",
            currency="PLN",
            raw_text=raw[:2000],
        )

    # ── Utility ──

    def _parse_iso_date(self, iso_str: str) -> str:
        """Extract YYYY-MM-DD from ISO8601 datetime string."""
        if iso_str and len(iso_str) >= 10:
            return iso_str[:10]
        return ""

    def _extract_authority(self, text: str) -> str:
        for auth in self.config.defence_authorities:
            if auth.lower() in text.lower():
                return auth
        return ""

    def _find_authority(self, text: str) -> str:
        patterns = [
            r"(?:Zamawiający|Nazwa zamawiającego)[:\s]+([^\n]{5,100})",
            r"(?:Instytucja zamawiająca)[:\s]+([^\n]{5,100})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return self._extract_authority(text)

    def _find_date(self, text: str) -> str:
        patterns = [
            r"(?:Data publikacji|Data ogłoszenia)[:\s]+(\d{4}-\d{2}-\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{2}\.\d{2}\.\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1)
                if re.match(r"\d{2}\.\d{2}\.\d{4}", raw):
                    parts = raw.split(".")
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
                return raw
        return ""

    def _find_description(self, text: str) -> str:
        """Extract short description from BZP notice (section 4.5.1)."""
        patterns = [
            # BZP-specific: "4.5.1.) Krótki opis przedmiotu zamówienia\n<text>"
            r"4\.5\.1\.\)[^\n]*\n(.{20,600}?)(?:\n4\.|$)",
            # Generic
            r"(?:Krótki opis|Przedmiot zamówienia|Opis zamówienia)[:\s]+(.{30,500}?)(?:\n\d|\n\n|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                desc = m.group(1).strip()
                # Take only first 3 lines
                desc_lines = [l for l in desc.split("\n") if l.strip()][:3]
                return " ".join(desc_lines)[:400]
        return ""

    def _find_quantity(self, text: str) -> Optional[int]:
        patterns = [
            r"(\d[\d\s]*)\s*(?:sztuk|szt\.?|egzemplarz|egz\.|komplet|zestawów)",
            r"(?:Ilość|Liczba)[:\s]+(\d[\d\s]*)",
            r"(\d+)\s*(?:przyczepa|naczepa|pojazd|szt)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1).replace(" ", ""))
                    if 1 <= v <= 10000:
                        return v
                except ValueError:
                    continue
        return None

    def _find_value(self, text: str) -> Optional[float]:
        """Extract estimated procurement value from BZP notice."""
        patterns = [
            # BZP section 4.3: estimated value
            r"4\.3\.\)[^\n]*zamówienia[:\s]*([\d\s]+)\s*PLN",
            # BZP section 8.2: contract value (actual)
            r"8\.2\.\)[^\n]*umow[^\n]*:\s*([\d\s,.]+)\s*PLN",
            # Generic
            r"(?:Wartość zamówienia|Szacunkowa wartość|Łączna wartość)[^\d]{0,20}([\d\s,.]+)\s*(?:PLN|zł)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val_str = m.group(1).replace(" ", "").replace(",", ".")
                try:
                    v = float(val_str)
                    if v > 100:
                        return v
                except ValueError:
                    continue
        return None

    def _find_winner(self, text: str) -> str:
        """Extract winner company name from BZP award notice."""
        patterns = [
            # BZP section 7.3.1: winner name
            r"7\.3\.1\)[^\n]*zamówienia[:\s]+([^\n]{5,120})",
            # Alternative format
            r"(?:Nazwa \(firma\) wykonawcy)[^\n]*:\s+([^\n]{5,120})",
            # Generic fallback
            r"(?:Nazwa wykonawcy|Wybrany wykonawca)[:\s]+([^\n]{5,100})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # Reject if it looks like a number/amount
                if not re.match(r"^[\d\s,.\+]+$", name):
                    return name[:120]
        return ""

    def _find_duration(self, text: str) -> str:
        """Extract contract duration from BZP notice."""
        patterns = [
            # BZP section 8.3: period of performance
            r"8\.3\.\)[^\n]*realizacji[^\n]*:\s+([^\n]{3,80})",
            # Generic
            r"(?:Okres realizacji|Czas trwania zamówienia)[:\s]+([^\n]{3,60})",
            r"(\d+)\s*(?:miesięcy|miesiące|tygodni|lat|dni)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:80]
        return ""

    def _find_ref_id(self, text: str) -> str:
        patterns = [
            # BZP format: 2026/BZP 00XXXXXX
            r"(?:Numer ogłoszenia|Nr ogłoszenia)[:\s]+(20\d\d/BZP\s[\d/]+)",
            r"(20\d\d/BZP\s[\d]+(?:/\d+)?)",
            r"(?:Numer referencyjny)[:\s]+([A-Z0-9/\-_.]{4,40})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

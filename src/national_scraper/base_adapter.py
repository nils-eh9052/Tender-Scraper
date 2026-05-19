"""
Base Adapter — Abstract class that every country adapter implements.

Each adapter defines:
- Where to search (URLs, parameters)
- How to search (fill forms, click buttons, read results)
- How to extract details (selectors, text patterns)
- Country-specific keywords and authority patterns
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .core import BrowserCore


@dataclass
class SearchResult:
    """A single search result from a national portal."""
    title: str
    url: str
    authority: str = ""
    date: str = ""
    value: Optional[float] = None
    currency: str = ""
    reference_id: str = ""  # National ID (not TED ID)
    snippet: str = ""


@dataclass
class NoticeDetail:
    """Full detail extracted from a national portal notice."""
    title: str = ""
    description: str = ""
    authority: str = ""
    date: str = ""
    value: Optional[float] = None
    currency: str = ""
    quantity: Optional[int] = None
    winner: str = ""
    deadline: str = ""
    duration: str = ""
    reference_id: str = ""
    url: str = ""
    source_code: str = ""  # e.g. "DE-SB", "PL-EZ"
    raw_text: str = ""     # Full page text for AI processing
    status: str = ""       # Pipeline status: Open/Closed/Awarded/Cancelled (adapter-set)


@dataclass
class AdapterConfig:
    """Configuration for a country adapter."""
    country_name: str
    country_code: str       # e.g. "DE", "PL"
    source_code: str        # e.g. "DE-SB", "PL-EZ"
    base_url: str
    search_url: str
    language: str           # e.g. "de", "pl", "en"

    # Keywords to search for (in the local language)
    trailer_keywords: list = field(default_factory=list)

    # Defence authority patterns to filter for
    defence_authorities: list = field(default_factory=list)

    # Rate limiting
    min_interval_seconds: float = 2.0


class BaseAdapter(ABC):
    """Abstract base for country-specific scrapers."""

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        self.browser = browser
        self.config = config

    @abstractmethod
    def search(self, keyword: str, max_results: int = 50) -> list:
        """
        Search the national portal for a keyword.

        Must handle:
        - Filling search forms
        - Waiting for JavaScript-rendered results
        - Pagination (if needed)
        - Parsing the result list

        Returns list of SearchResult objects.
        """
        pass

    @abstractmethod
    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """
        Navigate to a search result and extract full details.

        Must handle:
        - Loading the detail page
        - Extracting all available fields

        Returns NoticeDetail or None on failure.
        """
        pass

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Run all configured keywords and deduplicate by URL/reference_id/title.

        Returns deduplicated list of SearchResult objects.
        """
        all_results: dict = {}

        keywords = self.config.trailer_keywords
        if test_mode:
            keywords = keywords[:2]  # Only first 2 keywords in test mode

        for keyword in keywords:
            results = self.search(keyword, max_results=max_results_per_keyword)
            for r in results:
                # Dedup by URL or reference ID
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r

        return list(all_results.values())

    def filter_defence(self, results: list) -> list:
        """Filter results to defence-relevant ones only."""
        defence = []
        for r in results:
            authority_lower = (r.authority or "").lower()
            title_lower = (r.title or "").lower()
            snippet_lower = (r.snippet or "").lower()

            is_defence = any(
                pattern.lower() in authority_lower
                or pattern.lower() in title_lower
                or pattern.lower() in snippet_lower
                for pattern in self.config.defence_authorities
            )

            if is_defence:
                defence.append(r)

        return defence

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        """Convert to the standard pipeline format (compatible with TED notices)."""
        # ID prefix de-duplication: some adapters (e.g. UA-Prozorro, NL-TenderNed)
        # already store the country code inside reference_id ("UA-2026-...", "NL-577684").
        # Without this guard we'd produce "UA-UA-2026-..." / "NL-NL-577684".
        cc_prefix = f"{self.config.country_code}-"
        if detail.reference_id:
            tender_id = (
                detail.reference_id
                if detail.reference_id.startswith(cc_prefix)
                else f"{cc_prefix}{detail.reference_id}"
            )
        else:
            tender_id = ""

        return {
            "tender_id": tender_id,
            "source": self.config.source_code,
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": self.config.country_name,
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date[:10] if detail.date else "",
            "_value_amount": detail.value,
            "_value_currency": detail.currency or self._default_currency(),
            "_winner_name": detail.winner,
            "ted_url": "",
            "_description_final": detail.description[:500] if detail.description else "",
            "_national_raw_text": detail.raw_text[:10000],

            "_status": detail.status or "",

            # Trailer classification fields (to be filled by AI classifier)
            "_trailer_type_1": None,
            "_trailer_category_1": None,
            "_trailer_quantity_1": detail.quantity,
            "_trailer_type_2": None,
            "_trailer_category_2": None,
            "_trailer_quantity_2": None,
            "_additional_equipment": None,
            "_contract_duration": detail.duration,

            "_raw": {"source": self.config.source_code, "url": detail.url},
        }

    def _default_currency(self) -> str:
        currencies = {
            "DE": "EUR", "PL": "PLN", "SE": "SEK", "NO": "NOK",
            "CZ": "CZK", "DK": "DKK", "GB": "GBP", "CH": "CHF",
            "TR": "TRY",
        }
        return currencies.get(self.config.country_code, "EUR")

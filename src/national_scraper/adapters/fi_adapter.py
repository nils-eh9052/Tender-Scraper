"""
Finland Adapter — Hilma (hankintailmoitukset.fi)

Finland uses Hilma as the official national procurement portal.
All public procurement above the threshold must be published here.

Defence procurement authorities:
  - Puolustusvoimat (Finnish Defence Forces)
  - Puolustusministeriö (Ministry of Defence)
  - Puolustusvoimien Logistiikkalaitos (Defence Forces Logistics Command)
  - Sotilaslääketieteen Keskus (Centre for Military Medicine)

Key trailer vocabulary (Finnish):
  - perävaunu        = trailer
  - puoliperävaunu   = semitrailer
  - lavetti          = low-bed transporter
  - säiliöperävaunu  = tank trailer
  - kenttäkeittiö    = field kitchen (often trailer-mounted)
  - kontti           = container (may be on trailer chassis)

Hilma has a REST API at https://www.hankintailmoitukset.fi/fi/rest/ but
authentication and full docs are not public — browser scraping is safer.

STATUS: STUB — not yet implemented. Run --validate-portals fi first to confirm
that Puolustusvoimat actually publishes trailer tenders on Hilma (they may use
TED exclusively for defence procurement under Directive 2009/81/EC).
"""

from typing import Optional

from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

HILMA_BASE_URL = "https://www.hankintailmoitukset.fi"
HILMA_SEARCH_URL = "https://www.hankintailmoitukset.fi/fi/search"


def create_fi_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Finland",
        country_code="FI",
        source_code="FI-HI",
        base_url=HILMA_BASE_URL,
        search_url=HILMA_SEARCH_URL,
        language="fi",
        trailer_keywords=[
            "perävaunu",            # trailer
            "puoliperävaunu",       # semitrailer
            "lavetti",              # low-bed transporter
            "säiliöperävaunu",      # tank trailer
            "kenttäkeittiö",        # field kitchen (often trailer-mounted)
            "kontti perävaunu",     # container trailer
            "kuorma-autoperävaunu", # truck trailer
        ],
        defence_authorities=[
            "Puolustusvoimat",
            "Puolustusministeriö",
            "Puolustusvoimien Logistiikkalaitos",
            "Sotilaslääketieteen Keskus",
            "Maavoimat",            # Army
            "Merivoimat",           # Navy
            "Ilmavoimat",           # Air Force
        ],
        min_interval_seconds=3.0,
    )


class FIAdapter(BaseAdapter):
    """
    Finland-specific scraper for Hilma procurement portal.

    NOT YET IMPLEMENTED. Raises NotImplementedError on all methods.
    Run --validate-portals fi first to confirm the portal carries
    defence trailer tenders before investing in implementation.
    """

    def search(self, keyword: str, max_results: int = 50) -> list[SearchResult]:
        """TODO: Implement after validation confirms Hilma carries defence trailers."""
        raise NotImplementedError(
            "Finland adapter not yet implemented. "
            "Run --validate-portals fi to check if Hilma carries defence trailers."
        )

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """TODO: Implement after search() works."""
        raise NotImplementedError("Finland adapter not yet implemented.")

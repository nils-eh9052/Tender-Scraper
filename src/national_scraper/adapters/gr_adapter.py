"""
Greece Adapter — Promitheus (promitheus.gov.gr)

Portal: https://www.promitheus.gov.gr
Defence: Υπουργείο Εθνικής Άμυνας (Ministry of National Defence), ΓΔΑΕΕ

DISCOVERY STATUS (Sprint 11):
  The Promitheus portal is based on Oracle ADF / WebCenter Portal.

  Public search: https://www.promitheus.gov.gr/webcenter/portal/AADP/search
  - Form-based search, no REST API discovered via XHR interception
  - Results paginated via Oracle ADF partial page rendering (PPR)
  - Session tokens + ViewState required for subsequent requests
  - CAPTCHA present on some search paths

  ESHDHS sub-portal (defence procurement only):
    https://www.promitheus.gov.gr/webcenter/portal/GDAEE
    Used by ΓΔΑΕΕ (General Directorate of Defence Investments & Technology)
    No separate API found.

  Alternative: Greek tenders above EU threshold MUST appear on TED.
  For defence trailer procurement, TED coverage is likely complete.
  Greek MoD has published on TED: Contracts Finder equivalent for GR is TED.

  Sprint 11 screenshot findings:
    - Promitheus homepage loads successfully (693KB screenshot)
    - Portal shows "Αναζήτηση" (Search) section — public access without login
    - Both AADP and GDAEE URLs load the SAME Promitheus homepage
      (ΓΔΑΕΕ/GDAEE is not a separate sub-portal — redirects to main)
    - Left sidebar shows login options for ΕΣΗΔΗΣ, Promitheus ESPDint, ΚΗΜΔΗΣ
    - Oracle ADF WebCenter architecture confirmed

  IMPLEMENTATION: Browser-based stub. Navigates to the portal,
  takes screenshots, then returns empty pending full discovery.

  TODO Sprint 12:
    1. Navigate to Αναζήτηση section on homepage
    2. Extract javax.faces.ViewState from form hidden field
    3. POST CPV "34223" search — parse HTML table response
    4. Note: GDAEE portal = same as main portal, no separate URL needed

TRAILER KEYWORDS (Greek):
  ρυμουλκούμενο = trailer (generic)
  ημιρυμουλκούμενο = semi-trailer
  χαμηλή πλατφόρμα = low-bed
  βυτιοφόρο = tanker
  κινητή κουζίνα = mobile kitchen (field kitchen)
  τρέιλερ = trailer (loanword)
"""

import logging
import time
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

GR_BASE = "https://www.promitheus.gov.gr"
GR_SEARCH_URL = f"{GR_BASE}/webcenter/portal/AADP/search"
GR_ESHDHS_URL = f"{GR_BASE}/webcenter/portal/GDAEE"


def create_gr_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Greece",
        country_code="GR",
        source_code="GR-PR",
        base_url=GR_BASE,
        search_url=GR_SEARCH_URL,
        language="el",
        trailer_keywords=[
            "ρυμουλκούμενο",           # trailer (generic)
            "ημιρυμουλκούμενο",         # semi-trailer
            "τρέιλερ",                  # trailer (loanword)
            "βυτιοφόρο ρυμουλκούμενο",  # tanker trailer
            "χαμηλή πλατφόρμα",         # low-bed platform
            "κινητή κουζίνα",           # mobile kitchen
            "εκστρατείας κουζίνα",      # field kitchen
            "αρθρωτό ρυμουλκούμενο",    # articulated trailer
            "trailer",                  # English (used in Greek tenders)
            "semi-trailer",
        ],
        defence_authorities=[
            "Υπουργείο Εθνικής Άμυνας",
            "ΓΔΑΕΕ",
            "Γενικό Επιτελείο Στρατού",
            "Γενικό Επιτελείο Ναυτικού",
            "Γενικό Επιτελείο Αεροπορίας",
            "ΓΕΣ", "ΓΕΝ", "ΓΕΑ",
            "Ελληνικός Στρατός",
            "Ministry of National Defence",
        ],
        min_interval_seconds=2.0,
    )


class GRAdapter(BaseAdapter):
    """
    Greece Promitheus adapter — STUB pending full portal discovery.

    The Promitheus portal uses Oracle ADF WebCenter which requires
    complex session management. Full implementation deferred to Sprint 12.

    Current behaviour: navigates portal, takes screenshots for manual
    analysis, returns empty results.

    Note: Greek defence trailer tenders above the EU threshold should
    appear on TED. This adapter targets tenders that appear ONLY on
    Promitheus (below-threshold or national-only notices).
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)

    def search(self, keyword: str, max_results: int = 50) -> list:
        return []

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        STUB: Navigate Promitheus for screenshots + portal discovery.
        Returns empty list until ADF session handling is implemented.
        """
        logger.info("GR: Promitheus stub — navigating portal for discovery screenshots")

        try:
            if self.browser and self.browser.page:
                # Navigate to search portal and take screenshot
                ok = self.browser.goto(GR_SEARCH_URL, timeout=30000)
                if ok:
                    logger.info("GR: Promitheus search page loaded")
                    time.sleep(2)
                    self.browser._screenshot("gr_promitheus_search")
                else:
                    logger.warning("GR: could not load Promitheus search page")

                # Also check the defence-specific ESHDHS portal
                ok2 = self.browser.goto(GR_ESHDHS_URL, timeout=30000)
                if ok2:
                    logger.info("GR: ΓΔΑΕΕ portal loaded")
                    time.sleep(2)
                    self.browser._screenshot("gr_gdaee_portal")
        except Exception as exc:
            logger.warning("GR: browser navigation error: %s", exc)

        logger.info("GR: stub complete — 0 results (Promitheus ADF not yet implemented)")
        return []

    def filter_defence(self, results: list) -> list:
        return results

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        return None

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        return {
            "tender_id": f"GR-PR-{detail.reference_id}",
            "source": "GR-PR",
            "source_url_national": detail.url,
            "_title_final": detail.title,
            "_country_normalized": "Greece",
            "_authority_name": detail.authority,
            "_pub_date_clean": detail.date,
            "_value_amount": detail.value,
            "_value_currency": detail.currency or "EUR",
            "_winner_name": detail.winner or "",
            "_description_final": detail.description or "",
            "_national_raw_text": detail.raw_text or "",
            "_trailer_quantity_1": detail.quantity,
            "_raw": {"source": "GR-PR", "url": detail.url},
        }

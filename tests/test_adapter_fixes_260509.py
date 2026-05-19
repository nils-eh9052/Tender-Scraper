"""
Tests for Sprint 14d adapter fixes:
  - UA Prozorro status mapping
  - CZ NEN status regex + CPV extraction
  - CZ result-page winner extraction (mock)
  - FR BOAMP titulaire winner passthrough
  - NO Doffin status mapping + expanded winner patterns

Run:
    python3 -m unittest tests.test_adapter_fixes_260509 -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.national_scraper.adapters.ua_adapter import (
    _map_prozorro_status,
    UAAdapter,
    create_ua_config,
)
from src.national_scraper.adapters.cz_adapter import (
    _map_cz_status,
    CZAdapter,
    create_cz_config,
)
from src.national_scraper.adapters.no_adapter import (
    _map_doffin_status,
    NOAdapter,
    create_no_config,
)
from src.national_scraper.adapters.fr_adapter import FRAdapter, create_fr_config
from src.national_scraper.base_adapter import NoticeDetail, SearchResult


def _mock_browser():
    b = MagicMock()
    b.goto.return_value = True
    b.wait_seconds.return_value = None
    b._screenshot.return_value = None
    b.get_page_text.return_value = ""
    b.current_url.return_value = ""
    b.page = MagicMock()
    return b


# ──────────────────────────────────────────────────────────────────────────────
# TEIL 1 — UA Prozorro status mapping
# ──────────────────────────────────────────────────────────────────────────────

class TestMapProzorroStatus(unittest.TestCase):

    def test_active_tendering_is_open(self):
        self.assertEqual(_map_prozorro_status("active.tendering"), "Open")

    def test_active_enquiries_is_open(self):
        self.assertEqual(_map_prozorro_status("active.enquiries"), "Open")

    def test_active_qualification_is_awarded(self):
        self.assertEqual(_map_prozorro_status("active.qualification"), "Awarded")

    def test_active_awarded_is_awarded(self):
        self.assertEqual(_map_prozorro_status("active.awarded"), "Awarded")

    def test_complete_is_closed(self):
        self.assertEqual(_map_prozorro_status("complete"), "Closed")

    def test_cancelled_is_cancelled(self):
        self.assertEqual(_map_prozorro_status("cancelled"), "Cancelled")

    def test_unsuccessful_is_cancelled(self):
        self.assertEqual(_map_prozorro_status("unsuccessful"), "Cancelled")

    def test_unknown_returns_empty(self):
        self.assertEqual(_map_prozorro_status("draft"), "")

    def test_empty_returns_empty(self):
        self.assertEqual(_map_prozorro_status(""), "")

    def test_case_insensitive(self):
        self.assertEqual(_map_prozorro_status("COMPLETE"), "Closed")
        self.assertEqual(_map_prozorro_status("Active.Tendering"), "Open")


class TestUAStatusInToStandardFormat(unittest.TestCase):
    """UA get_detail passes status through to_standard_format."""

    def setUp(self):
        self.adapter = UAAdapter(_mock_browser(), create_ua_config())

    def test_status_present_in_output(self):
        d = NoticeDetail(
            reference_id="UA-2026-01-01-000001-a",
            source_code="UA-PR",
            status="Open",
        )
        out = self.adapter.to_standard_format(d)
        self.assertEqual(out["_status"], "Open")

    def test_empty_status_present_in_output(self):
        d = NoticeDetail(reference_id="UA-2026-01-01-000002-a", source_code="UA-PR")
        out = self.adapter.to_standard_format(d)
        self.assertIn("_status", out)
        self.assertEqual(out["_status"], "")


# ──────────────────────────────────────────────────────────────────────────────
# TEIL 2 — CZ NEN status regex + CPV
# ──────────────────────────────────────────────────────────────────────────────

# Sample NEN page text (English UI) — representative subset
_CZ_SAMPLE_AWARDED = """\
CURRENT STATUS OF THE PROCUREMENT PROCEDURE
Zadán

CODE FROM THE CPV CODE LIST
34223300-9

NAME FROM THE CPV CODE LIST
Přívěsy

ESTIMATED VALUE (EXCL. VAT)
123,293.66
"""

_CZ_SAMPLE_OPEN = """\
CURRENT STATUS OF THE PROCUREMENT PROCEDURE
Probíhající

CODE FROM THE CPV CODE LIST
34138000-3

ESTIMATED VALUE (EXCL. VAT)
0
"""

_CZ_SAMPLE_CANCELLED = """\
CURRENT STATUS OF THE PROCUREMENT PROCEDURE
Zrušen
"""


class TestMapCzStatus(unittest.TestCase):

    def test_probiha_is_open(self):
        self.assertEqual(_map_cz_status("Probíhající"), "Open")

    def test_vyhlaseny_is_open(self):
        self.assertEqual(_map_cz_status("Vyhlášený"), "Open")

    def test_zadán_is_awarded(self):
        self.assertEqual(_map_cz_status("Zadán"), "Awarded")

    def test_ukonceny_is_closed(self):
        self.assertEqual(_map_cz_status("Ukončený"), "Closed")

    def test_zrusen_is_cancelled(self):
        self.assertEqual(_map_cz_status("Zrušen"), "Cancelled")

    def test_unknown_returns_empty(self):
        self.assertEqual(_map_cz_status("Neznámý"), "")


class TestCZFindStatus(unittest.TestCase):

    def setUp(self):
        self.adapter = CZAdapter(_mock_browser(), create_cz_config())

    def test_awarded_status_extracted(self):
        self.assertEqual(self.adapter._find_status(_CZ_SAMPLE_AWARDED), "Awarded")

    def test_open_status_extracted(self):
        self.assertEqual(self.adapter._find_status(_CZ_SAMPLE_OPEN), "Open")

    def test_cancelled_status_extracted(self):
        self.assertEqual(self.adapter._find_status(_CZ_SAMPLE_CANCELLED), "Cancelled")

    def test_missing_section_returns_empty(self):
        self.assertEqual(self.adapter._find_status("No status here"), "")


class TestCZFindCpv(unittest.TestCase):

    def setUp(self):
        self.adapter = CZAdapter(_mock_browser(), create_cz_config())

    def test_cpv_trailers_extracted(self):
        self.assertEqual(self.adapter._find_cpv(_CZ_SAMPLE_AWARDED), "34223300-9")

    def test_cpv_tank_transporter_extracted(self):
        self.assertEqual(self.adapter._find_cpv(_CZ_SAMPLE_OPEN), "34138000-3")

    def test_no_cpv_returns_empty(self):
        self.assertEqual(self.adapter._find_cpv("No CPV section here"), "")


# ──────────────────────────────────────────────────────────────────────────────
# TEIL 3 — CZ result tab winner (mock browser)
# ──────────────────────────────────────────────────────────────────────────────

_CZ_RESULT_SAME_LINE = """\
Výsledek zadávacího řízení
Dodavatel: ACME Trailers s.r.o.
Cena: 120 000 CZK
"""

_CZ_RESULT_NEXT_LINE_CZ = """\
VYBRANÝ DODAVATEL
Kovona System a.s.
Celková cena: 450 000 CZK
"""

_CZ_RESULT_NEXT_LINE_EN = """\
RESULT
SELECTED SUPPLIER
Nordic Defence Trailers s.r.o.
CONTRACT VALUE
350000 CZK
"""


class TestCZFindWinner(unittest.TestCase):

    def setUp(self):
        self.adapter = CZAdapter(_mock_browser(), create_cz_config())

    def test_same_line_dodavatel(self):
        self.assertEqual(self.adapter._find_winner(_CZ_RESULT_SAME_LINE), "ACME Trailers s.r.o.")

    def test_next_line_czech_heading(self):
        self.assertEqual(self.adapter._find_winner(_CZ_RESULT_NEXT_LINE_CZ), "Kovona System a.s.")

    def test_next_line_english_heading(self):
        self.assertEqual(self.adapter._find_winner(_CZ_RESULT_NEXT_LINE_EN), "Nordic Defence Trailers s.r.o.")

    def test_numeric_only_rejected(self):
        self.assertEqual(self.adapter._find_winner("DODAVATEL\n1234567.89\n"), "")

    def test_empty_text_returns_empty(self):
        self.assertEqual(self.adapter._find_winner(""), "")


class TestCZResultPageWinner(unittest.TestCase):

    def test_winner_extracted_same_line(self):
        browser = _mock_browser()
        browser.goto.return_value = True
        browser.get_page_text.return_value = _CZ_RESULT_SAME_LINE

        adapter = CZAdapter(browser, create_cz_config())
        result = SearchResult(
            title="Přívěsy",
            url="https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-26-V00010428",
            reference_id="N006/26/V00010428",
        )
        winner = adapter._try_result_page(result)
        self.assertEqual(winner, "ACME Trailers s.r.o.")

    def test_winner_extracted_next_line_english(self):
        browser = _mock_browser()
        browser.goto.return_value = True
        browser.get_page_text.return_value = _CZ_RESULT_NEXT_LINE_EN

        adapter = CZAdapter(browser, create_cz_config())
        result = SearchResult(
            title="Přívěsy",
            url="https://nen.nipez.cz/en/verejne-zakazky/detail-zakazky/N006-26-V00010428",
            reference_id="N006/26/V00010428",
        )
        winner = adapter._try_result_page(result)
        self.assertEqual(winner, "Nordic Defence Trailers s.r.o.")

    def test_graceful_skip_on_failed_page_load(self):
        browser = _mock_browser()
        browser.goto.return_value = False  # all URL attempts fail

        adapter = CZAdapter(browser, create_cz_config())
        result = SearchResult(
            title="X",
            url="https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-26-V00099999",
            reference_id="N006/26/V00099999",
        )
        winner = adapter._try_result_page(result)
        self.assertEqual(winner, "")


# ──────────────────────────────────────────────────────────────────────────────
# TEIL 3 — FR BOAMP titulaire winner passthrough
# ──────────────────────────────────────────────────────────────────────────────

class TestFRWinnerFromTitulaire(unittest.TestCase):
    """
    FRAdapter._record_to_detail already maps titulaire → detail.winner.
    This test verifies the end-to-end: API record with titulaire → to_standard_format
    → _winner_name is populated.
    """

    def setUp(self):
        self.adapter = FRAdapter(_mock_browser(), create_fr_config())

    def test_titulaire_list_becomes_winner(self):
        rec = {
            "idweb": "24-12345",
            "objet": "Remorque citerne de carburant",
            "nomacheteur": "MINARM/SCA",
            "dateparution": "2024-06-01",
            "datelimitereponse": None,
            "titulaire": ["Soframe SAS"],
            "url_avis": "https://www.boamp.fr/pages/avis/?q=idweb:24-12345",
            "donnees": {},
            "famille": "JOUE",
            "perimetre": "DIRECTIVE-81",
            "descripteur_libelle": ["Véhicules militaires"],
        }
        detail = self.adapter._record_to_detail(rec)
        self.assertEqual(detail.winner, "Soframe SAS")
        std = self.adapter.to_standard_format(detail)
        self.assertEqual(std["_winner_name"], "Soframe SAS")

    def test_titulaire_string_becomes_winner(self):
        rec = {
            "idweb": "24-67890",
            "objet": "Semi-remorque porte-char",
            "nomacheteur": "MINARM/DGA",
            "dateparution": "2024-07-01",
            "datelimitereponse": None,
            "titulaire": "LOHR Industrie",
            "url_avis": "",
            "donnees": {},
            "famille": "JOUE",
            "perimetre": "DIRECTIVE-81",
            "descripteur_libelle": [],
        }
        detail = self.adapter._record_to_detail(rec)
        self.assertEqual(detail.winner, "LOHR Industrie")

    def test_empty_titulaire_yields_empty_winner(self):
        rec = {
            "idweb": "24-11111",
            "objet": "Remorque",
            "nomacheteur": "MINARM",
            "dateparution": "2024-05-01",
            "datelimitereponse": None,
            "titulaire": None,
            "url_avis": "",
            "donnees": {},
            "famille": "JOUE",
            "perimetre": "DIRECTIVE-81",
            "descripteur_libelle": [],
        }
        detail = self.adapter._record_to_detail(rec)
        self.assertEqual(detail.winner, "")


# ──────────────────────────────────────────────────────────────────────────────
# TEIL 3 — NO Doffin status mapping + winner patterns
# ──────────────────────────────────────────────────────────────────────────────

class TestMapDoffinStatus(unittest.TestCase):

    def test_award_notice_type_is_awarded(self):
        self.assertEqual(_map_doffin_status("type=award_notice status=active auth=Forsvarsmateriell"), "Awarded")

    def test_status_awarded_is_awarded(self):
        self.assertEqual(_map_doffin_status("type=contract_notice status=awarded auth=X"), "Awarded")

    def test_active_contract_notice_is_open(self):
        self.assertEqual(_map_doffin_status("type=contract_notice status=active auth=X"), "Open")

    def test_expired_is_closed(self):
        self.assertEqual(_map_doffin_status("type=contract_notice status=expired auth=X"), "Closed")

    def test_cancelled_is_cancelled(self):
        self.assertEqual(_map_doffin_status("type=contract_notice status=cancelled auth=X"), "Cancelled")

    def test_empty_returns_empty(self):
        self.assertEqual(_map_doffin_status(""), "")


class TestNOFindWinner(unittest.TestCase):

    def setUp(self):
        self.adapter = NOAdapter(_mock_browser(), create_no_config())

    def test_leverandor_pattern(self):
        text = "Leverandør: Nordic Trailer AS\nAntall: 10"
        self.assertEqual(self.adapter._find_winner(text), "Nordic Trailer AS")

    def test_kontraktsvinner_pattern(self):
        text = "Kontraktsvinner: Norgesmilitær Transport AS"
        self.assertEqual(self.adapter._find_winner(text), "Norgesmilitær Transport AS")

    def test_valgt_leverandor_pattern(self):
        text = "Valgt leverandør: Frydenbø Trailer & Logistikk AS"
        self.assertEqual(self.adapter._find_winner(text), "Frydenbø Trailer & Logistikk AS")

    def test_tildelt_pattern(self):
        text = "Tildelt: Industribygg Trailer AS\nBeskrivelse: ..."
        self.assertEqual(self.adapter._find_winner(text), "Industribygg Trailer AS")

    def test_no_winner_returns_empty(self):
        text = "Ingen leverandørinformasjon tilgjengelig"
        self.assertEqual(self.adapter._find_winner(text), "")

    def test_numeric_value_not_treated_as_winner(self):
        # Pattern should not match pure numeric strings
        text = "Leverandør: 1234567.89"
        self.assertEqual(self.adapter._find_winner(text), "")


if __name__ == "__main__":
    unittest.main()

"""
Smoke tests for the TR-EKAP adapter — Sprint 14d.

Tests run entirely offline against tests/fixtures/tr_sample.json —
no live EKAP connection required.

Scenarios covered:
  1. _parse_api_response parses fixture JSON → 3 SearchResult objects
  2. filter_defence retains military notices, drops civilian
  3. _parse_tr_date handles DD.MM.YYYY, ISO datetime, and empty input
  4. get_detail falls back gracefully when browser returns empty page text
  5. to_standard_format: reference_id is NOT doubled (Sprint-14c dedup guard)
  6. _parse_html_results extracts results from text resembling EKAP innerText

Run:
    python3 -m unittest tests.test_tr_adapter -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.national_scraper.adapters.tr_adapter import (
    TrAdapter,
    create_tr_config,
)
from src.national_scraper.base_adapter import NoticeDetail, SearchResult

FIXTURE = Path(__file__).parent / "fixtures" / "tr_sample.json"


def _make_adapter() -> TrAdapter:
    return TrAdapter(MagicMock(), create_tr_config())


class TestParseApiResponse(unittest.TestCase):
    """_parse_api_response converts EKAP fixture JSON to SearchResult list."""

    def setUp(self):
        self.adapter = _make_adapter()
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_returns_three_results(self):
        results = self.adapter._parse_api_response(self.payload)
        self.assertEqual(len(results), 3)

    def test_first_result_fields(self):
        results = self.adapter._parse_api_response(self.payload)
        r = results[0]
        self.assertIsInstance(r, SearchResult)
        self.assertIn("2026/456789", r.reference_id)
        self.assertIn("Römork", r.title)
        self.assertIn("Kara Kuvvetleri", r.authority)
        self.assertEqual(r.currency, "TRY")
        self.assertEqual(r.value, 4_500_000.0)
        self.assertEqual(r.date, "2026-03-15")  # parsed from DD.MM.YYYY

    def test_iso_datetime_date_parsed(self):
        results = self.adapter._parse_api_response(self.payload)
        r = results[1]
        self.assertEqual(r.date, "2026-04-10")

    def test_url_contains_kayit_no(self):
        results = self.adapter._parse_api_response(self.payload)
        self.assertIn("2026%2F456789", results[0].url.replace("/", "%2F").replace("2026/456789", "2026%2F456789"))
        # Just verify URL is not the search page
        self.assertNotEqual(results[0].url, "https://ekap.kik.gov.tr/EKAP/Ortak/IhaleAra/index.html")

    def test_accepts_raw_list(self):
        raw_list = self.payload["data"]
        results = self.adapter._parse_api_response(raw_list)
        self.assertEqual(len(results), 3)


class TestFilterDefence(unittest.TestCase):
    """filter_defence keeps only military/defence authorities."""

    def setUp(self):
        self.adapter = _make_adapter()
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_two_defence_one_civilian(self):
        results = self.adapter._parse_api_response(self.payload)
        defence = self.adapter.filter_defence(results)
        # Fixture: Kara Kuvvetleri + MSB → defence; Ankara Büyükşehir → not
        self.assertEqual(len(defence), 2, f"Expected 2, got {len(defence)}: {[r.authority for r in defence]}")

    def test_civilian_excluded(self):
        results = self.adapter._parse_api_response(self.payload)
        defence = self.adapter.filter_defence(results)
        authorities = [r.authority.lower() for r in defence]
        self.assertFalse(any("büyükşehir" in a for a in authorities))

    def test_msb_included(self):
        results = self.adapter._parse_api_response(self.payload)
        defence = self.adapter.filter_defence(results)
        authorities = " ".join(r.authority.lower() for r in defence)
        self.assertIn("milli savunma", authorities)


class TestParseTrDate(unittest.TestCase):
    """_parse_tr_date normalises Turkish date formats."""

    def test_dd_mm_yyyy(self):
        self.assertEqual(TrAdapter._parse_tr_date("15.03.2026"), "2026-03-15")

    def test_iso_date_passthrough(self):
        self.assertEqual(TrAdapter._parse_tr_date("2026-04-10"), "2026-04-10")

    def test_iso_datetime(self):
        self.assertEqual(TrAdapter._parse_tr_date("2026-04-10T00:00:00"), "2026-04-10")

    def test_empty_string(self):
        self.assertEqual(TrAdapter._parse_tr_date(""), "")

    def test_none_equivalent(self):
        self.assertEqual(TrAdapter._parse_tr_date("null"), "")


class TestParseHtmlResults(unittest.TestCase):
    """_parse_html_results extracts records from EKAP innerText."""

    def setUp(self):
        self.adapter = _make_adapter()

    def test_basic_parse(self):
        sample_text = """
İhale Arama Sonuçları
2026/456789
Kurum Adı: Kara Kuvvetleri Komutanlığı
Platform Römork Alımı
15.03.2026
4.500.000,00 TL

2026/123456
Kurum Adı: Milli Savunma Bakanlığı
Yarı Römork Alımı
10.04.2026
8.200.000,00 TL
"""
        results = self.adapter._parse_html_results(sample_text)
        self.assertGreaterEqual(len(results), 1)
        ref_ids = [r.reference_id for r in results]
        self.assertIn("2026/456789", ref_ids)

    def test_empty_text(self):
        results = self.adapter._parse_html_results("")
        self.assertEqual(results, [])

    def test_no_reference_numbers(self):
        results = self.adapter._parse_html_results("Hiç ihale bulunamadı.")
        self.assertEqual(results, [])


class TestGetDetailFallback(unittest.TestCase):
    """get_detail falls back gracefully when browser page text is empty."""

    def setUp(self):
        self.adapter = _make_adapter()
        self.adapter.browser.get_page_text.return_value = ""
        self.adapter.browser.goto.return_value = True
        self.adapter.browser._screenshot = MagicMock()

    def test_returns_notice_detail_from_result(self):
        result = SearchResult(
            title="Platform Römork Alımı",
            url="https://ekap.kik.gov.tr/EKAP/Ortak/IhaleDuyuruDetay/index.html?ihaleKayitNo=2026%2F456789",
            authority="Kara Kuvvetleri Komutanlığı",
            reference_id="2026/456789",
            date="2026-03-15",
            value=4_500_000.0,
            currency="TRY",
        )
        detail = self.adapter.get_detail(result)
        self.assertIsInstance(detail, NoticeDetail)
        self.assertEqual(detail.currency, "TRY")
        self.assertEqual(detail.reference_id, "2026/456789")

    def test_no_url_skips_browser(self):
        result = SearchResult(
            title="Römork Alımı",
            url="",
            authority="MSB",
            reference_id="2026/111111",
            date="2026-01-01",
        )
        detail = self.adapter.get_detail(result)
        self.assertIsInstance(detail, NoticeDetail)
        # Browser goto should NOT have been called (no URL)
        self.adapter.browser.goto.assert_not_called()


class TestToStandardFormatIdDedup(unittest.TestCase):
    """
    BaseAdapter.to_standard_format must not double-prefix reference_id.
    Sprint-14c guard: reference_id already starting with 'TR-' must not
    become 'TR-TR-...'.
    """

    def setUp(self):
        self.adapter = _make_adapter()

    def test_bare_id_gets_prefixed(self):
        d = NoticeDetail(reference_id="2026/456789", source_code="TR-EKAP")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["tender_id"], "TR-2026/456789")

    def test_already_prefixed_not_doubled(self):
        d = NoticeDetail(reference_id="TR-2026/456789", source_code="TR-EKAP")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(
            std["tender_id"], "TR-2026/456789",
            f"Expected non-doubled ID, got {std['tender_id']!r}",
        )

    def test_empty_id_stays_empty(self):
        d = NoticeDetail(reference_id="", source_code="TR-EKAP")
        self.assertEqual(self.adapter.to_standard_format(d)["tender_id"], "")

    def test_currency_is_try(self):
        d = NoticeDetail(
            reference_id="2026/456789", source_code="TR-EKAP",
            currency="TRY", value=4_500_000.0,
        )
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["_value_currency"], "TRY")
        self.assertEqual(std["_value_amount"], 4_500_000.0)

    def test_country_name_is_turkey(self):
        d = NoticeDetail(reference_id="2026/456789", source_code="TR-EKAP")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["_country_normalized"], "Turkey")


class TestEndToEnd(unittest.TestCase):
    """
    Full fixture round-trip:
    parse_api_response → filter_defence → get_detail (mocked) → to_standard_format
    """

    def setUp(self):
        self.adapter = _make_adapter()
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_pipeline_produces_valid_notices(self):
        results = self.adapter._parse_api_response(self.payload)
        defence = self.adapter.filter_defence(results)
        self.assertGreaterEqual(len(defence), 1)

        # Mock browser for get_detail
        self.adapter.browser.goto.return_value = True
        self.adapter.browser.get_page_text.return_value = (
            "Kurum Adı: Kara Kuvvetleri Komutanlığı\n"
            "İhale Konusu: Platform römork alımı askeri nakliye için\n"
            "Tahmini Bedel: 4.500.000,00 TL\n"
            "10 adet platform römork\n"
            "Sözleşme Süresi: 6 ay\n"
        )
        self.adapter.browser._screenshot = MagicMock()

        notices = []
        for r in defence:
            detail = self.adapter.get_detail(r)
            if detail:
                notices.append(self.adapter.to_standard_format(detail))

        self.assertEqual(len(notices), len(defence))
        for n in notices:
            self.assertIn("TR-", n["tender_id"])
            self.assertEqual(n["_value_currency"], "TRY")
            self.assertEqual(n["_country_normalized"], "Turkey")
            # No double prefix
            self.assertFalse(n["tender_id"].startswith("TR-TR-"))


if __name__ == "__main__":
    unittest.main()

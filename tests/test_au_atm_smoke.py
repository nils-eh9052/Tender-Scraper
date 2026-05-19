"""
Smoke tests for the AU-ATM adapter — Sprint 15 (2026-05-10).

Tests run entirely offline against mock/fixture data — no live AusTender
connection required.

Scenarios:
  1. _parse_rss_item parses a well-formed RSS item block
  2. _fetch_rss parses a minimal RSS XML with two items
  3. search() keyword-filters RSS results correctly
  4. filter_defence() applies OR logic (keyword | UNSPSC-25 | agency)
  5. _parse_austender_date normalises DD-Mon-YYYY and DD Mon YYYY formats
  6. _parse_rfc2822_date converts RFC 2822 pubDate to ISO
  7. get_detail() extracts fields from stripped ATM HTML page text
  8. to_standard_format() produces correct tender_id prefix and currency
  9. discover_for_notice() routes AU- prefix to national_text discovery

Run:
    python -m pytest tests/test_au_atm_smoke.py -v
    # or
    python3 -m unittest tests.test_au_atm_smoke -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.national_scraper.adapters.au_atm_adapter import (
    AuAtmAdapter,
    create_au_atm_config,
    _parse_austender_date,
    _parse_rfc2822_date,
    _extract_unspsc,
    _extract_description,
    _strip_html,
)
from src.national_scraper.base_adapter import NoticeDetail, SearchResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

RSS_ITEM_DEFENCE = """\
<item>
  <title>LAND121-PHASE4-2026: Cargo Trailer Procurement - ADF Light Force</title>
  <link>https://www.tenders.gov.au/Atm/Show/aaa00000-0000-0000-0000-000000000001</link>
  <description>&lt;p&gt;Procurement of military cargo trailers for the Australian Army under LAND 121 Phase 4.&lt;/p&gt;</description>
  <guid>https://www.tenders.gov.au/Atm/Show/aaa00000-0000-0000-0000-000000000001</guid>
  <pubDate>Mon, 05 May 2026 00:00:00 GMT</pubDate>
</item>"""

RSS_ITEM_CIVILIAN = """\
<item>
  <title>GA2026/564: Panel Refresh - Hazard Extent &amp; Information Services Panel</title>
  <link>https://www.tenders.gov.au/Atm/Show/1c0a3c70-363d-4362-944f-22ef307fbb5c</link>
  <description>&lt;p&gt;Open request for tenders for Multi-Hazard Extent panel refresh.&lt;/p&gt;</description>
  <guid>https://www.tenders.gov.au/Atm/Show/1c0a3c70-363d-4362-944f-22ef307fbb5c</guid>
  <pubDate>Wed, 01 Apr 2026 00:00:00 GMT</pubDate>
</item>"""

MINIMAL_RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AusTender Current ATM List</title>
    {RSS_ITEM_DEFENCE}
    {RSS_ITEM_CIVILIAN}
  </channel>
</rss>"""

DETAIL_PAGE_TEXT = (
    "Home Approaches to Market Contract Notices "
    "Current ATM View - LAND121-PHASE4-2026 "
    "Cargo Trailer Procurement - ADF Light Force "
    "Contact Details Tenders Officer Email Address : contracts@defence.gov.au "
    "ATM ID : LAND121-PHASE4-2026 "
    "Agency : Department of Defence "
    "Category : 25170000 - Trailers "
    "Close Date & Time : 30-Jun-2026 12:00 pm (ACT Local Time) "
    "Show close time for other time zones "
    "Publish Date : 5-May-2026 "
    "Location : ACT Canberra "
    "ATM Type : Request for Tender "
    "Multi Agency Access : No "
    "Description : Procurement of 40 military cargo trailers for the ADF Light Force "
    "under the LAND 121 Phase 4 programme. Full requirements in attachments. "
    "Other Instructions : See attachments. "
    "Contact Details Tenders Officer Email Address : contracts@defence.gov.au "
    "Return to top"
)


def _make_adapter() -> AuAtmAdapter:
    adapter = AuAtmAdapter(MagicMock(), create_au_atm_config())
    return adapter


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestParseRssItem(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_adapter()

    def test_defence_item_fields(self):
        r = self.adapter._parse_rss_item(RSS_ITEM_DEFENCE)
        self.assertIsNotNone(r)
        self.assertIn("Cargo Trailer", r.title)
        self.assertEqual(r.reference_id, "LAND121-PHASE4-2026")
        self.assertEqual(r.date, "2026-05-05")
        self.assertIn("tenders.gov.au/Atm/Show", r.url)
        self.assertIn("military cargo trailers", r.snippet.lower())

    def test_civilian_item_fields(self):
        r = self.adapter._parse_rss_item(RSS_ITEM_CIVILIAN)
        self.assertIsNotNone(r)
        self.assertEqual(r.reference_id, "GA2026/564")
        self.assertIn("Panel Refresh", r.title)
        self.assertEqual(r.date, "2026-04-01")

    def test_empty_authority_from_rss(self):
        r = self.adapter._parse_rss_item(RSS_ITEM_DEFENCE)
        self.assertEqual(r.authority, "")

    def test_missing_title_returns_none(self):
        bad = "<item><link>https://example.com</link></item>"
        self.assertIsNone(self.adapter._parse_rss_item(bad))


class TestFetchRss(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_adapter()

    def _mock_session_get(self, text: str, status: int = 200):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.text = text
        self.adapter._session.get = MagicMock(return_value=mock_resp)

    def test_parses_two_items(self):
        self._mock_session_get(MINIMAL_RSS)
        items = self.adapter._fetch_rss()
        self.assertEqual(len(items), 2)

    def test_result_is_cached(self):
        self._mock_session_get(MINIMAL_RSS)
        items1 = self.adapter._fetch_rss()
        items2 = self.adapter._fetch_rss()
        # Session.get should only have been called once
        self.assertEqual(self.adapter._session.get.call_count, 1)
        self.assertEqual(len(items1), len(items2))

    def test_http_error_returns_empty(self):
        self._mock_session_get("", status=503)
        items = self.adapter._fetch_rss()
        self.assertEqual(items, [])

    def test_rss_item_count_in_expected_range(self):
        # Ensures a realistic RSS (100–500 items) passes sanity check
        self._mock_session_get(MINIMAL_RSS)
        items = self.adapter._fetch_rss()
        self.assertGreaterEqual(len(items), 1)
        self.assertLessEqual(len(items), 500)


class TestSearch(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MINIMAL_RSS
        self.adapter._session.get = MagicMock(return_value=mock_resp)

    def test_trailer_keyword_matches_defence_item(self):
        results = self.adapter.search("trailer")
        titles = [r.title for r in results]
        self.assertTrue(any("Cargo Trailer" in t for t in titles))

    def test_unrelated_keyword_returns_nothing(self):
        results = self.adapter.search("submarine periscope maintenance")
        self.assertEqual(len(results), 0)

    def test_max_results_respected(self):
        results = self.adapter.search("trailer", max_results=1)
        self.assertLessEqual(len(results), 1)


class TestFilterDefence(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_adapter()

    def _make_result(self, title="", authority="", snippet="") -> SearchResult:
        return SearchResult(title=title, url="https://example.com", authority=authority,
                            snippet=snippet)

    def test_keyword_match_kept(self):
        r = self._make_result(title="Cargo trailer procurement 40 units")
        kept = self.adapter.filter_defence([r])
        self.assertEqual(len(kept), 1)

    def test_defence_auth_kept(self):
        r = self._make_result(authority="Department of Defence", title="Catering Services")
        kept = self.adapter.filter_defence([r])
        self.assertEqual(len(kept), 1)

    def test_unspsc_25_kept(self):
        r = self._make_result(title="Vehicle procurement", snippet="unspsc=25170000 vehicles")
        kept = self.adapter.filter_defence([r])
        self.assertEqual(len(kept), 1)

    def test_civilian_no_match_dropped(self):
        r = self._make_result(title="Office cleaning services", authority="Department of Finance")
        kept = self.adapter.filter_defence([r])
        self.assertEqual(len(kept), 0)

    def test_or_logic_any_condition_sufficient(self):
        only_auth = self._make_result(authority="Royal Australian Navy", title="Rope procurement")
        only_kw   = self._make_result(title="Low-loader transport 5 units", authority="ATO")
        kept = self.adapter.filter_defence([only_auth, only_kw])
        self.assertEqual(len(kept), 2)


class TestParseAustenderDate(unittest.TestCase):

    def test_dd_mon_yyyy(self):
        self.assertEqual(_parse_austender_date("11-May-2026"), "2026-05-11")

    def test_d_mon_yyyy_no_leading_zero(self):
        self.assertEqual(_parse_austender_date("1-Apr-2026"), "2026-04-01")

    def test_with_time_suffix(self):
        self.assertEqual(_parse_austender_date("30-Jun-2026 12:00 pm"), "2026-06-30")

    def test_space_separated(self):
        self.assertEqual(_parse_austender_date("01 Apr 2026"), "2026-04-01")

    def test_empty_returns_empty(self):
        self.assertEqual(_parse_austender_date(""), "")

    def test_unknown_format_returns_empty(self):
        self.assertEqual(_parse_austender_date("2026/06/30"), "")


class TestParseRfc2822Date(unittest.TestCase):

    def test_typical_pubdate(self):
        self.assertEqual(_parse_rfc2822_date("Wed, 01 Apr 2026 00:00:00 GMT"), "2026-04-01")

    def test_mon_day(self):
        self.assertEqual(_parse_rfc2822_date("Mon, 05 May 2026 00:00:00 GMT"), "2026-05-05")

    def test_bad_input_returns_empty(self):
        self.assertEqual(_parse_rfc2822_date("not a date"), "")


class TestGetDetail(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = f"<html><body>{DETAIL_PAGE_TEXT}</body></html>"
        self.adapter._session.get = MagicMock(return_value=mock_resp)

    def test_returns_notice_detail(self):
        r = SearchResult(
            title="Cargo Trailer Procurement - ADF Light Force",
            url="https://www.tenders.gov.au/Atm/Show/aaa00000-0000-0000-0000-000000000001",
            reference_id="LAND121-PHASE4-2026",
        )
        detail = self.adapter.get_detail(r)
        self.assertIsInstance(detail, NoticeDetail)

    def test_agency_extracted(self):
        r = SearchResult(title="x", url="https://www.tenders.gov.au/Atm/Show/aaa-001")
        detail = self.adapter.get_detail(r)
        self.assertEqual(detail.authority, "Department of Defence")

    def test_deadline_extracted(self):
        r = SearchResult(title="x", url="https://www.tenders.gov.au/Atm/Show/aaa-001")
        detail = self.adapter.get_detail(r)
        self.assertEqual(detail.deadline, "2026-06-30")

    def test_pub_date_extracted(self):
        r = SearchResult(title="x", url="https://www.tenders.gov.au/Atm/Show/aaa-001")
        detail = self.adapter.get_detail(r)
        self.assertEqual(detail.date, "2026-05-05")

    def test_unspsc_in_raw_text(self):
        r = SearchResult(title="x", url="https://www.tenders.gov.au/Atm/Show/aaa-001")
        detail = self.adapter.get_detail(r)
        self.assertIn("UNSPSC: 25170000", detail.raw_text)

    def test_status_is_open(self):
        r = SearchResult(title="x", url="https://www.tenders.gov.au/Atm/Show/aaa-001")
        detail = self.adapter.get_detail(r)
        self.assertEqual(detail.status, "Open")

    def test_currency_is_aud(self):
        r = SearchResult(title="x", url="https://www.tenders.gov.au/Atm/Show/aaa-001")
        detail = self.adapter.get_detail(r)
        self.assertEqual(detail.currency, "AUD")

    def test_no_url_returns_none(self):
        r = SearchResult(title="x", url="")
        detail = self.adapter.get_detail(r)
        self.assertIsNone(detail)


class TestToStandardFormat(unittest.TestCase):

    def setUp(self):
        self.adapter = _make_adapter()

    def test_tender_id_prefixed(self):
        d = NoticeDetail(reference_id="LAND121-001", source_code="AU-AT")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["tender_id"], "AU-LAND121-001")

    def test_tender_id_not_double_prefixed(self):
        d = NoticeDetail(reference_id="AU-LAND121-001", source_code="AU-AT")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["tender_id"], "AU-LAND121-001")

    def test_currency_is_aud(self):
        d = NoticeDetail(reference_id="X", source_code="AU-AT", currency="AUD", value=500000.0)
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["_value_currency"], "AUD")
        self.assertEqual(std["_value_amount"], 500000.0)

    def test_country_name_is_australia(self):
        d = NoticeDetail(reference_id="X", source_code="AU-AT")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["_country_normalized"], "Australia")

    def test_source_code(self):
        d = NoticeDetail(reference_id="X", source_code="AU-AT")
        std = self.adapter.to_standard_format(d)
        self.assertEqual(std["source"], "AU-AT")


class TestDiscoveryRouting(unittest.TestCase):
    """discover_for_notice routes AU- notices to national_text (no auth docs)."""

    def test_au_notice_returns_text_doc_when_raw_text_present(self):
        from src.document_pipeline.discovery import discover_for_notice
        notice = {
            "tender_id": "AU-LAND121-001",
            "_national_raw_text": "UNSPSC: 25170000\nCargo trailer procurement " * 5,
            "source": "AU-AT",
        }
        docs = discover_for_notice(notice)
        self.assertGreaterEqual(len(docs), 1)
        self.assertEqual(docs[0].source, "AU-AT")
        self.assertEqual(docs[0].format, "txt")

    def test_au_notice_empty_raw_text_returns_empty(self):
        from src.document_pipeline.discovery import discover_for_notice
        notice = {
            "tender_id": "AU-LAND121-002",
            "_national_raw_text": "",
            "source": "AU-AT",
        }
        docs = discover_for_notice(notice)
        self.assertEqual(docs, [])


class TestHelpers(unittest.TestCase):

    def test_extract_unspsc_from_category_label(self):
        text = "Agency : Dept of Defence Category : 25170000 - Trailers Close Date"
        self.assertEqual(_extract_unspsc(text), "25170000")

    def test_extract_description(self):
        text = (
            "ATM ID : X Agency : Y Category : 12345678 "
            "Description : Procurement of 40 cargo trailers for the ADF. "
            "Other Instructions : See attachments."
        )
        desc = _extract_description(text)
        self.assertIn("cargo trailers", desc)
        self.assertNotIn("Other Instructions", desc)

    def test_strip_html_removes_tags(self):
        html = "<p>Hello <b>world</b></p><script>alert(1)</script>"
        result = _strip_html(html)
        self.assertEqual(result, "Hello world")


if __name__ == "__main__":
    unittest.main()

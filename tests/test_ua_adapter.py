"""
Smoke tests for the UA-Prozorro adapter — Sprint 14c bug fixes.

Two regressions under test:
  1. Tender-ID prefix doubling: detail.reference_id="UA-2026-..." was rendered as
     "UA-UA-2026-..." by base_adapter.to_standard_format.
  2. Missing value extraction: Prozorro stores the monetary amount on
     lots[0].value.amount when the top-level value is empty.

Tests use a saved API response (tests/fixtures/ua_011067a.json) for tender
UA-2026-04-08-011067-a — running against the live Prozorro API requires
network access and is out of scope for unit tests.

Run:
    python3 -m unittest tests.test_ua_adapter -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.national_scraper.adapters.ua_adapter import (
    UAAdapter,
    _extract_ua_value,
    create_ua_config,
)
from src.national_scraper.base_adapter import NoticeDetail, SearchResult


FIXTURE = Path(__file__).parent / "fixtures" / "ua_011067a.json"


def _make_adapter() -> UAAdapter:
    return UAAdapter(MagicMock(), create_ua_config())


class TestExtractValue(unittest.TestCase):
    def test_top_level_value_wins(self):
        amt, cur = _extract_ua_value(
            {"value": {"amount": 100, "currency": "UAH"}}
        )
        self.assertEqual(amt, 100.0)
        self.assertEqual(cur, "UAH")

    def test_falls_back_to_first_lot_with_amount(self):
        amt, cur = _extract_ua_value({
            "value": {},
            "lots": [{"value": {"amount": 20_800_000, "currency": "UAH"}}],
        })
        self.assertEqual(amt, 20_800_000.0)
        self.assertEqual(cur, "UAH")

    def test_skips_zero_amount_lot(self):
        amt, cur = _extract_ua_value({
            "lots": [
                {"value": {"amount": 0}},
                {"value": {"amount": 1_500_000, "currency": "UAH"}},
            ],
        })
        self.assertEqual(amt, 1_500_000.0)
        self.assertEqual(cur, "UAH")

    def test_minimal_step_fallback(self):
        amt, cur = _extract_ua_value(
            {"minimalStep": {"amount": 5_000, "currency": "UAH"}}
        )
        self.assertEqual(amt, 5_000.0)
        self.assertEqual(cur, "UAH")

    def test_returns_none_when_no_amount(self):
        self.assertEqual(_extract_ua_value({}), (None, None))
        self.assertEqual(_extract_ua_value({"value": {"amount": 0}}), (None, None))


class TestUaTenderEnd2End(unittest.TestCase):
    """
    Drives UAAdapter.get_detail against a saved Prozorro response, then pushes
    the NoticeDetail through to_standard_format and asserts on the keys the
    exporter consumes.
    """

    def setUp(self):
        self.adapter = _make_adapter()
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_value_resolves_from_lots_and_id_is_not_doubled(self):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = self.payload
        self.adapter._session.get = lambda *a, **kw: fake_resp  # type: ignore[assignment]

        seed = SearchResult(
            title="Закупівля транспортних причепів",
            url="https://prozorro.gov.ua/tender/UA-2026-04-08-011067-a",
            authority="Державний оператор тилу",
            reference_id="UA-2026-04-08-011067-a",
            date="2026-04-08",
            value=None,
            currency="UAH",
            snippet=json.dumps({"id": "f4a8c1e2b9d34a7f8c1e2b9d34a7f8c1"}),
        )

        detail = self.adapter.get_detail(seed)

        self.assertIsInstance(detail, NoticeDetail)
        self.assertEqual(
            detail.value, 20_800_000.0,
            f"expected lots[0].value.amount=20800000, got {detail.value}",
        )
        self.assertEqual(detail.currency, "UAH")
        self.assertEqual(detail.date, "2026-04-08")
        self.assertEqual(detail.reference_id, "UA-2026-04-08-011067-a")

        std = self.adapter.to_standard_format(detail)
        self.assertEqual(
            std["tender_id"], "UA-2026-04-08-011067-a",
            f"expected non-doubled ID, got {std['tender_id']!r}",
        )
        self.assertEqual(std["_value_amount"], 20_800_000.0)
        self.assertEqual(std["_value_currency"], "UAH")
        self.assertEqual(std["_pub_date_clean"], "2026-04-08")


class TestIdPrefixDedup(unittest.TestCase):
    """
    Direct check on BaseAdapter.to_standard_format: a reference_id that
    already starts with the country prefix must NOT be prefixed again.
    """

    def setUp(self):
        self.adapter = _make_adapter()

    def test_already_prefixed_is_not_doubled(self):
        d = NoticeDetail(reference_id="UA-2026-04-08-011067-a", source_code="UA-PR")
        self.assertEqual(
            self.adapter.to_standard_format(d)["tender_id"],
            "UA-2026-04-08-011067-a",
        )

    def test_bare_id_gets_prefixed(self):
        d = NoticeDetail(reference_id="2026-04-08-011067-a", source_code="UA-PR")
        self.assertEqual(
            self.adapter.to_standard_format(d)["tender_id"],
            "UA-2026-04-08-011067-a",
        )

    def test_empty_id_stays_empty(self):
        d = NoticeDetail(reference_id="", source_code="UA-PR")
        self.assertEqual(self.adapter.to_standard_format(d)["tender_id"], "")


if __name__ == "__main__":
    unittest.main()

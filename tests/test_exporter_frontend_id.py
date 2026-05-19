"""Smoke tests for ``src.exporter_frontend`` — Sprint 14a follow-up.

Two regressions are covered:

1.  Pre-Sprint-14c entries in ``relevant.json`` carry a doubled
    country-code prefix (``UA-UA-2026-...``). The exporter must
    de-duplicate the prefix when emitting the frontend ``id``.

2.  UAH→EUR conversion via the Sprint-14a Pfad-3 lookup
    (``_value_amount`` + ``_value_currency``) must yield a sensible
    EUR value when the data is present, including the newline-bug
    edge case (``"UAH\\nUAH"``).

The tests use stdlib ``unittest`` and synthetic notices — no
``relevant.json`` or ``shared/tenders.json`` is touched.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Allow ``python -m unittest tests.test_exporter_frontend_id`` from the
# scraper root; mirrors tests/test_ua_adapter.py
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.exporter_frontend import (   # noqa: E402
    _FX,
    _format_tender_id,
    _map_notice,
    _resolve_value_eur,
)


class FormatTenderIdTests(unittest.TestCase):
    """De-duplication of the country-code prefix."""

    def test_ua_double_prefix_is_stripped(self):
        self.assertEqual(
            _format_tender_id("UA-UA-2026-04-08-011067-a", "UA"),
            "UA-2026-04-08-011067-a",
        )

    def test_nl_double_prefix_is_stripped(self):
        self.assertEqual(
            _format_tender_id("NL-NL-577684", "NL"),
            "NL-577684",
        )

    def test_correct_prefix_is_idempotent(self):
        self.assertEqual(
            _format_tender_id("UA-2026-04-08-011067-a", "UA"),
            "UA-2026-04-08-011067-a",
        )

    def test_missing_prefix_is_added(self):
        # Edge case from the spec: raw national-shaped ID without prefix.
        self.assertEqual(
            _format_tender_id("2026-04-08-011067-a", "UA"),
            "UA-2026-04-08-011067-a",
        )

    def test_ted_numeric_id_is_never_touched(self):
        # 572650-2024 is a TED publication number; it must NOT receive
        # an SE- prefix even though the country resolves to Sweden.
        self.assertEqual(_format_tender_id("572650-2024", "SE"), "572650-2024")
        self.assertEqual(_format_tender_id("182178-2026", "SE"), "182178-2026")

    def test_blank_inputs_are_safe(self):
        self.assertEqual(_format_tender_id("", "UA"), "")
        self.assertEqual(_format_tender_id("UA-...", ""), "UA-...")

    def test_other_national_id_with_prefix_unchanged(self):
        # Adapter-supplied IDs that already look correct stay as is.
        self.assertEqual(
            _format_tender_id("CZ-N006/26/V00010428", "CZ"),
            "CZ-N006/26/V00010428",
        )
        self.assertEqual(
            _format_tender_id("FR-21-163372", "FR"),
            "FR-21-163372",
        )


class UahConversionTests(unittest.TestCase):
    """UAH→EUR conversion through ``_resolve_value_eur`` (Pfad 3)."""

    def setUp(self):
        # Snapshot the rate so failures are clearly attributable when the
        # _FX dict is updated quarterly.
        self.rate = _FX.get("UAH")

    def test_uah_rate_present(self):
        self.assertIsNotNone(self.rate, "_FX must include UAH (Sprint 14a)")
        # Loose sanity bracket — UAH/EUR has lived around 0.02 for years.
        self.assertGreater(self.rate, 0.01)
        self.assertLess(self.rate, 0.05)

    def test_uah_value_amount_path(self):
        # The Sprint-14c UA adapter writes _value_amount + _value_currency
        # via to_standard_format. _resolve_value_eur Pfad 3 must pick this up.
        notice = {
            "tender_id": "UA-2026-04-08-011067-a",
            "_value_amount": 20_800_000,
            "_value_currency": "UAH",
        }
        result = _resolve_value_eur(notice)
        expected = round(20_800_000 * self.rate, 2)
        self.assertAlmostEqual(result, expected, delta=10_000)
        # Hard sanity range ±10 k around the spec target ~478 400.
        self.assertGreater(result, 460_000)
        self.assertLess(result, 500_000)

    def test_uah_currency_newline_is_normalised(self):
        # Same newline edge case as NOK/BGN earlier; exporter must
        # accept ``UAH\nUAH`` and resolve to UAH.
        notice = {
            "tender_id": "UA-2026-04-08-011067-a",
            "_value_amount": 20_800_000,
            "_value_currency": "UAH\nUAH",
        }
        result = _resolve_value_eur(notice)
        self.assertGreater(result, 460_000)
        self.assertLess(result, 500_000)

    def test_uah_via_estimated_value_dict(self):
        # Pfad 2 (TED-style payload) must also handle UAH.
        notice = {
            "tender_id": "TEST-UAH",
            "estimated_value": {"amount": 20_800_000, "currency": "UAH"},
        }
        result = _resolve_value_eur(notice)
        self.assertGreater(result, 460_000)

    def test_no_value_data_returns_zero(self):
        # The actual UA-Tender currently ships with no value data —
        # Exporter must not invent numbers, fall through to 0.
        notice = {"tender_id": "UA-2026-04-08-011067-a"}
        self.assertEqual(_resolve_value_eur(notice), 0)


class MapNoticeIdEndToEndTests(unittest.TestCase):
    """``_map_notice`` writes the de-duplicated id field."""

    def test_ua_double_prefix_in_relevant_json_emits_clean_id(self):
        notice = {
            "tender_id": "UA-UA-2026-04-08-011067-a",
            "_country_normalized": "Ukraine",
            "_title_english": "Military Semi-trailer Low-bed Transporter",
            "_pub_date_clean": "2026-04-08",
        }
        out = _map_notice(notice, overrides={})
        self.assertEqual(out["id"], "UA-2026-04-08-011067-a")
        self.assertEqual(out["country_code"], "UA")
        self.assertEqual(out["country"], "Ukraine")

    def test_ted_id_is_passed_through(self):
        notice = {
            "tender_id": "572650-2024",
            "_country_normalized": "Netherlands",
            "_title_english": "Military Medical Trailers",
        }
        out = _map_notice(notice, overrides={})
        self.assertEqual(out["id"], "572650-2024")


if __name__ == "__main__":
    unittest.main(verbosity=2)

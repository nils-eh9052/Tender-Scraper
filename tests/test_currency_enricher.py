"""Stdlib-unittest tests for src.currency_enricher (Sprint 2026-05-09)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.currency_enricher import (   # noqa: E402
    AMOUNT_PATTERN,
    _format_eur,
    _parse_amount,
    enrich_description,
)


class ParseAmountTests(unittest.TestCase):
    """Locale-tolerant amount parser."""

    def test_en_thousands_with_decimal(self):
        self.assertAlmostEqual(_parse_amount("123,293.66"), 123293.66, places=2)

    def test_eu_thousands_with_decimal(self):
        self.assertAlmostEqual(_parse_amount("123.293,66"), 123293.66, places=2)

    def test_fr_space_thousands(self):
        self.assertAlmostEqual(_parse_amount("123 293,66"), 123293.66, places=2)

    def test_no_separator_with_decimal(self):
        self.assertAlmostEqual(_parse_amount("39999.99"), 39999.99, places=2)

    def test_ambiguous_thousand_format(self):
        # "1,234" with exactly three trailing digits → treated as thousands
        self.assertAlmostEqual(_parse_amount("1,234"), 1234.0, places=2)

    def test_ambiguous_decimal_two_digits(self):
        self.assertAlmostEqual(_parse_amount("1,23"), 1.23, places=2)

    def test_en_three_groups(self):
        self.assertAlmostEqual(_parse_amount("20,800,000"), 20_800_000.0, places=2)

    def test_eu_three_groups(self):
        self.assertAlmostEqual(_parse_amount("20.800.000"), 20_800_000.0, places=2)

    def test_simple_int(self):
        self.assertAlmostEqual(_parse_amount("12345"), 12345.0, places=2)

    def test_blank_returns_none(self):
        self.assertIsNone(_parse_amount(""))
        self.assertIsNone(_parse_amount("   "))


class FormatEurTests(unittest.TestCase):
    def test_under_1000(self):
        self.assertEqual(_format_eur(932.4), "932")

    def test_thousands(self):
        self.assertEqual(_format_eur(4932), "4.9K")

    def test_millions(self):
        self.assertEqual(_format_eur(478_400), "478.4K")
        self.assertEqual(_format_eur(2_500_000), "2.5M")


class AmountPatternTests(unittest.TestCase):
    """The regex must catch what we need and skip what we don't."""

    def test_simple_czk(self):
        m = AMOUNT_PATTERN.search("estimated value of 123,293.66 CZK.")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2).upper(), "CZK")

    def test_uah_with_million(self):
        m = AMOUNT_PATTERN.search("budget 20,800,000 UAH for trailers")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "20,800,000")

    def test_eur_is_not_in_pattern(self):
        # EUR is intentionally NOT enriched (it's already EUR).
        self.assertIsNone(AMOUNT_PATTERN.search("price 1,000.00 EUR"))

    def test_currency_not_followed_by_letters(self):
        # "TRYx" must not match TRY
        self.assertIsNone(AMOUNT_PATTERN.search("12345 TRYxx done"))

    def test_two_matches_in_one_text(self):
        text = "value of 123,293.66 CZK. Maximum price is 39,999.99 CZK including VAT."
        matches = AMOUNT_PATTERN.findall(text)
        self.assertEqual(len(matches), 2)


class EnrichDescriptionTests(unittest.TestCase):
    """End-to-end enrichment with FX rates."""

    FX = {
        "CZK": 0.040,
        "PLN": 0.233,
        "UAH": 0.023,
        "NOK": 0.085,
        "RON": 0.201,
        "BGN": 0.511,
    }

    def test_spec_example(self):
        text = (
            "Small-scale public contract with estimated value of 123,293.66 CZK. "
            "Maximum price per trailer unit is 39,999.99 CZK including VAT."
        )
        out, n = enrich_description(text, self.FX)
        self.assertEqual(n, 2)
        self.assertIn("123,293.66 CZK (~€4.9K)", out)
        self.assertIn("39,999.99 CZK (~€1.6K)", out)

    def test_uah_million(self):
        text = "Procurement budget 20,800,000 UAH for trailers."
        out, n = enrich_description(text, self.FX)
        self.assertEqual(n, 1)
        self.assertIn("20,800,000 UAH (~€478.4K)", out)

    def test_no_currency_unchanged(self):
        text = "Procurement of military trailers for the Armed Forces."
        out, n = enrich_description(text, self.FX)
        self.assertEqual(n, 0)
        self.assertEqual(out, text)

    def test_unknown_currency_unchanged(self):
        # JPY is in _SUPPORTED but not in our test FX dict
        text = "budget 1,000,000 JPY for office supplies."
        out, n = enrich_description(text, self.FX)
        self.assertEqual(n, 0)
        self.assertEqual(out, text)

    def test_idempotent(self):
        # Running twice must not double-append.
        text = "estimated value 32,000 PLN."
        once, n1 = enrich_description(text, self.FX)
        twice, n2 = enrich_description(once, self.FX)
        self.assertEqual(once, twice)
        self.assertEqual(n2, 0)
        self.assertEqual(n1, 1)
        self.assertIn("(~€7.5K)", once)

    def test_blank_text_returns_blank(self):
        out, n = enrich_description("", self.FX)
        self.assertEqual(out, "")
        self.assertEqual(n, 0)

    def test_below_threshold_skipped(self):
        # 1 RON ≈ €0.20 < €1 → no enrichment to avoid noise
        text = "minor cost 1 RON listed."
        out, n = enrich_description(text, self.FX)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

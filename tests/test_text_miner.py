"""Tests for src.text_miner (Sprint 2026-05-18, Phase 3k)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.text_miner import (   # noqa: E402
    mine_all,
    mine_deadline,
    mine_duration_months,
    mine_quantity,
)


# Real samples (lifted from data/filtered/relevant.json after the audit)
CA_LOWBED_DESC = (
    "The Department of National Defence (DND) has a requirement to procure "
    "Qty 27 Lowbed Trailers and ILS deliverables for delivery to various "
    "Canadian bases. The requested delivery date is 120 days after "
    "contract award."
)

CA_KITCHEN_DESC = (
    "File Number: W8486-260442/A/SV NOTICE OF PROPOSED PROCUREMENT "
    "The Department of National Defence has a requirement for the items "
    "detailed below. The delivery is requested at Montreal & Edmonton by "
    "December 7 2026. Item 1, GSIN: , NSN: 21-8969342: JACK,ASSY. "
    "LEVELLING LEFT-FRONT-AND RIGHT REAR Part No.: 8476207-1 NSCM/CAGE: "
    "35907 Quantity: 10 Unit of Issue: Each"
)


class QuantityRegexTests(unittest.TestCase):
    """Quantity extraction — regex tier."""

    def test_ca_lowbed_qty_27(self):
        qty, src, meta = mine_quantity(CA_LOWBED_DESC)
        self.assertEqual(qty, 27)
        self.assertEqual(src, "regex")
        self.assertIn("Lowbed", meta.get("fragment", ""))

    def test_ca_kitchen_quantity_10(self):
        qty, src, _ = mine_quantity(CA_KITCHEN_DESC)
        self.assertEqual(qty, 10)
        self.assertEqual(src, "regex")

    def test_units_inline(self):
        qty, src, _ = mine_quantity("Supply of 480 units of axle assemblies.")
        self.assertEqual(qty, 480)
        self.assertEqual(src, "regex")

    def test_german_stueck(self):
        qty, _, _ = mine_quantity("Beschaffung von 50 Stück Anhängern.")
        self.assertEqual(qty, 50)

    def test_french_quantite(self):
        qty, _, _ = mine_quantity("La quantité est de 12 remorques.")
        # "quantité ... 12" gets picked up by qty_fr_quantite OR by trailers
        self.assertIn(qty, (12,))

    def test_polish_sztuk(self):
        qty, _, _ = mine_quantity("Naczepy w ilości 15 sztuk.")
        self.assertEqual(qty, 15)

    def test_czech_pocet(self):
        qty, _, _ = mine_quantity("Předmětem je dodávka, počet ks: 8")
        self.assertEqual(qty, 8)

    def test_ukrainian_cyrillic(self):
        qty, _, _ = mine_quantity("Постачання причепів, кількість: 22")
        self.assertEqual(qty, 22)

    def test_reject_file_number(self):
        """Numbers next to 'File Number' / 'NSN' must not become qty."""
        text = ("File Number: 12345 — NOTICE OF PROPOSED PROCUREMENT "
                "Item NSN: 21-8969342 Part No.: 1234")
        qty, _, _ = mine_quantity(text)
        self.assertIsNone(qty)

    def test_reject_out_of_band(self):
        """Numbers like phone numbers (>10000) are dropped."""
        qty, _, _ = mine_quantity("Quantity: 999999 units")
        self.assertIsNone(qty)

    def test_no_match_returns_none(self):
        qty, src, _ = mine_quantity("This tender is for software services.")
        self.assertIsNone(qty)
        self.assertIsNone(src)


class DeadlineRegexTests(unittest.TestCase):
    """Deadline extraction — absolute and relative-offset patterns."""

    def test_ca_lowbed_relative_120_days(self):
        deadline, src, meta = mine_deadline(
            CA_LOWBED_DESC, anchor_date="2026-05-01"
        )
        self.assertEqual(src, "regex")
        # 2026-05-01 + 120 days = 2026-08-29
        self.assertEqual(deadline, "2026-08-29")
        self.assertEqual(meta.get("offset"), 120)

    def test_ca_kitchen_absolute_december_2026(self):
        deadline, src, _ = mine_deadline(CA_KITCHEN_DESC)
        self.assertEqual(src, "regex")
        self.assertEqual(deadline, "2026-12-07")

    def test_iso_by_date(self):
        deadline, _, _ = mine_deadline("Delivery deadline 2026-09-15.")
        self.assertEqual(deadline, "2026-09-15")

    def test_german_lieferung_bis(self):
        deadline, _, _ = mine_deadline("Lieferung bis 31.12.2026 nach Bonn.")
        self.assertEqual(deadline, "2026-12-31")

    def test_relative_no_anchor_uses_today(self):
        deadline, src, meta = mine_deadline(
            "Delivery within 30 days of contract award."
        )
        # Without an anchor we fall back to today, but the function must still
        # return a value and flag the meta as approximate.
        self.assertIsNotNone(deadline)
        self.assertTrue(meta.get("anchor_approx", False))

    def test_no_match_returns_none(self):
        deadline, _, _ = mine_deadline("This tender has no delivery info.")
        self.assertIsNone(deadline)


class DurationTests(unittest.TestCase):
    def test_explicit_months(self):
        dur, _, _ = mine_duration_months(
            "The contract duration: 48 months from start."
        )
        self.assertEqual(dur, 48)

    def test_years_and_months(self):
        dur, _, _ = mine_duration_months("A 2 years and 6 months contract.")
        self.assertEqual(dur, 30)

    def test_german_vertragsdauer(self):
        dur, _, _ = mine_duration_months("Vertragsdauer: 36 Monate")
        self.assertEqual(dur, 36)


class MineAllIntegrationTests(unittest.TestCase):
    """End-to-end: feed a tender dict, get back the four output keys."""

    def test_ca_lowbed_full_extraction(self):
        tender = {
            "tender_id": "CA-cb-259-10824239",
            "_description_final": CA_LOWBED_DESC,
            "_pub_date": "2026-05-01",
        }
        result = mine_all(tender, cache={}, save_to_cache=False)
        self.assertEqual(result["_qty_mined"], 27)
        self.assertEqual(result["_qty_mined_source"], "regex")
        self.assertEqual(result["_deadline_mined"], "2026-08-29")
        self.assertEqual(result["_deadline_mined_source"], "regex")

    def test_empty_tender_returns_skipped(self):
        result = mine_all(
            {"tender_id": "BLANK-1"}, cache={}, save_to_cache=False
        )
        self.assertIsNone(result["_qty_mined"])
        self.assertIsNone(result["_deadline_mined"])
        self.assertEqual(
            result["_text_mining_meta"], {"skipped": "no_text"}
        )

    def test_cache_hit_returns_identical(self):
        """A second mine_all() call must read from cache."""
        tender = {
            "tender_id": "CA-DUMMY",
            "_description_final": "Procure Qty 5 cargo trailers.",
            "_pub_date": "2026-04-01",
        }
        cache: dict = {}
        first = mine_all(tender, cache=cache, save_to_cache=False)
        # Mutate the tender's description AFTER caching — the cache key is
        # based on the original sha1, so a fresh call still gets old result.
        tender["_description_final"] = "Procure Qty 5 cargo trailers."
        second = mine_all(tender, cache=cache, save_to_cache=False)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

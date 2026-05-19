"""Smoke-tests for _clean_date in exporter_frontend.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from exporter_frontend import _clean_date


class CleanDateTests(unittest.TestCase):
    # Normal ISO inputs
    def test_plain_iso(self):
        self.assertEqual(_clean_date("2025-12-12"), "2025-12-12")

    def test_tz_plus_offset(self):
        self.assertEqual(_clean_date("2025-12-12+01:00"), "2025-12-12")

    def test_tz_z(self):
        self.assertEqual(_clean_date("2025-12-12Z"), "2025-12-12")

    def test_datetime_with_t(self):
        self.assertEqual(_clean_date("2025-12-12T10:00:00+01:00"), "2025-12-12")

    # Multi-line (TED API multi-lot bug)
    def test_multiline_same_date(self):
        val = "2025-12-12+01:00\n2025-12-12+01:00\n2025-12-12+01:00\n2025-12-12+01:00"
        self.assertEqual(_clean_date(val), "2025-12-12")

    def test_multiline_different_dates(self):
        # First line wins
        val = "2025-11-30+01:00\n2025-12-12+01:00"
        self.assertEqual(_clean_date(val), "2025-11-30")

    # List input
    def test_list_single(self):
        self.assertEqual(_clean_date(["2025-12-12+01:00"]), "2025-12-12")

    def test_list_multiple(self):
        self.assertEqual(_clean_date(["2025-12-12+01:00", "2025-12-15+01:00"]), "2025-12-12")

    def test_list_empty(self):
        self.assertEqual(_clean_date([]), "")

    # Edge / error cases
    def test_none(self):
        self.assertEqual(_clean_date(None), "")

    def test_empty_string(self):
        self.assertEqual(_clean_date(""), "")

    def test_garbage(self):
        self.assertEqual(_clean_date("not-a-date"), "")

    def test_partial_date(self):
        self.assertEqual(_clean_date("2025-12"), "")

    def test_zero(self):
        self.assertEqual(_clean_date(0), "")


if __name__ == "__main__":
    unittest.main()

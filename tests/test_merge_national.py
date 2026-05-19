"""Smoke-tests for tender_id dedup in merge_national_with_ted (main.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import merge_national_with_ted


def _make(tid: str, auth: str | None = None, title: str | None = None, year: str = "2026") -> dict:
    return {
        "tender_id": tid,
        "contracting_authority": {"name": auth or f"Authority-{tid}"},
        "title": title or f"Procurement notice {tid}",
        "publication_date": f"{year}-01-01",
        "source": "NAT",
    }


class MergeNationalDedupTests(unittest.TestCase):

    def test_same_id_not_duplicated(self):
        """Force-include + freshly scraped same ID → only 1 record in output."""
        existing = [_make("CZ-2026-001")]
        nationals = [_make("CZ-2026-001")]
        result = merge_national_with_ted(existing, nationals)
        ids = [r["tender_id"] for r in result]
        self.assertEqual(ids.count("CZ-2026-001"), 1)

    def test_new_id_is_added(self):
        """1 existing + 1 new national → 2 total."""
        existing = [_make("CZ-2026-001")]
        nationals = [_make("CZ-2026-002")]
        result = merge_national_with_ted(existing, nationals)
        self.assertEqual(len(result), 2)

    def test_dup_plus_new(self):
        """1 existing + 2 nationals (1 dup, 1 new) → 2 total, not 3."""
        existing = [_make("CZ-2026-001")]
        nationals = [_make("CZ-2026-001"), _make("CZ-2026-003")]
        result = merge_national_with_ted(existing, nationals)
        self.assertEqual(len(result), 2)
        ids = {r["tender_id"] for r in result}
        self.assertIn("CZ-2026-001", ids)
        self.assertIn("CZ-2026-003", ids)

    def test_empty_nationals(self):
        existing = [_make("CZ-2026-001")]
        result = merge_national_with_ted(existing, [])
        self.assertEqual(len(result), 1)

    def test_empty_existing(self):
        nationals = [_make("CZ-2026-001"), _make("CZ-2026-002")]
        result = merge_national_with_ted([], nationals)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()

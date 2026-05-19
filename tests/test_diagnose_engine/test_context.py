"""Tests for M2 context module (DiagnoseContext builder).

Tests log snippet extraction, adapter code path mapping, and missing file handling.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.diagnose_engine.context import (
    _adapter_file_path,
    _extract_log_snippet,
    _build_diff_summary,
    build_context,
    ADAPTER_FILE_MAP,
    DiagnoseContext,
)
from src.diagnose_engine import PROJECT_ROOT

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestAdapterFilePaths(unittest.TestCase):
    """Test adapter-key → file-path mapping."""

    def test_explicit_mappings(self):
        """All explicitly mapped adapters resolve correctly."""
        expected = {
            "ca":    "src/canada_loader.py",
            "au":    "src/national_scraper/adapters/au_ocds_adapter.py",
            "au-atm": "src/national_scraper/adapters/au_atm_adapter.py",
            "gb":    "src/national_scraper/adapters/uk_fts_adapter.py",
            "nspa":  "src/national_scraper/adapters/nspa_adapter.py",
            "de-ev": "src/national_scraper/adapters/de_evergabe_adapter.py",
            "ted":   "src/api_client.py",
        }
        for adapter, expected_rel in expected.items():
            path = _adapter_file_path(adapter)
            expected_path = PROJECT_ROOT / expected_rel
            self.assertEqual(path, expected_path, f"Wrong path for adapter '{adapter}'")

    def test_default_pattern(self):
        """Unknown adapters fall back to {adapter}_adapter.py pattern."""
        for adapter in ["fr", "de", "pl", "cz", "fi", "se", "no", "dk", "nl", "be", "es", "it", "ro", "ch", "lv", "ua", "ee", "lt", "gr"]:
            path = _adapter_file_path(adapter)
            expected = PROJECT_ROOT / f"src/national_scraper/adapters/{adapter}_adapter.py"
            self.assertEqual(path, expected, f"Wrong default path for adapter '{adapter}'")

    def test_all_25_adapters_resolve(self):
        """All 25 registered adapters resolve to a non-empty path."""
        all_adapters = [
            "ca", "au", "au-atm", "gb", "nspa", "de-ev", "ted",
            "fr", "de", "pl", "cz", "fi", "se", "no", "dk", "nl", "be",
            "es", "it", "ro", "ch", "lv", "ua", "ee", "lt",
        ]
        for adapter in all_adapters:
            path = _adapter_file_path(adapter)
            self.assertIsInstance(path, Path)
            self.assertTrue(str(path).endswith(".py"), f"Path for '{adapter}' doesn't end in .py: {path}")


class TestLogSnippetExtraction(unittest.TestCase):
    """Test log snippet extraction."""

    def test_extracts_lines_around_adapter(self):
        log_path = FIXTURE_DIR / "log_fr_pagination.log"
        snippet = _extract_log_snippet(log_path, "fr")
        self.assertIn("fr", snippet.lower())
        self.assertIn("pagination", snippet.lower())
        self.assertTrue(len(snippet) > 0)

    def test_missing_log_file_returns_empty(self):
        path = Path("/nonexistent/path/no_file.log")
        snippet = _extract_log_snippet(path, "fr")
        self.assertEqual(snippet, "")

    def test_no_adapter_mention_falls_back_to_last_100_lines(self):
        """When adapter not found in log, returns last 100 lines."""
        log_path = FIXTURE_DIR / "log_429.log"
        # 'xyz' is not mentioned in log_429.log
        snippet = _extract_log_snippet(log_path, "xyz")
        # Should return something (last 100 lines fallback)
        self.assertIsInstance(snippet, str)

    def test_max_chars_truncation(self):
        """Snippet is truncated to max_chars."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as fh:
            for i in range(500):
                fh.write(f"2026-05-19 [INFO] [mytest] line {i} with some content here\n")
            tmp_path = Path(fh.name)

        try:
            snippet = _extract_log_snippet(tmp_path, "mytest", max_chars=100)
            self.assertLessEqual(len(snippet), 200)  # some tolerance for truncation marker
        finally:
            tmp_path.unlink()

    def test_adapter_log_429(self):
        """ted adapter found in 429 log."""
        log_path = FIXTURE_DIR / "log_429.log"
        snippet = _extract_log_snippet(log_path, "ted")
        self.assertIn("429", snippet)

    def test_adapter_log_stale(self):
        """gb adapter found in stale log."""
        log_path = FIXTURE_DIR / "log_stale.log"
        snippet = _extract_log_snippet(log_path, "gb")
        self.assertIn("stale", snippet.lower())


class TestDiffSummary(unittest.TestCase):
    """Test diff summary from relevant.json."""

    def test_missing_relevant_json(self):
        summary = _build_diff_summary(Path("/nonexistent/relevant.json"), "fr")
        self.assertIn("not found", summary)

    def test_empty_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump([], fh)
            tmp = Path(fh.name)
        try:
            summary = _build_diff_summary(tmp, "fr")
            self.assertIn("0", summary)
        finally:
            tmp.unlink()

    def test_counts_correctly(self):
        data = [
            {"tender_id": "TED-001", "_source": "TED"},
            {"tender_id": "TED-002", "_source": "TED"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(data, fh)
            tmp = Path(fh.name)
        try:
            summary = _build_diff_summary(tmp, "ted")
            self.assertIn("2", summary)
        finally:
            tmp.unlink()


class TestBuildContext(unittest.TestCase):
    """Test full context builder."""

    def test_build_context_returns_diagnose_context(self):
        anomaly = {
            "run_id": "20260519_140354",
            "adapter": "gb",
            "rule": "pub_date_stale_60d",
            "severity": "info",
            "value": "2023-06-06",
            "baseline": "today - 60d = 2026-03-20",
            "message": "newest_pub_date=2023-06-06 is older than 60 days",
            "timestamp": "2026-05-19T14:03:54+00:00",
        }
        ctx = build_context(anomaly)
        self.assertIsInstance(ctx, DiagnoseContext)
        self.assertEqual(ctx.adapter, "gb")
        self.assertEqual(ctx.run_id, "20260519_140354")
        self.assertIsInstance(ctx.log_snippet, str)
        self.assertIsInstance(ctx.diff_summary, str)
        self.assertIsInstance(ctx.adapter_code, str)

    def test_adapter_code_contains_file_content_or_fallback(self):
        """Adapter code is either real source or fallback message."""
        anomaly = {
            "run_id": "20260519_140354",
            "adapter": "gb",
            "rule": "test",
            "severity": "warn",
            "value": "",
            "baseline": "",
            "message": "test",
            "timestamp": "2026-05-19T14:03:54+00:00",
        }
        ctx = build_context(anomaly)
        # Either real code or fallback message
        self.assertIsInstance(ctx.adapter_code, str)
        self.assertTrue(len(ctx.adapter_code) > 0)


if __name__ == "__main__":
    unittest.main()

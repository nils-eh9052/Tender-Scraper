"""Tests for src.health_monitor.parser"""
from __future__ import annotations

import pytest
from pathlib import Path

# The fixtures dir relative to this file
FIXTURES = Path(__file__).parent / "fixtures" / "health_logs"


def _parse(filename: str):
    """Helper: parse a fixture log and return list of metric dicts."""
    from src.health_monitor.parser import parse_log
    return parse_log(FIXTURES / filename)


class TestCleanRunLog:
    def test_returns_list(self):
        metrics = _parse("clean_run.log")
        assert isinstance(metrics, list)
        assert len(metrics) > 0

    def test_run_id_extracted(self):
        metrics = _parse("clean_run.log")
        for m in metrics:
            assert m["run_id"] == "20260519_080000", f"Bad run_id in {m}"

    def test_run_started_at_extracted(self):
        metrics = _parse("clean_run.log")
        for m in metrics:
            assert m["run_started_at"] is not None

    def test_argv_extracted(self):
        metrics = _parse("clean_run.log")
        first = metrics[0]
        assert first["argv"] is not None
        assert "main.py" in first["argv"]

    def test_no_exceptions(self):
        metrics = _parse("clean_run.log")
        for m in metrics:
            assert m["exception_count"] == 0, f"Unexpected exception in {m['adapter']}"
            assert m["exception_summary"] is None
            assert m["success"] is True

    def test_no_http_429(self):
        metrics = _parse("clean_run.log")
        for m in metrics:
            assert m["http_429_count"] == 0

    def test_fr_adapter_detected(self):
        metrics = _parse("clean_run.log")
        adapters = {m["adapter"] for m in metrics}
        assert "fr" in adapters, f"FR adapter not found in {adapters}"

    def test_no_adapter_detected(self):
        metrics = _parse("clean_run.log")
        adapters = {m["adapter"] for m in metrics}
        assert "no" in adapters, f"NO adapter not found in {adapters}"

    def test_cz_adapter_detected(self):
        metrics = _parse("clean_run.log")
        adapters = {m["adapter"] for m in metrics}
        assert "cz" in adapters, f"CZ adapter not found in {adapters}"


class TestRateLimitLog:
    def test_http_429_detected(self):
        metrics = _parse("rate_limit.log")
        # At least one metric should have 429 errors
        total_429 = sum(m.get("http_429_count", 0) for m in metrics)
        assert total_429 >= 2, f"Expected ≥2 HTTP 429, got {total_429}"

    def test_run_id_extracted(self):
        metrics = _parse("rate_limit.log")
        for m in metrics:
            assert m["run_id"] == "20260519_100000"

    def test_no_exceptions(self):
        metrics = _parse("rate_limit.log")
        for m in metrics:
            assert m["exception_count"] == 0

    def test_returns_list(self):
        metrics = _parse("rate_limit.log")
        assert len(metrics) > 0


class TestExceptionLog:
    def test_tracebacks_detected(self):
        metrics = _parse("exception.log")
        cz_metrics = [m for m in metrics if m["adapter"] == "cz"]
        assert cz_metrics, "CZ adapter not found in exception log"
        cz = cz_metrics[0]
        assert cz["exception_count"] >= 2, (
            f"Expected ≥2 tracebacks for CZ, got {cz['exception_count']}"
        )

    def test_exception_summary_populated(self):
        metrics = _parse("exception.log")
        cz_metrics = [m for m in metrics if m["adapter"] == "cz"]
        assert cz_metrics
        cz = cz_metrics[0]
        assert cz["exception_summary"] is not None
        assert "Traceback" in cz["exception_summary"] or "TimeoutError" in cz["exception_summary"]

    def test_success_false_on_exception(self):
        metrics = _parse("exception.log")
        cz_metrics = [m for m in metrics if m["adapter"] == "cz"]
        assert cz_metrics
        cz = cz_metrics[0]
        assert cz["success"] is False

    def test_exception_summary_max_1000_chars(self):
        metrics = _parse("exception.log")
        for m in metrics:
            if m["exception_summary"] is not None:
                assert len(m["exception_summary"]) <= 1000

    def test_run_id_extracted(self):
        metrics = _parse("exception.log")
        for m in metrics:
            assert m["run_id"] == "20260519_120000"


class TestParserEdgeCases:
    def test_no_sections_returns_single_entry(self):
        """Log with no adapter sections returns one entry (defaults to 'ted')."""
        from src.health_monitor.parser import parse_log_text
        text = "# Run started 2026-05-19T09:00:00\n# argv: main.py --phase export\n\nSome output line"
        metrics = parse_log_text(text)
        assert len(metrics) == 1
        assert metrics[0]["run_id"] == "20260519_090000"

    def test_null_over_wrong_value(self):
        """Fields that can't be extracted must be None, not a wrong value."""
        from src.health_monitor.parser import parse_log_text
        text = "# Run started 2026-05-19T09:00:00\n# argv: main.py --phase export\n"
        metrics = parse_log_text(text)
        m = metrics[0]
        # run_duration_seconds should be None if not found
        assert m["run_duration_seconds"] is None

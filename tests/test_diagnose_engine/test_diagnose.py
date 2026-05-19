"""Tests for M2 diagnose module (Sonnet/Opus full diagnosis).

All LLM calls are mocked — no real API calls are made.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.diagnose_engine.schema import FailureClass, Severity, VALID_FIX_TYPES
from src.diagnose_engine.context import DiagnoseContext

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open() as fh:
        return json.load(fh)


def _make_ctx(anomaly: dict) -> DiagnoseContext:
    return DiagnoseContext(
        anomaly=anomaly,
        log_snippet="2026-05-19 [INFO] test log line",
        diff_summary="relevant.json: 322 notices; 13 from adapter 'fr'",
        adapter_code="# adapter code stub",
        adapter=anomaly.get("adapter", "test"),
        run_id=anomaly.get("run_id", "20260519_140354"),
    )


def _mock_llm_response(failure_class: str, confidence: int) -> str:
    return json.dumps({
        "failure_class": failure_class,
        "confidence": confidence,
        "severity": "warn",
        "affected_files": ["src/national_scraper/adapters/fr_adapter.py"],
        "repro_steps": ["python -m src.health_monitor --collect", "python main.py --national fr"],
        "suggested_fix_type": "low_risk_auto",
        "fix_hint": "Check pagination logic in fr_adapter.py page loop.",
        "explanation": "FR-BOAMP adapter stops at page 1 instead of fetching all pages.",
    })


class TestDiagnoseFields(unittest.TestCase):
    """All required fields present in output."""

    def test_all_required_fields_present(self):
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        ctx = _make_ctx(anomaly)
        mock_resp = _mock_llm_response("pagination_bug", 85)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (mock_resp, {"input_tokens": 500, "output_tokens": 200})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "pagination_bug", 85)

        d = report.to_dict()
        required_fields = [
            "diagnosis_id", "created_at", "anomaly", "failure_class", "confidence",
            "severity", "affected_files", "repro_steps", "suggested_fix_type",
            "fix_hint", "explanation", "model_used", "cost_usd", "raw_llm_output",
        ]
        for field in required_fields:
            self.assertIn(field, d, f"Missing field: {field}")

    def test_fix_type_valid(self):
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        ctx = _make_ctx(anomaly)
        mock_resp = _mock_llm_response("pagination_bug", 85)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (mock_resp, {"input_tokens": 500, "output_tokens": 200})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "pagination_bug", 85)

        self.assertIn(report.suggested_fix_type, VALID_FIX_TYPES)

    def test_failure_class_is_enum(self):
        anomaly = _load_fixture("anomaly_stale_gb.json")
        ctx = _make_ctx(anomaly)
        stale_resp = json.dumps({
            "failure_class": "stale_data_source",
            "confidence": 90,
            "severity": "info",
            "affected_files": [],
            "repro_steps": [],
            "suggested_fix_type": "no_action",
            "fix_hint": "Source genuinely has no new data.",
            "explanation": "GB FTS newest pub date is 2023-06-06, over 60 days old.",
        })

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (stale_resp, {"input_tokens": 400, "output_tokens": 150})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "stale_data_source", 90)

        self.assertIsInstance(report.failure_class, FailureClass)
        self.assertEqual(report.failure_class, FailureClass.stale_data_source)


class TestModelRouting(unittest.TestCase):
    """Model routing: low confidence → Opus, high confidence → Sonnet."""

    def test_low_confidence_uses_opus(self):
        """triage_confidence < 60 → model_used contains 'opus'."""
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        ctx = _make_ctx(anomaly)
        mock_resp = _mock_llm_response("pagination_bug", 50)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (mock_resp, {"input_tokens": 600, "output_tokens": 250})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "pagination_bug", 50)

        self.assertIn("opus", report.model_used.lower())

    def test_high_confidence_uses_sonnet(self):
        """triage_confidence >= 60, non-complex class → model_used contains 'sonnet'."""
        anomaly = _load_fixture("anomaly_429_cluster.json")
        ctx = _make_ctx(anomaly)
        mock_resp = _mock_llm_response("rate_limit", 95)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (mock_resp, {"input_tokens": 400, "output_tokens": 150})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "rate_limit", 95)

        self.assertIn("sonnet", report.model_used.lower())

    def test_schema_change_uses_opus(self):
        """schema_change → Opus regardless of confidence."""
        anomaly = _load_fixture("anomaly_au_url_change.json")
        ctx = _make_ctx(anomaly)
        mock_resp = _mock_llm_response("schema_change", 75)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (mock_resp, {"input_tokens": 600, "output_tokens": 200})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "schema_change", 75)

        self.assertIn("opus", report.model_used.lower())

    def test_unknown_class_uses_opus(self):
        """unknown class → Opus."""
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        ctx = _make_ctx(anomaly)
        mock_resp = _mock_llm_response("unknown", 30)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (mock_resp, {"input_tokens": 600, "output_tokens": 200})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "unknown", 30)

        self.assertIn("opus", report.model_used.lower())


class TestDiagnoseFixTypeFallback(unittest.TestCase):
    """Fix type falls back to canonical map when LLM returns invalid value."""

    def test_invalid_fix_type_falls_back(self):
        anomaly = _load_fixture("anomaly_stale_gb.json")
        ctx = _make_ctx(anomaly)
        bad_resp = json.dumps({
            "failure_class": "stale_data_source",
            "confidence": 88,
            "severity": "info",
            "affected_files": [],
            "repro_steps": [],
            "suggested_fix_type": "completely_invalid_value",
            "fix_hint": "No action needed.",
            "explanation": "Stale data.",
        })

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            mock_call.return_value = (bad_resp, {"input_tokens": 300, "output_tokens": 100})
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "stale_data_source", 88)

        self.assertIn(report.suggested_fix_type, VALID_FIX_TYPES)
        # stale_data_source → no_action
        self.assertEqual(report.suggested_fix_type, "no_action")


class TestDryRun(unittest.TestCase):
    """--dry-run returns stub report without LLM call."""

    def test_dry_run_no_llm_call(self):
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        ctx = _make_ctx(anomaly)

        with patch("src.diagnose_engine.diagnose.call_with_usage") as mock_call:
            from src.diagnose_engine.diagnose import diagnose_anomaly
            report = diagnose_anomaly(ctx, "pagination_bug", 85, dry_run=True)

        mock_call.assert_not_called()
        self.assertIn("dry-run", report.fix_hint)
        self.assertEqual(report.cost_usd, 0.0)
        self.assertEqual(report.suggested_fix_type, "low_risk_auto")  # pagination_bug maps to low_risk_auto


if __name__ == "__main__":
    unittest.main()

"""Integration tests for M2 Diagnose Engine.

End-to-end pipeline with mocked LLM: anomaly fixture → context → triage → diagnose → DiagnosisReport.
No real API calls are made.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.diagnose_engine.context import build_context
from src.diagnose_engine.schema import DiagnosisReport, FailureClass, Severity, VALID_FIX_TYPES

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open() as fh:
        return json.load(fh)


class TestEndToEndFRPagination(unittest.TestCase):
    """FR pagination anomaly → full diagnosis pipeline."""

    def test_full_pipeline(self):
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        triage_resp = json.dumps({"failure_class": "pagination_bug", "confidence": 85})
        diagnose_resp = json.dumps({
            "failure_class": "pagination_bug",
            "confidence": 85,
            "severity": "warn",
            "affected_files": ["src/national_scraper/adapters/fr_adapter.py"],
            "repro_steps": [
                "python main.py --national fr",
                "Check FR-BOAMP API response for pagination tokens",
            ],
            "suggested_fix_type": "low_risk_auto",
            "fix_hint": "Fix pagination loop in fr_adapter.py to follow all page links.",
            "explanation": "FR-BOAMP adapter returns only 13 results vs expected 40. Pagination stops at page 1 due to missing next-page token handling.",
        })

        with (patch("src.diagnose_engine.triage.call_with_usage") as mock_triage,
              patch("src.diagnose_engine.diagnose.call_with_usage") as mock_diagnose):
            mock_triage.return_value = (triage_resp, {"input_tokens": 100, "output_tokens": 20})
            mock_diagnose.return_value = (diagnose_resp, {"input_tokens": 800, "output_tokens": 300})

            from src.diagnose_engine.triage import triage_anomaly
            from src.diagnose_engine.diagnose import diagnose_anomaly

            ctx = build_context(anomaly)
            triage_class, triage_conf = triage_anomaly(anomaly)
            report = diagnose_anomaly(ctx, triage_class, triage_conf)

        # Verify all required fields
        d = report.to_dict()
        required = [
            "diagnosis_id", "created_at", "anomaly", "failure_class", "confidence",
            "severity", "affected_files", "repro_steps", "suggested_fix_type",
            "fix_hint", "explanation", "model_used", "cost_usd", "raw_llm_output",
        ]
        for field in required:
            self.assertIn(field, d, f"Missing field: {field}")

        # Verify correct classification
        self.assertEqual(report.failure_class, FailureClass.pagination_bug)
        self.assertEqual(report.confidence, 85)
        self.assertIn(report.suggested_fix_type, VALID_FIX_TYPES)
        self.assertEqual(report.suggested_fix_type, "low_risk_auto")

        # Verify triage
        self.assertEqual(triage_class, "pagination_bug")
        self.assertEqual(triage_conf, 85)

        # Verify cost > 0
        self.assertGreater(report.cost_usd, 0.0)

        # Verify model is Sonnet (confidence >= 60, class is pagination_bug)
        self.assertIn("sonnet", report.model_used.lower())


class TestEndToEndStaleGB(unittest.TestCase):
    """GB stale data anomaly → full diagnosis pipeline."""

    def test_stale_maps_to_no_action(self):
        anomaly = _load_fixture("anomaly_stale_gb.json")
        triage_resp = json.dumps({"failure_class": "stale_data_source", "confidence": 90})
        diagnose_resp = json.dumps({
            "failure_class": "stale_data_source",
            "confidence": 90,
            "severity": "info",
            "affected_files": [],
            "repro_steps": ["python -m src.health_monitor --report"],
            "suggested_fix_type": "no_action",
            "fix_hint": "Source has no new data — not a bug.",
            "explanation": "UK FTS newest pub date is 2023-06-06, over 1000 days old. No defence tenders available.",
        })

        with (patch("src.diagnose_engine.triage.call_with_usage") as mock_triage,
              patch("src.diagnose_engine.diagnose.call_with_usage") as mock_diagnose):
            mock_triage.return_value = (triage_resp, {"input_tokens": 80, "output_tokens": 15})
            mock_diagnose.return_value = (diagnose_resp, {"input_tokens": 600, "output_tokens": 200})

            from src.diagnose_engine.triage import triage_anomaly
            from src.diagnose_engine.diagnose import diagnose_anomaly

            ctx = build_context(anomaly)
            triage_class, triage_conf = triage_anomaly(anomaly)
            report = diagnose_anomaly(ctx, triage_class, triage_conf)

        self.assertEqual(report.failure_class, FailureClass.stale_data_source)
        self.assertEqual(report.suggested_fix_type, "no_action")
        self.assertEqual(report.severity, Severity.info)


class TestEndToEnd429Cluster(unittest.TestCase):
    """429 rate limit cluster → full diagnosis pipeline."""

    def test_429_maps_to_low_risk_manual(self):
        anomaly = _load_fixture("anomaly_429_cluster.json")
        triage_resp = json.dumps({"failure_class": "rate_limit", "confidence": 95})
        diagnose_resp = json.dumps({
            "failure_class": "rate_limit",
            "confidence": 95,
            "severity": "warn",
            "affected_files": ["src/api_client.py"],
            "repro_steps": [
                "python main.py --phase index",
                "Reduce api.requests_per_second in config/settings.yaml",
            ],
            "suggested_fix_type": "low_risk_manual",
            "fix_hint": "Increase backoff delay or reduce request rate in settings.yaml.",
            "explanation": "TED API returned 5 HTTP 429 responses. Rate limit exceeded — reduce request frequency.",
        })

        with (patch("src.diagnose_engine.triage.call_with_usage") as mock_triage,
              patch("src.diagnose_engine.diagnose.call_with_usage") as mock_diagnose):
            mock_triage.return_value = (triage_resp, {"input_tokens": 80, "output_tokens": 15})
            mock_diagnose.return_value = (diagnose_resp, {"input_tokens": 600, "output_tokens": 200})

            from src.diagnose_engine.triage import triage_anomaly
            from src.diagnose_engine.diagnose import diagnose_anomaly

            ctx = build_context(anomaly)
            triage_class, triage_conf = triage_anomaly(anomaly)
            report = diagnose_anomaly(ctx, triage_class, triage_conf)

        self.assertEqual(report.failure_class, FailureClass.rate_limit)
        self.assertEqual(report.suggested_fix_type, "low_risk_manual")

    def test_report_is_serializable(self):
        """DiagnosisReport.to_dict() produces JSON-serializable output."""
        anomaly = _load_fixture("anomaly_429_cluster.json")
        triage_resp = json.dumps({"failure_class": "rate_limit", "confidence": 95})
        diagnose_resp = json.dumps({
            "failure_class": "rate_limit",
            "confidence": 95,
            "severity": "warn",
            "affected_files": ["src/api_client.py"],
            "repro_steps": [],
            "suggested_fix_type": "low_risk_manual",
            "fix_hint": "Slow down.",
            "explanation": "Rate limited.",
        })

        with (patch("src.diagnose_engine.triage.call_with_usage") as mock_triage,
              patch("src.diagnose_engine.diagnose.call_with_usage") as mock_diagnose):
            mock_triage.return_value = (triage_resp, {"input_tokens": 80, "output_tokens": 15})
            mock_diagnose.return_value = (diagnose_resp, {"input_tokens": 600, "output_tokens": 200})

            from src.diagnose_engine.triage import triage_anomaly
            from src.diagnose_engine.diagnose import diagnose_anomaly

            ctx = build_context(anomaly)
            triage_class, triage_conf = triage_anomaly(anomaly)
            report = diagnose_anomaly(ctx, triage_class, triage_conf)

        # Should not raise
        serialized = json.dumps(report.to_dict(), default=str)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["failure_class"], "rate_limit")


class TestEndToEndDiagnoseIDUnique(unittest.TestCase):
    """Each DiagnosisReport gets a unique ID."""

    def test_unique_ids(self):
        ids = {DiagnosisReport.make_id() for _ in range(20)}
        self.assertEqual(len(ids), 20)


if __name__ == "__main__":
    unittest.main()

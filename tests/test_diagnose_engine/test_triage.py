"""Tests for M2 triage module (Haiku pre-classifier).

All LLM calls are mocked — no real API calls are made.
"""
import json
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open() as fh:
        return json.load(fh)


class TestTriageValidResponse(unittest.TestCase):
    """Valid JSON response → correct FailureClass extracted."""

    def test_pagination_anomaly(self):
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        mock_response = json.dumps({"failure_class": "pagination_bug", "confidence": 85})

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (mock_response, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "pagination_bug")
        self.assertEqual(result_conf, 85)

    def test_stale_anomaly(self):
        anomaly = _load_fixture("anomaly_stale_gb.json")
        mock_response = json.dumps({"failure_class": "stale_data_source", "confidence": 90})

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (mock_response, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "stale_data_source")
        self.assertEqual(result_conf, 90)

    def test_rate_limit_anomaly(self):
        anomaly = _load_fixture("anomaly_429_cluster.json")
        mock_response = json.dumps({"failure_class": "rate_limit", "confidence": 95})

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (mock_response, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "rate_limit")
        self.assertEqual(result_conf, 95)

    def test_url_change_anomaly(self):
        anomaly = _load_fixture("anomaly_au_url_change.json")
        mock_response = json.dumps({"failure_class": "url_pattern_changed", "confidence": 90})

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (mock_response, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "url_pattern_changed")
        self.assertEqual(result_conf, 90)


class TestTriageInvalidResponse(unittest.TestCase):
    """Invalid JSON → returns ("unknown", 0)."""

    def test_invalid_json(self):
        anomaly = _load_fixture("anomaly_fr_pagination.json")

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = ("this is not json", {"input_tokens": 50, "output_tokens": 10})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "unknown")
        self.assertEqual(result_conf, 0)

    def test_empty_response(self):
        anomaly = _load_fixture("anomaly_stale_gb.json")

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = ("", {"input_tokens": 50, "output_tokens": 0})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "unknown")
        self.assertEqual(result_conf, 0)

    def test_unknown_failure_class(self):
        """Unknown class value → falls back to 'unknown'."""
        anomaly = _load_fixture("anomaly_429_cluster.json")
        mock_response = json.dumps({"failure_class": "totally_fake_class", "confidence": 70})

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (mock_response, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "unknown")

    def test_llm_exception(self):
        """LLM call raises exception → returns ("unknown", 0)."""
        anomaly = _load_fixture("anomaly_fr_pagination.json")

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.side_effect = RuntimeError("OpenRouter timeout")
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "unknown")
        self.assertEqual(result_conf, 0)

    def test_confidence_clamped(self):
        """Confidence out of range → clamped to 0-100."""
        anomaly = _load_fixture("anomaly_fr_pagination.json")
        mock_response = json.dumps({"failure_class": "pagination_bug", "confidence": 150})

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (mock_response, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "pagination_bug")
        self.assertEqual(result_conf, 100)  # clamped


class TestTriageMarkdownFence(unittest.TestCase):
    """Model wraps JSON in markdown fence → still parsed correctly."""

    def test_markdown_fence_stripped(self):
        anomaly = _load_fixture("anomaly_429_cluster.json")
        inner = json.dumps({"failure_class": "rate_limit", "confidence": 80})
        fenced = f"```json\n{inner}\n```"

        with patch("src.diagnose_engine.triage.call_with_usage") as mock_call:
            mock_call.return_value = (fenced, {"input_tokens": 100, "output_tokens": 20})
            from src.diagnose_engine.triage import triage_anomaly
            result_class, result_conf = triage_anomaly(anomaly)

        self.assertEqual(result_class, "rate_limit")
        self.assertEqual(result_conf, 80)


if __name__ == "__main__":
    unittest.main()

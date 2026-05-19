"""Haiku pre-classifier (triage) for M2 Diagnose Engine.

Calls claude-haiku-4.5 via llm_router to classify an anomaly into a
FailureClass with confidence 0-100. Returns ("unknown", 0) on parse error.
"""
from __future__ import annotations

import json
import logging

from src.env_loader import load_env_chain
from src.llm_router import call_with_usage, estimate_cost_usd
from src.diagnose_engine.schema import FailureClass

load_env_chain()

logger = logging.getLogger(__name__)

HAIKU = "anthropic/claude-haiku-4.5"

TRIAGE_SYSTEM = """You are a pipeline failure classifier for a defence procurement scraper.
Classify the anomaly into exactly one failure class and estimate confidence 0-100.

Failure classes:
- selector_drift: CSS/XPath selector no longer matches (Playwright adapters)
- url_pattern_changed: Portal changed URL format (e.g. /View → /Show)
- http_5xx_cluster: Portal outage, temporary server errors
- rate_limit: HTTP 429 repeated
- auth_changed: Portal now requires login (eIDAS, Keycloak, etc.)
- bot_detection: CloudFront/WAF blocks User-Agent
- pagination_bug: Adapter not fetching all pages (e.g. FR-BOAMP only 13 vs 40)
- schema_change: API returns new/changed fields
- stale_data_source: Source genuinely has no new data (not a bug)
- unknown: Insufficient evidence to classify

Few-shot examples:
{"anomaly": "FR fr_adapter: 13 results vs 40 expected, pagination stops at page 1"} → {"failure_class": "pagination_bug", "confidence": 85}
{"anomaly": "AU au_ocds: HTTP 404 on /api/ocds/contractPublished/v2/View/ATM2024"} → {"failure_class": "url_pattern_changed", "confidence": 90}
{"anomaly": "AU-ATM: 0 results, User-Agent blocked by CloudFront"} → {"failure_class": "bot_detection", "confidence": 80}
{"anomaly": "CZ cz_adapter: auth wall after login attempt, eIDAS SSO redirect"} → {"failure_class": "auth_changed", "confidence": 88}
{"anomaly": "TED api_client: HTTP 429 x3 in 10 minutes"} → {"failure_class": "rate_limit", "confidence": 95}
{"anomaly": "GB uk_fts: newest tender from 2023-06-06, no new data for 700+ days"} → {"failure_class": "stale_data_source", "confidence": 90}
{"anomaly": "NO no_adapter: newest tender 2023-09-21, doffin shows no new defence tenders"} → {"failure_class": "stale_data_source", "confidence": 85}

Return ONLY valid JSON: {"failure_class": "<class>", "confidence": <int>}"""

_VALID_CLASSES = {fc.value for fc in FailureClass}


def triage_anomaly(anomaly: dict) -> tuple[str, int]:
    """Run Haiku triage on a single anomaly dict.

    Returns:
        (failure_class_str, confidence_int)
        On parse failure: ("unknown", 0)
    """
    adapter = anomaly.get("adapter", "unknown")
    rule    = anomaly.get("rule", "")
    message = anomaly.get("message", "")
    severity = anomaly.get("severity", "")
    value    = anomaly.get("value", "")
    baseline = anomaly.get("baseline", "")

    user_prompt = json.dumps({
        "anomaly": (
            f"{adapter.upper()} {rule}: {message} "
            f"(value={value}, baseline={baseline}, severity={severity})"
        )
    })

    try:
        text, usage = call_with_usage(HAIKU, system=TRIAGE_SYSTEM, user=user_prompt, max_tokens=100)
    except Exception as exc:
        logger.warning("Triage LLM call failed: %s", exc)
        return ("unknown", 0)

    cost = estimate_cost_usd(HAIKU, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    logger.debug("Triage for %s/%s: cost=$%.5f", adapter, rule, cost)

    # Parse JSON response
    try:
        raw = text.strip()
        # Strip markdown fences if model wraps output
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        failure_class = result.get("failure_class", "unknown")
        confidence = int(result.get("confidence", 0))
        if failure_class not in _VALID_CLASSES:
            logger.warning("Triage returned unknown class %r — falling back to 'unknown'", failure_class)
            failure_class = "unknown"
        confidence = max(0, min(100, confidence))
        return (failure_class, confidence)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Triage JSON parse error: %s — raw: %r", exc, text[:200])
        return ("unknown", 0)

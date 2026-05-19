"""Full diagnosis engine using Sonnet/Opus for M2 Diagnose Engine.

Model routing:
  - triage_confidence < 60 OR class in (schema_change, unknown) → Opus
  - else → Sonnet (or DIAGNOSE_ENGINE_MODEL env override)

Loads prompt templates from config/diagnose_prompts.yaml.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from src.env_loader import load_env_chain
from src.llm_router import call_with_usage, estimate_cost_usd
from src.diagnose_engine import PROJECT_ROOT
from src.diagnose_engine.schema import (
    DiagnosisReport,
    FailureClass,
    FIX_TYPE_MAP,
    Severity,
    VALID_FIX_TYPES,
)
from src.diagnose_engine.context import DiagnoseContext

load_env_chain()

logger = logging.getLogger(__name__)

SONNET = "anthropic/claude-sonnet-4.6"
OPUS   = "anthropic/claude-opus-4.7"
HAIKU  = "anthropic/claude-haiku-4.5"

_PROMPTS_PATH = PROJECT_ROOT / "config" / "diagnose_prompts.yaml"

_VALID_CLASSES = {fc.value for fc in FailureClass}
_VALID_SEVERITIES = {s.value for s in Severity}


def _load_prompts() -> dict:
    """Load system and user_template from config/diagnose_prompts.yaml."""
    try:
        import yaml  # type: ignore
        with _PROMPTS_PATH.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("Could not load diagnose_prompts.yaml: %s", exc)
        return {
            "system": "You are a pipeline diagnose agent. Return JSON.",
            "user_template": "{message}",
        }


def _select_model(triage_class: str, triage_confidence: int) -> str:
    """Route to Opus for low-confidence or complex classes; else Sonnet."""
    if triage_confidence < 60 or triage_class in ("schema_change", "unknown"):
        return OPUS
    env_override = os.environ.get("DIAGNOSE_ENGINE_MODEL")
    return env_override or SONNET


def _safe_str_list(val) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val]
    return []


def _parse_llm_response(
    raw: str,
    anomaly: dict,
    triage_class: str,
    triage_confidence: int,
    model_used: str,
    cost_usd: float,
) -> DiagnosisReport:
    """Parse the LLM JSON response into a DiagnosisReport.

    Falls back to sensible defaults on parse error.
    """
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts[1:]:
            if part.startswith("json"):
                part = part[4:]
            text = part.strip()
            break

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("diagnose JSON parse error: %s — raw: %r", exc, raw[:300])
        data = {}

    # Extract fields with validation / fallback
    failure_class_raw = data.get("failure_class", triage_class)
    if failure_class_raw not in _VALID_CLASSES:
        failure_class_raw = triage_class if triage_class in _VALID_CLASSES else "unknown"

    confidence = data.get("confidence", triage_confidence)
    try:
        confidence = max(0, min(100, int(confidence)))
    except (ValueError, TypeError):
        confidence = triage_confidence

    severity_raw = data.get("severity", anomaly.get("severity", "warn"))
    if severity_raw not in _VALID_SEVERITIES:
        severity_raw = anomaly.get("severity", "warn")

    suggested_fix_type = data.get("suggested_fix_type", "")
    if suggested_fix_type not in VALID_FIX_TYPES:
        # Fall back to canonical mapping
        try:
            fc = FailureClass(failure_class_raw)
            suggested_fix_type = FIX_TYPE_MAP.get(fc, "high_risk_human")
        except ValueError:
            suggested_fix_type = "high_risk_human"

    return DiagnosisReport(
        diagnosis_id=DiagnosisReport.make_id(),
        created_at=DiagnosisReport.now_iso(),
        anomaly=anomaly,
        failure_class=FailureClass(failure_class_raw),
        confidence=confidence,
        severity=Severity(severity_raw),
        affected_files=_safe_str_list(data.get("affected_files")),
        repro_steps=_safe_str_list(data.get("repro_steps")),
        suggested_fix_type=suggested_fix_type,
        fix_hint=str(data.get("fix_hint", "No fix hint available.")),
        explanation=str(data.get("explanation", "No explanation available.")),
        model_used=model_used,
        cost_usd=cost_usd,
        raw_llm_output=raw,
    )


def diagnose_anomaly(
    ctx: DiagnoseContext,
    triage_class: str,
    triage_confidence: int,
    dry_run: bool = False,
) -> DiagnosisReport:
    """Run full diagnosis on a single anomaly context.

    Args:
        ctx:               DiagnoseContext from context.build_context()
        triage_class:      FailureClass string from triage.triage_anomaly()
        triage_confidence: Confidence integer 0-100 from triage
        dry_run:           If True, skip actual LLM call and return a stub report

    Returns:
        DiagnosisReport
    """
    model = _select_model(triage_class, triage_confidence)
    anomaly = ctx.anomaly

    if dry_run:
        # Return stub without calling LLM
        try:
            fc = FailureClass(triage_class)
        except ValueError:
            fc = FailureClass.unknown
        fix_type = FIX_TYPE_MAP.get(fc, "high_risk_human")
        return DiagnosisReport(
            diagnosis_id=DiagnosisReport.make_id(),
            created_at=DiagnosisReport.now_iso(),
            anomaly=anomaly,
            failure_class=fc,
            confidence=triage_confidence,
            severity=Severity(anomaly.get("severity", "warn")),
            affected_files=[],
            repro_steps=[],
            suggested_fix_type=fix_type,
            fix_hint="[dry-run] No LLM call made.",
            explanation="[dry-run] Triage result only — full diagnosis skipped.",
            model_used=f"[dry-run] would use {model}",
            cost_usd=0.0,
            raw_llm_output="",
        )

    prompts = _load_prompts()
    system = prompts.get("system", "You are a pipeline diagnose agent. Return JSON.")
    user_template = prompts.get("user_template", "{message}")

    log_lines = len(ctx.log_snippet.splitlines()) if ctx.log_snippet else 0

    user = user_template.format(
        adapter=anomaly.get("adapter", "unknown"),
        rule=anomaly.get("rule", ""),
        severity=anomaly.get("severity", ""),
        value=anomaly.get("value", ""),
        baseline=anomaly.get("baseline", ""),
        message=anomaly.get("message", ""),
        run_id=ctx.run_id,
        argv=anomaly.get("argv", "unknown"),
        log_lines=log_lines,
        log_snippet=ctx.log_snippet or "(no log available)",
        diff_summary=ctx.diff_summary,
        adapter_code=ctx.adapter_code,
        triage_class=triage_class,
        triage_confidence=triage_confidence,
    )

    try:
        raw_text, usage = call_with_usage(model, system=system, user=user, max_tokens=1500)
    except Exception as exc:
        logger.error("Diagnose LLM call failed [%s]: %s", model, exc)
        try:
            fc = FailureClass(triage_class)
        except ValueError:
            fc = FailureClass.unknown
        return DiagnosisReport(
            diagnosis_id=DiagnosisReport.make_id(),
            created_at=DiagnosisReport.now_iso(),
            anomaly=anomaly,
            failure_class=fc,
            confidence=0,
            severity=Severity(anomaly.get("severity", "warn")),
            affected_files=[],
            repro_steps=[],
            suggested_fix_type=FIX_TYPE_MAP.get(fc, "high_risk_human"),
            fix_hint=f"LLM call failed: {exc}",
            explanation=f"Diagnosis failed due to LLM error: {exc}",
            model_used=model,
            cost_usd=0.0,
            raw_llm_output=str(exc),
        )

    cost = estimate_cost_usd(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    logger.info("Diagnose %s/%s model=%s cost=$%.4f", ctx.adapter, anomaly.get("rule"), model, cost)

    return _parse_llm_response(
        raw=raw_text,
        anomaly=anomaly,
        triage_class=triage_class,
        triage_confidence=triage_confidence,
        model_used=model,
        cost_usd=cost,
    )

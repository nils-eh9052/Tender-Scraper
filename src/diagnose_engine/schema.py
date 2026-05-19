"""DiagnosisReport dataclass and supporting enums for M2 Diagnose Engine."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class FailureClass(str, Enum):
    selector_drift = "selector_drift"
    url_pattern_changed = "url_pattern_changed"
    http_5xx_cluster = "http_5xx_cluster"
    rate_limit = "rate_limit"
    auth_changed = "auth_changed"
    bot_detection = "bot_detection"
    pagination_bug = "pagination_bug"
    schema_change = "schema_change"
    stale_data_source = "stale_data_source"
    unknown = "unknown"


class Severity(str, Enum):
    info = "info"
    warn = "warn"
    critical = "critical"


# Maps FailureClass → suggested_fix_type
FIX_TYPE_MAP: dict[FailureClass, str] = {
    FailureClass.selector_drift:      "low_risk_auto",
    FailureClass.url_pattern_changed:  "low_risk_auto",
    FailureClass.pagination_bug:       "low_risk_auto",
    FailureClass.bot_detection:        "low_risk_auto",
    FailureClass.rate_limit:           "low_risk_manual",
    FailureClass.http_5xx_cluster:     "low_risk_manual",
    FailureClass.auth_changed:         "high_risk_human",
    FailureClass.schema_change:        "high_risk_human",
    FailureClass.unknown:              "high_risk_human",
    FailureClass.stale_data_source:    "no_action",
}

VALID_FIX_TYPES = frozenset({"low_risk_auto", "low_risk_manual", "high_risk_human", "no_action"})


@dataclass
class DiagnosisReport:
    diagnosis_id: str
    created_at: str
    anomaly: dict                  # full M1 AnomalyRecord
    failure_class: FailureClass
    confidence: int                # 0–100
    severity: Severity
    affected_files: list[str]
    repro_steps: list[str]
    suggested_fix_type: str        # "low_risk_auto" | "low_risk_manual" | "high_risk_human" | "no_action"
    fix_hint: str
    explanation: str
    model_used: str
    cost_usd: float
    raw_llm_output: str

    def to_dict(self) -> dict:
        return {
            "diagnosis_id":      self.diagnosis_id,
            "created_at":        self.created_at,
            "anomaly":           self.anomaly,
            "failure_class":     self.failure_class.value,
            "confidence":        self.confidence,
            "severity":          self.severity.value,
            "affected_files":    self.affected_files,
            "repro_steps":       self.repro_steps,
            "suggested_fix_type": self.suggested_fix_type,
            "fix_hint":          self.fix_hint,
            "explanation":       self.explanation,
            "model_used":        self.model_used,
            "cost_usd":          self.cost_usd,
            "raw_llm_output":    self.raw_llm_output,
        }

    @classmethod
    def make_id(cls) -> str:
        return str(uuid.uuid4())[:8]

    @classmethod
    def now_iso(cls) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

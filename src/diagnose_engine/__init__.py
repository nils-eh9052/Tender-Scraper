"""M2 Diagnose Engine for BPW Defence Tender Radar.

Reads anomaly files produced by M1 --collect and produces structured
DiagnosisReports via a triage (Haiku) + diagnose (Sonnet/Opus) pipeline.
"""
from __future__ import annotations

from pathlib import Path

# src/diagnose_engine/__init__.py is two levels below the project root:
#   <project_root>/src/diagnose_engine/__init__.py
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

__all__ = ["PROJECT_ROOT"]

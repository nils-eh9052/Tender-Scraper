"""Health Monitor package for BPW Defence Tender Radar.

Exports PROJECT_ROOT so all sub-modules resolve paths consistently.
"""
from pathlib import Path

# src/health_monitor/__init__.py is two levels below the project root:
#   <project_root>/src/health_monitor/__init__.py
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

__all__ = ["PROJECT_ROOT"]

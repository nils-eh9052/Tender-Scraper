"""Baseline computation for the health monitor.

Reads metrics.jsonl and computes rolling statistics per adapter:
  - tender_count_7d_mean    — 7-day rolling mean of tender_count
  - tender_count_30d_mean   — 30-day rolling mean of tender_count
  - http_error_7d_mean      — 7-day mean of (4xx + 5xx) per run
  - duration_7d_mean        — 7-day mean of run_duration_seconds
  - zero_streak             — number of consecutive most-recent runs with count==0

Writes baselines to data/.health/baselines.json (one entry per adapter).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.health_monitor import PROJECT_ROOT
from src.health_monitor.metrics import load_all_metrics, HEALTH_DIR

BASELINES_JSON: Path = HEALTH_DIR / "baselines.json"


def compute_baselines(
    metrics: Optional[list[dict]] = None,
    reference_date: Optional[datetime] = None,
) -> dict[str, dict]:
    """Compute per-adapter baselines from metrics history.

    Args:
        metrics:        Pre-loaded metric records. If None, loads from disk.
        reference_date: Reference point for "today" (used in tests).

    Returns:
        dict mapping adapter_key → baseline dict.
    """
    if metrics is None:
        metrics = load_all_metrics()

    if reference_date is None:
        reference_date = datetime.utcnow()

    cutoff_7d  = reference_date - timedelta(days=7)
    cutoff_30d = reference_date - timedelta(days=30)

    # Group metrics by adapter
    by_adapter: dict[str, list[dict]] = defaultdict(list)
    for m in metrics:
        adapter = m.get("adapter")
        if adapter:
            by_adapter[adapter].append(m)

    baselines: dict[str, dict] = {}

    for adapter, records in by_adapter.items():
        # Sort by run_id ascending (lexicographic sort works for YYYYMMDD_HHMMSS)
        records_sorted = sorted(records, key=lambda r: r.get("run_id") or "")

        # Compute 7d / 30d windows using run_started_at if available, else run_id
        def _run_dt(r: dict) -> Optional[datetime]:
            ts = r.get("run_started_at") or ""
            if ts:
                try:
                    return datetime.fromisoformat(ts)
                except ValueError:
                    pass
            # Fall back to run_id timestamp
            rid = r.get("run_id") or ""
            try:
                return datetime.strptime(rid, "%Y%m%d_%H%M%S")
            except ValueError:
                return None

        counts_7d:  list[float] = []
        counts_30d: list[float] = []
        errors_7d:  list[float] = []
        dur_7d:     list[float] = []

        for r in records_sorted:
            tc = r.get("tender_count")
            err_4xx = r.get("http_4xx_count") or 0
            err_5xx = r.get("http_5xx_count") or 0
            dur = r.get("run_duration_seconds")

            dt = _run_dt(r)
            if dt is None:
                # Include in 30d window as a fallback
                if tc is not None:
                    counts_30d.append(float(tc))
                continue

            if dt >= cutoff_30d:
                if tc is not None:
                    counts_30d.append(float(tc))
            if dt >= cutoff_7d:
                if tc is not None:
                    counts_7d.append(float(tc))
                errors_7d.append(float(err_4xx + err_5xx))
                if dur is not None:
                    dur_7d.append(float(dur))

        # Zero-streak: count consecutive most-recent runs with tender_count == 0
        zero_streak = 0
        for r in reversed(records_sorted):
            tc = r.get("tender_count")
            if tc is not None and tc == 0:
                zero_streak += 1
            else:
                break

        def _mean(lst: list) -> Optional[float]:
            return sum(lst) / len(lst) if lst else None

        baselines[adapter] = {
            "tender_count_7d_mean":  _mean(counts_7d),
            "tender_count_30d_mean": _mean(counts_30d),
            "http_error_7d_mean":    _mean(errors_7d),
            "duration_7d_mean":      _mean(dur_7d),
            "zero_streak":           zero_streak,
            "run_count_7d":          len(counts_7d),
            "run_count_30d":         len(counts_30d),
        }

    return baselines


def save_baselines(baselines: dict[str, dict]) -> None:
    """Persist baselines dict to data/.health/baselines.json."""
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    with BASELINES_JSON.open("w", encoding="utf-8") as fh:
        json.dump(baselines, fh, indent=2, ensure_ascii=False, default=str)


def load_baselines() -> dict[str, dict]:
    """Load baselines from data/.health/baselines.json."""
    if not BASELINES_JSON.exists():
        return {}
    with BASELINES_JSON.open(encoding="utf-8") as fh:
        return json.load(fh)


def refresh_baselines() -> dict[str, dict]:
    """Recompute and save baselines. Returns the new baselines dict."""
    baselines = compute_baselines()
    save_baselines(baselines)
    return baselines

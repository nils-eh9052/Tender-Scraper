"""Anomaly detection rules for the health monitor.

Each rule is a function rule_<name>(run_metric, baseline, thresholds) → Optional[dict].

No LLM calls. Pure threshold logic, YAML-overridable via config/health_thresholds.yaml.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.health_monitor import PROJECT_ROOT

THRESHOLDS_YAML: Path = PROJECT_ROOT / "config" / "health_thresholds.yaml"

# ---------------------------------------------------------------------------
# Default thresholds (overridable per-adapter via YAML)
# ---------------------------------------------------------------------------
DEFAULTS: dict = {
    "tender_count_drop_pct":       0.50,   # 50% drop triggers warn
    "tender_count_min_baseline":   5,      # only fire if baseline >= 5
    "zero_streak_threshold":       3,      # 3 consecutive zeros triggers warn
    "zero_streak_min_30d_mean":    5,      # only fire if 30d mean >= 5
    "pub_date_stale_days":         60,     # older than today-60d → info
    "http_error_spike_min":        3,      # max(3, 3*baseline)
    "http_error_spike_factor":     3.0,
    "duration_spike_factor":       3.0,
    "snapshot_drift_pct":          0.50,   # |new+removed| > 50% of tender_count
}


def _load_thresholds() -> dict:
    """Load YAML thresholds file and merge with defaults."""
    thresholds = dict(DEFAULTS)
    if not THRESHOLDS_YAML.exists():
        return thresholds
    try:
        import yaml  # type: ignore
        with THRESHOLDS_YAML.open(encoding="utf-8") as fh:
            overrides = yaml.safe_load(fh) or {}
        thresholds.update(overrides.get("global", {}))
    except Exception:
        pass
    return thresholds


def _adapter_thresholds(adapter: str, thresholds: dict) -> dict:
    """Return threshold dict merged with per-adapter overrides."""
    merged = dict(thresholds)
    per_adapter = thresholds.get("adapters", {})
    if adapter in per_adapter:
        merged.update(per_adapter[adapter])
    return merged


def _make_anomaly(
    run_metric: dict,
    rule: str,
    severity: str,
    value,
    baseline_desc: str,
    message: str,
) -> dict:
    return {
        "run_id":    run_metric.get("run_id"),
        "adapter":   run_metric.get("adapter"),
        "rule":      rule,
        "severity":  severity,
        "value":     str(value) if value is not None else None,
        "baseline":  baseline_desc,
        "message":   message,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

def rule_tender_count_drop_50pct(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Warn if tender_count dropped by ≥50% vs. 7d mean (only when baseline≥5)."""
    tc = run_metric.get("tender_count")
    mean_7d = baseline.get("tender_count_7d_mean")
    if tc is None or mean_7d is None:
        return None
    min_baseline = thresholds.get("tender_count_min_baseline", 5)
    drop_pct = thresholds.get("tender_count_drop_pct", 0.50)
    if mean_7d < min_baseline:
        return None
    if tc < drop_pct * mean_7d:
        return _make_anomaly(
            run_metric, "tender_count_drop_50pct", "warn",
            tc,
            f"7d_mean={mean_7d:.1f}",
            f"tender_count={tc} is below {int(drop_pct*100)}% of 7d mean ({mean_7d:.1f})",
        )
    return None


def rule_zero_tender_streak_3(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Warn if 3+ consecutive runs have count==0 for a 'working' adapter with 30d_mean≥5."""
    adapter_status = (run_metric.get("adapter_status") or "").lower()
    if adapter_status != "working":
        return None
    mean_30d = baseline.get("tender_count_30d_mean")
    if mean_30d is None:
        return None
    min_30d = thresholds.get("zero_streak_min_30d_mean", 5)
    if mean_30d < min_30d:
        return None
    streak = baseline.get("zero_streak", 0)
    threshold = thresholds.get("zero_streak_threshold", 3)
    if streak >= threshold:
        return _make_anomaly(
            run_metric, "zero_tender_streak_3", "warn",
            streak,
            f"30d_mean={mean_30d:.1f}, threshold={threshold}",
            f"Adapter has returned 0 tenders for {streak} consecutive runs "
            f"(30d mean={mean_30d:.1f})",
        )
    return None


def rule_pub_date_stale_60d(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Info if newest_pub_date is older than today-60d for a 'working' adapter."""
    adapter_status = (run_metric.get("adapter_status") or "").lower()
    if adapter_status != "working":
        return None
    newest = run_metric.get("newest_pub_date")
    if not newest:
        return None
    stale_days = thresholds.get("pub_date_stale_days", 60)
    try:
        pub_date = date.fromisoformat(newest)
    except ValueError:
        return None
    cutoff = date.today() - timedelta(days=stale_days)
    if pub_date < cutoff:
        return _make_anomaly(
            run_metric, "pub_date_stale_60d", "info",
            newest,
            f"today - {stale_days}d = {cutoff.isoformat()}",
            f"newest_pub_date={newest} is older than {stale_days} days",
        )
    return None


def rule_http_error_spike(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Warn if (4xx+5xx) exceeds max(3, 3*baseline_mean)."""
    count_4xx = run_metric.get("http_4xx_count") or 0
    count_5xx = run_metric.get("http_5xx_count") or 0
    total_errors = count_4xx + count_5xx
    mean_7d = baseline.get("http_error_7d_mean") or 0.0
    min_threshold = thresholds.get("http_error_spike_min", 3)
    factor = thresholds.get("http_error_spike_factor", 3.0)
    spike_threshold = max(min_threshold, factor * mean_7d)
    if total_errors > spike_threshold:
        return _make_anomaly(
            run_metric, "http_error_spike", "warn",
            total_errors,
            f"max({min_threshold}, {factor:.0f}*{mean_7d:.1f})={spike_threshold:.1f}",
            f"HTTP 4xx/5xx count={total_errors} exceeds spike threshold ({spike_threshold:.1f})",
        )
    return None


def rule_rate_limit_cluster(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Warn if any HTTP 429 responses were received."""
    count_429 = run_metric.get("http_429_count") or 0
    if count_429 > 0:
        return _make_anomaly(
            run_metric, "rate_limit_cluster", "warn",
            count_429,
            "0",
            f"Received {count_429} HTTP 429 (rate limit) response(s)",
        )
    return None


def rule_duration_spike(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Info if run_duration > 3× baseline mean (when baseline > 0)."""
    duration = run_metric.get("run_duration_seconds")
    mean_7d = baseline.get("duration_7d_mean")
    if duration is None or mean_7d is None or mean_7d <= 0:
        return None
    factor = thresholds.get("duration_spike_factor", 3.0)
    if duration > factor * mean_7d:
        return _make_anomaly(
            run_metric, "duration_spike", "info",
            f"{duration:.1f}s",
            f"7d_mean={mean_7d:.1f}s",
            f"run_duration={duration:.1f}s is more than {factor:.0f}× the 7d mean ({mean_7d:.1f}s)",
        )
    return None


def rule_unhandled_exception(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Critical if success==False or exception_count > 0."""
    success = run_metric.get("success", True)
    exc_count = run_metric.get("exception_count") or 0
    if not success or exc_count > 0:
        summary = run_metric.get("exception_summary") or ""
        snippet = summary[:200] if summary else "no traceback captured"
        return _make_anomaly(
            run_metric, "unhandled_exception", "critical",
            exc_count,
            "0",
            f"Adapter run failed with {exc_count} exception(s): {snippet}",
        )
    return None


def rule_snapshot_drift(
    run_metric: dict, baseline: dict, thresholds: dict
) -> Optional[dict]:
    """Warn if |new+removed| > 50% of tender_count."""
    tc = run_metric.get("tender_count")
    new_c = run_metric.get("new_tender_count") or 0
    rem_c = run_metric.get("removed_tender_count") or 0
    if tc is None or tc == 0:
        return None
    drift = abs(new_c + rem_c)
    pct = thresholds.get("snapshot_drift_pct", 0.50)
    if drift > pct * tc:
        return _make_anomaly(
            run_metric, "snapshot_drift", "warn",
            drift,
            f"{int(pct*100)}% of tender_count={tc}",
            f"Snapshot drift: {new_c} new + {rem_c} removed = {drift} "
            f"({drift/tc*100:.0f}% of {tc} tenders)",
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

ALL_RULES = [
    rule_tender_count_drop_50pct,
    rule_zero_tender_streak_3,
    rule_pub_date_stale_60d,
    rule_http_error_spike,
    rule_rate_limit_cluster,
    rule_duration_spike,
    rule_unhandled_exception,
    rule_snapshot_drift,
]


def check_anomalies(
    run_metric: dict,
    baseline: dict,
    thresholds: Optional[dict] = None,
) -> list[dict]:
    """Run all anomaly rules against a single run metric.

    Args:
        run_metric:  One metric record (from metrics.jsonl).
        baseline:    Baseline dict for this adapter (from baselines.json).
        thresholds:  Override thresholds (if None, loads from YAML).

    Returns:
        List of AnomalyRecord dicts (may be empty).
    """
    if thresholds is None:
        thresholds = _load_thresholds()

    adapter = run_metric.get("adapter", "")
    t = _adapter_thresholds(adapter, thresholds)

    anomalies = []
    for rule_fn in ALL_RULES:
        result = rule_fn(run_metric, baseline, t)
        if result is not None:
            anomalies.append(result)

    return anomalies


def check_all_latest(
    latest_metrics: dict[str, dict],
    baselines: dict[str, dict],
    thresholds: Optional[dict] = None,
) -> list[dict]:
    """Check anomalies for all adapters in latest_metrics.

    Args:
        latest_metrics: {adapter_key: latest_metric_dict}
        baselines:      {adapter_key: baseline_dict}
        thresholds:     Optional override thresholds.

    Returns:
        Flat list of all AnomalyRecord dicts across all adapters.
    """
    if thresholds is None:
        thresholds = _load_thresholds()

    all_anomalies = []
    for adapter, metric in latest_metrics.items():
        baseline = baselines.get(adapter, {})
        anomalies = check_anomalies(metric, baseline, thresholds)
        all_anomalies.extend(anomalies)
    return all_anomalies

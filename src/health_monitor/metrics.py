"""Metrics orchestrator.

Combines:
  - Log parser (per-adapter HTTP/exception/duration metrics)
  - Counts from relevant.json (tender_count, date range)
  - Snapshot diff (new_tender_count, removed_tender_count)
  - adapter_status.json (adapter_status field)

Writes one JSONL line per run_id+adapter to data/.health/metrics.jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.health_monitor import PROJECT_ROOT
from src.health_monitor.parser import parse_log
from src.health_monitor.counts import compute_counts
from src.health_monitor.snapshot_diff import (
    diff_snapshots,
    get_latest_two_snapshots,
    save_snapshot,
)

HEALTH_DIR: Path = PROJECT_ROOT / "data" / ".health"
METRICS_JSONL: Path = HEALTH_DIR / "metrics.jsonl"
ADAPTER_STATUS_JSON: Path = PROJECT_ROOT / "data" / "adapter_status.json"
RELEVANT_JSON: Path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
RUN_LOG_DIR: Path = PROJECT_ROOT / "data" / ".run_log"


def _load_adapter_statuses() -> dict[str, str]:
    """Load adapter_status.json and return {adapter_key: status_string}."""
    if not ADAPTER_STATUS_JSON.exists():
        return {}
    with ADAPTER_STATUS_JSON.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    result = {}
    for key, info in raw.items():
        if isinstance(info, dict):
            status = info.get("status", "unknown")
            result[key] = status
    return result


def _find_log_for_run_id(run_id: str) -> Optional[Path]:
    """Find the log file corresponding to a run_id stamp."""
    candidate = RUN_LOG_DIR / f"{run_id}.log"
    if candidate.exists():
        return candidate
    # Try the symlink "latest.log" as fallback
    latest = RUN_LOG_DIR / "latest.log"
    if latest.exists():
        return latest
    return None


def _load_existing_run_ids() -> set[str]:
    """Return the set of run_ids already written to metrics.jsonl."""
    if not METRICS_JSONL.exists():
        return set()
    run_ids: set[str] = set()
    with METRICS_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rid := rec.get("run_id"):
                    run_ids.add(rid)
            except json.JSONDecodeError:
                pass
    return run_ids


def collect(run_id: Optional[str] = None) -> list[dict]:
    """Collect metrics for one run and append to metrics.jsonl.

    Args:
        run_id: Optional run_id stamp (e.g. "20260519_140354"). If None,
                uses the most-recent log file in data/.run_log/.

    Returns:
        List of metric dicts that were written.
    """
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)

    # --- Find log file ---
    log_path: Optional[Path] = None
    if run_id:
        log_path = _find_log_for_run_id(run_id)
    else:
        # Pick the most recent non-symlink log
        if RUN_LOG_DIR.exists():
            logs = sorted(
                (p for p in RUN_LOG_DIR.glob("*.log") if p.name != "latest.log"),
                key=lambda p: p.stat().st_mtime,
            )
            if logs:
                log_path = logs[-1]
                # Derive run_id from filename
                run_id = log_path.stem  # e.g. "20260519_140354"

    if log_path is None or not log_path.exists():
        return []

    # --- Check if already collected ---
    existing = _load_existing_run_ids()
    if run_id and run_id in existing:
        return []  # Already collected, skip

    # --- Parse log ---
    parsed_metrics = parse_log(log_path)

    # --- Load reference data ---
    adapter_statuses = _load_adapter_statuses()
    counts_by_adapter = compute_counts()

    # --- Snapshot diff ---
    # Save snapshot of current relevant.json (keyed by run_id)
    if run_id and RELEVANT_JSON.exists():
        with RELEVANT_JSON.open(encoding="utf-8") as fh:
            current_data = json.load(fh)
        if isinstance(current_data, list):
            save_snapshot(run_id, current_data)

    old_snap, new_snap = get_latest_two_snapshots()

    # Build a lookup from log-parsed metrics (only adapters seen in this run's log)
    log_by_adapter: dict[str, dict] = {m["adapter"]: m for m in parsed_metrics}

    # Snapshot diff values (global, applied to all adapters)
    snap_new: Optional[int] = None
    snap_removed: Optional[int] = None
    if old_snap and new_snap:
        try:
            diff = diff_snapshots(old_snap, new_snap)
            snap_new = diff.new_count
            snap_removed = diff.removed_count
        except Exception:
            pass

    # Derive run metadata from log header (use first parsed metric if available)
    run_started_at: Optional[str] = None
    argv: Optional[list] = None
    run_duration: Optional[float] = None
    log_file_str = str(log_path)
    if parsed_metrics:
        first = parsed_metrics[0]
        run_started_at = first.get("run_started_at")
        argv = first.get("argv")
        run_duration = first.get("run_duration_seconds")

    # --- Build one metric entry per registered adapter (all 25) ---
    # Adapters registered in the pipeline (everything except "tr" retired)
    registered_adapters = [k for k in adapter_statuses if k not in ("tr", "_meta")]
    if not registered_adapters:
        # Fallback: use counts keys union log keys
        registered_adapters = list(
            set(counts_by_adapter.keys()) | set(log_by_adapter.keys())
        )

    enriched: list[dict] = []
    for adapter in registered_adapters:
        log_m = log_by_adapter.get(adapter, {})
        counts = counts_by_adapter.get(adapter, {})

        # counts.py is authoritative for tender_count and dates
        tender_count = counts.get("tender_count", log_m.get("tender_count"))
        newest_pub = counts.get("newest_pub_date", log_m.get("newest_pub_date"))
        oldest_pub = counts.get("oldest_pub_date", log_m.get("oldest_pub_date"))

        m: dict = {
            "run_id":               run_id,
            "run_started_at":       run_started_at or log_m.get("run_started_at"),
            "argv":                 argv or log_m.get("argv"),
            "log_file":             log_file_str,
            "adapter":              adapter,
            "adapter_status":       adapter_statuses.get(adapter),
            "tender_count":         tender_count,
            "new_tender_count":     snap_new,
            "removed_tender_count": snap_removed,
            "newest_pub_date":      newest_pub,
            "oldest_pub_date":      oldest_pub,
            "run_duration_seconds": log_m.get("run_duration_seconds", run_duration),
            "http_4xx_count":       log_m.get("http_4xx_count", 0),
            "http_5xx_count":       log_m.get("http_5xx_count", 0),
            "http_429_count":       log_m.get("http_429_count", 0),
            "exception_count":      log_m.get("exception_count", 0),
            "exception_summary":    log_m.get("exception_summary"),
            "success":              log_m.get("success", True),
        }
        enriched.append(m)

    # --- Write to JSONL ---
    if enriched:
        with METRICS_JSONL.open("a", encoding="utf-8") as fh:
            for m in enriched:
                fh.write(json.dumps(m, ensure_ascii=False, default=str) + "\n")

    return enriched


def load_all_metrics() -> list[dict]:
    """Load all metric records from metrics.jsonl."""
    if not METRICS_JSONL.exists():
        return []
    records = []
    with METRICS_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def latest_by_adapter(metrics: Optional[list[dict]] = None) -> dict[str, dict]:
    """Return the most recent metric record for each adapter.

    Args:
        metrics: Optional pre-loaded metrics list. If None, loads from disk.

    Returns:
        dict mapping adapter_key → latest metric dict.
    """
    if metrics is None:
        metrics = load_all_metrics()

    latest: dict[str, dict] = {}
    for m in metrics:
        adapter = m.get("adapter", "")
        run_id = m.get("run_id") or ""
        if adapter not in latest or run_id > (latest[adapter].get("run_id") or ""):
            latest[adapter] = m
    return latest

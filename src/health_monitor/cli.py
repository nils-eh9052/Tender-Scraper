"""CLI entry point for the health monitor.

Usage:
    python -m src.health_monitor --collect [--run-id <stamp>]
    python -m src.health_monitor --report [--json]
    python -m src.health_monitor --baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Optional

from src.health_monitor import PROJECT_ROOT
from src.health_monitor.metrics import collect, load_all_metrics, latest_by_adapter
from src.health_monitor.baselines import refresh_baselines, load_baselines
from src.health_monitor.anomalies import check_all_latest, _load_thresholds


# ANSI colour codes (no-op on systems without terminal support)
_RESET  = "\033[0m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"

_SEVERITY_COLOUR = {
    "critical": _RED,
    "warn":     _YELLOW,
    "info":     _CYAN,
}


def _colour(text: str, code: str) -> str:
    """Wrap text in an ANSI colour code if stdout is a terminal."""
    if sys.stdout.isatty():
        return f"{code}{text}{_RESET}"
    return text


def cmd_collect(run_id: Optional[str] = None) -> int:
    """--collect: parse the latest (or specified) run log and write metrics."""
    written = collect(run_id=run_id)
    if not written:
        print("[health-monitor] No new metrics to collect (already up to date or no log found).")
        return 0
    print(f"[health-monitor] Collected {len(written)} adapter metric(s):")
    for m in written:
        tc   = m.get("tender_count")
        exc  = m.get("exception_count") or 0
        ok   = "OK" if m.get("success") else "FAIL"
        print(f"  {m['adapter']:<12} tender_count={tc}  exceptions={exc}  [{ok}]")
    return 0


def cmd_baseline() -> int:
    """--baseline: recompute and save baselines from metrics history."""
    baselines = refresh_baselines()
    print(f"[health-monitor] Baselines refreshed for {len(baselines)} adapter(s).")
    for adapter, b in sorted(baselines.items()):
        mean_7d = b.get("tender_count_7d_mean")
        streak  = b.get("zero_streak", 0)
        print(
            f"  {adapter:<12} 7d_mean={mean_7d!s:<8} zero_streak={streak}"
        )
    return 0


def _load_all_adapter_statuses() -> dict[str, str]:
    """Load adapter_status.json → {adapter_key: status_string}, excluding retired."""
    status_path = PROJECT_ROOT / "data" / "adapter_status.json"
    if not status_path.exists():
        return {}
    with status_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return {
        k: (v.get("status", "unknown") if isinstance(v, dict) else "unknown")
        for k, v in raw.items()
        if k not in ("tr", "_meta")  # exclude retired and metadata key
    }


def cmd_report(as_json: bool = False) -> int:
    """--report: display adapter health table for all 25 registered adapters."""
    # All registered adapters (excluding retired "tr")
    all_statuses = _load_all_adapter_statuses()
    if not all_statuses:
        print("[health-monitor] data/adapter_status.json not found.")
        return 1

    # Latest metric per adapter (may be empty for adapters never collected)
    all_metrics = load_all_metrics()
    latest = latest_by_adapter(all_metrics)

    baselines = load_baselines()
    thresholds = _load_thresholds()
    anomalies_all = check_all_latest(latest, baselines, thresholds)

    # Group anomalies by adapter
    anomalies_by_adapter: dict[str, list[dict]] = {}
    for a in anomalies_all:
        anomalies_by_adapter.setdefault(a.get("adapter", ""), []).append(a)

    # Sorted adapter list — all registered (25), not just those with metrics
    all_adapters = sorted(all_statuses.keys())

    if as_json:
        report = {
            "generated_at": date.today().isoformat(),
            "adapters": [],
            "anomalies": anomalies_all,
        }
        for adapter in all_adapters:
            m = latest.get(adapter, {})
            b = baselines.get(adapter, {})
            tc = m.get("tender_count")
            mean_7d = b.get("tender_count_7d_mean")
            delta_7d = round(tc - mean_7d, 1) if tc is not None and mean_7d is not None else None
            report["adapters"].append({
                "adapter":       adapter,
                "status":        m.get("adapter_status") or all_statuses.get(adapter),
                "last_run":      m.get("run_id"),
                "tender_count":  tc,
                "delta_7d":      delta_7d,
                "newest_pub":    m.get("newest_pub_date"),
                "anomaly_count": len(anomalies_by_adapter.get(adapter, [])),
            })
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0

    # ---- Text report ----
    header = (
        f"{'adapter':<12} {'status':<18} {'last_run':<18} "
        f"{'tenders':>8} {'delta_7d':>9} {'newest_pub':<12} {'anomalies'}"
    )
    print(_colour(_BOLD + header, _BOLD))
    print("-" * len(header))

    for adapter in all_adapters:
        m = latest.get(adapter, {})
        b = baselines.get(adapter, {})

        status = m.get("adapter_status") or all_statuses.get(adapter, "unknown")
        last_run = m.get("run_id") or "—"
        tc = m.get("tender_count")
        tc_str = str(tc) if tc is not None else "—"
        mean_7d = b.get("tender_count_7d_mean")
        delta_7d_str = ""
        if tc is not None and mean_7d is not None:
            delta_7d_str = f"{tc - mean_7d:+.0f}"

        newest_pub = m.get("newest_pub_date") or "—"

        adapter_anomalies = anomalies_by_adapter.get(adapter, [])
        anom_str = ""
        for a in adapter_anomalies:
            sev = a.get("severity", "")
            rule = a.get("rule", "")
            col = _SEVERITY_COLOUR.get(sev, "")
            anom_str += _colour(f"[{sev.upper()}:{rule}] ", col)

        row = (
            f"{adapter:<12} "
            f"{status:<18} "
            f"{last_run:<18} "
            f"{tc_str:>8} "
            f"{delta_7d_str:>9} "
            f"{newest_pub:<12} "
            f"{anom_str}"
        )
        print(row)

    if anomalies_all:
        print()
        print(_colour(_BOLD + "ANOMALIES DETAIL:", _BOLD))
        for a in anomalies_all:
            sev = a.get("severity", "info")
            col = _SEVERITY_COLOUR.get(sev, "")
            prefix = _colour(f"[{sev.upper()}]", col)
            print(
                f"  {prefix} {a.get('adapter')}/{a.get('rule')}: "
                f"{a.get('message')}"
            )

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m src.health_monitor",
        description="BPW Defence Tender Radar — M1 Health Monitor",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--collect",
        action="store_true",
        help="Parse the latest run log and append metrics",
    )
    group.add_argument(
        "--baseline",
        action="store_true",
        help="Recompute and save rolling baselines from metrics history",
    )
    group.add_argument(
        "--report",
        action="store_true",
        help="Print health report table",
    )
    parser.add_argument(
        "--run-id",
        metavar="STAMP",
        help="Specific run_id to collect (e.g. 20260519_140354). Only used with --collect.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output report as JSON (only used with --report)",
    )

    args = parser.parse_args(argv)

    if args.collect:
        return cmd_collect(run_id=args.run_id)
    elif args.baseline:
        return cmd_baseline()
    elif args.report:
        return cmd_report(as_json=args.as_json)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

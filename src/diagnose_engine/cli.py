"""CLI entry point for M2 Diagnose Engine.

Usage:
    python -m src.diagnose_engine --analyze [--anomaly <file>] [--dry-run]
    python -m src.diagnose_engine --report [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.env_loader import load_env_chain
from src.diagnose_engine import PROJECT_ROOT
from src.diagnose_engine.context import build_context
from src.diagnose_engine.triage import triage_anomaly
from src.diagnose_engine.diagnose import diagnose_anomaly
from src.diagnose_engine.schema import DiagnosisReport

load_env_chain()

# ANSI colour codes
_RESET  = "\033[0m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_BOLD   = "\033[1m"

_FIX_COLOUR = {
    "low_risk_auto":    _GREEN,
    "low_risk_manual":  _CYAN,
    "high_risk_human":  _RED,
    "no_action":        _YELLOW,
}


def _colour(text: str, code: str) -> str:
    if sys.stdout.isatty():
        return f"{code}{text}{_RESET}"
    return text


DIAGNOSES_DIR = PROJECT_ROOT / "data" / ".health" / "diagnoses"
ANOMALIES_DIR = PROJECT_ROOT / "data" / ".health" / "anomalies"


def _load_anomalies(anomaly_file: Optional[str], target_date: Optional[str]) -> list[dict]:
    """Load anomaly list from an explicit file or from today's anomaly file."""
    if anomaly_file:
        path = Path(anomaly_file)
        if not path.exists():
            print(f"[diagnose] ERROR: anomaly file not found: {path}")
            return []
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    # Default: today's anomaly file
    today = target_date or date.today().isoformat()
    path = ANOMALIES_DIR / f"{today}.json"
    if not path.exists():
        print(f"[diagnose] No anomaly file found for {today}: {path}")
        print(f"[diagnose] Run: python -m src.health_monitor --collect")
        return []
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _save_report(report: DiagnosisReport) -> Path:
    """Save a DiagnosisReport to data/.health/diagnoses/<date>/<id>.json."""
    today = date.today().isoformat()
    out_dir = DIAGNOSES_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.diagnosis_id}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False, default=str)
    return out_path


def cmd_analyze(
    anomaly_file: Optional[str] = None,
    dry_run: bool = False,
    target_date: Optional[str] = None,
) -> int:
    """--analyze: triage and diagnose all anomalies."""
    anomalies = _load_anomalies(anomaly_file, target_date)
    if not anomalies:
        print("[diagnose] No anomalies to analyze.")
        return 0

    print(f"[diagnose] Analyzing {len(anomalies)} anomaly(ies){'  [DRY-RUN]' if dry_run else ''}")

    # Table header
    header = (
        f"{'adapter':<14} {'failure_class':<22} {'conf':>5} "
        f"{'fix_type':<20} {'cost':>8} {'model'}"
    )
    print(_colour(_BOLD + header, _BOLD))
    print("-" * len(header))

    total_cost = 0.0
    reports: list[DiagnosisReport] = []

    for anomaly in anomalies:
        adapter = anomaly.get("adapter", "?")
        rule    = anomaly.get("rule", "?")

        # Step 1: Build context
        ctx = build_context(anomaly)

        # Step 2: Triage (Haiku)
        triage_class, triage_conf = triage_anomaly(anomaly)

        # Step 3: Full diagnosis
        report = diagnose_anomaly(ctx, triage_class, triage_conf, dry_run=dry_run)
        reports.append(report)
        total_cost += report.cost_usd

        fix_col = _colour(report.suggested_fix_type, _FIX_COLOUR.get(report.suggested_fix_type, ""))
        model_short = report.model_used.split("/")[-1].replace("[dry-run] would use ", "~")
        # strip prefix for display
        model_display = model_short[:30]

        row = (
            f"{adapter:<14} "
            f"{report.failure_class.value:<22} "
            f"{report.confidence:>5} "
            f"{fix_col:<20} "
            f"${report.cost_usd:>7.4f} "
            f"{model_display}"
        )
        print(row)

        # Save to disk (even in dry-run, to preserve triage result)
        if not dry_run:
            saved_path = _save_report(report)
            print(f"  → saved: {saved_path.relative_to(PROJECT_ROOT)}")

    print()
    print(f"Total cost: ${total_cost:.4f} USD  |  Reports: {len(reports)}")
    if dry_run:
        print("[DRY-RUN] No reports saved. Run without --dry-run to persist diagnoses.")

    return 0


def cmd_report(target_date: Optional[str] = None) -> int:
    """--report: display all diagnosis reports for a given date."""
    today = target_date or date.today().isoformat()
    report_dir = DIAGNOSES_DIR / today

    if not report_dir.exists():
        print(f"[diagnose] No diagnosis reports found for {today}")
        return 0

    report_files = sorted(report_dir.glob("*.json"))
    if not report_files:
        print(f"[diagnose] No diagnosis reports found in {report_dir}")
        return 0

    print(f"[diagnose] Diagnosis reports for {today} ({len(report_files)} total):")
    print()

    for path in report_files:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        adapter = data.get("anomaly", {}).get("adapter", "?")
        rule    = data.get("anomaly", {}).get("rule", "?")
        fc      = data.get("failure_class", "?")
        conf    = data.get("confidence", 0)
        fix_t   = data.get("suggested_fix_type", "?")
        fix_h   = data.get("fix_hint", "")
        expl    = data.get("explanation", "")
        model   = data.get("model_used", "?").split("/")[-1]
        cost    = data.get("cost_usd", 0.0)
        did     = data.get("diagnosis_id", path.stem)

        print(f"  [{did}] {adapter}/{rule}")
        print(f"    failure_class={fc}  confidence={conf}  severity={data.get('severity', '?')}")
        print(f"    fix_type={fix_t}  model={model}  cost=${cost:.4f}")
        print(f"    fix_hint: {fix_h}")
        print(f"    explanation: {expl}")
        print()

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.diagnose_engine",
        description="BPW Defence Tender Radar — M2 Diagnose Engine",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--analyze",
        action="store_true",
        help="Triage and diagnose all anomalies (default: today's file)",
    )
    group.add_argument(
        "--report",
        action="store_true",
        help="Display saved diagnosis reports for a given date",
    )
    parser.add_argument(
        "--anomaly",
        metavar="FILE",
        help="Path to anomaly JSON file (list or single record). Only used with --analyze.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Triage only (Haiku), skip full Sonnet/Opus diagnosis. No LLM cost for full diagnose.",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        dest="target_date",
        help="Date to analyze/report (default: today).",
    )

    args = parser.parse_args(argv)

    if args.analyze:
        return cmd_analyze(
            anomaly_file=args.anomaly,
            dry_run=args.dry_run,
            target_date=args.target_date,
        )
    elif args.report:
        return cmd_report(target_date=args.target_date)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

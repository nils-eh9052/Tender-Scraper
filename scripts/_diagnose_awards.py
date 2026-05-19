#!/usr/bin/env python3
"""
Award Forensic Diagnosis — Sprint 14d Pipeline Hardening

Checks five things about the current relevant.json + LLM award cache:

  a) How many notices have computed status == "Awarded" (exporter_frontend logic)?
  b) How many have award.awarded == True in the award block?
  c) How many LLM cache entries have applied=True and match!=None?
  d) Diff: IDs in LLM cache as applied, but tender NOT in relevant.json OR
           tender is in relevant.json but award.awarded != True.
  e) Heuristic leak: tenders with award.winner_name set but award.awarded != True.

Outputs to terminal + docs/RUNS/award_diagnose_<YYYYMMDD>.md.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RELEVANT = ROOT / "data" / "filtered" / "relevant.json"
LLM_LOG  = ROOT / "data" / ".award_match_llm_log.json"
OUT_DIR  = ROOT / "docs" / "RUNS"

sys.path.insert(0, str(ROOT / "src"))
from exporter_frontend import _resolve_status  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def _award_awarded(n: dict) -> bool:
    a = n.get("award") or {}
    return bool(isinstance(a, dict) and a.get("awarded"))

def _winner_name(n: dict) -> str | None:
    a = n.get("award") or {}
    if isinstance(a, dict):
        w = a.get("winner_name")
        if w:
            return str(w)
    return n.get("_winner_name") or None


# ── main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    today = date.today()
    label = today.strftime("%y%m%d")

    # Load relevant.json
    with open(RELEVANT, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)
    by_id = {n.get("tender_id"): n for n in notices}

    # ── a) computed status via exporter_frontend waterfall
    status_counts: dict[str, int] = {}
    for n in notices:
        s = _resolve_status(n, today)
        status_counts[s] = status_counts.get(s, 0) + 1
    awarded_status = status_counts.get("Awarded", 0)

    # ── b) award.awarded == True in the notice
    awarded_block = [n for n in notices if _award_awarded(n)]

    # ── c) LLM cache with applied=True + match!=None
    llm_log: dict = {}
    if LLM_LOG.exists():
        with open(LLM_LOG, encoding="utf-8") as f:
            llm_log = json.load(f)
    llm_applied = {
        tid: entry
        for tid, entry in llm_log.items()
        if entry.get("applied") and entry.get("match")
    }

    # ── d) diff: applied in cache but not properly merged in relevant.json
    gap_not_in_relevant: list[tuple[str, str]] = []   # (target_id, match_id)
    gap_no_award_block:  list[tuple[str, str, int]] = []  # (target_id, match_id, confidence)

    for tid, entry in llm_applied.items():
        match_id = entry["match"]
        conf     = entry.get("confidence", 0)
        if tid not in by_id:
            gap_not_in_relevant.append((tid, match_id))
        elif not _award_awarded(by_id[tid]):
            gap_no_award_block.append((tid, match_id, conf))

    # ── e) winner_name set but award.awarded not True
    winner_no_awarded = [
        (n.get("tender_id"), _winner_name(n))
        for n in notices
        if _winner_name(n) and not _award_awarded(n)
    ]

    # ── build report ──────────────────────────────────────────────────────────
    lines: list[str] = [
        f"# Award Forensic Diagnosis — {today.isoformat()}",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total notices in relevant.json | {len(notices)} |",
        f"| Computed status = Awarded (exporter_frontend) | {awarded_status} |",
        f"| award.awarded == True (notice block) | {len(awarded_block)} |",
        f"| LLM log: applied=True + match!=None | {len(llm_applied)} |",
        f"| Gap: applied in LLM cache but tender missing from relevant.json | {len(gap_not_in_relevant)} |",
        f"| Gap: applied in LLM cache but no award.awarded in relevant.json | {len(gap_no_award_block)} |",
        f"| Heuristic leak: winner_name set, award.awarded missing | {len(winner_no_awarded)} |",
        "",
        "## Status distribution (computed)",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- **{status}**: {count}")

    if gap_not_in_relevant:
        lines += [
            "",
            "## Gap D1: Applied in LLM cache but tender not in relevant.json",
            "",
            "| Target ID | Matched Award ID |",
            "|-----------|-----------------|",
        ]
        for tid, mid in gap_not_in_relevant:
            lines.append(f"| {tid} | {mid} |")

    if gap_no_award_block:
        lines += [
            "",
            "## Gap D2: Applied in LLM cache but award.awarded missing in relevant.json",
            "",
            "| Target ID | Matched Award ID | Confidence |",
            "|-----------|-----------------|------------|",
        ]
        for tid, mid, conf in sorted(gap_no_award_block, key=lambda x: -x[2]):
            lines.append(f"| {tid} | {mid} | {conf} |")

    if winner_no_awarded:
        lines += [
            "",
            "## Gap E: winner_name set but award.awarded missing",
            "",
            "| Tender ID | Winner Name |",
            "|-----------|-------------|",
        ]
        for tid, w in winner_no_awarded[:30]:
            lines.append(f"| {tid} | {str(w)[:80]} |")
        if len(winner_no_awarded) > 30:
            lines.append(f"| ... | ({len(winner_no_awarded) - 30} more) |")

    lines += [
        "",
        "## LLM log — full applied entries",
        "",
        "| Target ID | Match ID | Confidence | Reasoning (truncated) |",
        "|-----------|----------|------------|-----------------------|",
    ]
    for tid, entry in sorted(llm_applied.items(), key=lambda x: -x[1].get("confidence", 0)):
        reasoning = (entry.get("reasoning") or "")[:80].replace("|", "/")
        lines.append(f"| {tid} | {entry['match']} | {entry.get('confidence',0)} | {reasoning} |")

    report = "\n".join(lines)

    # ── print to terminal ─────────────────────────────────────────────────────
    print(report)
    print()

    # ── write markdown ────────────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"award_diagnose_{label}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"[OK] Report written: {out_path}")

    # ── action recommendations ────────────────────────────────────────────────
    total_gap = len(gap_not_in_relevant) + len(gap_no_award_block)
    print()
    if total_gap == 0 and not winner_no_awarded:
        print("[OK] No award gaps detected. LLM cache fully merged.")
    else:
        if total_gap > 0:
            print(f"[!] {total_gap} LLM-applied awards not reflected in relevant.json.")
            print("    -> Run: python main.py --award-match-llm --confidence 65")
        if winner_no_awarded:
            print(f"[!] {len(winner_no_awarded)} notices have winner_name but award.awarded missing.")
            print("    -> Run: python main.py --award-match")


if __name__ == "__main__":
    run()

"""Force-re-classify a subset of tenders bypassing the enrichment cache.

Targeted at the gap exposed by ``scripts/_audit_extracted_fields.py``:
notices that have a Window-A English `description_en` but are still missing
one or more of `_trailer_type_1_ai`, `_trailer_quantity_1_ai`,
`_contract_duration_ai`. Re-classification on the English copy via the
patched ``_build_prompt`` (description_en preferred, explicit qty/duration
hints) closes most of these gaps.

Cost guardrail: caps the number of API calls per run via ``--max-calls``
(default 60 ≈ ~$0.35 with Sonnet 4.6 at ~$3 in / $15 out per 1M).

Usage::

    # default: 60 candidates from data/.reclass_candidates.txt, prioritised
    python3 scripts/_force_reclassify.py

    # custom limit
    python3 scripts/_force_reclassify.py --max-calls 30

    # specific IDs (comma-separated)
    python3 scripts/_force_reclassify.py --ids UA-2026-...,CZ-N006/...

    # dry-run: print plan, no API calls, no file writes
    python3 scripts/_force_reclassify.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Workspace-aware .env loading (workspace-root .env.local + repo-local .env).
from src.env_loader import load_env_chain  # noqa: E402
load_env_chain()

from src.classifier import AiClassifier  # noqa: E402

REL_PATH = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
CANDIDATES_PATH = PROJECT_ROOT / "data" / ".reclass_candidates.txt"
ENRICHMENT_LOG_PATH = PROJECT_ROOT / "data" / ".enrichment_log.json"

# National prefixes that we prioritise (data-poorest).
_NATIONAL_PRIORITY = ("UA", "NO", "EE", "NL", "FR", "CZ", "PL", "UK", "GB", "DE", "RO", "IT", "ES", "BE")


def _is_national(tid: str) -> bool:
    if "-" not in tid:
        return False
    head = tid.split("-")[0]
    return not head.isdigit()


def _country_prefix(tid: str) -> str:
    return tid.split("-")[0] if "-" in tid else ""


def _missing_fields(notice: dict) -> tuple[bool, bool, bool]:
    return (
        not notice.get("_trailer_type_1_ai"),
        not notice.get("_trailer_quantity_1_ai"),
        not notice.get("_contract_duration_ai"),
    )


def _gap_score(notice: dict) -> int:
    """Higher = more fields missing (more leverage from re-class)."""
    return sum(_missing_fields(notice))


def _prioritise(notices_by_id: dict[str, dict], all_ids: list[str]) -> list[str]:
    """Sort candidates: national-prefix first, then by gap-count desc."""
    def key(tid: str) -> tuple[int, int]:
        n = notices_by_id.get(tid)
        if not n:
            return (3, 0)
        is_national = _is_national(tid)
        national_rank = 0 if is_national else 1  # nationals first
        return (national_rank, -_gap_score(n))
    return sorted(all_ids, key=key)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=60,
                    help="Maximum API calls to make (cost guardrail). Default 60.")
    ap.add_argument("--ids", type=str, default=None,
                    help="Comma-separated tender IDs to re-classify. Overrides candidates file.")
    ap.add_argument("--candidates", type=Path, default=CANDIDATES_PATH,
                    help="Path to candidate-IDs file (one ID per line).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan only — no API calls, no file writes.")
    args = ap.parse_args()

    if not REL_PATH.exists():
        print(f"[!] relevant.json not found: {REL_PATH}")
        return 1

    with open(REL_PATH, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)
    notices_by_id: dict[str, dict] = {n["tender_id"]: n for n in notices if n.get("tender_id")}

    # ── pick candidate ids ──
    if args.ids:
        candidate_ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    elif args.candidates.exists():
        candidate_ids = [
            line.strip() for line in args.candidates.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        # derive on the fly from notices
        candidate_ids = [
            tid for tid, n in notices_by_id.items()
            if any(_missing_fields(n)) and n.get("description_en")
        ]

    candidate_ids = _prioritise(notices_by_id, candidate_ids)

    # ── apply max-calls ceiling ──
    if args.max_calls and len(candidate_ids) > args.max_calls:
        candidate_ids = candidate_ids[: args.max_calls]

    print(f"  Targets: {len(candidate_ids)} (max-calls={args.max_calls})")
    by_prefix: dict[str, int] = {}
    for tid in candidate_ids:
        by_prefix[_country_prefix(tid) or "TED"] = by_prefix.get(_country_prefix(tid) or "TED", 0) + 1
    for prefix, n in sorted(by_prefix.items(), key=lambda kv: -kv[1]):
        print(f"    [{prefix}] {n}")

    if args.dry_run:
        print("  [dry-run] would re-classify the above; exiting.")
        return 0

    classifier = AiClassifier()
    if not classifier.is_available:
        print("[!] LLM_OPENROUTER_API_KEY not set — aborting.")
        return 1

    # ── enrichment log: load (we re-write entries for re-classified IDs) ──
    if ENRICHMENT_LOG_PATH.exists():
        with open(ENRICHMENT_LOG_PATH, encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = {}

    summary: dict[str, Any] = {
        "evaluated":   0,
        "succeeded":   0,
        "failed":      0,
        "fields_set":  {"type": 0, "qty": 0, "dur": 0},
        "samples":     [],
    }

    # Anthropic pricing (Sonnet 4.6 list, USD per 1M tokens)
    PRICE_IN = 3.0
    PRICE_OUT = 15.0
    in_tok = 0
    out_tok = 0

    for i, tid in enumerate(candidate_ids):
        n = notices_by_id.get(tid)
        if not n:
            continue
        summary["evaluated"] += 1
        before = (
            bool(n.get("_trailer_type_1_ai")),
            bool(n.get("_trailer_quantity_1_ai")),
            bool(n.get("_contract_duration_ai")),
        )

        print(f"  [{i+1}/{len(candidate_ids)}] {tid}", flush=True)
        # Call classifier directly — bypasses the cache (no log lookup here).
        result = classifier.classify_notice(n)
        if not result:
            summary["failed"] += 1
            continue

        # Apply only if relevant=true (otherwise the classifier rejected it
        # which we wouldn't want to overwrite with).
        if not result.get("relevant"):
            summary["failed"] += 1
            continue

        AiClassifier._apply_ai_result(n, result)
        # Update cache so subsequent --phase classify runs reuse the new result.
        log[tid] = {
            "result":    result,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "title":     n.get("_title_final") or n.get("_title_english") or "",
            "_force_reclass_2026_05_09": True,
        }
        summary["succeeded"] += 1

        after = (
            bool(n.get("_trailer_type_1_ai")),
            bool(n.get("_trailer_quantity_1_ai")),
            bool(n.get("_contract_duration_ai")),
        )
        for key, b, a in zip(("type", "qty", "dur"), before, after):
            if a and not b:
                summary["fields_set"][key] += 1

        # Sonnet response includes usage? Best-effort token tally —
        # AiClassifier doesn't expose it, so we skip exact accounting and
        # rely on the rough estimate at the end.
        if len(summary["samples"]) < 5:
            summary["samples"].append({
                "id": tid,
                "type": n.get("_trailer_type_1_ai") or "—",
                "qty": n.get("_trailer_quantity_1_ai"),
                "duration": n.get("_contract_duration_ai") or "—",
            })

        # Save periodically so a crash mid-run doesn't lose progress.
        if (i + 1) % 10 == 0:
            with open(ENRICHMENT_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            with open(REL_PATH, "w", encoding="utf-8") as f:
                json.dump(notices, f, ensure_ascii=False, indent=2)

    # final write
    with open(ENRICHMENT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    with open(REL_PATH, "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)

    print()
    print("  Summary:")
    print(f"    evaluated:           {summary['evaluated']}")
    print(f"    succeeded:           {summary['succeeded']}")
    print(f"    failed:              {summary['failed']}")
    print(f"    new trailer_type_1:  {summary['fields_set']['type']}")
    print(f"    new trailer_qty_1:   {summary['fields_set']['qty']}")
    print(f"    new contract_duration: {summary['fields_set']['dur']}")
    # Rough cost estimate: ~700 in + 250 out per call
    est_in = summary["succeeded"] * 700
    est_out = summary["succeeded"] * 250
    print(
        f"    est. tokens (rough): {est_in} in / {est_out} out → "
        f"~${est_in * PRICE_IN / 1e6 + est_out * PRICE_OUT / 1e6:.3f}"
    )
    if summary["samples"]:
        print()
        print("  Samples:")
        for s in summary["samples"]:
            print(f"    {s['id']}  type={s['type']!s:.40s}  qty={s['qty']}  dur={s['duration']!s:.30s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

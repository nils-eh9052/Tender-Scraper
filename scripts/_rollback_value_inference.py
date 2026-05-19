"""
Value-Inference Rollback (2026-05-18).

Removes all inferred-value artefacts from relevant.json. Defence-Intelligence
context: missing values are themselves a signal — inferred estimates distort
data perception. Only measured values (set by the source, not by the
inference module) survive.

Removed fields:
  - _value_inferred
  - _value_confidence
  - _value_inferred_reasoning

Preserved fields:
  - estimated_value (source dict)
  - _value_amount / _value_currency / _value_eur_num (measured)
  - _duration_months_inferred (Phase 3j contract-type, stays active)

Usage:
    python scripts/_rollback_value_inference.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEVANT_PATH = ROOT / "data" / "filtered" / "relevant.json"

INFERENCE_FIELDS = (
    "_value_inferred",
    "_value_confidence",
    "_value_inferred_reasoning",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strip value-inference fields from relevant.json")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    args = parser.parse_args()

    if not RELEVANT_PATH.exists():
        sys.exit(f"Not found: {RELEVANT_PATH}")

    with open(RELEVANT_PATH, encoding="utf-8") as f:
        notices = json.load(f)

    removed = {k: 0 for k in INFERENCE_FIELDS}
    touched_notices = 0

    for n in notices:
        touched = False
        for k in INFERENCE_FIELDS:
            if k in n:
                del n[k]
                removed[k] += 1
                touched = True
        if touched:
            touched_notices += 1

    print(f"Total notices:                {len(notices)}")
    print(f"Notices touched:              {touched_notices}")
    for k, c in removed.items():
        print(f"  removed {k}: {c}")

    if args.dry_run:
        print("\n[dry-run] No file writes.")
        return

    with open(RELEVANT_PATH, "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Wrote {RELEVANT_PATH}")


if __name__ == "__main__":
    main()

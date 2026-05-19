"""Audit extracted-field coverage in relevant.json (2026-05-09).

Counts per-country presence of:
  * `_trailer_type_1_ai`
  * `_trailer_quantity_1_ai`     (canonical field; spec called it `_trailer_qty_1_ai`)
  * `_contract_duration_ai`
  * `description_en`             (Window A — English description)

Writes a Markdown report to docs/RUNS/field_extraction_audit_<YYMMDD>.md.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REL_PATH = PROJECT_ROOT / "data" / "filtered" / "relevant.json"


def _country_group(notice: dict) -> str:
    tid = str(notice.get("tender_id", ""))
    if "-" in tid:
        head = tid.split("-")[0]
        if head.isdigit():  # TED-style numeric
            return "TED"
        return head
    return "?"


def _has(value) -> bool:
    return value not in (None, "", [], {})


def main() -> int:
    if not REL_PATH.exists():
        print(f"[!] relevant.json not found: {REL_PATH}")
        return 1
    with open(REL_PATH, encoding="utf-8") as f:
        rel = json.load(f)

    fields = (
        "_trailer_type_1_ai",
        "_trailer_quantity_1_ai",
        "_contract_duration_ai",
        "description_en",
    )

    by_group: dict[str, dict[str, int]] = defaultdict(lambda: dict(total=0, **{f: 0 for f in fields}))
    candidates_for_reclass: list[str] = []  # missing >=1 field but description_en present

    for n in rel:
        grp = _country_group(n)
        s = by_group[grp]
        s["total"] += 1
        for f in fields:
            if _has(n.get(f)):
                s[f] += 1
        # Reclass candidate: at least one field missing AND description_en is set
        missing = any(not _has(n.get(f)) for f in (
            "_trailer_type_1_ai", "_trailer_quantity_1_ai", "_contract_duration_ai"
        ))
        if missing and _has(n.get("description_en")):
            candidates_for_reclass.append(n["tender_id"])

    rows = sorted(by_group.items(), key=lambda kv: -kv[1]["total"])

    out_dir = PROJECT_ROOT / "docs" / "RUNS"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"field_extraction_audit_{date.today():%y%m%d}.md"

    lines: list[str] = []
    lines.append(f"# Field-Extraction Audit — {date.today():%Y-%m-%d}")
    lines.append("")
    lines.append(
        f"`relevant.json`: **{len(rel)}** notices total. Goal: surface countries where "
        f"the AI classifier failed to populate trailer-quantity / contract-duration / "
        f"trailer-type from non-English source text. Window A produced "
        f"`description_en` for 256/256 notices, so re-classification on the English "
        f"copy should close most of these gaps."
    )
    lines.append("")
    lines.append(
        "| Group | Total | trailer_type_1 | trailer_quantity_1 | contract_duration | description_en |"
    )
    lines.append(
        "| ----- | ----: | -------------: | -----------------: | ----------------: | -------------: |"
    )
    for grp, s in rows:
        cells = [grp, s["total"]]
        for f in fields:
            cells.append(f"{s[f]} ({s[f] / s['total']:.0%})")
        lines.append("| " + " | ".join(str(x) for x in cells) + " |")

    lines.append("")
    lines.append("## Re-Classification Candidates")
    lines.append("")
    lines.append(
        f"**{len(candidates_for_reclass)}** notices are missing at least one of "
        f"`_trailer_type_1_ai`, `_trailer_quantity_1_ai`, `_contract_duration_ai` "
        f"**AND** have a `description_en` field. These are the targets for the "
        f"selective Sonnet re-classification run."
    )
    lines.append("")
    lines.append("```")
    for tid in candidates_for_reclass[:50]:
        lines.append(tid)
    if len(candidates_for_reclass) > 50:
        lines.append(f"... and {len(candidates_for_reclass) - 50} more")
    lines.append("```")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Wrote {out_path}")

    # Also dump just the IDs to a sidecar file for the reclass runner.
    ids_path = PROJECT_ROOT / "data" / ".reclass_candidates.txt"
    ids_path.write_text("\n".join(candidates_for_reclass), encoding="utf-8")
    print(f"[OK] Wrote {len(candidates_for_reclass)} candidate IDs → {ids_path}")

    print()
    for grp, s in rows:
        print(
            f"  [{grp}] total={s['total']} type={s['_trailer_type_1_ai']:>3} "
            f"qty={s['_trailer_quantity_1_ai']:>3} dur={s['_contract_duration_ai']:>3} "
            f"desc_en={s['description_en']:>3}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

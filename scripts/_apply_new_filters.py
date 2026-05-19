"""Retroactive Filter-Hardening — Sprint 14j.

Applies two filters to ``data/filtered/relevant.json``:
  (1) MIN_VALUE_EUR — drop tenders with 0 < estimated_value_eur < 100_000
      (unknown / null values are KEPT).
  (2) Repair-Only Heuristic — drop tenders that look like pure
      repair/maintenance/service contracts (no new-equipment purchase).

Backups relevant.json to ``relevant.json.pre-filter-hardening-260513.bak``
before writing.

Audit trail: ``docs/RUNS/filter_hardening_260513.md`` with per-filter
drop counts, country/source breakdown, and 10 example tenders per filter.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEVANT = ROOT / "data" / "filtered" / "relevant.json"
BACKUP = ROOT / "data" / "filtered" / "relevant.json.pre-filter-hardening-260513.bak"
AUDIT_OUT = ROOT / "docs" / "RUNS" / "filter_hardening_260513.md"

sys.path.insert(0, str(ROOT))
from src.filter_engine import (
    MIN_VALUE_EUR,
    _resolve_value_eur,
    is_above_value_threshold,
    is_repair_only,
)


def _country_of(notice: dict) -> str:
    return (
        notice.get("_country_normalized")
        or (notice.get("contracting_authority") or {}).get("country", "")
        or notice.get("country", "")
        or "?"
    )


def _source_of(notice: dict) -> str:
    src = notice.get("_source")
    if src:
        return src
    raw = notice.get("_raw") or {}
    if isinstance(raw, dict) and raw.get("source"):
        return raw["source"]
    tid = str(notice.get("tender_id") or "")
    if tid.startswith(("UA-", "UK-", "CZ-", "NL-", "FR-", "DE-", "DK-", "FI-", "ES-", "IT-", "BE-", "SE-", "NO-")):
        return "National"
    if tid.startswith("CA-"):
        return "CA"
    if tid.startswith("AU-"):
        return "AU"
    return "TED" if tid else "?"


def _title_of(notice: dict) -> str:
    for k in ("title_en", "_title_final", "title", "announcement_title"):
        v = notice.get(k)
        if isinstance(v, str) and v.strip():
            return v[:80]
        if isinstance(v, dict):
            for vv in v.values():
                if vv:
                    return str(vv)[:80]
    return ""


def main() -> int:
    if not RELEVANT.exists():
        print(f"ERROR: {RELEVANT} not found", file=sys.stderr)
        return 1

    with open(RELEVANT, encoding="utf-8") as f:
        notices = json.load(f)
    pre_total = len(notices)
    print(f"Loaded {pre_total} notices from {RELEVANT.relative_to(ROOT)}")

    # Backup
    if not BACKUP.exists():
        shutil.copy2(RELEVANT, BACKUP)
        print(f"Backup created: {BACKUP.relative_to(ROOT)}")
    else:
        print(f"Backup already exists: {BACKUP.relative_to(ROOT)} (skipping)")

    dropped_value: list[dict] = []
    dropped_repair: list[dict] = []
    kept: list[dict] = []

    for n in notices:
        # Filter 1: value threshold (must run first — repair check can skip on value-drop)
        if not is_above_value_threshold(n):
            dropped_value.append(n)
            continue
        # Filter 2: repair-only
        if is_repair_only(n):
            dropped_repair.append(n)
            continue
        kept.append(n)

    post_total = len(kept)
    print(f"\n=== Filter Results ===")
    print(f"  Pre-total          : {pre_total}")
    print(f"  Dropped (value<100k): {len(dropped_value)}")
    print(f"  Dropped (repair)   : {len(dropped_repair)}")
    print(f"  Post-total         : {post_total}")

    # Write filtered relevant.json
    with open(RELEVANT, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    print(f"  Wrote {post_total} notices to {RELEVANT.relative_to(ROOT)}")

    # Build audit markdown
    by_country_value: Counter = Counter(_country_of(n) for n in dropped_value)
    by_source_value: Counter = Counter(_source_of(n) for n in dropped_value)
    by_country_repair: Counter = Counter(_country_of(n) for n in dropped_repair)
    by_source_repair: Counter = Counter(_source_of(n) for n in dropped_repair)
    by_country_total: Counter = by_country_value + by_country_repair
    by_source_total: Counter = by_source_value + by_source_repair

    AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_OUT, "w", encoding="utf-8") as f:
        f.write(f"# Filter Hardening Audit — 2026-05-13\n\n")
        f.write(f"**Sprint:** 14j — Filter-Hardening (Mindestwert + Repair-Filter)\n\n")
        f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}Z\n\n")
        f.write(f"**Source:** `data/filtered/relevant.json`\n\n")
        f.write(f"**Backup:** `{BACKUP.name}`\n\n")
        f.write(f"---\n\n## 1. Aggregate\n\n")
        f.write(f"| Metric | Value |\n|--------|------:|\n")
        f.write(f"| Pre-total | {pre_total} |\n")
        f.write(f"| Dropped — value <€{int(MIN_VALUE_EUR):,} | {len(dropped_value)} |\n")
        f.write(f"| Dropped — repair-only | {len(dropped_repair)} |\n")
        f.write(f"| Post-total | **{post_total}** |\n")
        f.write(f"| Net Δ | {post_total - pre_total:+d} |\n\n")

        f.write(f"---\n\n## 2. Country Breakdown\n\n")
        f.write(f"| Country | value-drops | repair-drops | total |\n|---------|-----------:|-------------:|------:|\n")
        for c in sorted(set(by_country_total.keys()), key=lambda k: -by_country_total[k])[:20]:
            f.write(f"| {c} | {by_country_value.get(c,0)} | {by_country_repair.get(c,0)} | {by_country_total.get(c,0)} |\n")

        f.write(f"\n---\n\n## 3. Source Breakdown\n\n")
        f.write(f"| Source | value-drops | repair-drops | total |\n|--------|-----------:|-------------:|------:|\n")
        for s in sorted(set(by_source_total.keys()), key=lambda k: -by_source_total[k]):
            f.write(f"| {s} | {by_source_value.get(s,0)} | {by_source_repair.get(s,0)} | {by_source_total.get(s,0)} |\n")

        f.write(f"\n---\n\n## 4. Sample Drops — Value <€{int(MIN_VALUE_EUR):,}\n\n")
        f.write(f"First 10 (sorted by value ascending):\n\n")
        sample_value = sorted(dropped_value, key=lambda n: _resolve_value_eur(n) or 0)[:10]
        f.write(f"| tender_id | country | value EUR | title |\n|-----------|---------|----------:|-------|\n")
        for n in sample_value:
            v = _resolve_value_eur(n) or 0
            f.write(f"| `{n.get('tender_id')}` | {_country_of(n)} | {v:,.0f} | {_title_of(n)} |\n")

        f.write(f"\n---\n\n## 5. Sample Drops — Repair-Only\n\n")
        f.write(f"First 10:\n\n")
        sample_repair = dropped_repair[:10]
        f.write(f"| tender_id | country | value EUR | title |\n|-----------|---------|----------:|-------|\n")
        for n in sample_repair:
            v = _resolve_value_eur(n) or 0
            f.write(f"| `{n.get('tender_id')}` | {_country_of(n)} | {v:,.0f} | {_title_of(n)} |\n")

        f.write(f"\n---\n\n## 6. Filter Rules (applied)\n\n")
        f.write(f"### MIN_VALUE_EUR = €{int(MIN_VALUE_EUR):,}\n\n")
        f.write(f"- `value >= MIN_VALUE_EUR` → KEEP\n")
        f.write(f"- `value == 0 or None` → KEEP (unknown — could be large)\n")
        f.write(f"- `value < MIN_VALUE_EUR` → DROP\n\n")
        f.write(f"Overridable via env var `BPW_MIN_VALUE_EUR`.\n\n")
        f.write(f"### Repair-Only Heuristic\n\n")
        f.write(f"- Repair keywords (8 languages) in `config/repair_keywords_negative.json`\n")
        f.write(f"- Procurement keywords (offset) in same file\n")
        f.write(f"- `≥2 repair hits AND 0 procurement hits` → DROP\n")
        f.write(f"- Mixed (`≥1 repair AND ≥1 procurement`) → KEEP\n")

    print(f"\nAudit report: {AUDIT_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build docs/RUNS/run_260511_activation_diff.md from pre/post snapshots
and live activity logs.

Inputs:
  - data/snapshots/snapshot_pre-activation-260511.json
  - data/snapshots/snapshot_post-activation-260511.json
  - data/.national_fallback_cache.json (B2-Fallback activity)
  - data/.document_extraction_cache.json (extraction coverage)
  - data/filtered/relevant.json (current state)

Output:
  - docs/RUNS/run_260511_activation_diff.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRE = ROOT / "data" / "snapshots" / "snapshot_pre-activation-260511.json"
POST = ROOT / "data" / "snapshots" / "snapshot_post-activation-260511.json"
FB_CACHE = ROOT / "data" / ".national_fallback_cache.json"
EX_CACHE = ROOT / "data" / ".document_extraction_cache.json"
RELEVANT = ROOT / "data" / "filtered" / "relevant.json"
PRE_RELEVANT = ROOT / "data" / "filtered" / "relevant.json.pre-activation-260511.bak"
OUT = ROOT / "docs" / "RUNS" / "run_260511_activation_diff.md"


def _load(p: Path) -> dict | list | None:
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"WARN: failed to load {p}: {e}", file=sys.stderr)
        return None


def _delta(pre: int | float | None, post: int | float | None) -> str:
    if pre is None or post is None:
        return "—"
    d = post - pre
    sign = "+" if d > 0 else ""
    return f"{sign}{d}"


def main() -> int:
    pre = _load(PRE) or {}
    post = _load(POST) or {}
    fb_cache = _load(FB_CACHE) or {}
    ex_cache = _load(EX_CACHE) or {}
    relevant = _load(RELEVANT) or []
    pre_relevant = _load(PRE_RELEVANT) or []

    OUT.parent.mkdir(parents=True, exist_ok=True)

    # === Coverage Stats ===
    pre_total = pre.get("total_tenders", 0)
    post_total = post.get("total_tenders", 0)

    # IDs new in post-run (vs pre)
    pre_ids = {n.get("tender_id") for n in pre_relevant if n.get("tender_id")}
    post_ids = {n.get("tender_id") for n in relevant if n.get("tender_id")}
    new_ids = post_ids - pre_ids
    removed_ids = pre_ids - post_ids

    # === B2-Fallback ===
    fb_entries = list(fb_cache.values()) if isinstance(fb_cache, dict) else []
    fb_keys = list(fb_cache.keys()) if isinstance(fb_cache, dict) else []
    fb_by_country: Counter = Counter()
    fb_with_docs = 0
    fb_with_winner = 0
    for k, v in (fb_cache.items() if isinstance(fb_cache, dict) else []):
        if not isinstance(v, dict):
            continue
        country = k.split(":")[-1] if ":" in k else "?"
        fb_by_country[country] += 1
        if v.get("documents"):
            fb_with_docs += 1
        af = v.get("additional_fields") or {}
        if af.get("winner"):
            fb_with_winner += 1

    # === Doc Extraction Coverage ===
    ex_keys = list(ex_cache.keys()) if isinstance(ex_cache, dict) else []
    ex_with_types = 0
    ex_high_conf = 0  # confidence >= 50
    if isinstance(ex_cache, dict):
        for v in ex_cache.values():
            if not isinstance(v, dict):
                continue
            if v.get("trailer_types"):
                ex_with_types += 1
            if (v.get("confidence") or 0) >= 50:
                ex_high_conf += 1

    # === CZ Winner ===
    cz_with_winner_pre = 0
    cz_with_winner_post = 0
    for n in pre_relevant:
        if (n.get("tender_id") or "").startswith("CZ-"):
            a = n.get("award") or {}
            if (isinstance(a, dict) and a.get("winner_name")) or n.get("_winner_name") or n.get("_fallback_winner"):
                cz_with_winner_pre += 1
    for n in relevant:
        if (n.get("tender_id") or "").startswith("CZ-"):
            a = n.get("award") or {}
            if (isinstance(a, dict) and a.get("winner_name")) or n.get("_winner_name") or n.get("_fallback_winner"):
                cz_with_winner_post += 1

    # === Extracted specs in current relevant.json ===
    relevant_with_specs = sum(1 for n in relevant if n.get("_extracted_specs"))

    # === Build Markdown ===
    lines: list[str] = []
    lines.append("# Run Diff — 2026-05-11 Activation\n")
    lines.append("**Sprint 14h — Sprint 14g Keyword-Merge + B2-Fallback + GPT-4o + CZ-Winner Activation**\n")
    lines.append(f"\nGenerated: from `snapshot_pre-activation-260511.json` ↔ `snapshot_post-activation-260511.json`\n")

    lines.append("\n## 1. Tenders.json Summary (frontend export)\n")
    lines.append(
        "| Metric | Pre | Post | Δ |\n"
        "|--------|----:|-----:|---:|\n"
        f"| Total tenders | {pre_total} | {post_total} | {_delta(pre_total, post_total)} |\n"
        f"| Distinct IDs | {pre.get('distinct_tender_ids', 0)} | {post.get('distinct_tender_ids', 0)} | {_delta(pre.get('distinct_tender_ids'), post.get('distinct_tender_ids'))} |\n"
        f"| Zero-value | {pre.get('zero_or_null_value', 0)} | {post.get('zero_or_null_value', 0)} | {_delta(pre.get('zero_or_null_value'), post.get('zero_or_null_value'))} |\n"
        f"| Total EUR value | {pre.get('total_estimated_value_eur', 0):,.0f} | {post.get('total_estimated_value_eur', 0):,.0f} | — |\n"
    )

    lines.append("\n### Status breakdown\n\n")
    lines.append("| Status | Pre | Post | Δ |\n|--------|----:|-----:|---:|\n")
    pre_st = pre.get("count_by_status", {}) or {}
    post_st = post.get("count_by_status", {}) or {}
    for s in sorted(set(list(pre_st.keys()) + list(post_st.keys()))):
        lines.append(f"| {s} | {pre_st.get(s, 0)} | {post_st.get(s, 0)} | {_delta(pre_st.get(s, 0), post_st.get(s, 0))} |\n")

    lines.append("\n### Source breakdown\n\n")
    lines.append("| Source | Pre | Post | Δ |\n|--------|----:|-----:|---:|\n")
    pre_sr = pre.get("count_by_source", {}) or {}
    post_sr = post.get("count_by_source", {}) or {}
    for s in sorted(set(list(pre_sr.keys()) + list(post_sr.keys()))):
        lines.append(f"| {s} | {pre_sr.get(s, 0)} | {post_sr.get(s, 0)} | {_delta(pre_sr.get(s, 0), post_sr.get(s, 0))} |\n")

    lines.append("\n### Country top-10\n\n")
    lines.append("| Country | Pre | Post | Δ |\n|---------|----:|-----:|---:|\n")
    pre_ct = pre.get("count_by_country_top10", {}) or {}
    post_ct = post.get("count_by_country_top10", {}) or {}
    for c in sorted(set(list(pre_ct.keys()) + list(post_ct.keys()))):
        lines.append(f"| {c} | {pre_ct.get(c, 0)} | {post_ct.get(c, 0)} | {_delta(pre_ct.get(c, 0), post_ct.get(c, 0))} |\n")

    lines.append("\n## 2. relevant.json — ID-level diff\n\n")
    lines.append(f"- Pre-run IDs: **{len(pre_ids)}**\n")
    lines.append(f"- Post-run IDs: **{len(post_ids)}**\n")
    lines.append(f"- New IDs (post − pre): **{len(new_ids)}**\n")
    lines.append(f"- Removed IDs (pre − post): **{len(removed_ids)}**\n")
    if new_ids:
        sample = sorted(new_ids)[:20]
        lines.append(f"\nSample new IDs (first 20):\n```\n{chr(10).join(sample)}\n```\n")

    lines.append("\n## 3. B2 National Fallback Activity\n\n")
    lines.append(f"- Cache entries: **{len(fb_keys)}**\n")
    lines.append(f"- With documents: **{fb_with_docs}**\n")
    lines.append(f"- With winner extracted: **{fb_with_winner}**\n")
    if fb_by_country:
        lines.append("\n| Country | Cache hits |\n|---------|----------:|\n")
        for c, n in fb_by_country.most_common():
            lines.append(f"| {c} | {n} |\n")

    lines.append("\n## 4. CZ Winner Coverage\n\n")
    lines.append(
        f"| | CZ tenders with winner |\n|---|---:|\n"
        f"| Pre-run | {cz_with_winner_pre} |\n"
        f"| Post-run | {cz_with_winner_post} |\n"
        f"| Δ | {_delta(cz_with_winner_pre, cz_with_winner_post)} |\n"
    )

    lines.append("\n## 5. GPT-4o Document Extraction Coverage\n\n")
    lines.append(f"- Cache entries: **{len(ex_keys)}**\n")
    lines.append(f"- With ≥1 trailer type: **{ex_with_types}**\n")
    lines.append(f"- High confidence (≥50): **{ex_high_conf}**\n")
    lines.append(f"- Notices in current relevant.json with `_extracted_specs`: **{relevant_with_specs}**\n")

    lines.append("\n## 6. Files Modified\n\n")
    lines.append("- `config/settings.yaml` — keyword merge applied (Sprint 14g)\n")
    lines.append("- `data/filtered/relevant.json` — new tenders from --all run\n")
    lines.append("- `shared/tenders.json` — frontend export refreshed\n")
    lines.append("- `data/.national_fallback_cache.json` — B2-Fallback cache populated\n")
    lines.append("- `data/.document_extraction_cache.json` — GPT-4o extraction cache extended\n")
    lines.append("\n**Backups:**\n")
    lines.append("- `shared/tenders.json.pre-activation-260511.bak`\n")
    lines.append("- `data/filtered/relevant.json.pre-activation-260511.bak`\n")
    lines.append("- `config/settings.yaml.pre-activation-260511.bak`\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"Diff report written: {OUT.relative_to(ROOT)}")
    print(f"\nKey numbers:")
    print(f"  Total tenders        : {pre_total} → {post_total} ({_delta(pre_total, post_total)})")
    print(f"  New tender IDs       : {len(new_ids)}")
    print(f"  B2-Fallback cache    : {len(fb_keys)} entries, {fb_with_winner} with winner")
    print(f"  CZ winners           : {cz_with_winner_pre} → {cz_with_winner_post}")
    print(f"  Extracted specs      : {relevant_with_specs} notices")
    return 0


if __name__ == "__main__":
    sys.exit(main())

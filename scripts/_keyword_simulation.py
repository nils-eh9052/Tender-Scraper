"""Re-Filter-Probe: simulates how many previously-rejected tenders would pass
the relevance threshold with the proposed new keywords from
docs/SETTINGS_KEYWORD_DIFF.yaml.

Datenbasis: data/.filter_cache.json (189 MB) — uses cached `enriched` notice
data when present, falls back to data/raw/details/{id}.json otherwise.

NO real re-run: only score recomputation against title + description text.
Output: stdout summary; estimate of [previously rejected → would now pass].

Usage:
    python3 scripts/_keyword_simulation.py [--threshold 25] [--max-low 500]
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "config" / "settings.yaml"
DIFF = ROOT / "docs" / "SETTINGS_KEYWORD_DIFF.yaml"
FILTER_CACHE = ROOT / "data" / ".filter_cache.json"
RAW_DETAILS = ROOT / "data" / "raw" / "details"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def _load_keywords_from(yaml_path: Path, key: str = "keywords") -> dict[str, list[str]]:
    """Returns {category: [terms_lower]} merged across all languages."""
    with open(yaml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    block = cfg.get(key, {}) or {}
    out: dict[str, list[str]] = {}
    for cat, by_lang in block.items():
        if not isinstance(by_lang, dict):
            continue
        terms: list[str] = []
        for lang, lst in by_lang.items():
            if isinstance(lst, list):
                for t in lst:
                    if isinstance(t, str) and t.strip():
                        terms.append(t.strip().lower())
        out[cat] = sorted(set(terms))
    return out


def _load_diff_terms() -> dict[str, list[str]]:
    """Read docs/SETTINGS_KEYWORD_DIFF.yaml and return {category: [terms]}."""
    if not DIFF.exists():
        return {}
    with open(DIFF, encoding="utf-8") as f:
        diff = yaml.safe_load(f)
    out: dict[str, list[str]] = {}
    for section in ("additions_to_existing_categories", "proposed_new_categories"):
        for cat, by_lang in (diff.get(section, {}) or {}).items():
            terms: list[str] = []
            for lang, items in (by_lang or {}).items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and isinstance(it.get("term"), str):
                        terms.append(it["term"].strip().lower())
            if terms:
                out.setdefault(cat, []).extend(sorted(set(terms)))
    return out


def _build_text_for_notice(notice: dict | None) -> str:
    """Concatenate title + description fields into a single lowercase string."""
    if not notice:
        return ""
    parts: list[str] = []
    for k in ("title", "_title_final", "announcement_title", "contract_title"):
        v = notice.get(k)
        if isinstance(v, dict):
            parts.extend(str(x) for x in v.values() if x)
        elif isinstance(v, str):
            parts.append(v)
    for k in ("description", "_description_final"):
        v = notice.get(k)
        if isinstance(v, dict):
            parts.extend(str(x) for x in v.values() if x)
        elif isinstance(v, str):
            parts.append(v)
    return " ".join(parts).lower()


def _score_text(
    text: str,
    keywords_by_cat: dict[str, list[str]],
    cpvs: list[str],
    weights: dict[str, int],
    cpv_buckets: dict[str, set[str]],
) -> int:
    """Compute relevance score from keyword matches + CPV matches."""
    if not text and not cpvs:
        return 0

    score = 0

    # Keyword scoring
    for cat, terms in keywords_by_cat.items():
        for t in terms:
            if not t:
                continue
            # Word-boundary substring match (cheap; settings.yaml original logic)
            if t in text:
                if cat == "generic_trailer":
                    score += weights.get("keyword_generic_trailer", 5)
                elif cat == "defence_context":
                    score += weights.get("defence_context_word", 10)
                else:
                    score += weights.get("keyword_category_match", 15)
                # Don't double-count multiple matches in same category
                break

    # CPV scoring
    cpv_set = {c[:8] for c in cpvs if c}
    if cpv_set & cpv_buckets.get("tier1", set()):
        score += weights.get("cpv_tier1_match", 30)
    elif cpv_set & cpv_buckets.get("tier2", set()):
        score += weights.get("cpv_tier2_match", 20)
    elif cpv_set & cpv_buckets.get("tier3", set()):
        score += weights.get("cpv_tier3_match", 5)

    return score


def _load_settings_full() -> tuple[dict, dict[str, set[str]], dict[str, int]]:
    with open(SETTINGS, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cpv_buckets = {
        "tier1": set(cfg.get("cpv_codes", {}).get("tier1_trailer_direct", []) or []),
        "tier2": set(cfg.get("cpv_codes", {}).get("tier2_defence_vehicles", []) or []),
        "tier3": set(cfg.get("cpv_codes", {}).get("tier3_transport_broad", []) or []),
    }
    weights = cfg.get("scoring", {}).get("weights", {}) or {}
    return cfg, cpv_buckets, weights


def _load_raw_detail(tid: str) -> dict | None:
    p = RAW_DETAILS / f"{tid}.json"
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=int, default=25,
                        help="Score threshold for passing (default: settings.yaml threshold_relevant=25)")
    parser.add_argument("--max-low", type=int, default=1000,
                        help="Max number of score-<10 entries to sample (extrapolated)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = parser.parse_args()
    random.seed(args.seed)

    # Load keyword sets
    cur_kw = _load_keywords_from(SETTINGS)
    new_kw = _load_diff_terms()
    log.info(f"Current keywords: {sum(len(v) for v in cur_kw.values())} terms across {len(cur_kw)} cats")
    log.info(f"Proposed new   : {sum(len(v) for v in new_kw.values())} terms across {len(new_kw)} cats")

    # Merge: union per category
    merged_kw: dict[str, list[str]] = {}
    for cat, terms in cur_kw.items():
        merged_kw[cat] = list(terms)
    for cat, terms in new_kw.items():
        merged_kw.setdefault(cat, [])
        merged_kw[cat].extend(t for t in terms if t not in merged_kw[cat])
    log.info(f"Merged total   : {sum(len(v) for v in merged_kw.values())} terms across {len(merged_kw)} cats")

    cfg, cpv_buckets, weights = _load_settings_full()

    # Load filter_cache
    log.info(f"Loading {FILTER_CACHE.name} (189 MB, ~10s)...")
    with open(FILTER_CACHE, encoding="utf-8") as f:
        fc = json.load(f)
    log.info(f"Filter cache: {len(fc):,} entries")

    # Buckets of interest:
    # 1. Score 10-24 (near-miss, just below threshold)
    # 2. Score <10 (low signal — sampled)
    near_miss_ids = [tid for tid, v in fc.items()
                     if 10 <= v.get("score", 0) < args.threshold]
    low_sig_ids = [tid for tid, v in fc.items() if v.get("score", 0) < 10]

    log.info(f"\nNear-miss (score 10-{args.threshold-1}): {len(near_miss_ids):,}")
    log.info(f"Low-signal  (score <10):           {len(low_sig_ids):,}")

    # Sample low-signal
    if len(low_sig_ids) > args.max_low:
        low_sig_sample = random.sample(low_sig_ids, args.max_low)
    else:
        low_sig_sample = low_sig_ids
    log.info(f"Low-signal sample (extrapolated): {len(low_sig_sample):,}")

    def evaluate(ids: list[str], label: str) -> tuple[int, int, list[tuple[str, int, int]]]:
        evaluated = 0
        flipped = 0
        examples: list[tuple[str, int, int]] = []
        for tid in ids:
            entry = fc.get(tid, {})
            old_score = entry.get("score", 0)
            notice = entry.get("enriched") or _load_raw_detail(tid)
            text = _build_text_for_notice(notice)
            cpvs = (notice or {}).get("cpv_codes", []) or []
            new_score = _score_text(text, merged_kw, cpvs, weights, cpv_buckets)
            evaluated += 1
            if new_score >= args.threshold and old_score < args.threshold:
                flipped += 1
                if len(examples) < 8:
                    examples.append((tid, old_score, new_score))
        return evaluated, flipped, examples

    log.info("\nRe-scoring near-miss bucket...")
    nm_eval, nm_flip, nm_ex = evaluate(near_miss_ids, "near-miss")
    log.info("\nRe-scoring low-signal sample...")
    ls_eval, ls_flip, ls_ex = evaluate(low_sig_sample, "low-signal")

    # Extrapolate low-signal
    low_total = len(low_sig_ids)
    ls_flip_rate = (ls_flip / ls_eval) if ls_eval else 0.0
    ls_extrapolated = int(round(ls_flip_rate * low_total))

    print("\n" + "=" * 64)
    print("RE-FILTER SIMULATION RESULTS")
    print("=" * 64)
    print(f"Threshold for passing : {args.threshold}")
    print()
    print("Near-miss bucket (score 10-{}):".format(args.threshold - 1))
    print(f"  Evaluated      : {nm_eval:,}")
    print(f"  Now passing    : {nm_flip:,}  ({(nm_flip/nm_eval*100 if nm_eval else 0):.1f}%)")
    print()
    print(f"Low-signal sample (random {ls_eval:,} of {low_total:,}):")
    print(f"  Now passing in sample : {ls_flip:,}  ({ls_flip_rate*100:.1f}%)")
    print(f"  Extrapolated total    : {ls_extrapolated:,}")
    print()
    print(f"ESTIMATED TOTAL UPLIFT : {nm_flip + ls_extrapolated:,} previously-rejected → would now pass")
    print(f"  Lower bound (near-miss only): {nm_flip:,}")
    print(f"  Upper bound (incl. extrapolated low-signal): {nm_flip + ls_extrapolated:,}")
    print()
    print("Sample flips (near-miss):")
    for tid, old, new in nm_ex:
        print(f"  {tid:18s}  score {old:>3d} → {new:>3d}")
    if ls_ex:
        print("Sample flips (low-signal):")
        for tid, old, new in ls_ex[:4]:
            print(f"  {tid:18s}  score {old:>3d} → {new:>3d}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

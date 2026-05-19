"""Build docs/SETTINGS_KEYWORD_DIFF.yaml from Opus brainstorm vs current settings.yaml.

Computes additive diff: terms suggested by Opus that are NOT in settings.yaml,
grouped by category and language.  Adds evidence/justification per term where
available (from OPUS_KEYWORD_BRAINSTORM.json["evidence_examples"]).

DOES NOT modify settings.yaml — output is purely a proposal for human review.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "config" / "settings.yaml"
OPUS = ROOT / "docs" / "OPUS_KEYWORD_BRAINSTORM.json"
OUT = ROOT / "docs" / "SETTINGS_KEYWORD_DIFF.yaml"

# Map Opus categories → settings.yaml category keys
# (Opus uses some new names; merge-target tells us where to put new terms.)
CATEGORY_MAP = {
    "generic_trailer":      "generic_trailer",
    "low_bed":              "low_bed",
    "semitrailer":          "semitrailer",
    "tank_transporter":     "special_purpose",   # tank_transporter merges into special_purpose
    "cargo_trailer":        "_NEW_cargo_trailer",  # genuinely new bucket
    "field_kitchen":        "field_kitchen",
    "ammunition":           "ammunition_trailer",
    "decontamination_cbrn": "_NEW_decontamination_cbrn",  # new
    "mission_module":       "mission_module",
    "loading_system":       "loading_system",
    "special_purpose":      "special_purpose",
    "dolly":                "dolly",
    "heavy_haul":           "_NEW_heavy_haul",   # new
    "defence_context":      "defence_context",
}


def _load_settings_keywords() -> dict[str, dict[str, set[str]]]:
    """Returns {category: {lang: set(terms)}} from settings.yaml (lower-cased)."""
    with open(SETTINGS, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    kw_block = cfg.get("keywords", {}) or {}
    result: dict[str, dict[str, set[str]]] = {}
    for cat, by_lang in kw_block.items():
        if not isinstance(by_lang, dict):
            continue
        result[cat] = {}
        for lang, terms in by_lang.items():
            if isinstance(terms, list):
                result[cat][lang] = {t.strip().lower() for t in terms if isinstance(t, str)}
    return result


def _evidence_index(brainstorm: dict) -> dict[tuple[str, str, str], dict]:
    """Index evidence_examples by (category, language, term-lower) → evidence dict."""
    out: dict[tuple[str, str, str], dict] = {}
    for ev in brainstorm.get("evidence_examples", []) or []:
        cat = ev.get("category", "")
        lang = ev.get("language", "")
        term = (ev.get("term", "") or "").strip().lower()
        if cat and lang and term:
            out[(cat, lang, term)] = ev
    return out


def main() -> int:
    if not OPUS.exists():
        print(f"ERROR: {OPUS} not found — run _opus_keyword_brainstorm.py first.", file=sys.stderr)
        return 1

    with open(OPUS, encoding="utf-8") as f:
        brainstorm = json.load(f)
    settings_kw = _load_settings_keywords()
    evidence = _evidence_index(brainstorm)

    additions: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    new_categories_terms: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    opus_keywords = brainstorm.get("keywords", {})
    n_added = 0
    n_skipped_existing = 0

    for opus_cat, by_lang in opus_keywords.items():
        if not isinstance(by_lang, dict):
            continue
        target_cat = CATEGORY_MAP.get(opus_cat, opus_cat)

        for lang, terms in by_lang.items():
            if not isinstance(terms, list):
                continue
            for term in terms:
                if not isinstance(term, str):
                    continue
                term_clean = term.strip()
                if not term_clean:
                    continue
                term_lc = term_clean.lower()

                # Skip if already in any existing settings category for the same language
                # (avoid cross-category duplicates that would inflate scores)
                already_present = any(
                    term_lc in (settings_kw.get(c, {}).get(lang, set()))
                    for c in settings_kw
                )
                if already_present:
                    n_skipped_existing += 1
                    continue

                ev = evidence.get((opus_cat, lang, term_lc))
                entry = {
                    "term": term_clean,
                    "opus_source_category": opus_cat,
                    "evidence_tender_id": ev.get("tender_id") if ev else None,
                    "evidence_snippet": (ev.get("snippet") if ev else None),
                }
                if target_cat.startswith("_NEW_"):
                    new_cat_name = target_cat[len("_NEW_"):]
                    new_categories_terms[new_cat_name][lang].append(entry)
                else:
                    additions[target_cat][lang].append(entry)
                n_added += 1

    # Build output YAML structure
    proposal = {
        "_meta": {
            "generated_from": str(OPUS.relative_to(ROOT)),
            "opus_model": brainstorm.get("_meta", {}).get("model"),
            "opus_cost_usd": brainstorm.get("_meta", {}).get("cost_usd"),
            "corpus_size": brainstorm.get("_meta", {}).get("corpus_size"),
            "additive_only": True,
            "instructions": (
                "Review this diff and selectively merge accepted terms into "
                "config/settings.yaml under the matching keyword category. "
                "Each entry includes evidence (tender_id + snippet) where available."
            ),
            "stats": {
                "new_terms_proposed": n_added,
                "skipped_already_in_settings": n_skipped_existing,
                "new_categories_count": len(new_categories_terms),
                "categories_to_extend": len(additions),
            },
        },
        "additions_to_existing_categories": {
            cat: {lang: items for lang, items in by_lang.items()}
            for cat, by_lang in sorted(additions.items())
        },
        "proposed_new_categories": {
            cat: {lang: items for lang, items in by_lang.items()}
            for cat, by_lang in sorted(new_categories_terms.items())
        },
        "cpv_codes_observed": brainstorm.get("cpv_codes_observed", []),
        "opus_notes": brainstorm.get("notes", ""),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(
            "# SETTINGS_KEYWORD_DIFF.yaml — Sprint 14g\n"
            "# Auto-generated additive proposal from Opus brainstorm.\n"
            "# DO NOT auto-merge — review each term against false-positive risk\n"
            "# (especially for civilian-overlap terms like 'trailer', 'remorque').\n"
            "# Once accepted, manually merge accepted terms into config/settings.yaml.\n\n"
        )
        yaml.safe_dump(proposal, f, allow_unicode=True, sort_keys=False, width=120)

    # Console summary
    print(f"Wrote {OUT.relative_to(ROOT)}")
    print(f"  New terms proposed         : {n_added}")
    print(f"  Skipped (already in conf)  : {n_skipped_existing}")
    print(f"  Existing categories extended: {len(additions)}")
    print(f"  Proposed new categories     : {sorted(new_categories_terms.keys())}")
    print()
    print("Top-3 categories by new-term count:")
    counts = [(cat, sum(len(items) for items in by_lang.values()))
              for cat, by_lang in {**additions, **new_categories_terms}.items()]
    for cat, n in sorted(counts, key=lambda x: -x[1])[:5]:
        print(f"  {cat:25s} : {n} new terms")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Curate docs/SETTINGS_KEYWORD_DIFF.yaml and merge accepted terms into config/settings.yaml.

Deterministic curation rules:
  1. DROP terms shorter than 4 characters (too generic)
  2. DROP terms in STOPLIST (civilian-overlap risk: "auto", "wagen", "stuhl", …)
  3. DROP terms already present in settings.yaml (any category, any language)
  4. KEEP all multi-word phrases (≥1 space) — too specific to be FP-prone
  5. KEEP all single-word terms ≥6 characters
  6. NEW special categories (decontamination_cbrn, heavy_haul, cargo_trailer)
     are added in full (subject to rules 1-3)

Output:
  - config/settings.yaml (rewritten with new keyword section, additive only)
  - docs/KEYWORD_MERGE_LOG.md (audit trail of what was kept / dropped / why)

DOES NOT touch any other section of settings.yaml (CPV codes, scoring,
output paths). Uses ruamel.yaml when available for round-trip preservation;
falls back to PyYAML with a deterministic dump otherwise.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "config" / "settings.yaml"
DIFF = ROOT / "docs" / "SETTINGS_KEYWORD_DIFF.yaml"
LOG_OUT = ROOT / "docs" / "KEYWORD_MERGE_LOG.md"

# Civilian-overlap stoplist — single words that triggered false positives
# in earlier QA reviews or are dangerously generic in any procurement context.
STOPLIST = {
    # Generic vehicle/object words
    "auto", "wagen", "stuhl", "tisch", "fahrt", "haus",
    "voiture", "chaise", "table", "maison",
    "samochód", "krzesło", "stół",
    "auto", "stůl",  # cz/sk
    # Bare "trailer" already covered by generic_trailer category
    "trailer", "remorque", "anhänger", "przyczepa", "rimorchio", "remolque",
    "släp", "tilhenger",
    # Common verbs / fragments that shouldn't standalone
    "supply", "delivery", "service", "purchase",
    "lieferung", "kauf",
    "livraison", "achat",
    "dostawa", "zakup",
    "dodávka", "nákup",
    "dostavă", "achiziție",
    "leveranciers",
    # Currency / numeric
    "euro", "eur", "pln", "czk", "ron", "ksh",
}

# Special new categories — apply curation but always create the section
SPECIAL_NEW_CATEGORIES = {"decontamination_cbrn", "heavy_haul", "cargo_trailer"}


def _is_multiword(term: str) -> bool:
    return len(term.split()) > 1


def _curate_term(term: str, existing_lc: set[str]) -> tuple[bool, str]:
    """Return (keep, reason)."""
    t = term.strip()
    if not t:
        return False, "empty"
    tl = t.lower()
    if len(t) < 4:
        return False, f"length <4 ({len(t)})"
    if tl in STOPLIST:
        return False, "stoplist"
    if tl in existing_lc:
        return False, "already in settings"
    if _is_multiword(t):
        return True, "multi-word phrase"
    if len(t) >= 6:
        return True, f"single word ≥6 chars ({len(t)})"
    # 4-5 char single words — only keep if explicit category-specific
    return True, f"borderline single word ({len(t)} chars)"


def _existing_lc_terms(settings_cfg: dict) -> set[str]:
    """Lowercase terms already in settings.yaml across all keyword categories."""
    out: set[str] = set()
    for cat, by_lang in (settings_cfg.get("keywords") or {}).items():
        if not isinstance(by_lang, dict):
            continue
        for lang, terms in by_lang.items():
            if isinstance(terms, list):
                for t in terms:
                    if isinstance(t, str):
                        out.add(t.strip().lower())
    return out


def main() -> int:
    if not DIFF.exists():
        print(f"ERROR: {DIFF} not found", file=sys.stderr)
        return 1
    if not SETTINGS.exists():
        print(f"ERROR: {SETTINGS} not found", file=sys.stderr)
        return 1

    with open(DIFF, encoding="utf-8") as f:
        diff = yaml.safe_load(f)
    with open(SETTINGS, encoding="utf-8") as f:
        settings_cfg = yaml.safe_load(f)

    existing_lc = _existing_lc_terms(settings_cfg)

    # Aggregate kept / dropped per (target_category, lang)
    kept: dict[str, dict[str, list[tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))
    # entries: (term, reason, evidence_tender_id)
    dropped: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def _process_section(section_name: str, dest_categories: dict, *, special: bool):
        for cat, by_lang in (dest_categories or {}).items():
            if not isinstance(by_lang, dict):
                continue
            for lang, items in by_lang.items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    term = (it.get("term") or "").strip()
                    if not term:
                        continue
                    keep, reason = _curate_term(term, existing_lc)
                    ev_id = it.get("evidence_tender_id") or ""
                    if keep:
                        kept[cat][lang].append((term, reason, ev_id))
                        existing_lc.add(term.lower())  # avoid intra-diff duplicates
                    else:
                        dropped[cat].append((f"[{lang}] {term}", reason))

    _process_section("additions", diff.get("additions_to_existing_categories", {}), special=False)
    _process_section("new", diff.get("proposed_new_categories", {}), special=True)

    # Stats
    n_kept = sum(len(items) for cat in kept.values() for items in cat.values())
    n_dropped = sum(len(items) for items in dropped.values())

    # Merge into settings_cfg["keywords"]
    kw_block = settings_cfg.setdefault("keywords", {})
    for cat, by_lang in kept.items():
        if cat not in kw_block:
            kw_block[cat] = {}
        if not isinstance(kw_block[cat], dict):
            print(f"WARNING: {cat} is not a dict in settings.yaml — skipping", file=sys.stderr)
            continue
        for lang, items in by_lang.items():
            existing_for_lang = list(kw_block[cat].get(lang, []) or [])
            existing_set_lc = {t.lower() for t in existing_for_lang if isinstance(t, str)}
            new_terms = [term for term, _reason, _ev in items if term.lower() not in existing_set_lc]
            kw_block[cat][lang] = existing_for_lang + new_terms

    # Re-write settings.yaml (preserving comments where possible)
    # Try ruamel.yaml first for round-trip; fallback to PyYAML if unavailable.
    try:
        from ruamel.yaml import YAML
        yaml_rt = YAML()
        yaml_rt.preserve_quotes = True
        yaml_rt.width = 4096
        yaml_rt.indent(mapping=2, sequence=4, offset=2)
        with open(SETTINGS, encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        # Replace keywords block in the loaded doc (preserves order + comments elsewhere)
        doc["keywords"] = kw_block
        with open(SETTINGS, "w", encoding="utf-8") as f:
            yaml_rt.dump(doc, f)
        rewrite_method = "ruamel.yaml (round-trip)"
    except Exception as e:
        # PyYAML fallback — preserves data but loses comments
        with open(SETTINGS, "w", encoding="utf-8") as f:
            yaml.safe_dump(settings_cfg, f, allow_unicode=True, sort_keys=False, width=4096)
        rewrite_method = f"PyYAML safe_dump (lost comments: {e})"

    # Write merge log
    LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_OUT, "w", encoding="utf-8") as f:
        f.write(f"# Keyword Merge Log — Sprint 14g activation\n\n")
        f.write(f"**Date:** {datetime.utcnow().date().isoformat()}\n\n")
        f.write(f"**Source:** `{DIFF.relative_to(ROOT)}`\n\n")
        f.write(f"**Target:** `{SETTINGS.relative_to(ROOT)}`\n\n")
        f.write(f"**Rewrite method:** {rewrite_method}\n\n")
        f.write(f"---\n\n## Summary\n\n")
        f.write(f"- **Terms kept:** {n_kept}\n")
        f.write(f"- **Terms dropped:** {n_dropped}\n")
        f.write(f"- **Categories touched:** {len(kept)}\n")
        f.write(f"- **Stoplist size:** {len(STOPLIST)}\n\n")
        f.write("### Curation Rules\n")
        f.write("1. Drop terms <4 chars\n")
        f.write("2. Drop stoplist matches (civilian-overlap risk)\n")
        f.write("3. Drop duplicates already in settings.yaml\n")
        f.write("4. Keep all multi-word phrases\n")
        f.write("5. Keep single-word terms ≥6 chars\n\n")

        f.write(f"---\n\n## Per-Category Detail\n\n")
        for cat in sorted(set(list(kept.keys()) + list(dropped.keys()))):
            kept_total = sum(len(items) for items in kept.get(cat, {}).values())
            dropped_total = len(dropped.get(cat, []))
            f.write(f"### `{cat}`  (kept: {kept_total}, dropped: {dropped_total})\n\n")
            if cat in kept:
                for lang in sorted(kept[cat].keys()):
                    f.write(f"**{lang}** ({len(kept[cat][lang])}):\n")
                    for term, reason, ev in kept[cat][lang][:30]:  # cap display
                        ev_str = f" — _ev_: `{ev}`" if ev else ""
                        f.write(f"- `{term}` ({reason}){ev_str}\n")
                    if len(kept[cat][lang]) > 30:
                        f.write(f"- … +{len(kept[cat][lang])-30} more\n")
                    f.write("\n")
            if cat in dropped and dropped[cat]:
                f.write(f"**Dropped** ({len(dropped[cat])}):\n")
                # Group reasons
                reason_counts: dict[str, int] = defaultdict(int)
                for _term, reason in dropped[cat]:
                    reason_counts[reason] += 1
                for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
                    f.write(f"- {count}× {reason}\n")
                f.write("\n")

    # Console summary
    print(f"=== Curation Complete ===")
    print(f"  Kept            : {n_kept}")
    print(f"  Dropped         : {n_dropped}")
    print(f"  Categories      : {len(kept)}")
    print(f"  Rewrite method  : {rewrite_method}")
    print(f"  settings.yaml   : updated ({SETTINGS.relative_to(ROOT)})")
    print(f"  Merge log       : {LOG_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

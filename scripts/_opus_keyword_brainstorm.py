"""Opus 4.7 brainstorm pass over docs/AWARDED_CORPUS.json.

Reads the corpus, packs it into a single prompt, asks Opus to extract a
comprehensive multilingual keyword list per defence-trailer category.

Output: docs/OPUS_KEYWORD_BRAINSTORM.json (UTF-8, indent=2)

Cost estimate (200k context Opus, $15/M in / $75/M out):
  86 entries × ~1500 char/entry = ~129k char ≈ 32k tokens input
  output ~6k tokens
  → ~$0.93 per call. Budget: ≤ $15.

Usage:
    python3 scripts/_opus_keyword_brainstorm.py [--dry-run]

Env:
    ANTHROPIC_API_KEY or LLM_ANTHROPIC_API_KEY required.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load .env (mirrors main.py's inline loader)
_env_path = ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _val = _line.partition("=")
        _key, _val = _key.strip(), _val.strip()
        if _val and not os.environ.get(_key):
            os.environ[_key] = _val
CORPUS_PATH = ROOT / "docs" / "AWARDED_CORPUS.json"
OUT_PATH = ROOT / "docs" / "OPUS_KEYWORD_BRAINSTORM.json"

MODEL = "openrouter/anthropic/claude-opus-4.1"  # routed via OpenRouter (Anthropic direct exhausted)
MAX_TOKENS = 8000
DESC_LIMIT = 1500  # chars of description per tender
TITLE_LIMIT = 500

CATEGORIES = [
    "generic_trailer",
    "low_bed",
    "heavy_haul",
    "semitrailer",
    "tank_transporter",
    "cargo_trailer",
    "field_kitchen",
    "ammunition",
    "decontamination_cbrn",
    "mission_module",
    "loading_system",
    "special_purpose",
    "dolly",
    "defence_context",
]

SYSTEM_PROMPT = """You are a defence-procurement linguistics expert.
You will receive a corpus of awarded/closed defence-trailer tenders in their
ORIGINAL languages (German, French, Polish, Czech, Romanian, Italian, Dutch,
Danish, Swedish, Norwegian, Spanish, Ukrainian, Greek, etc.).

Your task: extract a COMPREHENSIVE multilingual keyword list per defence-trailer
category. Be systematic — when a tender uses a specific term in one language,
PROACTIVELY infer plausible equivalents in other major procurement languages
(de, en, fr, it, es, pl, cs, sk, ro, nl, da, sv, no, fi, uk, ua, hu, sl, hr,
el, pt, tr, et, lt, lv).

Categories (return keys exactly as listed):
- generic_trailer        — generic "trailer", "anhanger", "remorque", "przyczepa"
- low_bed                — Tieflader, lowboy, niskopodwoziowa, surbaissée
- heavy_haul             — HET, schwerlast, transport tonnage, heavy equipment transport
- semitrailer            — articulated, sattelauflieger, semi-remorque, naczepa
- tank_transporter       — tank transport carrier (NOT fuel tank), Panzertransport
- cargo_trailer          — general purpose / cargo / Lastenanhänger
- field_kitchen          — Feldküche, kuchnia polowa, polní kuchyně, cuisine de campagne
- ammunition             — Munitions-, przyczepa amunicyjna, remorque munitions
- decontamination_cbrn   — CBRN/ABC-Dekontamination, dekontaminace, NBC
- mission_module         — Wechselaufbau, shelter, abrollbehälter, mission module
- loading_system         — Hakenladegerät, hookloader, ampliroll, abrollkipper
- special_purpose        — Bergeanhänger, recovery, brückenleger, pioniergerät
- dolly                  — dolly axle, Nachläufer
- defence_context        — military/defence/army terms (used for scoring boost)

Return ONLY a valid JSON object (no markdown fences, no commentary) with this
exact schema:
{
  "languages": ["de", "en", "fr", "pl", "cs", "ro", "it", "nl", "da", "sv", "no", "es", "uk", ...],
  "keywords": {
    "<category>": {
      "<lang>": ["<term1>", "<term2>", ...]
    }
  },
  "cpv_codes_observed": ["34223000", "35610000", ...],
  "evidence_examples": [
    {
      "tender_id": "<id>",
      "language": "<lang>",
      "category": "<category>",
      "term": "<term>",
      "snippet": "<short context from corpus>"
    }
  ],
  "notes": "<brief observations on coverage gaps or ambiguities>"
}

RULES:
1. Each term must be lowercase EXCEPT proper nouns/acronyms (NATO, CBRN, BAAINBw).
2. Do NOT duplicate terms across categories — pick the BEST fit.
3. Include at least 3 terms per (category, language) pair where evidence exists.
4. For low-evidence (lang, category) pairs, make conservative inferences only —
   prefer omission over hallucination.
5. Include compound/phrase keywords if they appear (e.g. "remorque porte-engins",
   "system załadunku DROPS").
6. Keep "evidence_examples" focused — pick 1 representative example per
   (category, language) you're confident about (target: 30–60 examples total).
7. CPV codes: include any observed in the corpus, especially non-trailer codes
   that signal defence trailer procurement (e.g. 35400000, 50114000).
"""


def _build_corpus_text(corpus: list[dict]) -> str:
    """Pack the corpus into a compact, model-readable format."""
    lines: list[str] = []
    for i, c in enumerate(corpus, 1):
        country = c.get("country") or "?"
        lang = c.get("language") or "?"
        title = (c.get("title_original") or "")[:TITLE_LIMIT].strip()
        desc = (c.get("description_original") or "")[:DESC_LIMIT].strip()
        cpv = ",".join((c.get("cpv_codes") or [])[:6])
        authority = (c.get("authority") or "")[:80]
        winner = (c.get("winner") or "")[:80]
        block = (
            f"---\n"
            f"#{i} [{country}/{lang}] {c.get('tender_id', '?')} "
            f"(CPV: {cpv}; auth: {authority}; winner: {winner})\n"
            f"TITLE: {title}\n"
            f"DESC: {desc}\n"
        )
        lines.append(block)
    return "\n".join(lines)


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Build the prompt, print stats, but do NOT call Opus.")
    parser.add_argument("--input", type=Path, default=CORPUS_PATH,
                        help="Override corpus path.")
    parser.add_argument("--output", type=Path, default=OUT_PATH,
                        help="Override output path.")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: corpus not found: {args.input}", file=sys.stderr)
        return 1

    with open(args.input, encoding="utf-8") as f:
        corpus = json.load(f)

    print(f"Loaded {len(corpus)} corpus entries from {args.input.relative_to(ROOT)}")

    user_msg = (
        f"Corpus of {len(corpus)} resolved defence-trailer tenders below.\n"
        f"Categories to extract: {', '.join(CATEGORIES)}\n\n"
        f"=== CORPUS START ===\n"
        f"{_build_corpus_text(corpus)}\n"
        f"=== CORPUS END ===\n\n"
        f"Now produce the JSON keyword extraction described in the system message."
    )

    print(f"Prompt size       : {len(user_msg):,} chars")
    print(f"Estimated tokens  : ~{len(user_msg)//4:,} input, ~{MAX_TOKENS} max output")
    print(f"Estimated cost    : ~${(len(user_msg)//4)/1_000_000 * 15.0 + MAX_TOKENS/1_000_000 * 75.0:.3f}")

    if args.dry_run:
        print("\n[dry-run] Skipping API call.")
        return 0

    sys.path.insert(0, str(ROOT))
    from src import llm_router

    try:
        text, usage = llm_router.call_with_usage(
            MODEL, SYSTEM_PROMPT, user_msg, max_tokens=MAX_TOKENS
        )
    except Exception as e:
        print(f"ERROR: Opus call failed: {e}", file=sys.stderr)
        return 2

    actual_cost = llm_router.estimate_cost_usd(
        MODEL, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    )
    print(f"\nOpus call complete:")
    print(f"  Input tokens    : {usage.get('input_tokens', 0):,}")
    print(f"  Output tokens   : {usage.get('output_tokens', 0):,}")
    print(f"  Actual cost     : ${actual_cost:.4f}")

    cleaned = _strip_fences(text)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Save raw for inspection
        raw_path = args.output.with_suffix(".raw.txt")
        raw_path.write_text(text, encoding="utf-8")
        print(f"ERROR: JSON parse failed: {e}", file=sys.stderr)
        print(f"  Raw output saved to: {raw_path.relative_to(ROOT)}", file=sys.stderr)
        return 3

    # Augment with usage metadata
    result["_meta"] = {
        "model": MODEL,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cost_usd": round(actual_cost, 4),
        "corpus_size": len(corpus),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Summary stats
    kws = result.get("keywords", {})
    total_terms = sum(len(v) for cat in kws.values() for v in cat.values()) if isinstance(kws, dict) else 0
    n_categories = len(kws) if isinstance(kws, dict) else 0
    n_languages = len(result.get("languages", []))

    print(f"\nResult written to: {args.output.relative_to(ROOT)}")
    print(f"  Categories      : {n_categories}")
    print(f"  Languages       : {n_languages}")
    print(f"  Total terms     : {total_terms}")
    print(f"  Evidence items  : {len(result.get('evidence_examples', []))}")
    print(f"  CPV observed    : {len(result.get('cpv_codes_observed', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

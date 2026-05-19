"""
Description Quality Audit — Sprint 14j+

Classifies every notice in relevant.json into:
  CLEAN          — description_en ≤4 sentences, no boilerplate, human-readable
  RAW_ENGLISH    — description_en is an unedited English dump (pass-through or
                   starts with procurement-notice headers / too long)
  RAW_NATIVE     — no description_en, source text is non-English
  EMPTY          — no usable description at all

Writes docs/DESCRIPTION_AUDIT_260513.md with full stats + samples.

Usage:
    python scripts/_audit_description_quality.py
    python scripts/_audit_description_quality.py --json   # also dump JSON
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEVANT_PATH = ROOT / "data" / "filtered" / "relevant.json"
DESC_CACHE_PATH = ROOT / "data" / ".description_translation_cache.json"
AUDIT_OUT = ROOT / "docs" / "DESCRIPTION_AUDIT_260513.md"

# ── Bad-prefix patterns (lower-case) ─────────────────────────────────────────
BAD_PREFIXES: tuple[str, ...] = (
    "file number",
    "notice of proposed procurement",
    "avis de projet",
    "solicitation number",
    "reissue of request",
    "this solicitation",
    "nso number",
    "abn:",
    "procurement identification",
    "solicitation cancels",
    "this request for",
    "note:",
    "amendment",
)

_ENGLISH_STOPWORDS = {
    "the", "of", "for", "and", "with", "to", "in", "on", "by",
    "from", "at", "or", "is", "are", "as", "an", "be",
}


def _sentence_count(text: str) -> int:
    normalized = re.sub(r"(\d)\.(\d)", r"\1,\2", text)
    return len([s for s in re.split(r"[.!?]+", normalized) if len(s.strip()) > 10])


def _is_likely_english(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    if ascii_chars / max(len(text), 1) < 0.90:
        return False
    tokens = set(re.findall(r"\b[a-zA-Z]{2,}\b", text.lower()))
    return bool(tokens & _ENGLISH_STOPWORDS)


def _source_text(notice: dict) -> str:
    for f in ("_description_final", "description", "_description_english"):
        v = notice.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def classify(notice: dict, cache: dict) -> tuple[str, str]:
    """Return (class, reason)."""
    desc_en = (notice.get("description_en") or "").strip()
    src = _source_text(notice)
    tid = notice.get("tender_id", "")

    if not desc_en:
        if not src:
            return "EMPTY", "no description at all"
        if _is_likely_english(src):
            return "RAW_ENGLISH", "English source not yet cleaned"
        return "RAW_NATIVE", "non-English source, no description_en"

    # Has description_en — check quality
    low = desc_en.lower().strip()

    # Bad-prefix check
    for prefix in BAD_PREFIXES:
        if low.startswith(prefix):
            return "RAW_ENGLISH", f"starts with boilerplate: '{prefix}'"

    # Verbosity check — > 6 sentences = probably unprocessed
    n_sent = _sentence_count(desc_en)
    if n_sent > 6:
        return "RAW_ENGLISH", f"too long ({n_sent} sentences)"

    # Identical to source — only bad if the SOURCE itself is verbose or boilerplate.
    # A 1-2 sentence English summary that happens to be identical to an already-clean
    # source field (_description_english) is fine → classified CLEAN.
    if src and desc_en == src:
        src_sents = _sentence_count(src)
        src_low = src.lower().strip()
        if src_sents > 4 or any(src_low.startswith(p) for p in BAD_PREFIXES):
            return "RAW_ENGLISH", f"pass-through of verbose/boilerplate source ({src_sents} sent.)"

    # Cache check: was it a heuristic is_english pass-through of a long text?
    cache_key = f"{tid}:{hashlib.sha1(src.encode()).hexdigest()[:12]}" if src else ""
    entry = cache.get(cache_key)
    if entry and entry.get("is_english") and not entry.get("model"):
        if n_sent > 4:
            return "RAW_ENGLISH", f"heuristic passthrough, {n_sent} sentences"

    return "CLEAN", f"{n_sent} sentence(s)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Also write JSON output")
    parser.add_argument(
        "--relevant", default=str(RELEVANT_PATH), help="Path to relevant.json"
    )
    args = parser.parse_args()

    relevant_path = Path(args.relevant)
    if not relevant_path.exists():
        sys.exit(f"Not found: {relevant_path}")

    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    cache: dict = {}
    if DESC_CACHE_PATH.exists():
        with open(DESC_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)

    counts: Counter[str] = Counter()
    by_country: dict[str, Counter] = defaultdict(Counter)
    by_source: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list[dict]] = defaultdict(list)

    for n in notices:
        cls, reason = classify(n, cache)
        counts[cls] += 1
        country = n.get("_country_normalized") or "Unknown"
        source = n.get("_source") or "?"
        by_country[country][cls] += 1
        by_source[source][cls] += 1
        if len(samples[cls]) < 5:
            desc_en = (n.get("description_en") or "").strip()
            src = _source_text(n)
            samples[cls].append({
                "id": n.get("tender_id"),
                "country": country,
                "reason": reason,
                "desc_en_head": desc_en[:200],
                "src_head": src[:120],
            })

    total = len(notices)
    raw_count = counts["RAW_ENGLISH"]
    clean_count = counts["CLEAN"]
    raw_pct = raw_count / total * 100 if total else 0
    clean_pct = clean_count / total * 100 if total else 0

    # ── Write markdown report ─────────────────────────────────────────────────
    lines: list[str] = [
        f"# Description Quality Audit — {date.today().isoformat()}",
        "",
        f"**relevant.json:** `{relevant_path}` ({total} notices)",
        "",
        "## 1. Overall Classification",
        "",
        "| Class | Count | % |",
        "|-------|------:|--:|",
    ]
    for cls in ("CLEAN", "RAW_ENGLISH", "RAW_NATIVE", "EMPTY"):
        n_cls = counts[cls]
        pct = n_cls / total * 100 if total else 0
        lines.append(f"| {cls} | {n_cls} | {pct:.1f}% |")

    lines += [
        "",
        f"> **RAW_ENGLISH rate: {raw_pct:.1f}%** (target: <5% after cleaning pass)",
        "",
        "## 2. By Country",
        "",
        "| Country | CLEAN | RAW_ENGLISH | RAW_NATIVE | EMPTY |",
        "|---------|------:|------------:|-----------:|------:|",
    ]
    for country in sorted(by_country, key=lambda c: -sum(by_country[c].values())):
        cc = by_country[country]
        lines.append(
            f"| {country} | {cc['CLEAN']} | {cc['RAW_ENGLISH']} | "
            f"{cc['RAW_NATIVE']} | {cc['EMPTY']} |"
        )

    lines += [
        "",
        "## 3. By Source",
        "",
        "| Source | CLEAN | RAW_ENGLISH | RAW_NATIVE | EMPTY |",
        "|--------|------:|------------:|-----------:|------:|",
    ]
    for src in sorted(by_source, key=lambda s: -sum(by_source[s].values())):
        cc = by_source[src]
        lines.append(
            f"| {src} | {cc['CLEAN']} | {cc['RAW_ENGLISH']} | "
            f"{cc['RAW_NATIVE']} | {cc['EMPTY']} |"
        )

    lines += ["", "## 4. RAW_ENGLISH Samples (up to 5)", ""]
    for s in samples.get("RAW_ENGLISH", []):
        lines += [
            f"**{s['id']}** ({s['country']}) — _{s['reason']}_",
            f"```",
            s["desc_en_head"][:200],
            f"```",
            "",
        ]

    lines += ["", "## 5. CLEAN Samples (up to 3)", ""]
    for s in samples.get("CLEAN", [])[:3]:
        lines += [
            f"**{s['id']}** ({s['country']})",
            f"```",
            s["desc_en_head"][:200],
            f"```",
            "",
        ]

    AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Audit written → {AUDIT_OUT}")

    # Console summary
    print(f"\nTotal: {total} | CLEAN: {clean_count} ({clean_pct:.1f}%) | "
          f"RAW_ENGLISH: {raw_count} ({raw_pct:.1f}%)")
    print(f"       RAW_NATIVE: {counts['RAW_NATIVE']} | EMPTY: {counts['EMPTY']}")

    print("\nBy country (RAW_ENGLISH):")
    for country in sorted(by_country, key=lambda c: -by_country[c]["RAW_ENGLISH"]):
        r = by_country[country]["RAW_ENGLISH"]
        if r:
            print(f"  {country}: {r}")

    if args.json:
        json_out = AUDIT_OUT.with_suffix(".json")
        json_out.write_text(
            json.dumps(
                {"total": total, "counts": dict(counts),
                 "by_country": {k: dict(v) for k, v in by_country.items()},
                 "samples": {k: v for k, v in samples.items()}},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[OK] JSON written → {json_out}")


if __name__ == "__main__":
    main()

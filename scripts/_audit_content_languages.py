"""
Content Language Audit — diagnostic tool
Read-only analysis of shared/tenders.json.

Usage:
    python3 scripts/_audit_content_languages.py
    python3 scripts/_audit_content_languages.py /path/to/tenders.json

Checks whether title_en (or title) and description fields are English.
Heuristic: ASCII ratio > 0.85 AND at least one common English stop-word present.
Exit code is always 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Default path: repo_root/shared/tenders.json ───────────────────────────────
# __file__ = ted-scraper/ted-scraper/scripts/_audit_content_languages.py
# parent   = scripts/
# .parent  = ted-scraper/  (inner)
# .parent  = ted-scraper/  (outer)
# .parent  = 02_Tender Radar/
# / shared / tenders.json
DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "shared" / "tenders.json"
)

# Common English stop-words used as language signal
EN_STOP_WORDS = {
    "the", "of", "for", "and", "with", "to", "in", "on", "by", "from",
    "or", "is", "are", "as", "an", "be", "a", "this", "that", "which",
    "no", "not", "at", "its", "their",
    "procurement", "supply", "framework", "acquisition",
    "trailer", "trailers", "vehicle", "vehicles", "military", "defence",
    "defense", "truck", "trucks", "equipment", "contract", "tender",
    "purchase", "delivery", "maintenance", "transport", "units", "pcs",
    "low-bed", "semi-trailer",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ascii_ratio(text: str) -> float:
    """Return the fraction of characters with ord < 128."""
    if not text:
        return 0.0
    return sum(1 for ch in text if ord(ch) < 128) / len(text)


def _has_en_stop_word(text: str) -> bool:
    """Return True if at least one known English stop-word appears in text."""
    # Simple word-boundary split: lower-case, strip punctuation
    words = set(
        w.strip("\"'.,;:!?()[]{}/-")
        for w in text.lower().split()
    )
    return bool(words & EN_STOP_WORDS)


def is_english(text: str | None) -> bool:
    """Heuristic: either pure ASCII (>= 0.98 ratio) OR stop-word present.

    Rationale: every EU procurement language except English uses non-ASCII
    characters (accents, umlauts, Cyrillic, Czech háček…).  A title that is
    >98% plain ASCII is almost certainly English (or at worst Latin-script with
    no diacritics — which still reads correctly in English UI).
    Short titles like "Car Trailer" or "Hook-lift trucks" are pure ASCII but
    lack stop-words; the 0.98 gate catches them without false positives from
    e.g. Polish "Zakup pojazdow" (also pure ASCII — so we keep the stop-word
    gate as a secondary signal for longer texts where Polish/Estonian/Turkish
    would also be pure ASCII).
    """
    if not text or not text.strip():
        return False
    ratio = _ascii_ratio(text)
    # Short pure-ASCII title: almost certainly English in this dataset
    if ratio >= 0.98 and len(text.split()) <= 12:
        return True
    # Longer text: require both high ASCII + a recognisable stop-word
    return ratio > 0.85 and _has_en_stop_word(text)


# ── Load ──────────────────────────────────────────────────────────────────────

def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    # tenders.json may be a list or a dict with a list under a key
    if isinstance(data, list):
        return data
    # try common wrapper keys
    for key in ("tenders", "results", "items", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    # fallback: values of top-level dict
    if isinstance(data, dict):
        return list(data.values())
    return []


# ── Analysis ──────────────────────────────────────────────────────────────────

def audit(tenders: list[dict]) -> None:
    total = len(tenders)
    if total == 0:
        print("No tenders found in file.")
        return

    en_title_count = 0
    en_desc_count = 0
    missing_title_en = 0
    non_en_titles: list[dict] = []
    non_en_descs: list[dict] = []

    for t in tenders:
        tid = t.get("id") or t.get("tender_id") or t.get("_id") or "—"
        country = (
            t.get("country")
            or t.get("_country_normalized")
            or t.get("buyer_country")
            or "—"
        )

        # ── Title ──────────────────────────────────────────────────────────
        title_en = t.get("title_en") or t.get("title") or ""
        if not (t.get("title_en") or "").strip():
            missing_title_en += 1

        if is_english(title_en):
            en_title_count += 1
        else:
            non_en_titles.append({
                "id": tid,
                "country": country,
                "title": (title_en or "").strip()[:80],
            })

        # ── Description ────────────────────────────────────────────────────
        description = t.get("description") or t.get("_description_final") or ""
        if is_english(description):
            en_desc_count += 1
        else:
            non_en_descs.append({
                "id": tid,
                "country": country,
                "description": (description or "").strip()[:80],
            })

    pct_title = 100 * en_title_count / total
    pct_desc = 100 * en_desc_count / total

    # ── Overall stats ─────────────────────────────────────────────────────
    print("=" * 72)
    print("CONTENT LANGUAGE AUDIT")
    print("=" * 72)
    print(f"  Total tenders          : {total:,}")
    print(f"  English titles         : {en_title_count:,}  ({pct_title:.1f}%)")
    print(f"  English descriptions   : {en_desc_count:,}  ({pct_desc:.1f}%)")
    print(f"  Missing title_en field : {missing_title_en:,}")
    print()

    # ── Top 10 non-English titles ──────────────────────────────────────────
    print("-" * 72)
    print(f"TOP 10 NON-ENGLISH TITLES  ({len(non_en_titles)} total non-English)")
    print("-" * 72)
    if non_en_titles:
        for row in non_en_titles[:10]:
            print(f"  [{row['country']:>12}]  {row['id']:<20}  {row['title']}")
    else:
        print("  (all titles appear to be English)")
    print()

    # ── Top 10 non-English descriptions ───────────────────────────────────
    print("-" * 72)
    print(f"TOP 10 NON-ENGLISH DESCRIPTIONS  ({len(non_en_descs)} total non-English)")
    print("-" * 72)
    if non_en_descs:
        for row in non_en_descs[:10]:
            print(f"  [{row['country']:>12}]  {row['id']:<20}  {row['description']}")
    else:
        print("  (all descriptions appear to be English)")
    print()
    print("=" * 72)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = DEFAULT_PATH

    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        print(f"  Default path: {DEFAULT_PATH}", file=sys.stderr)
        print("  Pass an explicit path as argv[1] if needed.", file=sys.stderr)
        sys.exit(0)  # diagnostic tool — always exit 0

    print(f"Loading {path} …", file=sys.stderr)
    tenders = load(path)
    print(f"Loaded {len(tenders):,} tenders.", file=sys.stderr)
    print(file=sys.stderr)

    audit(tenders)


if __name__ == "__main__":
    main()

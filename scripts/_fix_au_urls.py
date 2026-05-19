"""Backfill: rewrite broken AusTender CN URLs in relevant.json.

The au_ocds_adapter previously emitted ``https://www.tenders.gov.au/cn/{ID}/View``
which returns HTTP 404 (verified 2026-05-20).  The correct pattern is
``https://www.tenders.gov.au/cn/Show/{ID}`` (case-insensitive Cn vs cn).

This script rewrites ``source_url_national`` for every AU-TEN notice in
``data/filtered/relevant.json``.  A dry-run mode shows the diff without
mutating the file.  Also invalidates any matching entries from the URL
health cache so the next Phase 3l pass re-validates with the fresh URL.

Usage:
    python scripts/_fix_au_urls.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEVANT = ROOT / "data" / "filtered" / "relevant.json"
URL_CACHE = ROOT / "data" / ".url_health_cache.json"

_OLD_PATTERN = re.compile(
    r"^https?://(?:www\.)?tenders\.gov\.au/cn/([A-Za-z0-9_\-]+)/View/?$",
    re.IGNORECASE,
)


def _new_url(cn_id: str) -> str:
    cn_clean = re.sub(r"[^\w\-]", "", cn_id)
    return f"https://www.tenders.gov.au/cn/Show/{cn_clean}"


def _is_au(notice: dict) -> bool:
    if (notice.get("_source") or "").upper() == "AU-TEN":
        return True
    tid = str(notice.get("tender_id") or "")
    return tid.upper().startswith("AU-TEN-")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not RELEVANT.exists():
        print(f"  [!] {RELEVANT} not found", file=sys.stderr)
        return 1

    notices = json.loads(RELEVANT.read_text(encoding="utf-8"))
    au_total = sum(1 for n in notices if _is_au(n))
    changes = 0
    cache_invalidations: set[str] = set()

    for n in notices:
        if not _is_au(n):
            continue
        url = n.get("source_url_national") or ""
        m = _OLD_PATTERN.match(url) if isinstance(url, str) else None
        if not m:
            continue
        cn_id = m.group(1)
        fixed = _new_url(cn_id)
        if fixed == url:
            continue
        print(f"  {cn_id:<14}  {url}  →  {fixed}")
        n["source_url_national"] = fixed
        cache_invalidations.add(url)
        changes += 1

    print()
    print(f"  AU-TEN total in relevant.json: {au_total}")
    print(f"  URL rewrites performed:        {changes}")
    print(f"  Cache entries to invalidate:   {len(cache_invalidations)}")

    if args.dry_run:
        print("  [dry-run] no files written")
        return 0

    if changes:
        RELEVANT.write_text(json.dumps(notices, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  ✓ Wrote {RELEVANT.relative_to(ROOT)}")

    if cache_invalidations and URL_CACHE.exists():
        cache = json.loads(URL_CACHE.read_text(encoding="utf-8"))
        before = len(cache)
        for stale_url in cache_invalidations:
            cache.pop(stale_url, None)
        URL_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"  ✓ Removed {before - len(cache)} stale entries from URL health cache")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

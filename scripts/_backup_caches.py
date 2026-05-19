#!/usr/bin/env python3
"""Backup critical pipeline state.

Default: copy critical state into ``data/.backups/<stamp>/`` and rotate so
only the last ``MAX_BACKUPS`` directories survive. Also supports listing
existing backups and restoring a chosen stamp.

Usage:
    python scripts/_backup_caches.py              # take a backup
    python scripts/_backup_caches.py --list       # list available stamps
    python scripts/_backup_caches.py --restore <stamp>
    python scripts/_backup_caches.py --dry-run    # show what would happen

Excluded by design:
    data/.filter_cache.json  (~189 MB, regenerable from data/raw/details/*)
    data/raw/details/*.json  (~35k files, regenerable from TED API)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "data" / ".backups"
MAX_BACKUPS = 14

# Critical state. Paths are relative to PROJECT_ROOT. Missing files are
# silently skipped — a backup should never fail just because some cache
# hasn't been initialised yet.
TARGETS = [
    # Main data file
    "data/filtered/relevant.json",

    # Costly caches (LLM-spend or hours of rebuild)
    "data/.enrichment_log.json",
    "data/.document_extraction_cache.json",
    "data/.award_match_llm_log.json",

    # State / resume
    "data/.checkpoint.json",
    "data/.url_health_cache.json",

    # Cheap caches (regenerable but nice to keep)
    "data/.translation_cache.json",
    "data/.description_translation_cache.json",
    "data/.contract_type_cache.json",
    "data/.text_mining_cache.json",
    "data/.national_fallback_cache.json",
    "data/.strategy_a_cache.json",
]


def _human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def take_backup(dry_run: bool = False) -> Path:
    """Copy ``TARGETS`` into ``data/.backups/<stamp>/`` and rotate."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_dir = BACKUP_DIR / stamp
    total = 0
    copied: list[tuple[str, int]] = []
    for rel in TARGETS:
        src = PROJECT_ROOT / rel
        if not src.exists():
            continue
        size = src.stat().st_size
        total += size
        copied.append((rel, size))
        if not dry_run:
            dst = dst_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    if not copied:
        print("[backup] nothing to back up — pipeline state empty")
        return dst_dir

    print(
        f"[backup] {'DRY-RUN ' if dry_run else ''}{stamp} — "
        f"{len(copied)} files, {_human_size(total)}"
    )
    for rel, size in copied:
        print(f"  {rel}  ({_human_size(size)})")

    if dry_run:
        return dst_dir

    # Rotate: keep newest MAX_BACKUPS dirs only.
    existing = sorted(p for p in BACKUP_DIR.glob("*") if p.is_dir())
    for old in existing[:-MAX_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)
    print(
        f"[backup] dir={dst_dir.relative_to(PROJECT_ROOT)}  "
        f"retained={MAX_BACKUPS}"
    )
    return dst_dir


def list_backups() -> None:
    if not BACKUP_DIR.exists():
        print("(no backups yet)")
        return
    entries = sorted(p for p in BACKUP_DIR.glob("*") if p.is_dir())
    if not entries:
        print("(no backups yet)")
        return
    for p in entries:
        total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        n = sum(1 for f in p.rglob("*") if f.is_file())
        print(f"  {p.name}  {n} files  {_human_size(total)}")


def restore(stamp: str, dry_run: bool = False) -> None:
    src_dir = BACKUP_DIR / stamp
    if not src_dir.is_dir():
        print(f"[restore] no backup with stamp '{stamp}'", file=sys.stderr)
        sys.exit(2)
    n = 0
    for src in src_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(src_dir)
        dst = PROJECT_ROOT / rel
        print(f"  {'DRY-RUN ' if dry_run else ''}restore {rel}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        n += 1
    print(
        f"[restore] {'DRY-RUN ' if dry_run else ''}"
        f"{n} files restored from {stamp}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Backup critical pipeline state.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true", help="list existing backups")
    g.add_argument(
        "--restore", metavar="STAMP", help="restore a backup by stamp"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="show actions without changing files",
    )
    args = p.parse_args()

    if args.list:
        list_backups()
    elif args.restore:
        restore(args.restore, dry_run=args.dry_run)
    else:
        take_backup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

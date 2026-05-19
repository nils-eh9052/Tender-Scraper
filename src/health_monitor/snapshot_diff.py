"""Snapshot diff for tender counts.

Compares two relevant.json snapshots (or any list of dicts with "tender_id")
and returns the count of new and removed tenders.

Snapshots live in data/filtered/.snapshots/<run_id>.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.health_monitor import PROJECT_ROOT

SNAPSHOTS_DIR: Path = PROJECT_ROOT / "data" / "filtered" / ".snapshots"


class SnapshotDiff:
    """Result of diffing two snapshots."""

    def __init__(self, new_count: int, removed_count: int):
        self.new_count = new_count
        self.removed_count = removed_count

    def __repr__(self) -> str:
        return f"SnapshotDiff(new={self.new_count}, removed={self.removed_count})"


def _load_ids(path: Path) -> set[str]:
    """Load a JSON file and return the set of tender_id values."""
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return {item["tender_id"] for item in data if isinstance(item, dict) and "tender_id" in item}
    if isinstance(data, dict):
        # Support dict-of-dicts format (tender_id as key)
        return set(data.keys())
    return set()


def diff_snapshots(old_path: Path, new_path: Path) -> SnapshotDiff:
    """Compute the diff between two snapshot files.

    Args:
        old_path: Path to the older snapshot JSON.
        new_path: Path to the newer snapshot JSON.

    Returns:
        SnapshotDiff with new_count and removed_count.
    """
    old_ids = _load_ids(old_path)
    new_ids = _load_ids(new_path)

    new_count = len(new_ids - old_ids)
    removed_count = len(old_ids - new_ids)

    return SnapshotDiff(new_count=new_count, removed_count=removed_count)


def diff_lists(old_data: list[dict], new_data: list[dict]) -> SnapshotDiff:
    """Compute a diff between two in-memory lists of tender dicts.

    Useful for testing without filesystem access.
    """
    old_ids = {item["tender_id"] for item in old_data if "tender_id" in item}
    new_ids = {item["tender_id"] for item in new_data if "tender_id" in item}

    new_count = len(new_ids - old_ids)
    removed_count = len(old_ids - new_ids)

    return SnapshotDiff(new_count=new_count, removed_count=removed_count)


def save_snapshot(run_id: str, data: list[dict], snapshots_dir: Path = SNAPSHOTS_DIR) -> Path:
    """Save a relevant.json snapshot for a given run_id.

    Args:
        run_id:       Run ID string (e.g. "20260519_140354").
        data:         List of tender dicts (the full relevant.json contents).
        snapshots_dir: Directory to write snapshots into.

    Returns:
        Path to the written snapshot file.
    """
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshots_dir / f"{run_id}.json"

    # Store only tender_id to keep snapshots small
    ids = [{"tender_id": item["tender_id"]} for item in data if "tender_id" in item]
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(ids, fh, ensure_ascii=False, separators=(",", ":"))

    return out_path


def get_latest_two_snapshots(
    snapshots_dir: Path = SNAPSHOTS_DIR,
) -> tuple[Optional[Path], Optional[Path]]:
    """Return the two most recent snapshot files (oldest, newest).

    Returns (None, None) if fewer than 2 snapshots exist.
    """
    if not snapshots_dir.exists():
        return None, None

    snapshots = sorted(snapshots_dir.glob("*.json"))
    if len(snapshots) < 2:
        return None, None

    return snapshots[-2], snapshots[-1]

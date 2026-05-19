"""Tests for src.health_monitor.snapshot_diff"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.health_monitor.snapshot_diff import diff_snapshots, diff_lists, SnapshotDiff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot_file(tmp_dir: Path, name: str, tender_ids: list[str]) -> Path:
    """Write a snapshot JSON file containing the given tender IDs."""
    data = [{"tender_id": tid} for tid in tender_ids]
    p = tmp_dir / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# diff_lists — in-memory
# ---------------------------------------------------------------------------

class TestDiffLists:
    def test_five_new_tenders(self):
        """Two fixture relevant.json files with 5 new tenders → diff returns 5."""
        old_data = [{"tender_id": f"TID-{i}"} for i in range(10)]
        new_data = [{"tender_id": f"TID-{i}"} for i in range(15)]  # 5 new ones (10..14)
        diff = diff_lists(old_data, new_data)
        assert diff.new_count == 5, f"Expected 5 new, got {diff.new_count}"
        assert diff.removed_count == 0

    def test_five_removed_tenders(self):
        old_data = [{"tender_id": f"TID-{i}"} for i in range(10)]
        new_data = [{"tender_id": f"TID-{i}"} for i in range(5)]  # 5 removed
        diff = diff_lists(old_data, new_data)
        assert diff.removed_count == 5
        assert diff.new_count == 0

    def test_no_change(self):
        data = [{"tender_id": f"TID-{i}"} for i in range(10)]
        diff = diff_lists(data, data)
        assert diff.new_count == 0
        assert diff.removed_count == 0

    def test_mixed_new_and_removed(self):
        old_data = [{"tender_id": f"TID-{i}"} for i in range(10)]
        new_data = [{"tender_id": f"TID-{i}"} for i in range(3, 16)]  # 3 removed (0,1,2), 6 new (10..15)
        diff = diff_lists(old_data, new_data)
        assert diff.new_count == 6
        assert diff.removed_count == 3

    def test_empty_old(self):
        old_data = []
        new_data = [{"tender_id": f"TID-{i}"} for i in range(5)]
        diff = diff_lists(old_data, new_data)
        assert diff.new_count == 5
        assert diff.removed_count == 0

    def test_empty_new(self):
        old_data = [{"tender_id": f"TID-{i}"} for i in range(5)]
        new_data = []
        diff = diff_lists(old_data, new_data)
        assert diff.new_count == 0
        assert diff.removed_count == 5

    def test_both_empty(self):
        diff = diff_lists([], [])
        assert diff.new_count == 0
        assert diff.removed_count == 0


# ---------------------------------------------------------------------------
# diff_snapshots — file-based
# ---------------------------------------------------------------------------

class TestDiffSnapshots:
    def test_five_new_from_files(self):
        """Spec requirement: two snapshot files with 5 new tenders → returns 5."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            old_ids = [f"TID-{i}" for i in range(10)]
            new_ids = old_ids + [f"NEW-{i}" for i in range(5)]
            old_path = _make_snapshot_file(tmp_dir, "old.json", old_ids)
            new_path = _make_snapshot_file(tmp_dir, "new.json", new_ids)
            diff = diff_snapshots(old_path, new_path)
            assert diff.new_count == 5, f"Expected 5 new tenders, got {diff.new_count}"
            assert diff.removed_count == 0

    def test_removed_from_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            old_ids = [f"TID-{i}" for i in range(10)]
            new_ids = [f"TID-{i}" for i in range(7)]
            old_path = _make_snapshot_file(tmp_dir, "old.json", old_ids)
            new_path = _make_snapshot_file(tmp_dir, "new.json", new_ids)
            diff = diff_snapshots(old_path, new_path)
            assert diff.removed_count == 3
            assert diff.new_count == 0

    def test_nonexistent_old_path(self):
        """Missing old path → old_ids is empty set, everything in new is 'new'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            new_ids = [f"TID-{i}" for i in range(5)]
            new_path = _make_snapshot_file(tmp_dir, "new.json", new_ids)
            old_path = tmp_dir / "nonexistent.json"
            diff = diff_snapshots(old_path, new_path)
            assert diff.new_count == 5
            assert diff.removed_count == 0

    def test_no_change_same_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            ids = [f"TID-{i}" for i in range(10)]
            path = _make_snapshot_file(tmp_dir, "snap.json", ids)
            diff = diff_snapshots(path, path)
            assert diff.new_count == 0
            assert diff.removed_count == 0


# ---------------------------------------------------------------------------
# SnapshotDiff repr
# ---------------------------------------------------------------------------

class TestSnapshotDiffRepr:
    def test_repr(self):
        d = SnapshotDiff(new_count=5, removed_count=2)
        assert "5" in repr(d)
        assert "2" in repr(d)

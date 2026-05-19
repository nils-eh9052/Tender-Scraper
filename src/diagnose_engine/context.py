"""Context collection for M2 Diagnose Engine.

Builds a DiagnoseContext from an anomaly record by reading:
  - Log snippets from data/.run_log/<run_id>.log
  - Diff summary from data/filtered/relevant.json
  - Adapter source code (first 200 lines)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.diagnose_engine import PROJECT_ROOT

# ---------------------------------------------------------------------------
# Adapter → source file mapping
# ---------------------------------------------------------------------------

ADAPTER_FILE_MAP: dict[str, str] = {
    "ca":       "src/canada_loader.py",
    "au":       "src/national_scraper/adapters/au_ocds_adapter.py",
    "au-atm":   "src/national_scraper/adapters/au_atm_adapter.py",
    "gb":       "src/national_scraper/adapters/uk_fts_adapter.py",
    "nspa":     "src/national_scraper/adapters/nspa_adapter.py",
    "de-ev":    "src/national_scraper/adapters/de_evergabe_adapter.py",
    "ted":      "src/api_client.py",
}


def _adapter_file_path(adapter: str) -> Path:
    """Return Path to the adapter source file for the given adapter key."""
    if adapter in ADAPTER_FILE_MAP:
        rel = ADAPTER_FILE_MAP[adapter]
    else:
        rel = f"src/national_scraper/adapters/{adapter}_adapter.py"
    return PROJECT_ROOT / rel


# ---------------------------------------------------------------------------
# Log snippet extraction
# ---------------------------------------------------------------------------

def _extract_log_snippet(log_path: Path, adapter: str, max_chars: int = 4000) -> str:
    """Extract ±50 lines around the adapter block from a log file.

    Returns an empty string if the log file does not exist.
    """
    if not log_path.exists():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""

    # Find lines that mention the adapter
    adapter_lines = [
        i for i, line in enumerate(lines)
        if adapter.lower() in line.lower()
    ]
    if not adapter_lines:
        # Fall back to last 100 lines of log
        snippet_lines = lines[-100:]
    else:
        # Window: ±50 lines around first and last mention
        start = max(0, adapter_lines[0] - 50)
        end   = min(len(lines), adapter_lines[-1] + 50)
        snippet_lines = lines[start:end]

    snippet = "\n".join(snippet_lines)
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "\n...[truncated]"
    return snippet


# ---------------------------------------------------------------------------
# Diff summary
# ---------------------------------------------------------------------------

def _build_diff_summary(relevant_path: Path, adapter: str) -> str:
    """Build a brief summary of new/removed tender IDs from relevant.json.

    Compares snapshot files if available; otherwise just reports tender count.
    """
    if not relevant_path.exists():
        return "relevant.json not found"
    try:
        with relevant_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return f"relevant.json read error: {exc}"

    if not isinstance(data, list):
        return "relevant.json format unexpected"

    # Filter to this adapter's tenders
    adapter_prefix = adapter.upper().replace("-", "_")
    adapter_tenders = [
        t for t in data
        if (t.get("_source") or "").upper() == adapter.upper()
        or (t.get("tender_id") or "").startswith(adapter.upper())
        or (t.get("tender_id") or "").upper().startswith(adapter_prefix)
    ]

    total = len(data)
    adapter_count = len(adapter_tenders)

    if adapter_count:
        ids = [t.get("tender_id", "?") for t in adapter_tenders[:5]]
        id_preview = ", ".join(ids)
        if adapter_count > 5:
            id_preview += f" ... (+{adapter_count - 5} more)"
        return (
            f"relevant.json: {total} total notices; "
            f"{adapter_count} from adapter '{adapter}': {id_preview}"
        )
    return (
        f"relevant.json: {total} total notices; "
        f"0 found for adapter '{adapter}'"
    )


# ---------------------------------------------------------------------------
# Adapter code snippet
# ---------------------------------------------------------------------------

def _load_adapter_code(adapter: str, max_lines: int = 200) -> str:
    """Load the first max_lines of the adapter source file."""
    path = _adapter_file_path(adapter)
    if not path.exists():
        return f"# Adapter file not found: {path.relative_to(PROJECT_ROOT)}"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[:max_lines])
    except Exception as exc:
        return f"# Could not read adapter file: {exc}"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

@dataclass
class DiagnoseContext:
    anomaly: dict           # full AnomalyRecord from M1
    log_snippet: str        # ±50 lines around adapter block, max 4000 chars
    diff_summary: str       # added/removed tender ID summary
    adapter_code: str       # first 200 lines of adapter file
    adapter: str            # adapter key
    run_id: str


def build_context(anomaly: dict) -> DiagnoseContext:
    """Build a DiagnoseContext from an M1 AnomalyRecord dict.

    Reads log file and relevant.json from standard paths under PROJECT_ROOT.
    """
    adapter = anomaly.get("adapter", "unknown")
    run_id  = anomaly.get("run_id") or "unknown"

    # Log file
    run_log_dir = PROJECT_ROOT / "data" / ".run_log"
    log_path = run_log_dir / f"{run_id}.log"
    if not log_path.exists():
        # Try latest.log symlink
        latest = run_log_dir / "latest.log"
        if latest.exists():
            log_path = latest

    log_snippet = _extract_log_snippet(log_path, adapter)

    # Diff summary from relevant.json
    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    diff_summary = _build_diff_summary(relevant_path, adapter)

    # Adapter source code
    adapter_code = _load_adapter_code(adapter)

    return DiagnoseContext(
        anomaly=anomaly,
        log_snippet=log_snippet,
        diff_summary=diff_summary,
        adapter_code=adapter_code,
        adapter=adapter,
        run_id=run_id,
    )

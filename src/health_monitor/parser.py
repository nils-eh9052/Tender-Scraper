"""Log parser for the health monitor.

Parses stdout/log transcripts produced by main.py into per-adapter metric
dictionaries. All heuristics are regex-based; no LLM calls.

Log format assumptions:
  - First two lines: "# Run started <ISO>" and "# argv: ..."
  - Adapter sections are identified by "── <Country> (<PREFIX>)" banners, or
    by [INFO] lines containing adapter module names.
  - HTTP codes appear as "HTTP 429", "status_code=404", etc.
  - Tracebacks begin with "Traceback (most recent call last):" and end at the
    next blank line.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Source-prefix → adapter key mapping (from spec)
# ---------------------------------------------------------------------------
PREFIX_TO_ADAPTER: dict[str, str] = {
    "CA-CB":  "ca",
    "CA-cb":  "ca",
    "AU-TEN": "au",
    "AU-AT":  "au-atm",
    "CZ-NEN": "cz",
    "CZ-N006": "cz",
    "FR-BP":  "fr",
    "UK-CF":  "gb",
    "NO-DF":  "no",
    "EE-RP":  "ee",
    "NL-TN":  "nl",
    "UA-PR":  "ua",
    "NSPA-EP":"nspa",
}

# Adapter key → display name used in log section banners
ADAPTER_BANNER_PATTERNS: dict[str, list[str]] = {
    "de":      ["Germany", "DE ──", "── DE"],
    "de-ev":   ["Evergabe", "DE-EV", "de-evergabe"],
    "pl":      ["Poland", "── PL ──", "── PL)"],
    "fi":      ["Finland", "── FI ──"],
    "se":      ["Sweden", "── SE ──"],
    "no":      ["Norway", "── NO ──", "NO-DF", "Doffin"],
    "cz":      ["Czech", "── CZ ──", "CZ-NEN", "NIPEZ"],
    "fr":      ["France", "── FR ──", "FR-BP", "BOAMP"],
    "dk":      ["Denmark", "── DK ──"],
    "ro":      ["Romania", "── RO ──"],
    "nl":      ["Netherlands", "── NL ──", "NL-TN", "TenderNed"],
    "be":      ["Belgium", "── BE ──"],
    "es":      ["Spain", "── ES ──"],
    "it":      ["Italy", "── IT ──"],
    "ua":      ["Ukraine", "── UA ──", "UA-PR", "Prozorro"],
    "ch":      ["Switzerland", "── CH ──"],
    "gb":      ["United Kingdom", "── UK ──", "── GB ──", "UK-CF", "UK-FTS"],
    "gr":      ["Greece", "── GR ──"],
    "ee":      ["Estonia", "── EE ──", "EE-RP"],
    "lv":      ["Latvia", "── LV ──"],
    "lt":      ["Lithuania", "── LT ──"],
    "au":      ["Australia", "── AU ──", "AU-TEN", "AusTender"],
    "au-atm":  ["AU-ATM", "AusTender ATM", "au-atm"],
    "ca":      ["Canada", "── CA ──", "CA-CB", "CanadaBuys"],
    "nspa":    ["NSPA", "── NSPA ──", "NSPA-EP"],
    "ted":     ["TED", "── TED ──", "ted.europa.eu", "PHASE 1", "PHASE 2"],
}

# Module-name fragments that identify adapter log lines
ADAPTER_MODULE_PATTERNS: dict[str, list[str]] = {
    "de":      ["de_adapter"],
    "de-ev":   ["de_evergabe_adapter"],
    "pl":      ["pl_adapter"],
    "fi":      ["fi_adapter"],
    "se":      ["se_adapter"],
    "no":      ["no_adapter"],
    "cz":      ["cz_adapter"],
    "fr":      ["fr_adapter"],
    "dk":      ["dk_adapter"],
    "ro":      ["ro_adapter"],
    "nl":      ["nl_adapter"],
    "be":      ["be_adapter"],
    "es":      ["es_adapter"],
    "it":      ["it_adapter"],
    "ua":      ["ua_adapter"],
    "ch":      ["ch_adapter"],
    "gb":      ["uk_fts_adapter", "uk_scraper"],
    "gr":      ["gr_adapter"],
    "ee":      ["ee_adapter"],
    "lv":      ["lv_adapter"],
    "lt":      ["lt_adapter"],
    "au":      ["au_ocds_adapter"],
    "au-atm":  ["au_atm_adapter"],
    "ca":      ["canada_loader"],
    "nspa":    ["nspa_adapter"],
    "ted":     ["api_client", "index_builder", "detail_fetcher", "ted_bulk"],
}

# Regex patterns
_RE_RUN_STARTED = re.compile(r"^# Run started (.+)$")
_RE_ARGV        = re.compile(r"^# argv: (.+)$")
_RE_HTTP_CODE   = re.compile(r"(?:HTTP|status_code)[= ](\d{3})")
_RE_TRACEBACK   = re.compile(r"^Traceback \(most recent call last\):")
_RE_DURATION    = re.compile(
    r"(?:duration|elapsed|took)[:\s=]+([0-9]+(?:\.[0-9]+)?)\s*s",
    re.IGNORECASE,
)

# Pattern for adapter section banner lines like "── France (FR-BP) ──"
_RE_SECTION_BANNER = re.compile(r"──\s+(.+?)\s+(?:\(([^)]+)\)\s+)?──")

# Tender count lines: e.g. "National notices found: 40", "Total: 13 tenders"
_RE_TENDER_FOUND = re.compile(
    r"(?:National notices found|national notices|tenders? found|"
    r"total tenders?|results?)[:\s]+(\d+)",
    re.IGNORECASE,
)
# Merge summary: "X added, Y enriched, Z id-dupes skipped, N total"
_RE_ADDED       = re.compile(r"(\d+)\s+added", re.IGNORECASE)
_RE_NEW         = re.compile(r"(\d+)\s+new", re.IGNORECASE)
_RE_REMOVED     = re.compile(r"(\d+)\s+removed", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_log(log_path: Path) -> list[dict]:
    """Parse a run log file and return a list of per-adapter metric dicts.

    Each dict matches the metric schema defined in the spec. Fields that
    cannot be extracted are set to None.

    Args:
        log_path: Path to the log file.

    Returns:
        List of metric dicts — one per adapter encountered in the log.
        If the log has no adapter sections, returns a single "ted" entry
        covering the whole log.
    """
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return _parse_lines(lines, str(log_path))


def parse_log_text(text: str, log_path: str = "") -> list[dict]:
    """Parse log text (for testing with fixture strings)."""
    return _parse_lines(text.splitlines(), log_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_lines(lines: list[str], log_path: str) -> list[dict]:
    run_id, run_started_at, argv = _extract_header(lines)

    # Segment log into per-adapter blocks
    segments = _segment_by_adapter(lines)

    metrics = []
    for adapter, seg_lines in segments.items():
        m = _extract_adapter_metrics(
            adapter=adapter,
            lines=seg_lines,
            run_id=run_id,
            run_started_at=run_started_at,
            argv=argv,
            log_path=log_path,
        )
        metrics.append(m)

    # If nothing was detected, produce a single "ted" entry covering all lines
    if not metrics:
        m = _extract_adapter_metrics(
            adapter="ted",
            lines=lines,
            run_id=run_id,
            run_started_at=run_started_at,
            argv=argv,
            log_path=log_path,
        )
        metrics.append(m)

    return metrics


def _extract_header(lines: list[str]) -> tuple[Optional[str], Optional[str], Optional[list[str]]]:
    """Extract run_id, run_started_at, and argv from the first few header lines."""
    run_started_at: Optional[str] = None
    argv: Optional[list[str]] = None

    for line in lines[:10]:
        m = _RE_RUN_STARTED.match(line.strip())
        if m:
            raw_ts = m.group(1).strip()
            try:
                dt = datetime.fromisoformat(raw_ts)
                run_started_at = dt.isoformat()
            except ValueError:
                run_started_at = raw_ts
            continue

        m = _RE_ARGV.match(line.strip())
        if m:
            argv = m.group(1).strip().split()
            continue

    # Derive run_id from timestamp
    run_id: Optional[str] = None
    if run_started_at:
        try:
            dt = datetime.fromisoformat(run_started_at)
            run_id = dt.strftime("%Y%m%d_%H%M%S")
        except ValueError:
            pass

    return run_id, run_started_at, argv


def _detect_adapter_for_line(line: str) -> Optional[str]:
    """Return the adapter key if a line belongs to a specific adapter section."""
    # Check module-name patterns first (most reliable)
    for adapter, patterns in ADAPTER_MODULE_PATTERNS.items():
        for pat in patterns:
            if pat in line:
                return adapter

    # Check banner patterns
    for adapter, patterns in ADAPTER_BANNER_PATTERNS.items():
        for pat in patterns:
            if pat in line:
                return adapter

    # Check source prefixes in line
    for prefix, adapter in PREFIX_TO_ADAPTER.items():
        if prefix in line:
            return adapter

    return None


def _segment_by_adapter(lines: list[str]) -> dict[str, list[str]]:
    """Split log lines into per-adapter segments.

    Strategy:
    1. Look for section banner lines ("── France (FR-BP) ──") to detect
       explicit adapter sections.
    2. Fall back to per-line module-name matching.

    Returns a dict: adapter_key → list of lines.
    """
    # First pass: find explicit section banners
    section_starts: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        # Banner pattern: "── France (FR-BP) ──" or "  ── France (FR-BP) ──"
        m = _RE_SECTION_BANNER.search(line)
        if m:
            # Try to identify adapter from the banner text + optional prefix
            banner_text = m.group(1) + " " + (m.group(2) or "")
            detected = None
            for adapter, patterns in ADAPTER_BANNER_PATTERNS.items():
                for pat in patterns:
                    if pat.lower() in banner_text.lower():
                        detected = adapter
                        break
                if detected:
                    break
            if not detected:
                # Try module patterns on the banner text
                for adapter, patterns in ADAPTER_MODULE_PATTERNS.items():
                    for pat in patterns:
                        if pat.lower() in banner_text.lower():
                            detected = adapter
                            break
                    if detected:
                        break
            if detected:
                section_starts.append((i, detected))

    if section_starts:
        # Use banners to segment
        segments: dict[str, list[str]] = {}

        # Lines before the first banner: attribute to a "pre-banner" section.
        # We try to identify an adapter from them; default to "ted".
        first_banner_idx = section_starts[0][0]
        if first_banner_idx > 0:
            pre_lines = lines[:first_banner_idx]
            pre_adapter = "ted"
            for pl in pre_lines:
                detected = _detect_adapter_for_line(pl)
                if detected and detected != "ted":
                    pre_adapter = detected
                    break
            segments[pre_adapter] = list(pre_lines)

        for idx, (start_line, adapter) in enumerate(section_starts):
            end_line = section_starts[idx + 1][0] if idx + 1 < len(section_starts) else len(lines)
            if adapter not in segments:
                segments[adapter] = []
            segments[adapter].extend(lines[start_line:end_line])
        return segments

    # Fallback: assign each line to an adapter based on module-name detection
    # Group consecutive lines with the same adapter
    segments_ordered: list[tuple[str, list[str]]] = []
    current_adapter: Optional[str] = None
    current_lines: list[str] = []

    for line in lines:
        detected = _detect_adapter_for_line(line)
        if detected and detected != current_adapter:
            if current_adapter and current_lines:
                segments_ordered.append((current_adapter, current_lines))
            current_adapter = detected
            current_lines = [line]
        elif current_adapter:
            current_lines.append(line)
        else:
            # Pre-adapter header lines go to "ted" by default
            if not current_adapter:
                current_adapter = "ted"
                current_lines = [line]

    if current_adapter and current_lines:
        segments_ordered.append((current_adapter, current_lines))

    # Merge segments with the same adapter key
    merged: dict[str, list[str]] = {}
    for adapter, seg_lines in segments_ordered:
        if adapter not in merged:
            merged[adapter] = []
        merged[adapter].extend(seg_lines)

    return merged


def _extract_adapter_metrics(
    adapter: str,
    lines: list[str],
    run_id: Optional[str],
    run_started_at: Optional[str],
    argv: Optional[list[str]],
    log_path: str,
) -> dict:
    """Extract all metrics for a single adapter from its log lines."""
    http_4xx = 0
    http_5xx = 0
    http_429 = 0
    tracebacks: list[str] = []
    tender_count: Optional[int] = None
    new_tender_count: Optional[int] = None
    removed_tender_count: Optional[int] = None
    run_duration_seconds: Optional[float] = None
    newest_pub_date: Optional[str] = None
    oldest_pub_date: Optional[str] = None

    in_traceback = False
    tb_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # HTTP codes
        for m in _RE_HTTP_CODE.finditer(line):
            code = int(m.group(1))
            if code == 429:
                http_429 += 1
            elif 400 <= code < 500:
                http_4xx += 1
            elif 500 <= code < 600:
                http_5xx += 1

        # Traceback detection
        if _RE_TRACEBACK.match(stripped):
            in_traceback = True
            tb_lines = [line]
            continue

        if in_traceback:
            if stripped == "" and tb_lines:
                # End of traceback
                tracebacks.append("\n".join(tb_lines))
                tb_lines = []
                in_traceback = False
            else:
                tb_lines.append(line)

        # Duration
        if run_duration_seconds is None:
            m = _RE_DURATION.search(line)
            if m:
                try:
                    run_duration_seconds = float(m.group(1))
                except ValueError:
                    pass

        # Tender counts
        m = _RE_TENDER_FOUND.search(line)
        if m:
            try:
                tender_count = int(m.group(1))
            except ValueError:
                pass

        # New/added tender counts
        m = _RE_ADDED.search(line)
        if m and new_tender_count is None:
            try:
                new_tender_count = int(m.group(1))
            except ValueError:
                pass

        m = _RE_NEW.search(line)
        if m and new_tender_count is None:
            try:
                new_tender_count = int(m.group(1))
            except ValueError:
                pass

        # Removed tender counts
        m = _RE_REMOVED.search(line)
        if m and removed_tender_count is None:
            try:
                removed_tender_count = int(m.group(1))
            except ValueError:
                pass

    # Flush any open traceback at end of segment
    if in_traceback and tb_lines:
        tracebacks.append("\n".join(tb_lines))

    exception_count = len(tracebacks)
    exception_summary: Optional[str] = None
    if tracebacks:
        combined = "\n\n".join(tracebacks)
        exception_summary = combined[:1000]

    # success = false if there are unhandled exceptions
    success = exception_count == 0

    return {
        "run_id": run_id,
        "run_started_at": run_started_at,
        "argv": argv,
        "log_file": log_path,
        "adapter": adapter,
        "adapter_status": None,  # filled in by metrics.py from adapter_status.json
        "tender_count": tender_count,
        "new_tender_count": new_tender_count,
        "removed_tender_count": removed_tender_count,
        "newest_pub_date": newest_pub_date,
        "oldest_pub_date": oldest_pub_date,
        "run_duration_seconds": run_duration_seconds,
        "http_4xx_count": http_4xx,
        "http_5xx_count": http_5xx,
        "http_429_count": http_429,
        "exception_count": exception_count,
        "exception_summary": exception_summary,
        "success": success,
    }

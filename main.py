#!/usr/bin/env python3
"""
TED Defence Trailer Scraper - Main Pipeline Runner

Usage:
    python main.py --all                  # Run full pipeline
    python main.py --phase index          # Phase 1 only: Build index
    python main.py --phase details        # Phase 2 only: Fetch details
    python main.py --phase filter         # Phase 3 only: Filter & score
    python main.py --phase export         # Phase 4 only: Excel export
    python main.py --phase classify       # Optional: AI classification
    python main.py --test                 # Test run (10 notices)
    python main.py --two-stage            # Use Haiku pre-filter + Sonnet
    python main.py --parallel             # Use parallel classifier
    python main.py --batch                # Use batch API (50% cheaper)
    python main.py --since 2026-01-01     # Only fetch notices since date
    python main.py --incremental          # Auto-detect last run date
    python main.py --enrich               # Add fulltext enrichment step
    python main.py --enrich-only          # Only enrich existing data + export
    python main.py --award-match          # Run award notice matching
"""

import argparse
import json
import logging
import os
import shutil
import sys
import time
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, date
from threading import Lock
from typing import Optional

# Load .env file (API keys etc.)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key, _val = _key.strip(), _val.strip()
                if _val and not os.environ.get(_key):  # Set if missing or empty
                    os.environ[_key] = _val

# Fix Windows terminal encoding so print() works with all characters
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.api_client import TedApiClient
from src.index_builder import IndexBuilder
from src.detail_fetcher import DetailFetcher
from src.filter_engine import FilterEngine
from src.exporter import ExcelExporter
from src.classifier import AiClassifier, TwoStageClassifier, ParallelClassifier, BatchClassifier
from src.uk_scraper import UKContractsFinderScraper
from src.exporter_frontend import export_tenders_for_frontend

LAST_RUN_PATH = PROJECT_ROOT / "data" / ".last_run.json"

# ── Timing utility ───────────────────────────────────────────────────────────

_phase_timings: list[tuple[str, float]] = []


class Timer:
    """Context manager that prints elapsed time and records it for the summary."""
    def __init__(self, name: str):
        self.name = name
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.time()
        print(f"\n  [timer] {self.name}...")
        return self

    def __exit__(self, *_):
        elapsed = time.time() - self._start
        _phase_timings.append((self.name, elapsed))
        print(f"  [timer] {self.name}: {elapsed:.1f}s")


def _print_timing_summary():
    if not _phase_timings:
        return
    print("\n" + "="*60)
    print("  TIMING SUMMARY")
    print("="*60)
    total = sum(t for _, t in _phase_timings)
    for name, t in _phase_timings:
        bar = "#" * int(t / total * 30) if total else ""
        print(f"  {name:<32} {t:6.1f}s  {bar}")
    print(f"  {'TOTAL':<32} {total:6.1f}s")


# ── Adapter registry ─────────────────────────────────────────────────────────

def get_adapter_registry() -> dict:
    """Return all available national portal adapters."""
    import importlib
    registry = {}
    for mod, cls_name, cfg_name, key in [
        ("src.national_scraper.adapters.de_adapter", "DEAdapter", "create_de_config", "de"),
        ("src.national_scraper.adapters.pl_adapter", "PLAdapter", "create_pl_config", "pl"),
        ("src.national_scraper.adapters.fi_adapter", "FIAdapter", "create_fi_config", "fi"),
        ("src.national_scraper.adapters.se_adapter", "SEAdapter", "create_se_config", "se"),
        ("src.national_scraper.adapters.no_adapter", "NOAdapter", "create_no_config", "no"),
        ("src.national_scraper.adapters.cz_adapter", "CZAdapter", "create_cz_config", "cz"),
        ("src.national_scraper.adapters.fr_adapter", "FRAdapter", "create_fr_config", "fr"),
        ("src.national_scraper.adapters.dk_adapter", "DKAdapter", "create_dk_config", "dk"),
        ("src.national_scraper.adapters.ro_adapter", "ROAdapter", "create_ro_config", "ro"),
        ("src.national_scraper.adapters.nl_adapter", "NLAdapter", "create_nl_config", "nl"),
        ("src.national_scraper.adapters.be_adapter", "BEAdapter", "create_be_config", "be"),
        ("src.national_scraper.adapters.es_adapter", "ESAdapter", "create_es_config", "es"),
        ("src.national_scraper.adapters.it_adapter", "ITAdapter", "create_it_config", "it"),
        ("src.national_scraper.adapters.ua_adapter", "UAAdapter", "create_ua_config", "ua"),
        ("src.national_scraper.adapters.ch_adapter", "CHAdapter", "create_ch_config", "ch"),
        ("src.national_scraper.adapters.uk_fts_adapter", "UKFTSAdapter", "create_uk_fts_config", "gb"),
        ("src.national_scraper.adapters.de_evergabe_adapter", "DEEvergabeAdapter", "create_de_evergabe_config", "de-ev"),
        ("src.national_scraper.adapters.gr_adapter", "GRAdapter", "create_gr_config", "gr"),
        ("src.national_scraper.adapters.ee_adapter", "EEAdapter", "create_ee_config", "ee"),
        ("src.national_scraper.adapters.lv_adapter", "LVAdapter", "create_lv_config", "lv"),
        ("src.national_scraper.adapters.lt_adapter", "LTAdapter", "create_lt_config", "lt"),
        ("src.national_scraper.adapters.au_ocds_adapter", "AuOcdsAdapter", "create_au_ocds_config", "au"),
        ("src.national_scraper.adapters.au_atm_adapter", "AuAtmAdapter", "create_au_atm_config", "au-atm"),
        ("src.national_scraper.adapters.canada_loader", "CanadaBuysAdapter", "create_canada_config", "ca"),
        # NSPA (NATO Support and Procurement Agency) — Sprint 14k, 2026-05-14.
        # Special: not a country adapter — keyed as "nspa". Public portal,
        # no login. Current trailer-yield ~0 (mostly munitions spare parts),
        # but kept as infrastructure for occasional Boxer/trailer fielding.
        ("src.national_scraper.adapters.nspa_adapter", "NSPAAdapter", "create_nspa_config", "nspa"),
        # TR adapter parked (Sprint 14d) — defence procurement
        #  not portal-accessible. Re-enable explicitly via --national tr.
        # ("src.national_scraper.adapters.tr_adapter", "TrAdapter", "create_tr_config", "tr"),
    ]:
        try:
            m = importlib.import_module(mod)
            registry[key] = (getattr(m, cls_name), getattr(m, cfg_name))
        except (ImportError, AttributeError):
            pass
    return registry


def setup_logging(verbose: bool = False):
    """Configure logging for the pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                PROJECT_ROOT / "data" / f"pipeline_{datetime.now():%Y%m%d_%H%M}.log",
                encoding="utf-8"
            )
        ]
    )


def load_config() -> dict:
    """Load configuration from YAML."""
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_last_run() -> dict:
    """Load .last_run.json if it exists."""
    if LAST_RUN_PATH.exists():
        with open(LAST_RUN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_last_run(notices_processed: int):
    """Save .last_run.json with today's date and notice count."""
    data = {
        "last_run_date": date.today().isoformat(),
        "notices_processed": notices_processed
    }
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_RUN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run_phase_index(config: dict, test_mode: bool = False, date_from: str = None):
    """Phase 1+2: Build index AND fetch all details in one pass."""
    print("\n" + "="*60)
    print("  PHASE 1+2: Building Index & Fetching Details (merged)")
    print("="*60)

    if date_from:
        config = dict(config)
        config["search"] = dict(config.get("search", {}))
        config["search"]["date_from"] = date_from
        print(f"  Overriding date_from: {date_from}")

    builder = IndexBuilder(config, output_dir=str(PROJECT_ROOT / "data" / "raw"))
    max_pages = 1 if test_mode else None
    index = builder.build_index(max_pages_per_query=max_pages)

    # Force-include after normal index build
    print("\n  Running force-include fetch...")
    force_count = builder.fetch_force_include()
    print(f"  Force-include: {force_count} new notices fetched")

    total = index["metadata"]["total_notices"]
    saved = index["metadata"].get("total_details_saved", total)
    print(f"\n  [OK] Index built: {total} unique notices")
    print(f"  [OK] Details saved: {saved} (inline with search)")
    return index


def run_phase_details(config: dict, test_mode: bool = False):
    """Phase 2: Legacy - now handled by Phase 1. Only re-fetches missing."""
    print("\n" + "="*60)
    print("  PHASE 2: Detail Check (already fetched in Phase 1)")
    print("="*60)

    details_dir = PROJECT_ROOT / "data" / "raw" / "details"
    count = len(list(details_dir.glob("*.json"))) if details_dir.exists() else 0
    print(f"\n  [OK] {count} details already on disk (fetched in Phase 1)")
    return count


class _Tee:
    """Write to multiple streams simultaneously (real stdout/stderr + log file).

    Used by ``_setup_run_log()`` so every ``print()`` and exception traceback
    lands both on the terminal and in ``data/.run_log/<stamp>.log``.
    """

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False


def _setup_run_log(log_dir: Path, max_logs: int = 30) -> Optional[Path]:
    """Mirror stdout/stderr into ``data/.run_log/YYYYMMDD_HHMMSS.log``.

    Foundation for the Self-Healing Health-Monitor (M1) and Diagnose-Engine
    (M2): every pipeline run leaves a persistent trace on disk. The most
    recent run is also accessible via the ``latest.log`` symlink.

    Keeps the most recent ``max_logs`` timestamped files; older rotates out.
    Returns the log path, or ``None`` if the log file couldn't be created
    (in which case the pipeline continues with normal stdout only).
    """
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"{stamp}.log"
        # Line-buffered: every print() flushes immediately — important for
        # diagnosing crashes where the very last line tells you where it died.
        fh = open(log_path, "a", encoding="utf-8", buffering=1)
        fh.write(f"# Run started {datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"# argv: {' '.join(sys.argv)}\n")
        fh.flush()
        sys.stdout = _Tee(sys.__stdout__, fh)
        sys.stderr = _Tee(sys.__stderr__, fh)
        # Rotate: only touch timestamped files (skip latest.log symlink, etc.)
        logs = sorted(log_dir.glob("2*.log"))
        for old in logs[:-max_logs]:
            try:
                old.unlink()
            except OSError:
                pass
        # ``latest.log`` convenience pointer (symlink; fallback to copy on
        # filesystems that don't support symlinks, e.g. Windows w/o admin).
        latest = log_dir / "latest.log"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(log_path.name)
        except (OSError, NotImplementedError):
            try:
                shutil.copy2(log_path, latest)
            except OSError:
                pass
        return log_path
    except OSError:
        return None


def _snapshot_pre_filter(filtered_dir: Path, max_snapshots: int = 10) -> Optional[Path]:
    """Snapshot relevant.json BEFORE Phase 3 overwrites it.

    Writes to ``data/filtered/.snapshots/YYYYMMDD_HHMMSS.json`` and rotates
    the directory so only the most recent ``max_snapshots`` files are kept.

    Returns the snapshot path, or ``None`` if relevant.json doesn't exist yet
    (first run of the project — nothing to back up).
    """
    src = filtered_dir / "relevant.json"
    if not src.exists():
        return None
    snap_dir = filtered_dir / ".snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = snap_dir / f"{stamp}.json"
    shutil.copy2(src, dst)
    # Rotate: keep only the newest max_snapshots files
    snaps = sorted(snap_dir.glob("*.json"))
    for old in snaps[:-max_snapshots]:
        try:
            old.unlink()
        except OSError:
            pass
    return dst


def run_phase_filter(config: dict):
    """Phase 3: Filter and score notices."""
    print("\n" + "="*60)
    print("  PHASE 3: Filtering & Scoring")
    print("="*60)

    # PreCon: snapshot existing relevant.json before Phase 3 overwrites it.
    # Recovery: cp data/filtered/.snapshots/<stamp>.json data/filtered/relevant.json
    filtered_dir = PROJECT_ROOT / "data" / "filtered"
    snap = _snapshot_pre_filter(filtered_dir)
    if snap:
        try:
            rel = snap.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = snap
        print(f"  [snapshot] {rel} (rotating, keep last 10)")

    engine = FilterEngine(config)
    stats = engine.filter_and_score_all(
        details_dir=str(PROJECT_ROOT / "data" / "raw" / "details"),
        output_dir=str(PROJECT_ROOT / "data" / "filtered")
    )

    print(f"\n  [OK] Processed: {stats['total_processed']}")
    print(f"  [OK] Defence:    {stats.get('total_defence', '?')}")
    print(f"  [--] Skipped:    {stats.get('total_non_defence_skipped', 0)} (non-defence)")
    print(f"  [OK] Relevant:   {stats['total_relevant']} (after dedup)")
    print(f"  [OK] High conf:  {stats['total_high_confidence']}")

    if stats.get("by_category"):
        print("\n  By Category:")
        for cat, count in sorted(stats["by_category"].items(),
                                  key=lambda x: -x[1]):
            print(f"    {cat.replace('_', ' ').title():.<30} {count}")

    return stats


def _build_classifier(args):
    """Build the appropriate classifier based on CLI flags.

    Parallel execution is ON by default (--sequential to disable).
    """
    sequential = getattr(args, "sequential", False)

    if args.batch:
        print("  Using BatchClassifier (50% discount via Batches API)")
        return BatchClassifier()

    if args.two_stage:
        base = TwoStageClassifier()
        tag = "TwoStageClassifier (Haiku pre-filter + Sonnet)"
    else:
        base = AiClassifier()
        tag = "AiClassifier (Sonnet)"

    if sequential:
        print(f"  Using {tag} [sequential]")
        return base

    # Default: wrap with 5-worker parallel executor
    print(f"  Using {tag} + ParallelClassifier (5 workers)")
    return ParallelClassifier(base)


def run_phase_classify(config: dict, test_mode: bool = False, args=None):
    """Optional: AI 2-step classification (strict filter + precise classification)."""
    print("\n" + "="*60)
    print("  PHASE 3b: AI Classification (Optional)")
    print("="*60)

    if args is not None:
        classifier = _build_classifier(args)
    else:
        classifier = AiClassifier()

    if not classifier.is_available:
        print("  [!] Skipped: LLM_OPENROUTER_API_KEY not set")
        print("  Set: $env:LLM_OPENROUTER_API_KEY = \"sk-or-v1-...\"")
        return

    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not filtered_path.exists():
        print("  [!] No filtered data found. Run phase 'filter' first.")
        return

    with open(filtered_path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    relevant = classifier.classify_batch(notices, test_mode=test_mode)

    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(relevant, f, ensure_ascii=False, indent=2)

    print(f"\n  [OK] AI result: {len(relevant)} relevant notices (from {len(notices)} input)")
    return relevant


def run_phase_enrich(config: dict, test_mode: bool = False):
    """Phase 3c: Fulltext enrichment (requires --enrich flag)."""
    print("\n" + "="*60)
    print("  PHASE 3c: Fulltext Enrichment")
    print("="*60)

    try:
        from src.enricher import FulltextEnricher
    except ImportError as e:
        print(f"  [!] enricher module not available: {e}")
        return

    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not filtered_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return

    with open(filtered_path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    enricher = FulltextEnricher(config)
    if not enricher.is_available:
        print("  [!] Skipped: LLM_OPENROUTER_API_KEY not set")
        return

    limit = 5 if test_mode else None
    enriched_notices = enricher.enrich_batch(notices, limit=limit)

    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(enriched_notices, f, ensure_ascii=False, indent=2)

    print(f"\n  [OK] Enrichment complete: {len(enriched_notices)} notices saved")
    return enriched_notices


def run_phase_award_match(config: dict, test_mode: bool = False):
    """Phase 3d: Award notice matching."""
    print("\n" + "="*60)
    print("  PHASE 3d: Award Notice Matching")
    print("="*60)

    try:
        from src.award_matcher import AwardMatcher
    except ImportError as e:
        print(f"  [!] award_matcher module not available: {e}")
        return

    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not filtered_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return

    with open(filtered_path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    matcher = AwardMatcher(config)
    limit = 5 if test_mode else None
    updated_notices = matcher.match_batch(notices, limit=limit)

    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(updated_notices, f, ensure_ascii=False, indent=2)

    print(f"\n  [OK] Award matching complete: {len(updated_notices)} notices")
    return updated_notices


def run_phase_award_match_llm(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
    confidence_min: int = 75,
):
    """Phase 3d-LLM: Reasoning-based award matching for unmatched tenders.

    Reads ``data/filtered/relevant.json``, runs the LLM matcher against
    the candidates already in the file, writes the file back when matches
    were applied. Cache lives at ``data/.award_match_llm_log.json``.
    """
    try:
        from src.award_matcher_llm import LLMAwardMatcher, DEFAULT_MODEL
    except ImportError as e:
        print("\n" + "=" * 60)
        print("  PHASE 3d-LLM: LLM Award Notice Matching")
        print("=" * 60)
        print(f"  [!] award_matcher_llm module not available: {e}")
        return None

    print("\n" + "=" * 60)
    print(f"  PHASE 3d-LLM: LLM Award Notice Matching ({DEFAULT_MODEL})")
    print("=" * 60)

    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not filtered_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return None

    with open(filtered_path, "r", encoding="utf-8") as f:
        notices = json.load(f)

    matcher = LLMAwardMatcher(confidence_min=confidence_min)
    if not dry_run and not matcher.is_available:
        print("  [!] LLM_OPENROUTER_API_KEY not set — aborting LLM match.")
        print("      Set LLM_OPENROUTER_API_KEY in .env.")
        return None

    target_ids = sample if sample else None
    updated_notices, summary = matcher.match_batch(
        notices, target_ids=target_ids, dry_run=dry_run,
    )

    # Always write back: even cache-only re-runs may have applied additional
    # award blocks if relevant.json changed since the last run.
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(updated_notices, f, ensure_ascii=False, indent=2)

    # ── Summary output ───────────────────────────────────────────────
    print(
        f"\n  [LLM-match summary]"
        f"\n    targets evaluated:        {summary['total_targets']}"
        f"\n    cache hits:               {summary['cache_hits']}"
        f"\n    API calls:                {summary['api_calls']}"
        f"\n    matched & applied:        {summary['matched']}"
        f"\n    rejected (low confidence):{summary['rejected_low_confidence']}"
        f"\n    no usable candidates:     {summary['no_candidates']}"
        f"\n    no match found:           {summary['no_match']}"
        f"\n    input tokens:             {summary.get('input_tokens', 0)}"
        f"\n    output tokens:            {summary.get('output_tokens', 0)}"
        f"\n    estimated cost (USD):     {summary['cost_usd']}"
    )

    if summary["applied"]:
        print("\n  [Applied matches]")
        for m in summary["applied"][:10]:
            tag = " (cache)" if m.get("from_cache") else ""
            reason = (m.get("reasoning") or "").replace("\n", " ")[:80]
            print(
                f"    {m['target']} → {m['match']}  "
                f"[conf={m['confidence']}]{tag}  {reason}"
            )
        if len(summary["applied"]) > 10:
            print(f"    ... and {len(summary['applied']) - 10} more")

    return summary


def run_phase_translate_titles(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
):
    """Translate non-English titles in ``relevant.json`` via Claude Haiku.

    Cache at ``data/.translation_cache.json``; re-runs hit the cache for
    every entry unless ``--force-refresh`` (not implemented as CLI flag —
    delete the cache file by hand if a re-translate is needed).
    """
    print("\n" + "=" * 60)
    print("  PHASE 3e: Title Translation (Haiku 4.5)")
    print("=" * 60)

    try:
        from src.translator import translate_titles
    except ImportError as e:
        print(f"  [!] translator module not available: {e}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return None

    summary = translate_titles(
        relevant_path,
        target_ids=sample,
        dry_run=dry_run,
    )

    print(
        f"\n  [translate-titles summary]"
        f"\n    total notices:            {summary['total']}"
        f"\n    evaluated:                {summary['evaluated']}"
        f"\n    skipped (no title):       {summary['skipped_no_title']}"
        f"\n    already English (heur.):  {summary['already_english']}"
        f"\n    translated now (API):     {summary['translated_now']}"
        f"\n    from cache:               {summary['from_cache']}"
        f"\n    errors:                   {summary['errors']}"
        f"\n    input tokens:             {summary.get('input_tokens', 0)}"
        f"\n    output tokens:            {summary.get('output_tokens', 0)}"
        f"\n    estimated cost (USD):     {summary['cost_usd']}"
        f"\n    model:                    {summary.get('model')}"
    )

    if summary.get("samples"):
        print("\n  [Sample translations]")
        for s in summary["samples"]:
            print(
                f"    {s['id']}  ({s['country']})\n"
                f"      {s['original'][:100]!r}\n"
                f"      → {s['title_en'][:100]!r}"
            )

    return summary


def run_phase_translate_descriptions(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
    force_clean: bool = False,
):
    """Phase 3e-2: Translate non-English descriptions (Sonnet) then clean RAW_ENGLISH (Haiku)."""
    print("\n" + "=" * 60)
    print("  PHASE 3e-2: Description Translation (Sonnet 4.6)")
    print("=" * 60)

    try:
        from src.translator import translate_descriptions, process_descriptions
    except ImportError as e:
        print(f"  [!] translator module not available: {e}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return None

    summary = translate_descriptions(
        relevant_path,
        target_ids=sample,
        dry_run=dry_run,
    )

    print(
        f"\n  [translate-descriptions summary]"
        f"\n    total notices:            {summary['total']}"
        f"\n    evaluated:                {summary['evaluated']}"
        f"\n    skipped (no source):      {summary['skipped_no_source']}"
        f"\n    already English (heur.):  {summary['already_english']}"
        f"\n    translated now (API):     {summary['translated_now']}"
        f"\n    from cache:               {summary['from_cache']}"
        f"\n    errors:                   {summary['errors']}"
        f"\n    input tokens:             {summary.get('input_tokens', 0)}"
        f"\n    output tokens:            {summary.get('output_tokens', 0)}"
        f"\n    estimated cost (USD):     {summary['cost_usd']}"
        f"\n    model:                    {summary.get('model')}"
    )

    if summary.get("samples"):
        print("\n  [Sample translations]")
        for s in summary["samples"]:
            print(
                f"    {s['id']}  ({s['country']})\n"
                f"      src:  {s['original'][:100]!r}\n"
                f"      → en: {s['desc_en'][:100]!r}"
            )

    # ── Haiku cleaning pass — always runs to catch newly added RAW_ENGLISH entries
    print("\n" + "=" * 60)
    print("  PHASE 3e-3: Description Cleaning (Haiku 4.5)")
    if force_clean:
        print("  [force-clean: bypassing clean-cache for all RAW_ENGLISH notices]")
    print("=" * 60)

    clean_summary = process_descriptions(
        relevant_path,
        target_ids=sample,
        force_clean=force_clean,
        dry_run=dry_run,
    )

    print(
        f"\n  [clean-descriptions summary]"
        f"\n    total notices:            {clean_summary['total']}"
        f"\n    already clean:            {clean_summary['already_clean']}"
        f"\n    evaluated (needs clean):  {clean_summary['evaluated']}"
        f"\n    skipped (no source):      {clean_summary['skipped_no_source']}"
        f"\n    cleaned now (API):        {clean_summary['cleaned_now']}"
        f"\n    from cache:               {clean_summary['from_cache']}"
        f"\n    errors:                   {clean_summary['errors']}"
        f"\n    input tokens:             {clean_summary.get('input_tokens', 0)}"
        f"\n    output tokens:            {clean_summary.get('output_tokens', 0)}"
        f"\n    estimated cost (USD):     {clean_summary['cost_usd']}"
        f"\n    model:                    {clean_summary.get('model')}"
    )

    if clean_summary.get("samples"):
        print("\n  [Cleaning samples]")
        for s in clean_summary["samples"]:
            print(
                f"    {s['id']}  ({s['country']})\n"
                f"      before: {s['before'][:100]!r}\n"
                f"      after:  {s['after'][:100]!r}"
            )

    return summary


def run_phase_extract_documents(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
    force: bool = False,
    test_mode: bool = False,
    no_fallback_cache: bool = False,
):
    """Phase 3g — download, extract, and AI-structure tender documents.

    Discovers PDFs/docx linked from each notice, extracts text, and uses
    Sonnet 4.6 to parse structured specs (_extracted_specs). Results are
    cached in data/.document_extraction_cache.json.
    """
    print("\n" + "=" * 60)
    print("  PHASE 3g: Document Extraction")
    print("=" * 60)

    try:
        from src.document_pipeline.orchestrator import run_extraction
    except ImportError as e:
        print(f"  [!] document_pipeline module not available: {e}")
        return

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return

    with open(relevant_path, encoding="utf-8") as f:
        notices = json.load(f)

    updated = run_extraction(
        notices,
        force=force,
        test_mode=test_mode,
        sample_ids=sample,
        dry_run=dry_run,
        no_fallback_cache=no_fallback_cache,
    )

    if not dry_run:
        with open(relevant_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)
        print(f"  [OK] relevant.json updated with _extracted_specs")


def run_phase_strategy_a(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
    force: bool = False,
    test_mode: bool = False,
):
    """Strategy A — proactive Vergabeunterlagen scraping for DE/PL/CZ tenders.

    Reads buyer_profile_url + tender_documents_access from _xml or the local
    TED XML cache, hits the buyer's national portal, downloads attached
    SWZ/LV/Vergabeunterlagen PDFs, and (unless dry_run) AI-structures them
    into _strategy_a_specs. Separate cache: data/.strategy_a_cache.json.

    Opt-in only via --strategy-a; not active in --all because the live portal
    scrapes are slower and more fragile than the standard 3g extraction.
    """
    print("\n" + "=" * 60)
    print("  STRATEGY A: Vergabeunterlagen Scraping (DE/PL/CZ)")
    print("=" * 60)

    try:
        from src.document_pipeline.strategy_a import run_strategy_a
    except ImportError as exc:
        print(f"  [!] strategy_a module unavailable: {exc}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found.")
        return None

    with open(relevant_path, encoding="utf-8") as f:
        notices = json.load(f)

    stats = run_strategy_a(
        notices,
        sample_ids=sample,
        test_mode=test_mode,
        dry_run=dry_run,
        force=force,
    )

    if not dry_run:
        with open(relevant_path, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)

    print(
        f"\n  Strategy-A summary:"
        f"\n    candidates:           {stats['candidates']}"
        f"\n    triggered (DE/PL/CZ): {stats['triggered']}"
        f"\n    no inputs (skipped):  {stats['no_inputs']}"
        f"\n    docs discovered:      {stats['docs_discovered']}"
        f"\n    docs alive (HEAD ok): {stats['docs_alive']}"
        f"\n    docs downloaded:      {stats['docs_downloaded']}"
        f"\n    text extracted:       {stats['docs_text_extracted']}"
        f"\n    auth_blocked (eIDAS): {stats['auth_blocked']}"
        f"\n    AI calls:             {stats['ai_calls']}"
        f"\n    cache hits:           {stats['cache_hits']}"
        f"\n    by country (trigger): DE={stats['by_country'].get('DE',0)} "
        f"PL={stats['by_country'].get('PL',0)} CZ={stats['by_country'].get('CZ',0)}"
        f"\n    yield (≥200 chars):   DE={stats['yield_by_country'].get('DE',0)} "
        f"PL={stats['yield_by_country'].get('PL',0)} CZ={stats['yield_by_country'].get('CZ',0)}"
    )
    if stats["extracted_tenders"]:
        print(f"    extracted tenders:    {', '.join(stats['extracted_tenders'][:10])}")
    return stats


def run_phase_enrich_descriptions(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
):
    """Phase 3f — annotate description fields with EUR equivalents.

    Pure regex + FX-dictionary lookup, zero API cost. Idempotent via
    a sha1 cache keyed on the raw description.
    """
    print("\n" + "=" * 60)
    print("  PHASE 3f: Description Currency Enrichment (regex + FX)")
    print("=" * 60)

    try:
        from src.currency_enricher import enrich_all
    except ImportError as e:
        print(f"  [!] currency_enricher module not available: {e}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found. Run filter phase first.")
        return None

    summary = enrich_all(
        relevant_path,
        target_ids=sample,
        dry_run=dry_run,
    )

    print(
        f"\n  [enrich-descriptions summary]"
        f"\n    total notices:                {summary['total']}"
        f"\n    evaluated:                    {summary['evaluated']}"
        f"\n    skipped (no description):     {summary['skipped_no_desc']}"
        f"\n    skipped (no currency match):  {summary['skipped_no_currency']}"
        f"\n    enriched now:                 {summary['enriched_now']}"
        f"\n    from cache:                   {summary['from_cache']}"
        f"\n    total currency matches:       {summary['match_count_total']}"
    )

    if summary.get("samples"):
        print("\n  [Sample enrichments]")
        for s in summary["samples"]:
            print(
                f"    {s['id']}  ({s['matches']} match{'es' if s['matches'] != 1 else ''})\n"
                f"      before: {s['before'][:140]!r}\n"
                f"      after:  {s['after'][:160]!r}"
            )

    return summary


def run_phase_contract_type(
    force: bool = False,
    dry_run: bool = False,
) -> Optional[dict]:
    """Phase 3j — classify contract type (framework / one_time / recurring)."""
    print("\n" + "=" * 60)
    print("  PHASE 3j: Contract Type Classification (regex)")
    print("=" * 60)
    try:
        from src.contract_type import run_contract_type_pass
    except ImportError as e:
        print(f"  [!] contract_type module not available: {e}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found.")
        return None

    summary = run_contract_type_pass(
        relevant_path,
        force=force,
        dry_run=dry_run,
    )
    print(
        f"\n  framework_agreement: {summary.get('framework_agreement', 0)}"
        f"\n  recurring:           {summary.get('recurring', 0)}"
        f"\n  one_time:            {summary.get('one_time', 0)}"
        f"\n  classified_now:      {summary['classified_now']}"
        f"\n  from cache:          {summary['from_cache']}"
    )
    return summary


def run_phase_text_mining(
    sample: Optional[list[str]] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Optional[dict]:
    """Phase 3k — regex-based text mining for quantity / deadline / duration.

    Sits between description-translate (3e-2) and document-extract (3g) so the
    mined values are already attached to each notice by the time the document
    pipeline runs. Free, deterministic, idempotent via sha1 cache.

    Args:
        sample:    Limit to these tender_ids (else: every notice).
        dry_run:   Compute but do not persist relevant.json.
        force:     Bypass cache (re-mine all selected notices).
    """
    print("\n" + "=" * 60)
    print("  PHASE 3k: Text Mining (regex on description text)")
    print("=" * 60)

    try:
        from src.text_miner import _save_cache, run_text_mining
    except ImportError as e:
        print(f"  [!] text_miner module not available: {e}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found.")
        return None

    with open(relevant_path, encoding="utf-8") as f:
        notices = json.load(f)

    if sample:
        sample_set = set(sample)
        targets = [n for n in notices if n.get("tender_id") in sample_set]
    else:
        targets = notices

    if force:
        # Invalidate cache entries for the targeted IDs only.
        from src.text_miner import _cache_key, _candidate_text, _load_cache
        cache = _load_cache()
        for n in targets:
            tid = (n.get("tender_id") or "").strip()
            text = _candidate_text(n)
            if not text:
                continue
            cache.pop(_cache_key(tid, text), None)
        _save_cache(cache)

    stats = run_text_mining(targets)

    print(
        f"\n  total notices:           {stats['total']}"
        f"\n  qty found:               {stats['qty_found']}"
        f"\n  qty found (text-only):   {stats['qty_from_text_only']}"
        f"\n  deadline found:          {stats['deadline_found']}"
        f"\n  duration found:          {stats['duration_found']}"
    )

    if not dry_run:
        # Stable in-place save (preserve key order).
        with open(relevant_path, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)
        print(f"  [OK] relevant.json updated with _qty_mined / _deadline_mined")

    return stats


def run_phase_url_validation(
    *, force: bool = False, only_sources: Optional[list[str]] = None,
    dry_run: bool = False,
) -> Optional[dict]:
    """Phase 3l — HEAD/ranged-GET probe of every notice's source URL.

    Attaches ``_url_status`` (alive | dead | auth_walled | timeout | unknown |
    no_url) so the exporter / frontend can hide or warn about broken links.

    Sits after data-prep phases (3k/3f/3j) and BEFORE Phase 4 export so the
    field is included in the exported tenders.json. Cache TTL 30 days — full
    re-probe of ~340 notices runs in <3 min, cache-hit run is instant.
    """
    print("\n" + "=" * 60)
    print("  PHASE 3l: URL Health Check")
    print("=" * 60)

    try:
        from src.url_validator import run_url_validation
    except ImportError as e:
        print(f"  [!] url_validator module not available: {e}")
        return None

    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    if not relevant_path.exists():
        print("  [!] No relevant.json found.")
        return None

    with open(relevant_path, encoding="utf-8") as f:
        notices = json.load(f)

    stats = run_url_validation(notices, force=force, only_sources=only_sources)
    print(
        f"\n  total:        {stats['total']}"
        f"\n  cache hits:   {stats['cache_hits']}"
        f"\n  checked:      {stats['checked']}"
        f"\n  alive:        {stats.get('alive', 0)}"
        f"\n  dead:         {stats.get('dead', 0)}"
        f"\n  auth_walled:  {stats.get('auth_walled', 0)}"
        f"\n  timeout:      {stats.get('timeout', 0)}"
        f"\n  no_url:       {stats['no_url']}"
    )

    if not dry_run:
        with open(relevant_path, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)
        print(f"  [OK] relevant.json updated with _url_status")

    return stats


def _run_merge_cached_awards(confidence_min: int = 65) -> None:
    """Re-apply LLM award cache to relevant.json after a filter rebuild.

    No API calls — reads only the local cache log.
    """
    try:
        from src.award_matcher_llm import merge_cached_awards
    except ImportError as e:
        print(f"  [award-cache] Module not available: {e}")
        return
    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    merged = merge_cached_awards(str(filtered_path), confidence_min=confidence_min)
    if merged:
        print(f"  [award-cache] Restored {merged} LLM awards from cache (conf>={confidence_min})")
    else:
        print(f"  [award-cache] No new LLM awards to restore from cache")


def _dedup_key(notice: dict) -> str:
    """Stable-ish cross-source dedup key: authority(25) | title(35) | year."""
    auth = (notice.get("contracting_authority") or {}).get("name", "")
    if not auth:
        auth = (notice.get("contracting_authority") or {}).get("name_short", "")
    title = notice.get("title") or ""
    if isinstance(title, dict):
        title = title.get("eng") or title.get("deu") or next(iter(title.values()), "")
    year = str(notice.get("publication_date") or "")[:4]
    return f"{str(auth).lower()[:25].strip()}|{str(title).lower()[:35].strip()}|{year}"


def _enrich_from_national(ted_notice: dict, nat: dict):
    """Fill empty TED fields with national portal data (non-destructive)."""
    tv = ted_notice.get("estimated_value") or {}
    nv = nat.get("estimated_value") or {}
    if not tv.get("amount") and nv.get("amount"):
        ted_notice["estimated_value"] = nv

    ta = ted_notice.get("award") or {}
    na = nat.get("award") or {}
    if not ta.get("winner_name") and na.get("winner_name"):
        ted_notice["award"] = na

    td = str(ted_notice.get("description") or "")
    nd = str(nat.get("description") or "")
    if len(nd) > len(td) + 50:
        ted_notice["description"] = nd

    # Source tracking: "TED" -> "TED+UK-CF"
    existing = ted_notice.get("source") or "TED"
    ted_notice["source"] = f"{existing}+{nat.get('source', '')}"
    if not ted_notice.get("source_url_national"):
        ted_notice["source_url_national"] = nat.get("source_url_national", "")


def merge_national_with_ted(ted_notices: list, national_notices: list) -> list:
    """Merge national portal notices into the TED dataset."""
    merged = list(ted_notices)
    ted_index = {_dedup_key(n): n for n in merged}
    existing_ids = {n.get("tender_id") for n in merged if n.get("tender_id")}

    added = 0
    enriched = 0
    skipped_dup = 0
    for nat in national_notices:
        tid = nat.get("tender_id")
        if tid and tid in existing_ids:
            skipped_dup += 1
            continue
        key = _dedup_key(nat)
        if key in ted_index and key.strip("|").strip():
            _enrich_from_national(ted_index[key], nat)
            enriched += 1
        else:
            merged.append(nat)
            if tid:
                existing_ids.add(tid)
            added += 1

    if skipped_dup:
        print(f"  Merge: {added} added, {enriched} enriched, {skipped_dup} id-dupes skipped, {len(merged)} total")
    else:
        print(f"  Merge: {added} added, {enriched} enriched, {len(merged)} total")
    return merged


def run_phase_uk(config: dict, test_mode: bool = False, date_from: str | None = None) -> list:
    """Phase 5: UK Contracts Finder scraping."""
    print("\n" + "=" * 60)
    print("  PHASE 5: UK Contracts Finder")
    print("=" * 60)

    pub_from = (
        date_from
        or config.get("search", {}).get("date_from")
        or "2015-01-01"
    )
    scraper = UKContractsFinderScraper(config, cache_dir=str(PROJECT_ROOT / "data" / "raw" / "uk"))
    notices = scraper.fetch_and_filter(published_from=pub_from, test_mode=test_mode)
    print(f"  [OK] UK normalized notices: {len(notices)}")
    return notices


_NATIONAL_FORCE_INCLUDE_PATH = PROJECT_ROOT / "config" / "national_force_include.json"


def update_national_force_include(notices: list):
    """
    Save relevant national notice IDs to national_force_include.json so they
    survive future full runs regardless of NEN/portal pagination.

    Only persists notices that have ``_trailer_type_1_ai`` set — i.e. notices
    that passed AI classification.  Lists are sorted alphabetically before
    writing so diffs stay clean.

    Called after classify so only AI-confirmed relevant notices are persisted.
    """
    try:
        if _NATIONAL_FORCE_INCLUDE_PATH.exists():
            with open(_NATIONAL_FORCE_INCLUDE_PATH, "r", encoding="utf-8") as f:
                force = json.load(f)
        else:
            force = {}
    except Exception:
        force = {}

    added = 0
    for notice in notices:
        # Only persist AI-classified nationals (trailer_type must be resolved)
        if not notice.get("_trailer_type_1_ai"):
            continue
        src = (notice.get("source") or "").replace("TED+", "").split("+")[0]
        tid = notice.get("tender_id", "")
        if not tid or not src or src == "TED":
            continue
        if src not in force:
            force[src] = []
        if tid not in force[src]:
            force[src].append(tid)
            added += 1

    # Sort each list alphabetically for stable diffs
    for src_key in force:
        if isinstance(force[src_key], list):
            force[src_key] = sorted(force[src_key])

    _NATIONAL_FORCE_INCLUDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_NATIONAL_FORCE_INCLUDE_PATH, "w", encoding="utf-8") as f:
        json.dump(force, f, ensure_ascii=False, indent=2)
    if added:
        print(f"  [force-include] +{added} new national IDs saved (AI-confirmed only)")


def ensure_force_includes(notices: list) -> list:
    """
    Append force-included national notices that are missing from the current
    relevant.json.  Reconstructs minimal notice dicts from the enrichment log.

    Called just before export so the Excel always contains all known-relevant
    national notices even when the portal adapter didn't fetch them this run.
    """
    if not _NATIONAL_FORCE_INCLUDE_PATH.exists():
        return notices

    try:
        with open(_NATIONAL_FORCE_INCLUDE_PATH, "r", encoding="utf-8") as f:
            force = json.load(f)
    except Exception:
        return notices

    # Load enrichment log for reconstruction
    log_path = PROJECT_ROOT / "data" / ".enrichment_log.json"
    log: dict = {}
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            pass

    existing_ids = {n.get("tender_id", "") for n in notices}
    added = 0

    for src_key, ids in force.items():
        if src_key.startswith("_"):
            continue
        for tid in ids:
            if tid in existing_ids:
                continue
            log_entry = log.get(tid, {})
            result = log_entry.get("result") or {}
            if not result.get("relevant", False):
                continue
            # Reconstruct minimal notice dict from enrichment log cache
            notice = {
                "tender_id": tid,
                "source": src_key,
                "_title_english": result.get("title_english", log_entry.get("title", "")),
                "_description_english": result.get("description_english", ""),
                "_trailer_type_1_ai": result.get("trailer_type_1") or result.get("trailer_type"),
                "_trailer_category_1_ai": result.get("trailer_category_1") or result.get("trailer_category"),
                "_trailer_quantity_1_ai": result.get("trailer_quantity_1") or result.get("trailer_quantity"),
                "_trailer_type_2_ai": result.get("trailer_type_2"),
                "_trailer_category_2_ai": result.get("trailer_category_2"),
                "_trailer_quantity_2_ai": result.get("trailer_quantity_2"),
                "_additional_equipment_ai": result.get("additional_equipment"),
                "_additional_qty_ai": result.get("additional_qty"),
                "_contract_duration_ai": result.get("contract_duration"),
                "_fulltext_enriched": False,
                "_force_included": True,
            }
            notices = list(notices)
            notices.append(notice)
            existing_ids.add(tid)
            added += 1

    if added:
        print(f"  [force-include] Restored {added} national notices from cache")
    return notices


def _merge_uk_into_relevant(uk_notices: list) -> int:
    """Append UK notices to data/filtered/relevant.json with cross-source dedup."""
    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    existing: list = []
    if filtered_path.exists():
        with open(filtered_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    merged = merge_national_with_ted(existing, uk_notices)

    filtered_path.parent.mkdir(parents=True, exist_ok=True)
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return len(merged)


def dedup_uk_fts_vs_cf(fts_notices: list, existing_notices: list) -> tuple[list, int]:
    """
    Cross-dedup UK-FTS notices against existing UK-CF notices.

    Exact match on tender_id; title-similarity match as fallback (≥4 common words).
    Returns (new_only, enriched_count) — new_only are FTS notices not found in CF,
    enriched_count is how many CF entries got winner/value data from FTS.
    """
    existing_uk = {
        n.get("tender_id", ""): n
        for n in existing_notices
        if "UK" in str(n.get("source", ""))
    }

    new_notices: list = []
    enriched = 0

    for fts in fts_notices:
        fts_tid = fts.get("tender_id", "")
        fts_title_words = set(str(fts.get("_title_final", "")).lower().split())

        matched_key = None

        # Exact ID match
        if fts_tid in existing_uk:
            matched_key = fts_tid
        else:
            # Title similarity
            for uid, ex in existing_uk.items():
                ex_words = set(str(ex.get("_title_final", "")).lower().split())
                if len(fts_title_words & ex_words) >= 4:
                    matched_key = uid
                    break

        if matched_key:
            ex = existing_uk[matched_key]
            changed = False
            if not ex.get("_winner_name") and fts.get("_winner_name"):
                ex["_winner_name"] = fts["_winner_name"]
                changed = True
            if not (ex.get("estimated_value") and ex["estimated_value"].get("amount")):
                if fts.get("estimated_value") and fts["estimated_value"].get("amount"):
                    ex["estimated_value"] = fts["estimated_value"]
                    changed = True
            if changed:
                ex["source"] = ex.get("source", "UK-CF") + "+UK-FTS"
                enriched += 1
        else:
            new_notices.append(fts)

    logger.info(f"UK-FTS dedup: {enriched} CF enriched, {len(new_notices)} new FTS-only")
    return new_notices, enriched


def run_bulk_comparison(config: dict, test_mode: bool = False) -> list:
    """Find notices in TED bulk CSV that our API queries missed."""
    print("\n" + "="*60)
    print("  TED BULK CSV: Comparing against existing dataset")
    print("="*60)

    from src.ted_bulk_loader import TEDBulkLoader

    loader = TEDBulkLoader(config, cache_dir=str(PROJECT_ROOT / "data" / "raw" / "ted_bulk"))

    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    existing_ids: set = set()
    if filtered_path.exists():
        with open(filtered_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_ids = {n.get("tender_id", "") for n in existing}
        print(f"  Existing dataset: {len(existing)} notices, {len(existing_ids)} unique IDs")
    else:
        print("  [!] No relevant.json found — comparison will show all bulk matches")

    missing = loader.find_missing_notices(
        existing_ids=existing_ids,
        test_mode=test_mode,
    )

    if missing:
        print(f"\n  Notices in TED CSV but NOT in our data: {len(missing)}")
        print(f"  {'Tender ID':<18} {'Country':<8} {'CPV':<12}")
        print(f"  {'-'*18} {'-'*8} {'-'*12}")
        for m in missing[:20]:
            print(f"  {m.get('tender_id','?'):<18} {m.get('country','?'):<8} {m.get('cpv','?'):<12}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")
    else:
        print("  No missing notices found (or no bulk data available)")

    out_path = PROJECT_ROOT / "data" / "raw" / "ted_bulk" / "missing_notices.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(missing, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {out_path} ({len(missing)} entries)")

    return missing


def run_canada(config: dict, test_mode: bool = False) -> list:
    """Load Canadian DND procurement data: historical contracts + active CanadaBuys tenders."""
    print("\n" + "="*60)
    print("  CANADA: open.canada.ca DND Procurement")
    print("="*60)

    from src.canada_loader import CanadaOpenDataLoader

    loader = CanadaOpenDataLoader(cache_dir=str(PROJECT_ROOT / "data" / "raw" / "canada"))

    # 1. Historical contracts (CKAN Datastore)
    matches = loader.load_and_filter(test_mode=test_mode)
    if matches:
        print(f"\n  [Historical] {len(matches)} DND trailer contracts (CA-OD):")
        for m in matches[:5]:
            print(f"    {m.get('tender_id','?'):<22} {m.get('date','?'):<12} {m.get('title','')[:50]}")
    else:
        print("  [Historical] No DND trailer contracts found")

    # 2. Active/recent tenders (CanadaBuys Open Data CSVs)
    print("\n  Loading CanadaBuys active tenders...")
    active = loader.load_active_tenders(test_mode=test_mode)
    if active:
        print(f"  [Active/Recent] {len(active)} DND trailer tenders (CA-CB):")
        for t in active[:10]:
            title = t.get("_title_final") or t.get("title", "")
            date = t.get("_pub_date","")
            status = t.get("_status","")
            print(f"    {t.get('tender_id','?'):<30} [{status:6}] {date:<12} {title[:50]}")
        if len(active) > 10:
            print(f"  ... and {len(active) - 10} more")
    else:
        print("  [Active] No active DND trailer tenders found")

    return matches  # historical returned separately; active go through classifier


def auto_apply_opus_findings(review: dict):
    """Automatically apply safe Opus QA findings to blacklist + manual_overrides."""
    bl_path = PROJECT_ROOT / "config" / "blacklist.json"
    ov_path = PROJECT_ROOT / "config" / "manual_overrides.json"

    # 1. False positives → blacklist
    fps = review.get("false_positives", [])
    if fps:
        try:
            bl = json.loads(bl_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            bl = {"false_positives": {"ids": []}, "known_duplicates": {"ids": []}}
        fp_ids = set(bl.get("false_positives", {}).get("ids", []))
        new_fps = 0
        for fp in fps:
            fid = fp.get("tender_id", "")
            if fid and fid not in fp_ids:
                fp_ids.add(fid)
                new_fps += 1
        bl["false_positives"]["ids"] = sorted(fp_ids)
        bl_path.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
        if new_fps:
            print(f"    → {new_fps} new false positives added to blacklist")

    # 2. Duplicates → blacklist (keep newer, remove older)
    dupes = review.get("duplicates", [])
    if dupes:
        try:
            bl = json.loads(bl_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            bl = {"false_positives": {"ids": []}, "known_duplicates": {"ids": []}}
        dupe_ids = set(bl.get("known_duplicates", {}).get("ids", []))
        new_dupes = 0
        for d in dupes:
            ids = d.get("tender_ids", [])
            if len(ids) >= 2:
                # Blacklist the older one (lower year suffix)
                def year_key(tid: str) -> str:
                    return tid.split("-")[-1] if "-" in tid else "0"
                to_remove = min(ids, key=year_key)
                if to_remove not in dupe_ids:
                    dupe_ids.add(to_remove)
                    new_dupes += 1
        bl["known_duplicates"]["ids"] = sorted(dupe_ids)
        bl_path.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
        if new_dupes:
            print(f"    → {new_dupes} duplicate IDs added to blacklist")

    # 3. Category errors → manual_overrides
    cat_errors = review.get("category_errors", [])
    if cat_errors:
        try:
            overrides = json.loads(ov_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            overrides = {}
        new_overrides = 0
        for ce in cat_errors:
            tid = ce.get("tender_id", "")
            suggested = ce.get("should_be", "")
            if tid and suggested and tid not in overrides:
                overrides[tid] = {
                    "trailer_category_1": suggested,
                    "reason": f"Opus auto: {ce.get('reason', '')}",
                }
                new_overrides += 1
        ov_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        if new_overrides:
            print(f"    → {new_overrides} category corrections added to overrides")

    # 4. Log suggestions that need human review
    buzzwords = review.get("blacklist_buzzwords", [])
    if buzzwords:
        print(f"    → Opus flags {len(buzzwords)} generic type-field entries (manual review needed)")

    ops = review.get("extraction_opportunities", [])
    if ops:
        print(f"    → Opus flags {len(ops)} extraction opportunities (slot-2 candidates)")

    # Save to named file for reference
    out = PROJECT_ROOT / "data" / "opus_review_latest.json"
    out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    → Saved: data/opus_review_latest.json")


def run_review(config: dict):
    """Optional: Opus-based post-run quality review of the latest Excel."""
    print("\n" + "="*60)
    print("  PHASE 5 (optional): Quality Review (Claude Opus)")
    print("="*60)

    try:
        from src.quality_review import QualityReviewer
    except ImportError as e:
        print(f"  [!] quality_review module unavailable: {e}")
        return

    export_dir = PROJECT_ROOT / "data" / "export"
    latest = export_dir / "TED_Defence_Trailers_LATEST.xlsx"
    if not latest.exists():
        # Fall back to newest versioned export
        candidates = sorted(
            [p for p in export_dir.glob("*.xlsx") if "LATEST" not in p.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            print("  [!] No Excel export found; skipping review.")
            return
        latest = candidates[0]

    reviewer = QualityReviewer()
    if not reviewer.is_available:
        print("  [!] LLM_OPENROUTER_API_KEY not set; skipping review.")
        return None

    print(f"  Reviewing: {latest.name}")
    result = reviewer.review(latest)
    if not result:
        print("  [!] Quality review returned no result.")
        return None

    summary = result.get("summary", {})
    print(f"  [OK] Reviewed {summary.get('total_rows', '?')} rows, "
          f"{summary.get('issues_found', '?')} issues flagged")
    print(f"  Saved: data/quality_review.json")

    print("  Auto-applying safe findings...")
    auto_apply_opus_findings(result)

    return result


def run_frontend_export() -> int:
    """Write shared/tenders.json for the defence-intel-web frontend."""
    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    shared_dir = PROJECT_ROOT.parent.parent / "shared"
    output_path = shared_dir / "tenders.json"
    shared_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  FRONTEND EXPORT: shared/tenders.json")
    print("=" * 60)

    count = export_tenders_for_frontend(relevant_path, output_path)
    print(f"\n  [OK] Frontend export: {count} tenders → {output_path}")
    return count


def run_phase_export(config: dict, test_mode: bool = False,
                     canada_notices: list = None):
    """Phase 4: Excel export."""
    print("\n" + "="*60)
    print("  PHASE 4: Excel Export")
    print("="*60)

    exporter = ExcelExporter(config)
    path = exporter.export(
        filtered_dir=str(PROJECT_ROOT / "data" / "filtered"),
        test_mode=test_mode,
        canada_notices=canada_notices or [],
    )

    if path:
        print(f"\n  [OK] Excel exported: {path}")
        print(f"  Template: Vorlage.xlsx (Scraper Data + Canada tab)")
        if canada_notices:
            print(f"  Canada (Historical): {len(canada_notices)} contracts")
    else:
        print("  [!] No data to export")

    return path


def run_api_test(config: dict):
    """Quick test to verify API connectivity."""
    print("\n" + "="*60)
    print("  API Connectivity Test")
    print("="*60)

    client = TedApiClient(config)
    query = client.build_query(
        cpv_codes=["34223000"],
        date_from="2024-01-01",
        date_to="2024-12-31"
    )

    print(f"  Query: {json.dumps(query, indent=2)}")
    print("  Sending request...")

    result = client.search(query, page=1)

    if result:
        total = result.get("total", result.get("totalNoticeCount", "?"))
        results = result.get("notices", result.get("results", []))
        print(f"  [OK] API reachable!")
        print(f"  Total results: {total}")
        print(f"  First page: {len(results)} notices")

        if results:
            first = results[0]
            print(f"  Sample notice keys: {list(first.keys())[:10]}")
            sample_path = PROJECT_ROOT / "data" / "raw" / "api_sample.json"
            with open(sample_path, "w", encoding="utf-8") as f:
                json.dump(first, f, ensure_ascii=False, indent=2)
            print(f"  Sample saved: {sample_path}")
    else:
        print("  [--] API request failed!")
        print("  Check network connectivity and API URL.")

    return result


def run_phase_de(config: dict, test_mode: bool = False) -> list:
    """Germany service.bund.de scraping phase."""
    print("\n" + "=" * 60)
    print("  PHASE DE: Germany service.bund.de")
    print("=" * 60)
    from src.de_scraper import DEServiceBundScraper
    scraper = DEServiceBundScraper(config, cache_dir=str(PROJECT_ROOT / "data" / "raw" / "de"))

    # Load existing notices for dedup
    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    existing: list = []
    if filtered_path.exists():
        with open(filtered_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    de_notices = scraper.fetch_and_filter(existing_notices=existing, test_mode=test_mode)
    print(f"  [OK] DE raw candidates: {len(de_notices)}")

    if de_notices:
        merged, added = scraper.merge_with_existing(de_notices, existing)
        filtered_path.parent.mkdir(parents=True, exist_ok=True)
        with open(filtered_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"  [OK] DE: {added} new notices added, "
              f"{len(de_notices) - added} matched existing TED entries")
        print(f"  [OK] relevant.json now: {len(merged)} notices")
    else:
        print("  [!] No DE notices found (check logs)")

    return de_notices


def run_phase_pl(config: dict, test_mode: bool = False) -> list:
    """Poland BZP scraping phase."""
    print("\n" + "=" * 60)
    print("  PHASE PL: Poland searchbzp.uzp.gov.pl")
    print("=" * 60)
    from src.pl_scraper import PLBZPScraper
    scraper = PLBZPScraper(config, cache_dir=str(PROJECT_ROOT / "data" / "raw" / "pl"))

    # Load existing for dedup
    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    existing: list = []
    if filtered_path.exists():
        with open(filtered_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    pl_notices = scraper.fetch_and_filter(existing_notices=existing, test_mode=test_mode)
    print(f"  [OK] PL raw candidates: {len(pl_notices)}")

    if pl_notices:
        # Simple dedup merge
        existing_keys = {scraper.dedup_key(n) for n in existing}
        new_ones = [n for n in pl_notices if scraper.dedup_key(n) not in existing_keys]
        merged = existing + new_ones
        filtered_path.parent.mkdir(parents=True, exist_ok=True)
        with open(filtered_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"  [OK] PL: {len(new_ones)} new notices added "
              f"({len(pl_notices) - len(new_ones)} duplicates skipped)")
        print(f"  [OK] relevant.json now: {len(merged)} notices")
    else:
        print("  [!] No PL notices found (check logs — platform may require JS rendering)")

    return pl_notices


def run_national_scraping(countries: list, config: dict,
                          test_mode: bool = False,
                          headless: bool = True) -> list:
    """
    Run national portal scraping for the specified countries.
    DE uses Playwright (service.bund.de).
    PL uses the eZamowienia REST API (ezamowienia.gov.pl) — no browser needed.

    Supported country codes: "de" (service.bund.de), "pl" (ezamowienia.gov.pl)

    Returns a list of notices in the standard pipeline format.
    Integrates screenshots + page-text dumps into data/raw/screenshots/.
    """
    try:
        from src.national_scraper.core import BrowserCore
    except ImportError as e:
        print(f"  [!] Playwright not installed: {e}")
        print("  Run: pip install playwright && playwright install chromium")
        return []

    adapter_registry = {}
    try:
        from src.national_scraper.adapters.de_adapter import DEAdapter, create_de_config
        adapter_registry["de"] = (DEAdapter, create_de_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.pl_adapter import PLAdapter, create_pl_config
        adapter_registry["pl"] = (PLAdapter, create_pl_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.fi_adapter import FIAdapter, create_fi_config
        adapter_registry["fi"] = (FIAdapter, create_fi_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.se_adapter import SEAdapter, create_se_config
        adapter_registry["se"] = (SEAdapter, create_se_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.no_adapter import NOAdapter, create_no_config
        adapter_registry["no"] = (NOAdapter, create_no_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.cz_adapter import CZAdapter, create_cz_config
        adapter_registry["cz"] = (CZAdapter, create_cz_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.fr_adapter import FRAdapter, create_fr_config
        adapter_registry["fr"] = (FRAdapter, create_fr_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.dk_adapter import DKAdapter, create_dk_config
        adapter_registry["dk"] = (DKAdapter, create_dk_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.ro_adapter import ROAdapter, create_ro_config
        adapter_registry["ro"] = (ROAdapter, create_ro_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.nl_adapter import NLAdapter, create_nl_config
        adapter_registry["nl"] = (NLAdapter, create_nl_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.be_adapter import BEAdapter, create_be_config
        adapter_registry["be"] = (BEAdapter, create_be_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.es_adapter import ESAdapter, create_es_config
        adapter_registry["es"] = (ESAdapter, create_es_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.it_adapter import ITAdapter, create_it_config
        adapter_registry["it"] = (ITAdapter, create_it_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.ua_adapter import UAAdapter, create_ua_config
        adapter_registry["ua"] = (UAAdapter, create_ua_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.ch_adapter import CHAdapter, create_ch_config
        adapter_registry["ch"] = (CHAdapter, create_ch_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.uk_fts_adapter import UKFTSAdapter, create_uk_fts_config
        adapter_registry["gb"] = (UKFTSAdapter, create_uk_fts_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.de_evergabe_adapter import DEEvergabeAdapter, create_de_evergabe_config
        adapter_registry["de-ev"] = (DEEvergabeAdapter, create_de_evergabe_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.gr_adapter import GRAdapter, create_gr_config
        adapter_registry["gr"] = (GRAdapter, create_gr_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.ee_adapter import EEAdapter, create_ee_config
        adapter_registry["ee"] = (EEAdapter, create_ee_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.lv_adapter import LVAdapter, create_lv_config
        adapter_registry["lv"] = (LVAdapter, create_lv_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.lt_adapter import LTAdapter, create_lt_config
        adapter_registry["lt"] = (LTAdapter, create_lt_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.au_ocds_adapter import AuOcdsAdapter, create_au_ocds_config
        adapter_registry["au"] = (AuOcdsAdapter, create_au_ocds_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.au_atm_adapter import AuAtmAdapter, create_au_atm_config
        adapter_registry["au-atm"] = (AuAtmAdapter, create_au_atm_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.canada_loader import CanadaBuysAdapter, create_canada_config
        adapter_registry["ca"] = (CanadaBuysAdapter, create_canada_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.nspa_adapter import NSPAAdapter, create_nspa_config
        adapter_registry["nspa"] = (NSPAAdapter, create_nspa_config)
    except ImportError:
        pass
    # TR adapter parked (Sprint 14d) — defence procurement
    #  not portal-accessible. Re-enable explicitly via --national tr.
    # try:
    #     from src.national_scraper.adapters.tr_adapter import TrAdapter, create_tr_config
    #     adapter_registry["tr"] = (TrAdapter, create_tr_config)
    # except ImportError:
    #     pass

    all_notices = []
    screenshot_dir = str(PROJECT_ROOT / "data" / "raw" / "screenshots")

    print(f"\n  Browser: {'visible' if not headless else 'headless'}")
    print(f"  Countries: {', '.join(countries).upper()}")
    print(f"  Mode: {'TEST (2 keywords, 3 details max)' if test_mode else 'FULL'}")

    with BrowserCore(headless=headless, slow_mo=100,
                     screenshot_dir=screenshot_dir) as browser:
        for country in countries:
            country = country.lower()
            if country not in adapter_registry:
                print(f"  [!] No adapter for '{country}' — supported: {list(adapter_registry.keys())}")
                continue

            AdapterClass, config_factory = adapter_registry[country]
            adapter_config = config_factory()
            adapter = AdapterClass(browser, adapter_config)

            print(f"\n  ── {adapter_config.country_name} ({adapter_config.source_code}) ──")

            # Search all keywords
            results = adapter.search_all_keywords(
                max_results_per_keyword=30,
                test_mode=test_mode,
            )
            print(f"  Raw search results:  {len(results)}")

            # Filter to defence-relevant
            defence = adapter.filter_defence(results)
            print(f"  Defence-relevant:    {len(defence)}")

            if not defence:
                # Still worth reporting — page text dumps are in screenshots/
                print(f"  [!] 0 defence results — check data/raw/screenshots/ for page dumps")
                continue

            # Fetch details — cap slow/large adapters
            notices = []
            if test_mode:
                detail_limit = 3
            elif country == "cz":
                detail_limit = min(len(defence), 150)
            elif country == "au":
                # AU-OCDS returns thousands of defence notices; results are
                # pre-sorted by relevance score so the cap keeps the best ones.
                detail_limit = min(len(defence), 500)
            else:
                detail_limit = len(defence)
            for i, result in enumerate(defence[:detail_limit]):
                print(f"    [{i+1}/{min(detail_limit, len(defence))}] {result.title[:60]}")
                detail = adapter.get_detail(result)
                if detail:
                    notice = adapter.to_standard_format(detail)
                    notices.append(notice)

            print(f"  Detailed notices:    {len(notices)}")
            all_notices.extend(notices)

    return all_notices


def run_single_national_isolated(country: str, config: dict,
                                  test_mode: bool = False,
                                  headless: bool = True) -> list:
    """
    Run a single national adapter with its own BrowserCore instance.

    Safe to call from a thread — each invocation owns its Playwright browser.
    REST-only adapters (NO, PL) still receive a BrowserCore but use it only
    for detail-page fetches if needed.
    """
    from src.national_scraper.core import BrowserCore

    registry = get_adapter_registry()
    if country not in registry:
        print(f"  [parallel] No adapter for '{country}'")
        return []

    AdapterClass, config_factory = registry[country]
    adapter_config = config_factory()
    screenshot_dir = str(PROJECT_ROOT / "data" / "raw" / "screenshots")

    print(f"  [parallel] Starting {adapter_config.country_name} ({country.upper()})...")
    try:
        with BrowserCore(headless=headless, slow_mo=100,
                         screenshot_dir=screenshot_dir) as browser:
            adapter = AdapterClass(browser, adapter_config)
            results = adapter.search_all_keywords(
                max_results_per_keyword=30,
                test_mode=test_mode,
            )
            defence = adapter.filter_defence(results)
            if test_mode:
                detail_limit = 3
            elif country == "cz":
                # CZ uses Playwright browser per detail page (~6s each).
                # Cap at 50 so CZ doesn't become a 40-minute bottleneck.
                detail_limit = min(len(defence), 150)
            else:
                detail_limit = len(defence)
            notices = []
            for i, r in enumerate(defence[:detail_limit]):
                detail = adapter.get_detail(r)
                if detail:
                    notices.append(adapter.to_standard_format(detail))
            if len(defence) > detail_limit:
                print(f"  [parallel] {country.upper()}: capped at {detail_limit} details "
                      f"({len(defence)} candidates)")
        print(f"  [parallel] {country.upper()} done: {len(notices)} notices")
        return notices
    except Exception as exc:
        print(f"  [parallel] {country.upper()} failed: {exc}")
        return []


_merge_lock = Lock()


def run_all_sources_parallel(config: dict, args) -> dict:
    """
    Launch all independent data sources concurrently and return their results.

    TED index, UK scraper, and each national portal adapter run in separate
    threads.  Results are collected and returned; merging into relevant.json
    happens after the sequential filter step.
    """
    headless = not getattr(args, "visible", False)
    test_mode = args.test

    tasks: dict[str, callable] = {}

    # TED index is always included
    tasks["ted_index"] = lambda: run_phase_index(config, test_mode=test_mode,
                                                  date_from=getattr(args, "_date_from", None))

    # UK Contracts Finder
    if getattr(args, "uk", False):
        tasks["uk"] = lambda: run_phase_uk(config, test_mode=test_mode,
                                            date_from=getattr(args, "_date_from", None))

    # National portal adapters — one browser instance per country
    if args.national is not None:
        countries = args.national if args.national else list(get_adapter_registry().keys())
        for country in countries:
            c = country.lower()
            tasks[f"national_{c}"] = lambda _c=c: run_single_national_isolated(
                _c, config, test_mode=test_mode, headless=headless)

    max_workers = min(len(tasks), 6)
    print(f"\n  Launching {len(tasks)} source(s) in parallel (max {max_workers} threads)...")
    for name in tasks:
        print(f"    • {name}")

    results: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
                print(f"  [parallel] {name}: done")
            except Exception as exc:
                print(f"  [parallel] {name}: FAILED — {exc}")
                results[name] = []

    return results


def _merge_national_into_relevant(national_notices: list) -> int:
    """Append national Playwright-scraped notices to relevant.json with dedup."""
    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    existing: list = []
    if filtered_path.exists():
        with open(filtered_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    merged = merge_national_with_ted(existing, national_notices)

    filtered_path.parent.mkdir(parents=True, exist_ok=True)
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return len(merged)


def _run_ted_bulk_full(config: dict, test_mode: bool = False):
    """
    Full pipeline for TED Bulk trailer-CPV candidates:
    1. Load missing notices from data/raw/ted_bulk/missing_notices.json
    2. Filter to trailer CPV codes (34223xxx, 34221xxx, 354xxxx)
    3. Load detail files from cache (fetch missing ones via TED API)
    4. Run AI classifier (TwoStage) on uncached candidates
    5. Merge newly classified relevant notices into relevant.json

    Results in data/raw/ted_bulk/trailer_cpv_classified.json
    """
    print("\n" + "="*60)
    print("  TED BULK FULL RUN: Trailer-CPV Candidates")
    print("="*60)

    missing_path = PROJECT_ROOT / "data" / "raw" / "ted_bulk" / "missing_notices.json"
    if not missing_path.exists():
        print("  [!] No missing_notices.json found. Run --ted-bulk first.")
        return

    with open(missing_path, "r", encoding="utf-8") as f:
        missing = json.load(f)

    TRAILER_CPV_PREFIXES = ["34223", "34221", "35600", "35610", "35400"]
    candidates = [m for m in missing
                  if any(m.get("cpv", "").startswith(p) for p in TRAILER_CPV_PREFIXES)]

    if test_mode:
        candidates = candidates[:20]

    print(f"  Trailer-CPV candidates: {len(candidates)}")

    # Load from detail cache or fetch via API
    details_dir = PROJECT_ROOT / "data" / "raw" / "details"
    detail_notices = []
    need_fetch = []
    for c in candidates:
        tid = c.get("tender_id", "")
        safe = tid.replace("/", "_")
        p = details_dir / f"{safe}.json"
        if p.exists():
            detail = json.load(open(p, encoding="utf-8"))
            if not detail.get("tender_id"):
                detail["tender_id"] = tid
            detail_notices.append(detail)
        else:
            need_fetch.append(c)

    if need_fetch:
        print(f"  Fetching {len(need_fetch)} notices from TED API...")
        from src.api_client import TedApiClient, ALL_FIELDS
        import time
        client = TedApiClient(config)
        BATCH = 20
        for i in range(0, len(need_fetch), BATCH):
            batch = need_fetch[i:i + BATCH]
            ids = " OR ".join([f'publication-number="{s["tender_id"]}"' for s in batch])
            query = {"query": f"({ids})", "fields": ALL_FIELDS, "page": 1,
                     "limit": BATCH, "paginationMode": "PAGE_NUMBER"}
            resp = client.search(query, page=1)
            if resp and resp.get("notices"):
                for notice in resp["notices"]:
                    pub_num = notice.get("publication-number", "")
                    if pub_num:
                        safe = pub_num.replace("/", "_")
                        with open(details_dir / f"{safe}.json", "w", encoding="utf-8") as fp:
                            json.dump(notice, fp, ensure_ascii=False, indent=2)
                        notice["tender_id"] = pub_num
                        detail_notices.append(notice)
            time.sleep(0.5)

    print(f"  Total for classification: {len(detail_notices)}")

    # Run AI classifier
    from src.classifier import TwoStageClassifier
    classifier = TwoStageClassifier()
    if not classifier.is_available:
        print("  [!] LLM_OPENROUTER_API_KEY not set — skipping classification")
        return

    relevant_new = classifier.classify_batch(detail_notices, test_mode=test_mode)
    print(f"  Classified relevant: {len(relevant_new)}")

    # Save results
    out = PROJECT_ROOT / "data" / "raw" / "ted_bulk" / "trailer_cpv_classified.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(relevant_new, f, ensure_ascii=False, indent=2)

    # Merge into relevant.json (dedup by tender_id)
    filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
    existing = []
    if filtered_path.exists():
        with open(filtered_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    existing_ids = {n.get("tender_id") for n in existing}
    unique_new = {}
    for n in relevant_new:
        tid = n.get("tender_id", "")
        if tid and tid not in existing_ids and tid not in unique_new:
            unique_new[tid] = n

    merged = existing + list(unique_new.values())
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"  [OK] Merged {len(unique_new)} new notices into relevant.json "
          f"({len(existing)} → {len(merged)})")


def _reclassify_other():
    """Remove 'Other' category entries from the enrichment cache so they get re-classified."""
    log_path = PROJECT_ROOT / "data" / ".enrichment_log.json"
    relevant_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"

    if not log_path.exists():
        print("  [!] No enrichment log found.")
        return
    if not relevant_path.exists():
        print("  [!] No relevant.json found.")
        return

    with open(log_path, "r", encoding="utf-8") as f:
        log = json.load(f)
    with open(relevant_path, "r", encoding="utf-8") as f:
        relevant = json.load(f)

    other_ids = []
    for notice in relevant:
        cat = (notice.get("_trailer_category_1_ai")
               or notice.get("trailer_category_1")
               or (notice.get("_ai") or {}).get("trailer_category_1", ""))
        if cat == "Other":
            other_ids.append(notice.get("tender_id"))

    print(f"  Other notices to reclassify: {len(other_ids)}")
    removed = 0
    for tid in other_ids:
        if tid in log:
            del log[tid]
            removed += 1

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"  Removed {removed} entries from enrichment log.")
    print("  Now run: python main.py --phase classify")
    print("  Or:      python main.py --all --since <date> --two-stage")


def main():
    # PreCon: persistent run log — every print() and traceback ends up in
    # ``data/.run_log/<stamp>.log`` and is reachable via the ``latest.log``
    # symlink. Foundation for Health-Monitor (M1) + Diagnose-Engine (M2).
    _log_path = _setup_run_log(PROJECT_ROOT / "data" / ".run_log")
    if _log_path:
        try:
            _log_rel = _log_path.relative_to(PROJECT_ROOT)
        except ValueError:
            _log_rel = _log_path
        print(f"[run-log] {_log_rel}")

    parser = argparse.ArgumentParser(
        description="TED Defence Trailer Scraper Pipeline"
    )
    parser.add_argument(
        "--phase",
        choices=["index", "details", "filter", "classify", "export", "test-api"],
        help="Run a specific pipeline phase"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run the full pipeline (index → details → filter → classify → export)"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test mode: process only a small number of notices"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--clear-log", action="store_true",
        help="Clear the AI enrichment log (re-process all notices on next run)"
    )
    # Classifier mode flags
    parser.add_argument(
        "--two-stage", action="store_true",
        help="Use TwoStageClassifier (Haiku pre-filter + Sonnet full classification)"
    )
    parser.add_argument(
        "--parallel", action="store_true",
        help="[Kept for backward compat] Parallel AI calls are now the default"
    )
    parser.add_argument(
        "--sequential", action="store_true",
        help="Disable parallel AI calls and parallel source fetching (for debugging)"
    )
    parser.add_argument(
        "--batch", action="store_true",
        help="Use BatchClassifier (Anthropic Batches API, 50 pct cost reduction)"
    )
    # Incremental scraping flags
    parser.add_argument(
        "--since", metavar="YYYY-MM-DD",
        help="Only fetch notices published since this date (overrides config date_from)"
    )
    parser.add_argument(
        "--incremental", action="store_true",
        help="Auto-detect last run date from .last_run.json and use as --since"
    )
    # Enrichment flags
    parser.add_argument(
        "--enrich", action="store_true",
        help="[Deprecated — enrichment now runs by default] Kept for backward compatibility"
    )
    parser.add_argument(
        "--no-enrich", action="store_true",
        help="Skip fulltext enrichment and award-match (saves time/cost for quick runs)"
    )
    parser.add_argument(
        "--enrich-only", action="store_true",
        help="Skip Phases 1-3b, only run fulltext enrichment on existing data + export"
    )
    parser.add_argument(
        "--award-match", action="store_true",
        help="Run award notice matching step (Phase 3d) — runs by default with enrichment"
    )
    parser.add_argument(
        "--award-match-llm", action="store_true",
        help="Run LLM-based award matcher (Sonnet 4.6) on notices that the heuristic matcher could not match. Default off, manual trigger because of $-Kosten. ~USD 1-5 for ~150 candidates."
    )
    parser.add_argument(
        "--award-match-llm-sample",
        type=str,
        default=None,
        help="Comma-separated tender-IDs to limit the LLM matcher to. Useful for smoke tests, e.g. --award-match-llm-sample 572650-2024,...",
    )
    parser.add_argument(
        "--award-match-llm-dry-run", action="store_true",
        help="Run LLM matcher in dry-run mode (no API calls, just candidate selection + cost preview)",
    )
    parser.add_argument(
        "--award-match-llm-confidence", type=int, default=75,
        help="Minimum confidence (0-100) the LLM must report for a match to be applied. Default 75."
    )
    parser.add_argument(
        "--translate-titles", action="store_true",
        help="Translate every non-English _title_final to English via Claude "
             "Haiku 4.5. Writes title_en into relevant.json. Cache at "
             "data/.translation_cache.json. Cheap (~$0.10-0.30 for 300 tenders; "
             "often less because English titles pass through without API call)."
    )
    parser.add_argument(
        "--translate-titles-sample", type=str, default=None,
        help="Comma-separated tender-IDs to limit the title translator to "
             "(smoke test mode)."
    )
    parser.add_argument(
        "--translate-titles-dry-run", action="store_true",
        help="Decide which titles need translation but make NO API calls."
    )
    parser.add_argument(
        "--translate-descriptions", action="store_true",
        help="Phase 3e-2: Translate non-English description fields to English "
             "via Claude Sonnet 4.6. Writes description_en into relevant.json. "
             "Cache: data/.description_translation_cache.json. ~$0.50-1.50 for "
             "256 tenders (most hit cache on re-runs)."
    )
    parser.add_argument(
        "--translate-descriptions-sample", type=str, default=None,
        help="Comma-separated tender-IDs to limit the description translator "
             "(smoke test mode)."
    )
    parser.add_argument(
        "--translate-descriptions-dry-run", action="store_true",
        help="Decide which descriptions need translation but make NO API calls."
    )
    parser.add_argument(
        "--force-clean", action="store_true",
        help="Re-run Haiku cleaning for all RAW_ENGLISH descriptions, bypassing the "
             "clean-cache. Use after a full translate-descriptions run to re-clean "
             "notices whose description_en is boilerplate/verbose. "
             "~$0.10-0.30 for ~74 notices (Haiku 4.5)."
    )
    parser.add_argument(
        "--enrich-descriptions", action="store_true",
        help="Phase 3f: regex-based EUR-equivalent enrichment in description "
             "text (e.g. '123,293.66 CZK' → '123,293.66 CZK (~€4.9K)'). "
             "Pure regex + FX lookup — 0 USD, no LLM calls. Cache: "
             "data/.description_enrich_cache.json."
    )
    parser.add_argument(
        "--enrich-descriptions-sample", type=str, default=None,
        help="Comma-separated tender-IDs to limit the description enricher "
             "to (smoke test mode)."
    )
    parser.add_argument(
        "--enrich-descriptions-dry-run", action="store_true",
        help="Compute enrichment matches but do NOT write back to relevant.json."
    )
    parser.add_argument(
        "--reclassify-other", action="store_true",
        help="Remove 'Other' category notices from enrichment cache and re-classify them"
    )
    parser.add_argument(
        "--contract-type", action="store_true",
        help="Phase 3j: Classify contract type (framework_agreement / one_time / recurring) "
             "using multilingual regex. Writes _contract_type into relevant.json. Free/instant."
    )
    parser.add_argument(
        "--text-mine", action="store_true",
        help="Phase 3k: Multilingual regex text mining for quantity, delivery "
             "deadline, and contract duration from _description_final / "
             "_national_raw_text. Writes _qty_mined / _deadline_mined / "
             "_duration_months_mined into relevant.json. Free/instant. "
             "Cache: data/.text_mining_cache.json."
    )
    parser.add_argument(
        "--text-mine-sample", type=str, default=None,
        help="Comma-separated tender-IDs to limit text mining to (smoke test)."
    )
    parser.add_argument(
        "--text-mine-dry-run", action="store_true",
        help="Compute mining results but do NOT write back to relevant.json."
    )
    parser.add_argument(
        "--text-mine-force", action="store_true",
        help="Bypass the text-mining cache and re-mine the targeted notices."
    )
    parser.add_argument(
        "--url-check", action="store_true",
        help="Phase 3l: Probe every notice's source_url_national and attach "
             "_url_status (alive / dead / auth_walled / timeout). Cache 30-day TTL "
             "in data/.url_health_cache.json. Runs late in --all (after data prep, "
             "before Phase 4 export). Free/no LLM."
    )
    parser.add_argument(
        "--url-check-force", action="store_true",
        help="Bypass the 30-day URL health cache and re-probe every URL."
    )
    parser.add_argument(
        "--url-check-source", action="append", default=None,
        help="Limit URL check to a specific _source code (repeatable; "
             "e.g. --url-check-source AU-TEN --url-check-source EE-RP)."
    )
    parser.add_argument(
        "--extract-documents", action="store_true",
        help=(
            "Phase 3g: Download, extract, and AI-structure procurement documents. "
            "For TED notices: downloads the English PDF via links.pdf.ENG. "
            "For UA/Prozorro: re-fetches fresh time-signed document URLs. "
            "Extracts text (PDF/docx) and uses Sonnet 4.6 to parse trailer specs "
            "into _extracted_specs. Cache: data/.document_extraction_cache.json. "
            "Cost: ~$0.01 per notice processed."
        )
    )
    parser.add_argument(
        "--extract-documents-sample", type=str, default=None,
        help="Comma-separated tender-IDs to limit document extraction to (smoke test)."
    )
    parser.add_argument(
        "--extract-documents-dry-run", action="store_true",
        help="Discover + download documents but skip AI structuring (0 API cost)."
    )
    parser.add_argument(
        "--extract-documents-force", action="store_true",
        help="Re-process all notices even if cache hit."
    )
    parser.add_argument(
        "--strategy-a", action="store_true", dest="strategy_a",
        help="Strategy A: proactively scrape Vergabeunterlagen / SWZ / "
             "Zadávací dokumentace PDFs from DE/PL/CZ buyer portals. "
             "Reads buyer_profile_url from _xml or data/ted_xml_cache, "
             "downloads attached docs, AI-structures specs. Cache: "
             "data/.strategy_a_cache.json. NOT active in --all."
    )
    parser.add_argument(
        "--strategy-a-sample", type=str, default=None, dest="strategy_a_sample",
        help="Comma-separated tender-IDs to limit Strategy A to (smoke test)."
    )
    parser.add_argument(
        "--strategy-a-dry-run", action="store_true", dest="strategy_a_dry_run",
        help="Strategy A: discover + download + extract text, skip AI structuring."
    )
    parser.add_argument(
        "--strategy-a-force", action="store_true", dest="strategy_a_force",
        help="Strategy A: bypass cache and re-run every candidate."
    )
    parser.add_argument(
        "--no-fallback-cache", action="store_true",
        help=(
            "Bypass the national fallback cache (data/.national_fallback_cache.json). "
            "Forces fresh portal searches for DE/PL/CZ tenders with dead/missing URLs."
        )
    )
    # Additional sources
    parser.add_argument(
        "--uk", action="store_true",
        help="Include UK Contracts Finder data (runs alongside TED in --all, or UK-only when standalone)"
    )
    parser.add_argument(
        "--de", action="store_true",
        help="Include Germany service.bund.de data (RSS feed + detail pages, no login required)"
    )
    parser.add_argument(
        "--pl", action="store_true",
        help="Include Poland BZP data (searchbzp.uzp.gov.pl, 2017-2024 historic notices)"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Run Opus quality review on latest Excel export"
    )
    parser.add_argument(
        "--no-review", action="store_true", dest="no_review",
        help="Skip automatic Opus quality review after --all run"
    )
    # Playwright-based national portal scraping
    parser.add_argument(
        "--national", nargs="*", metavar="COUNTRY",
        help="Scrape national portals via Playwright (e.g. --national de pl)"
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Show browser window when using --national (default: headless)"
    )
    parser.add_argument(
        "--llm", choices=["openrouter"], default="openrouter",
        help="LLM backend (always openrouter — kept for script compatibility)."
    )
    parser.add_argument(
        "--validate-portals", nargs="*", metavar="COUNTRY",
        dest="validate_portals",
        help="Validate if national portals carry defence trailer tenders. "
             "Takes known TED tenders and searches for the same authorities on "
             "the national portal. E.g. --validate-portals de pl"
    )
    parser.add_argument(
        "--ted-bulk", action="store_true",
        help="Load TED Open Data CSV bulk dumps and find notices missing from our dataset"
    )
    parser.add_argument(
        "--ted-bulk-full", action="store_true",
        help="Classify all TED Bulk trailer-CPV candidates via AI and merge into dataset"
    )
    parser.add_argument(
        "--canada", action="store_true",
        help="Load Canadian DND procurement data from open.canada.ca Open Data"
    )
    parser.add_argument(
        "--export-frontend", action="store_true", dest="export_frontend",
        help="After Excel export, write shared/tenders.json for the defence-intel-web frontend"
    )

    args = parser.parse_args()

    # Ensure data directories exist
    (PROJECT_ROOT / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "filtered").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "export").mkdir(parents=True, exist_ok=True)

    setup_logging(args.verbose)
    config = load_config()

    print("\n" + "+" + "="*58 + "+")
    print("|  TED Defence Trailer Scraper                             |")
    print("|  Hybrid API + Filtering Pipeline                         |")
    print("+" + "="*58 + "+")

    if args.clear_log:
        from src.classifier import AiClassifier
        AiClassifier.clear_log()
        print("  [OK] AI enrichment log cleared. All notices will be re-processed on next run.")
        return

    # ── TED bulk CSV standalone mode ──
    if getattr(args, "ted_bulk", False) and not args.all and not args.phase:
        print("\n  Mode: TED BULK CSV (historical data comparison)")
        run_bulk_comparison(config, test_mode=args.test)
        return

    # ── TED bulk full run: classify all trailer-CPV candidates ──
    if getattr(args, "ted_bulk_full", False):
        print("\n  Mode: TED BULK FULL RUN (classify trailer-CPV candidates + merge)")
        _run_ted_bulk_full(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── Canada standalone mode ──
    if getattr(args, "canada", False) and not args.all and not args.phase:
        print("\n  Mode: CANADA OPEN DATA (DND procurement) → Excel export")
        from src.canada_loader import CanadaOpenDataLoader
        loader = CanadaOpenDataLoader(cache_dir=str(PROJECT_ROOT / "data" / "raw" / "canada"))
        canada_notices = loader.load_and_filter(test_mode=args.test)
        active_tenders = loader.load_active_tenders(test_mode=args.test)
        print(f"  [OK] Canada historical: {len(canada_notices)} contracts")
        print(f"  [OK] CanadaBuys active: {len(active_tenders)} tenders")
        if active_tenders:
            for t in active_tenders[:5]:
                title = t.get("_title_final","") or t.get("title","")
                print(f"    [{t.get('_pub_date','?')}] {title[:70]}")
        run_phase_export(config, test_mode=args.test, canada_notices=canada_notices)
        return

    # ── Portal validation mode ──
    if args.validate_portals is not None:
        countries = args.validate_portals if args.validate_portals else ["de", "pl"]
        headless = not args.visible
        print(f"\n  Mode: PORTAL VALIDATION — {', '.join(c.upper() for c in countries)}")
        from src.national_scraper.validate_portals import run_validation
        run_validation(countries, headless=headless)
        return

    # Resolve date_from for incremental/since
    date_from = None
    if args.incremental:
        last_run = load_last_run()
        if last_run.get("last_run_date"):
            date_from = last_run["last_run_date"]
            print(f"  --incremental: using last run date {date_from}")
        else:
            print("  --incremental: no .last_run.json found, running full scrape")
    elif args.since:
        date_from = args.since
        print(f"  --since: overriding date_from to {date_from}")

    # Store date_from on args so parallel helpers can access it
    args._date_from = date_from

    # ── reclassify-other mode ──
    if getattr(args, "reclassify_other", False):
        print("\n  Mode: RECLASSIFY-OTHER (removing 'Other' from cache → re-classify)")
        _reclassify_other()
        return

    # ── enrich-only mode ──
    if args.enrich_only:
        print("\n  Mode: ENRICH-ONLY (skipping phases 1-3b)")
        run_phase_enrich(config, test_mode=args.test)
        if not getattr(args, "no_enrich", False):
            run_phase_award_match(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── award-match standalone mode ──
    if args.award_match and not args.all and not args.phase:
        print("\n  Mode: AWARD-MATCH (on existing filtered data)")
        run_phase_award_match(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── award-match-llm standalone mode (Sprint Top-1 LLM upgrade) ──
    if args.award_match_llm and not args.all and not args.phase:
        sample_ids = None
        if args.award_match_llm_sample:
            sample_ids = [
                s.strip() for s in args.award_match_llm_sample.split(",") if s.strip()
            ]
        print("\n  Mode: AWARD-MATCH-LLM (Sonnet 4.6, on existing filtered data)")
        run_phase_award_match_llm(
            sample=sample_ids,
            dry_run=args.award_match_llm_dry_run,
            confidence_min=args.award_match_llm_confidence,
        )
        run_phase_export(config, test_mode=args.test)
        return

    # ── translate-titles standalone mode (Title-Translation Pass) ──
    if args.translate_titles and not args.all and not args.phase:
        sample_ids = None
        if args.translate_titles_sample:
            sample_ids = [
                s.strip() for s in args.translate_titles_sample.split(",") if s.strip()
            ]
        print("\n  Mode: TRANSLATE-TITLES (Haiku 4.5, on existing filtered data)")
        run_phase_translate_titles(
            sample=sample_ids,
            dry_run=args.translate_titles_dry_run,
        )
        run_phase_export(config, test_mode=args.test)
        return

    # ── translate-descriptions standalone mode (Sonnet description translation) ──
    if args.translate_descriptions and not args.all and not args.phase:
        sample_ids = None
        if args.translate_descriptions_sample:
            sample_ids = [
                s.strip() for s in args.translate_descriptions_sample.split(",") if s.strip()
            ]
        print("\n  Mode: TRANSLATE-DESCRIPTIONS (Sonnet 4.6 + Haiku 4.5 cleaning)")
        run_phase_translate_descriptions(
            sample=sample_ids,
            dry_run=args.translate_descriptions_dry_run,
            force_clean=args.force_clean,
        )
        run_phase_export(config, test_mode=args.test)
        return

    # ── enrich-descriptions standalone mode (regex + FX, no LLM) ──
    if args.enrich_descriptions and not args.all and not args.phase:
        sample_ids = None
        if args.enrich_descriptions_sample:
            sample_ids = [
                s.strip() for s in args.enrich_descriptions_sample.split(",") if s.strip()
            ]
        print("\n  Mode: ENRICH-DESCRIPTIONS (regex + FX, on existing filtered data)")
        run_phase_enrich_descriptions(
            sample=sample_ids,
            dry_run=args.enrich_descriptions_dry_run,
        )
        run_phase_export(config, test_mode=args.test)
        return

    # ── contract-type standalone mode ──
    if getattr(args, "contract_type", False) and not args.all and not args.phase:
        print("\n  Mode: CONTRACT-TYPE (regex classifier, on existing data)")
        run_phase_contract_type()
        run_phase_export(config, test_mode=args.test)
        return

    # ── text-mine standalone mode ──
    if getattr(args, "text_mine", False) and not args.all and not args.phase:
        sample_ids = None
        if getattr(args, "text_mine_sample", None):
            sample_ids = [
                s.strip() for s in args.text_mine_sample.split(",") if s.strip()
            ]
        print("\n  Mode: TEXT-MINE (Phase 3k, regex on existing data)")
        run_phase_text_mining(
            sample=sample_ids,
            dry_run=getattr(args, "text_mine_dry_run", False),
            force=getattr(args, "text_mine_force", False),
        )
        run_phase_export(config, test_mode=args.test)
        return

    # ── url-check standalone mode (Phase 3l) ──
    if getattr(args, "url_check", False) and not args.all and not args.phase:
        print("\n  Mode: URL-CHECK (Phase 3l, HEAD-probe source_url_national)")
        run_phase_url_validation(
            force=getattr(args, "url_check_force", False),
            only_sources=getattr(args, "url_check_source", None),
        )
        run_phase_export(config, test_mode=args.test)
        return

    # ── strategy-a standalone mode (DE/PL/CZ Vergabeunterlagen scraping) ──
    if getattr(args, "strategy_a", False) and not args.all and not args.phase:
        sample_ids = None
        if getattr(args, "strategy_a_sample", None):
            sample_ids = [
                s.strip() for s in args.strategy_a_sample.split(",") if s.strip()
            ]
        print("\n  Mode: STRATEGY-A (national-portal Vergabeunterlagen scraping)")
        run_phase_strategy_a(
            sample=sample_ids,
            dry_run=getattr(args, "strategy_a_dry_run", False),
            force=getattr(args, "strategy_a_force", False),
            test_mode=args.test,
        )
        return

    # ── extract-documents standalone mode ──
    if getattr(args, "extract_documents", False) and not args.all and not args.phase:
        sample_ids = None
        if getattr(args, "extract_documents_sample", None):
            sample_ids = [
                s.strip() for s in args.extract_documents_sample.split(",") if s.strip()
            ]
        print("\n  Mode: EXTRACT-DOCUMENTS (Phase 3g, on existing filtered data)")
        run_phase_extract_documents(
            sample=sample_ids,
            dry_run=getattr(args, "extract_documents_dry_run", False),
            force=getattr(args, "extract_documents_force", False),
            test_mode=args.test,
            no_fallback_cache=getattr(args, "no_fallback_cache", False),
        )
        return

    # ── --national standalone mode (Playwright-based) ──
    if args.national is not None and not args.all and not args.phase:
        countries = args.national if args.national else ["de", "pl"]  # default: all
        headless = not args.visible
        print(f"\n  Mode: NATIONAL PORTAL (Playwright) — {', '.join(c.upper() for c in countries)}")
        nat_notices = run_national_scraping(
            countries=countries,
            config=config,
            test_mode=args.test,
            headless=headless,
        )
        print(f"\n  National notices found: {len(nat_notices)}")
        if nat_notices:
            total = _merge_national_into_relevant(nat_notices)
            print(f"  relevant.json after merge: {total} notices")
            run_phase_translate_titles()
            run_phase_translate_descriptions(force_clean=args.force_clean)
            run_phase_contract_type()
            run_phase_export(config, test_mode=args.test)
        return

    # ── UK-only standalone mode (--uk without --all, --phase, --enrich-only) ──
    if args.uk and not args.all and not args.phase and not args.de and not args.pl:
        print("\n  Mode: UK-ONLY (UK fetch -> merge -> classify -> export)")
        uk_notices = run_phase_uk(config, test_mode=args.test, date_from=date_from)
        total = _merge_uk_into_relevant(uk_notices)
        print(f"  relevant.json after merge: {total} notices")
        run_phase_classify(config, test_mode=args.test, args=args)
        run_phase_export(config, test_mode=args.test)
        if args.review:
            run_review(config)
        return

    # ── DE standalone mode ──
    if args.de and not args.all and not args.phase:
        print("\n  Mode: DE-ONLY (service.bund.de -> merge -> export)")
        run_phase_de(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── PL standalone mode ──
    if args.pl and not args.all and not args.phase and not args.de:
        print("\n  Mode: PL-ONLY (BZP -> merge -> export)")
        run_phase_pl(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── DE + PL combined standalone ──
    if (args.de or args.pl) and not args.all and not args.phase:
        print("\n  Mode: DE+PL (service.bund.de + BZP -> merge -> export)")
        if args.de:
            run_phase_de(config, test_mode=args.test)
        if args.pl:
            run_phase_pl(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── Single phase ──
    if args.phase == "test-api":
        run_api_test(config)
    elif args.phase == "index":
        run_phase_index(config, test_mode=args.test, date_from=date_from)
    elif args.phase == "details":
        run_phase_details(config, test_mode=args.test)
    elif args.phase == "filter":
        run_phase_filter(config)
    elif args.phase == "classify":
        run_phase_classify(config, test_mode=args.test, args=args)
    elif args.phase == "export":
        run_phase_export(config, test_mode=args.test)
        if getattr(args, "export_frontend", False):
            run_frontend_export()

    # ── Full pipeline ──
    elif args.all:
        sequential = getattr(args, "sequential", False)

        if sequential:
            # ── Sequential fallback (original behaviour) ──
            print("\n  Mode: SEQUENTIAL (--sequential flag set)")
            with Timer("Phase 1+2: TED Index"):
                run_phase_index(config, test_mode=args.test, date_from=date_from)
                run_phase_details(config, test_mode=args.test)
            with Timer("Phase 3: Filter"):
                run_phase_filter(config)
            with Timer("Phase 3: Award Cache Restore"):
                _run_merge_cached_awards()
            if args.uk:
                with Timer("Source: UK Contracts Finder"):
                    uk_notices = run_phase_uk(config, test_mode=args.test, date_from=date_from)
                    total = _merge_uk_into_relevant(uk_notices)
                    print(f"  relevant.json after UK merge: {total} notices")
            if args.de:
                with Timer("Source: DE service.bund.de"):
                    run_phase_de(config, test_mode=args.test)
            if args.pl:
                with Timer("Source: PL BZP"):
                    run_phase_pl(config, test_mode=args.test)
            if args.national is not None:
                countries = args.national if args.national else list(get_adapter_registry().keys())
                headless = not args.visible
                with Timer(f"Source: National ({', '.join(c.upper() for c in countries)})"):
                    nat_notices = run_national_scraping(
                        countries=countries, config=config,
                        test_mode=args.test, headless=headless)
                    if nat_notices:
                        total = _merge_national_into_relevant(nat_notices)
                        print(f"  relevant.json after national merge: {total} notices")
        else:
            # ── Parallel source fetching ──
            print("\n  Mode: PARALLEL (sources run concurrently)")
            with Timer("Phase 1: All Sources (parallel)"):
                source_results = run_all_sources_parallel(config, args)

            # UK results come back as raw notices — merge after filter
            uk_notices_parallel = source_results.get("uk") or []

            # National results: one key per country
            nat_notices_parallel = []
            for key, val in source_results.items():
                if key.startswith("national_") and val:
                    nat_notices_parallel.extend(val)

            with Timer("Phase 3: Filter"):
                run_phase_filter(config)
            with Timer("Phase 3: Award Cache Restore"):
                _run_merge_cached_awards()

            # Merge non-TED sources into relevant.json (sequential — one writer at a time)
            if uk_notices_parallel:
                total = _merge_uk_into_relevant(uk_notices_parallel)
                print(f"  relevant.json after UK merge: {total} notices")
            if args.de:
                with Timer("Source: DE service.bund.de"):
                    run_phase_de(config, test_mode=args.test)
            if args.pl:
                with Timer("Source: PL BZP"):
                    run_phase_pl(config, test_mode=args.test)
            if nat_notices_parallel:
                total = _merge_national_into_relevant(nat_notices_parallel)
                print(f"  relevant.json after national merge: {total} notices")

        with Timer("Phase 3b: AI Classify"):
            run_phase_classify(config, test_mode=args.test, args=args)

        # ── Persist all relevant national IDs for future runs ──
        filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
        if filtered_path.exists():
            with open(filtered_path, "r", encoding="utf-8") as _f:
                _classified = json.load(_f)
            update_national_force_include(_classified)

        # Title translation pass — runs before Award-Match so the LLM
        # matcher sees English titles for better cross-language matching.
        with Timer("Phase 3e: Title Translation"):
            run_phase_translate_titles()

        # Description translation — Sonnet translates non-English descriptions
        # into English prose. Must run BEFORE currency enrichment so the
        # enricher annotates the English description_en, not the source language.
        with Timer("Phase 3e-2: Description Translation + Cleaning"):
            run_phase_translate_descriptions(force_clean=args.force_clean)

        # Text mining — multilingual regex over description_en + raw text to
        # extract qty / delivery-deadline / contract-duration. Runs AFTER
        # translation (English description_en is the strongest mining target)
        # and BEFORE document extraction so Phase 3g can audit whether the
        # document-derived qty matches the mined qty.
        with Timer("Phase 3k: Text Mining"):
            run_phase_text_mining(force=getattr(args, "text_mine_force", False))

        # Description currency enrichment — pure regex + FX lookup, free.
        # Runs after Translate so non-English numeric formats (e.g. CZ
        # ``"123,293.66 CZK"``) are surfaced in their already-translated
        # English description text. Runs before Award-Match-LLM so the
        # Sonnet reasoner sees EUR equivalents in the candidate context.
        with Timer("Phase 3f: Description Currency Enrichment"):
            run_phase_enrich_descriptions()

        # Contract type classification — regex-based, free, instant
        with Timer("Phase 3j: Contract Type"):
            run_phase_contract_type(force=getattr(args, "force_clean", False))

        # URL health check — HEAD-probe source_url_national, attach
        # _url_status so the exporter / frontend can hide / warn on dead links.
        # 30-day cache TTL means full-run cost is ~3 min once, then ~0 s.
        # Placed here (after data prep, before Phase 4 export) so the field
        # propagates into tenders.json on the same run.
        with Timer("Phase 3l: URL Health Check"):
            run_phase_url_validation(
                force=getattr(args, "url_check_force", False),
                only_sources=getattr(args, "url_check_source", None),
            )

        # Document extraction — only runs when --extract-documents is passed
        # (opt-in: can add ~15 min and $0.05–0.50 depending on notice count).
        if getattr(args, "extract_documents", False):
            with Timer("Phase 3g: Document Extraction"):
                run_phase_extract_documents(
                    dry_run=getattr(args, "extract_documents_dry_run", False),
                    force=getattr(args, "extract_documents_force", False),
                    test_mode=args.test,
                    no_fallback_cache=getattr(args, "no_fallback_cache", False),
                )

        if not getattr(args, "no_enrich", False):
            with Timer("Phase 3c: Fulltext Enrich"):
                run_phase_enrich(config, test_mode=args.test)
            with Timer("Phase 3d: Award Match"):
                run_phase_award_match(config, test_mode=args.test)
            with Timer("Phase 3d-LLM: Award Match (cache)"):
                run_phase_award_match_llm(confidence_min=65)
        elif args.award_match:
            with Timer("Phase 3d: Award Match"):
                run_phase_award_match(config, test_mode=args.test)
            with Timer("Phase 3d-LLM: Award Match (cache)"):
                run_phase_award_match_llm(confidence_min=65)

        # ── Restore force-included national notices missing this run ──
        if filtered_path.exists():
            with open(filtered_path, "r", encoding="utf-8") as _f:
                _current = json.load(_f)
            _restored = ensure_force_includes(_current)
            if len(_restored) > len(_current):
                with open(filtered_path, "w", encoding="utf-8") as _f:
                    json.dump(_restored, _f, ensure_ascii=False, indent=2)

        # ── Canada historical data ──
        canada_notices = []
        if getattr(args, "canada", False):
            with Timer("Source: Canada Open Data"):
                from src.canada_loader import CanadaOpenDataLoader
                loader = CanadaOpenDataLoader(
                    cache_dir=str(PROJECT_ROOT / "data" / "raw" / "canada"))
                canada_notices = loader.load_and_filter(test_mode=args.test)
                print(f"  [OK] Canada (Historical): {len(canada_notices)} contracts")

        with Timer("Phase 4: Export"):
            run_phase_export(config, test_mode=args.test, canada_notices=canada_notices)

        if getattr(args, "export_frontend", False):
            run_frontend_export()

        # Auto-run Opus review after --all (unless --no-review or test mode)
        run_opus = (
            args.review or
            (args.all and not args.test and not getattr(args, "no_review", False))
        )
        if run_opus:
            with Timer("Phase 5: Quality Review"):
                run_review(config)

        # Save last run
        filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
        if filtered_path.exists():
            with open(filtered_path, "r", encoding="utf-8") as f:
                notices = json.load(f)
            save_last_run(notices_processed=len(notices))
            print(f"\n  [OK] Saved .last_run.json ({len(notices)} notices processed)")

        _print_timing_summary()
        print("\n  [OK] Full pipeline complete!")
    else:
        parser.print_help()
        print("\n  Tip: Start with --phase test-api to verify connectivity")


if __name__ == "__main__":
    main()

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
import sys
import yaml
from pathlib import Path
from datetime import datetime, date

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

# Alias: LLM_ANTHROPIC_API_KEY → ANTHROPIC_API_KEY (used by classifier, enricher, quality_review)
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("LLM_ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["LLM_ANTHROPIC_API_KEY"]

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
from src.classifier import AiClassifier, TwoStageClassifier, ParallelClassifier, BatchClassifier, OpenRouterClassifier
from src.uk_scraper import UKContractsFinderScraper

LAST_RUN_PATH = PROJECT_ROOT / "data" / ".last_run.json"


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


def run_phase_filter(config: dict):
    """Phase 3: Filter and score notices."""
    print("\n" + "="*60)
    print("  PHASE 3: Filtering & Scoring")
    print("="*60)

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
    """Build the appropriate classifier based on CLI flags."""
    # OpenRouter backend (--llm openrouter) — inactive by default, quality not yet validated
    if getattr(args, "llm", "anthropic") == "openrouter":
        print("  Using OpenRouterClassifier (LLM_MODEL_NAME from .env — EXPERIMENTAL)")
        return OpenRouterClassifier()

    if args.batch:
        print("  Using BatchClassifier (50% discount via Batches API)")
        return BatchClassifier()
    elif args.two_stage:
        print("  Using TwoStageClassifier (Haiku pre-filter + Sonnet)")
        cls = TwoStageClassifier()
        if args.parallel:
            print("  Wrapping with ParallelClassifier")
            return ParallelClassifier(cls)
        return cls
    elif args.parallel:
        print("  Using ParallelClassifier")
        base = AiClassifier()
        return ParallelClassifier(base)
    else:
        return AiClassifier()


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
        print("  [!] Skipped: ANTHROPIC_API_KEY not set")
        print("  Set: $env:ANTHROPIC_API_KEY = \"sk-ant-...\"")
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
        print("  [!] Skipped: ANTHROPIC_API_KEY not set")
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

    added = 0
    enriched = 0
    for nat in national_notices:
        key = _dedup_key(nat)
        if key in ted_index and key.strip("|").strip():
            _enrich_from_national(ted_index[key], nat)
            enriched += 1
        else:
            merged.append(nat)
            added += 1

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
        print("  [!] ANTHROPIC_API_KEY not set; skipping review.")
        return

    print(f"  Reviewing: {latest.name}")
    result = reviewer.review(latest)
    if not result:
        print("  [!] Quality review returned no result.")
        return

    summary = result.get("summary", {})
    print(f"  [OK] Reviewed {summary.get('total_rows', '?')} rows, "
          f"{summary.get('issues_found', '?')} issues flagged")
    print(f"  Saved: data/quality_review.json")


def run_phase_export(config: dict, test_mode: bool = False):
    """Phase 4: Excel export."""
    print("\n" + "="*60)
    print("  PHASE 4: Excel Export")
    print("="*60)

    exporter = ExcelExporter(config)
    path = exporter.export(
        filtered_dir=str(PROJECT_ROOT / "data" / "filtered"),
        test_mode=test_mode
    )

    if path:
        print(f"\n  [OK] Excel exported: {path}")
        print(f"  Template: Vorlage.xlsx (Scraper Data)")
        print(f"  Format: Defence-only, deduplicated, 14 columns, English")
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
        from src.national_scraper.adapters.no_adapter import NOAdapter, create_no_config
        adapter_registry["no"] = (NOAdapter, create_no_config)
    except ImportError:
        pass
    try:
        from src.national_scraper.adapters.cz_adapter import CZAdapter, create_cz_config
        adapter_registry["cz"] = (CZAdapter, create_cz_config)
    except ImportError:
        pass

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

            # Fetch details
            notices = []
            detail_limit = 3 if test_mode else len(defence)
            for i, result in enumerate(defence[:detail_limit]):
                print(f"    [{i+1}/{min(detail_limit, len(defence))}] {result.title[:60]}")
                detail = adapter.get_detail(result)
                if detail:
                    notice = adapter.to_standard_format(detail)
                    notices.append(notice)

            print(f"  Detailed notices:    {len(notices)}")
            all_notices.extend(notices)

    return all_notices


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


def main():
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
        help="Use ParallelClassifier (5 concurrent requests with retry + jitter)"
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
        help="Add fulltext enrichment step (Phase 3c) after AI classification"
    )
    parser.add_argument(
        "--enrich-only", action="store_true",
        help="Skip Phases 1-3b, only run fulltext enrichment on existing data + export"
    )
    parser.add_argument(
        "--award-match", action="store_true",
        help="Run award notice matching step (Phase 3d)"
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
        "--llm", choices=["anthropic", "openrouter"], default="anthropic",
        help="LLM backend for classification: 'anthropic' (default, Claude) or "
             "'openrouter' (uses LLM_OPENROUTER_API_KEY + LLM_MODEL_NAME from .env). "
             "NOT ACTIVE yet — validate quality before switching."
    )
    parser.add_argument(
        "--validate-portals", nargs="*", metavar="COUNTRY",
        dest="validate_portals",
        help="Validate if national portals carry defence trailer tenders. "
             "Takes known TED tenders and searches for the same authorities on "
             "the national portal. E.g. --validate-portals de pl"
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

    # ── enrich-only mode ──
    if args.enrich_only:
        print("\n  Mode: ENRICH-ONLY (skipping phases 1-3b)")
        run_phase_enrich(config, test_mode=args.test)
        if args.award_match or args.enrich:
            run_phase_award_match(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        return

    # ── award-match standalone mode ──
    if args.award_match and not args.all and not args.phase:
        print("\n  Mode: AWARD-MATCH (on existing filtered data)")
        run_phase_award_match(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
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

    # ── Full pipeline ──
    elif args.all:
        run_phase_index(config, test_mode=args.test, date_from=date_from)
        run_phase_details(config, test_mode=args.test)
        run_phase_filter(config)
        if args.uk:
            uk_notices = run_phase_uk(config, test_mode=args.test, date_from=date_from)
            total = _merge_uk_into_relevant(uk_notices)
            print(f"  relevant.json after UK merge: {total} notices")
        if args.de:
            run_phase_de(config, test_mode=args.test)
        if args.pl:
            run_phase_pl(config, test_mode=args.test)
        if args.national is not None:
            countries = args.national if args.national else ["de", "pl"]
            headless = not args.visible
            nat_notices = run_national_scraping(
                countries=countries, config=config,
                test_mode=args.test, headless=headless)
            if nat_notices:
                total = _merge_national_into_relevant(nat_notices)
                print(f"  relevant.json after national merge: {total} notices")
        run_phase_classify(config, test_mode=args.test, args=args)
        if args.enrich:
            run_phase_enrich(config, test_mode=args.test)
        if args.award_match or args.enrich:
            run_phase_award_match(config, test_mode=args.test)
        run_phase_export(config, test_mode=args.test)
        if args.review:
            run_review(config)

        # Save last run
        filtered_path = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
        if filtered_path.exists():
            with open(filtered_path, "r", encoding="utf-8") as f:
                notices = json.load(f)
            save_last_run(notices_processed=len(notices))
            print(f"\n  [OK] Saved .last_run.json ({len(notices)} notices processed)")

        print("\n  [OK] Full pipeline complete!")
    else:
        parser.print_help()
        print("\n  Tip: Start with --phase test-api to verify connectivity")


if __name__ == "__main__":
    main()

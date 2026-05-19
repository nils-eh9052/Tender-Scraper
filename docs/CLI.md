# CLI Reference

Generated from `python main.py --help`.

```
usage: main.py [-h] [--phase {index,details,filter,classify,export,test-api}]
               [--all] [--test] [--verbose] [--clear-log] [--two-stage]
               [--parallel] [--sequential] [--batch] [--since YYYY-MM-DD]
               [--incremental] [--enrich] [--no-enrich] [--enrich-only]
               [--award-match] [--reclassify-other] [--uk] [--de] [--pl]
               [--review] [--no-review] [--national [COUNTRY ...]] [--visible]
               [--llm {anthropic,openrouter}]
               [--validate-portals [COUNTRY ...]] [--ted-bulk]
               [--ted-bulk-full] [--canada]

TED Defence Trailer Scraper Pipeline

options:
  -h, --help            show this help message and exit
  --phase {index,details,filter,classify,export,test-api}
                        Run a specific pipeline phase
  --all                 Run the full pipeline (index → details → filter →
                        classify → export)
  --test                Test mode: process only a small number of notices
  --verbose, -v         Enable debug logging
  --clear-log           Clear the AI enrichment log (re-process all notices on
                        next run)
  --two-stage           Use TwoStageClassifier (Haiku pre-filter + Sonnet full
                        classification)
  --parallel            [Kept for backward compat] Parallel AI calls are now
                        the default
  --sequential          Disable parallel AI calls and parallel source fetching
                        (for debugging)
  --batch               Use BatchClassifier (Anthropic Batches API, 50 pct
                        cost reduction)
  --since YYYY-MM-DD    Only fetch notices published since this date
                        (overrides config date_from)
  --incremental         Auto-detect last run date from .last_run.json and use
                        as --since
  --enrich              [Deprecated — enrichment now runs by default] Kept for
                        backward compatibility
  --no-enrich           Skip fulltext enrichment and award-match (saves
                        time/cost for quick runs)
  --enrich-only         Skip Phases 1-3b, only run fulltext enrichment on
                        existing data + export
  --award-match         Run award notice matching step (Phase 3d) — runs by
                        default with enrichment
  --award-match-llm     Phase 3d-LLM: Sonnet 4.6 reasoning-based award matcher
                        for tenders the heuristic matcher could not match.
                        OFF by default (manual trigger because of $-Kosten).
                        Cost: ~USD 0.20 for ~150 unmatched candidates.
                        Cache: data/.award_match_llm_log.json — re-runs are
                        free.
  --award-match-llm-sample <id1,id2,…>
                        Restrict the LLM matcher to specific tender-IDs.
                        Useful for smoke tests:
                          --award-match-llm
                          --award-match-llm-sample 572650-2024,...
  --award-match-llm-dry-run
                        Run the LLM matcher in dry-run mode: select
                        candidates and print plan, but make NO API calls.
  --award-match-llm-confidence <int>
                        Minimum confidence (0–100) at which an LLM match is
                        applied. Default 75.
  --translate-titles    Phase 3e: Title-Translation Pass via Claude Haiku 4.5.
                        For every notice in relevant.json without an English
                        _title_final, write a concise English `title_en`.
                        Heuristic skips already-English titles (no API call).
                        Cache: data/.translation_cache.json — re-runs hit
                        cache for every entry. Cost: ~$0.05 for 300 tenders.
  --translate-titles-sample <id1,id2,…>
                        Restrict the translator to specific tender-IDs (smoke).
  --translate-titles-dry-run
                        Plan candidate translations without making API calls.
  --translate-descriptions
                        Phase 3e-2: Description Translation via Claude Sonnet
                        4.6. For each notice in relevant.json: picks the best
                        source description (``_description_final → description
                        → _raw.description``), checks if English, and if not
                        sends it to Sonnet with an instruction to translate +
                        summarise into max. 4 clear English sentences. Writes
                        ``description_en`` into relevant.json.
                        Cache: data/.description_translation_cache.json.
                        Cache-key includes sha1(source) so invalidates on
                        content change. Cost: ~$0.15 for 256 tenders on first
                        run; subsequent runs hit cache (≈$0).
  --translate-descriptions-sample <id1,id2,…>
                        Restrict the description translator to specific IDs.
  --translate-descriptions-dry-run
                        Plan candidate translations without making API calls.
  --enrich-descriptions Phase 3f: regex + FX-Lookup. Sucht im
                        ``description``-Feld jeder Notice nach
                        ``<amount> <currency>`` und hängt EUR-Equivalent in
                        Klammern an, z.B.
                        ``"123,293.66 CZK"`` → ``"123,293.66 CZK (~€4.9K)"``.
                        Pure Regex, 0 USD, idempotent. Cache:
                        data/.description_enrich_cache.json.
  --enrich-descriptions-sample <id1,id2,…>
                        Restrict enrichment to specific tender-IDs (smoke).
  --enrich-descriptions-dry-run
                        Compute matches but skip writing back to relevant.json.
  --reclassify-other    Remove 'Other' category notices from enrichment cache
                        and re-classify them
  --extract-documents   Phase 3g: Download procurement documents (TED ENG PDF,
                        UA Prozorro docx), extract text (pdfplumber/python-docx,
                        Vision fallback for scans), AI-structure specs into
                        _extracted_specs. Default model: gpt-4o via OpenRouter
                        (F1=0.911). Override: EXTRACTION_MODEL env var.
                        Opt-in: not part of --all unless flag is passed.
                        Cache key: "{tender_id}:{model_slug}" — model change
                        forces fresh calls automatically.
                        Cache: data/.document_extraction_cache.json.
                        Cost: ~$0.0065 per notice (gpt-4o); Vision: ~$0.005/page.
                        Fallback: Sonnet 4.6 on OpenRouter error (auto).
  EXTRACTION_MODEL      Env var: override the extraction model for --extract-documents.
                        Examples:
                          EXTRACTION_MODEL=openrouter/openai/gpt-4o       (default)
                          EXTRACTION_MODEL=anthropic/claude-sonnet-4-6    (Sonnet)
                          EXTRACTION_MODEL=openrouter/mistralai/mistral-large
  --extract-documents-sample <id1,id2,…>
                        Restrict document extraction to specific tender-IDs.
  --extract-documents-dry-run
                        Discover + download docs, but skip AI structuring (0 USD).
  --extract-documents-force
                        Re-process all notices even if cache hit.
  --uk                  Include UK Contracts Finder data (runs alongside TED
                        in --all, or UK-only when standalone)
  --de                  Include Germany service.bund.de data (RSS feed +
                        detail pages, no login required)
  --pl                  Include Poland BZP data (searchbzp.uzp.gov.pl,
                        2017-2024 historic notices)
  --review              Run Opus quality review on latest Excel export
  --no-review           Skip automatic Opus quality review after --all run
  --national [COUNTRY ...]
                        Scrape national portals via Playwright (e.g.
                        --national de pl)
                        Available: se no cz fr dk nl es it ch de-ev gb ua ee lv lt
                                   be fi ro pl gr
  --visible             Show browser window when using --national (default:
                        headless)
  --llm {anthropic,openrouter}
                        LLM backend for classification: 'anthropic' (default,
                        Claude) or 'openrouter' (uses LLM_OPENROUTER_API_KEY +
                        LLM_MODEL_NAME from .env). NOT ACTIVE yet — validate
                        quality before switching.
  --validate-portals [COUNTRY ...]
                        Validate if national portals carry defence trailer
                        tenders. Takes known TED tenders and searches for the
                        same authorities on the national portal.
  --ted-bulk            Load TED Open Data CSV bulk dumps and find notices
                        missing from our dataset
  --ted-bulk-full       Classify all TED Bulk trailer-CPV candidates via AI
                        and merge into dataset
  --canada              Load Canadian DND procurement data from open.canada.ca
                        Open Data
  --export-frontend     After Excel export, write shared/tenders.json for the
                        defence-intel-web frontend (../../shared/tenders.json
                        relative to scraper root). Creates shared/ if absent.
```

## Frontend Export

Writes `../../shared/tenders.json` in the JSON schema expected by defence-intel-web.
Can be run standalone or appended to any export phase:

```bash
# Re-export Excel + write frontend JSON in one step
python main.py --phase export --export-frontend

# Combined with a full pipeline run
python main.py --all --two-stage --export-frontend

# Standalone (no Excel, no API calls)
python -m src.exporter_frontend
```

Field mapping highlights (see `shared/README.md` for full table):
- `source`: defensive rule — TED-pattern ID (`\d+-\d{4}`) → `"TED"`, else `"National"`
- `country` / `country_code`: resolved from `_country_normalized`, then `contracting_authority.country`, then `_raw.organisation-country-buyer`
- `estimated_value_eur`: converted from `estimated_value.amount` using fixed FX rates when `_value_eur_num` is absent

## Common Workflows

```bash
# Weekly incremental update (~5 min, ~$0.10)
python main.py --all --incremental --two-stage

# Full re-run with all sources (~25 min warm, ~$2)
python main.py --all --national se no cz fr dk nl es it ch gb ua ee lv lt --uk --canada --two-stage

# Re-export only (no API calls)
python main.py --phase export

# Fix 'Other' category notices
python main.py --reclassify-other --phase classify

# Run only Czech and French portals
python main.py --national cz fr

# Debug with visible browser
python main.py --national cz --visible --test
```

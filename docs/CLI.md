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
  --reclassify-other    Remove 'Other' category notices from enrichment cache
                        and re-classify them
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
```

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

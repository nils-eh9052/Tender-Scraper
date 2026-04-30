# Sprint 10 Summary — Adapter Fixes + Timeout Resilience
**Date:** 2026-04-30  
**Branch:** `sprint10/adapter-fixes`  
**Run:** `data/sprint10_run.log` → `data/export/260430_TED_Tender Data_00.01.xlsx`

---

## Goals & Outcomes

| Task | Goal | Result |
|------|------|--------|
| Task 0: Resilience Layer | `resilience.py` RetrySession + `core.py` goto retry + `main.py` graceful degradation | ✅ Done |
| Task 1: UK-FTS | Continue-on-timeout instead of break | ✅ Code fixed — FTS API cursor still broken at page 5 |
| Task 2: UA Prozorro | Increase detail_limit 200→500 | ✅ Done — **first ever UA result** |
| Task 3: CH simap.ch | Expand keywords + authority sweeps | ✅ Done — still 0 relevant (no active trailer tenders) |
| Task 4: DE-EV credentials | Diagnose 0 results | ✅ Confirmed correct (CPV too broad, non-trailer) |
| IT ANAC URL fix | Fix malformed hrefs from Liferay CMS | ✅ Bonus fix — `_fix_anac_url()` helper |

---

## Pipeline Results

### Source Breakdown (relevant.json after run)

| Source | Notices |
|--------|---------|
| TED | 194 |
| CZ-NEN | 32 |
| FR-BOAMP | 13 |
| UK-CF | 6 |
| NO-Doffin | 3 |
| NL-TenderNed | 1 |
| UA-Prozorro | **1 (NEW)** |
| **Total** | **250** |

**+1 vs Sprint 9b (249)** — one new Ukrainian notice added.

### Adapter Raw Results (national scraper phase)

| Adapter | Candidates | Notes |
|---------|-----------|-------|
| CZ | 150 (capped, 216 found) | Playwright, slowest (~28 min) |
| FR | 40 | |
| NL | 86 | |
| NO | 7 | |
| SE | 8 | |
| CH | 29 | Defence candidates, 0 trailer match |
| DE-EV | 22 | Non-trailer |
| IT | 8 | URL fix working |
| ES | 1 | |
| UA | 1 | **MATCH: Напівпричіп трал в/п 30-50 т** |
| DK | 2 | |
| UK-FTS | 0 | Cursor timeout at page 5, see below |
| UK-CF | 6 (cached) | |

### Classification (Phase 3b)

- Input: 8,130 notices (7,698 TED + 432 national)
- From cache: 245 (3%)
- AI calls: 18
- **Output: 247 relevant** (+ 3 force-included = 250 total)
- Runtime: 41.4s (TwoStageClassifier, 5 workers)

### Excel Export

- `data/export/260430_TED_Tender Data_00.01.xlsx`
- Scraper Data sheet: **230 rows** (250 − ~20 filtered by export rules)
- Canada (Historical): 604 contracts
- Total runtime: 2638.5s (43.9 min)

---

## New Code (Sprint 10)

### `src/national_scraper/resilience.py` (NEW)

```
RetrySession:
  - max_retries=3, backoff_base=2.0
  - Rotating user agents (8 pool)
  - Auto-retry on 429/500/502/503/504
  - Exponential backoff + jitter
  
retry_request():  convenience function
```

### `src/national_scraper/core.py`

- `goto()` now has `max_retries=2` with `2^attempt` backoff
- Page-closed recovery preserved (immediate, no retry loop)

### `main.py`

- `results[name] = []` on adapter failure (was `None`, caused downstream TypeError)

### `src/national_scraper/adapters/uk_fts_adapter.py`

- Uses `RetrySession` (max_retries=3)
- `max_pages`: 200 → 20 (cursor timeouts make deep pagination impractical)
- Pagination: `consecutive_errors` counter (max=5), `continue` instead of `break` on timeout

### `src/national_scraper/adapters/ua_adapter.py`

- Uses `RetrySession`
- `detail_limit`: 200 → 500

### `src/national_scraper/adapters/ch_adapter.py`

- Uses `RetrySession`
- Keywords expanded: `Tiefladeanhänger`, `Abrollbehälter`, `Munitionsanhänger`, `Panzertransportanhänger`, `remorque plateforme`
- Authority sweeps: added `Logistikbasis der Armee`, `VBS DDPS` alongside `armasuisse`

### `src/national_scraper/adapters/it_adapter.py`

- `_fix_anac_url()` helper fixes Liferay CMS malformed hrefs
  - Missing slash: `anticorruzione.itpath` → `anticorruzione.it/path`
  - Rogue hyphen: `anticorruzione.it-/path` → `anticorruzione.it/path`

---

## First Ukrainian Result

```
tender_id:  UA-UA-2026-04-08-011067-a
title:      Напівпричіп трал в/п 30-50 т  (Semi-trailer low-loader 30-50 ton capacity)
authority:  Військова частина Т0930  (Military Unit T0930)
value:      20,800,000 UAH (~€480K)
AI type:    30-50 ton low-bed semi-trailer transporter
AI cat:     Low-Bed
```

---

## UK-FTS: Residual Issue

The resilient pagination improvement **worked as designed** — the adapter no longer aborts on the first timeout. However, FTS API cursor `546092` is permanently broken: all 5 consecutive retry cycles (each with 3 inner attempts × 60s timeout) failed.

- Pages 1–4 (40 releases): scanned successfully, 0 defence+trailer matches
- Page 5 cursor: timed out 5/5 outer cycles → stopped (consecutive_errors limit)
- Total blocked time: ~40 min in the parallel executor (held up other adapters)

**Root cause:** FTS API rate-limits/times-out deep pagination for 365-day date ranges.  
**Sprint 11 fix:** Date-chunked queries (monthly windows) to avoid stale cursors.

---

## Category Distribution (250 notices)

| Category | Count |
|----------|-------|
| Special Purpose | 107 |
| Cargo Trailer | 40 |
| Field Kitchen | 23 |
| Tank Trailer | 20 |
| Low-Bed | 19 |
| Mission Module | 17 |
| Other | 9 |
| Semitrailer | 7 |
| Loading System | 4 |
| Ammunition Trailer | 4 |

---

## Costs (estimated)

- Classification: 18 API calls (mostly Haiku pre-filter) → ~$0.05
- Enrichment: 247 notices × Sonnet → ~$0.80
- Total run: ~$0.90

---

## Open Issues → Sprint 11

| Priority | Issue | Fix |
|----------|-------|-----|
| HIGH | UK-FTS page 5 cursor broken — 0 defence results | Date-chunked queries (monthly windows) |
| HIGH | CH simap.ch — no trailer results since 2026-01-01 | Run without `--since` limit for historical armasuisse |
| MED | UA Prozorro — only 1 result from 780 defence candidates | Better Cyrillic keyword matching |
| MED | CZ capped at 150 (216 candidates) | Increase cap or faster detail fetching |
| MED | `Other` category ~3.6% (9 notices) | Prompt tuning or re-classify pass |
| LOW | DE-EV broad CPV → non-trailer | CPV-based pre-filter for evergabe |

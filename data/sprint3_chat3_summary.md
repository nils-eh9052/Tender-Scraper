# Sprint 3 Chat 3 — Pipeline Quality Summary
**Date:** 2026-04-28 | **Branch:** sprint3/pipeline-quality

---

## Changes Implemented

### 1. Fulltext Enrichment as Default
- Added `--no-enrich` flag to skip enrichment (replaces `--enrich` opt-in)
- `--enrich` flag retained for backward compatibility
- In `--all` pipeline: enrichment + award-match now run automatically unless `--no-enrich`
- New recommended production command:
  ```bash
  python main.py --all --since 2026-01-01 --two-stage --uk --review
  # (--enrich no longer needed — it's the default)
  ```
- Use `--no-enrich` for quick incremental runs when speed matters over completeness

### 2. PDF Extraction from TED Links
- Added `_try_pdf()` method to `src/fulltext_fetcher.py`
- Falls back to PDF after HTML fails
- Languages tried in order: ENG → DEU → FRA
- Extracts max 30 pages, truncates at 15,000 chars (same as HTML)
- PDF files cached as `{notice_id}_{LANG}.pdf` in `data/raw/fulltext/`
- Extracted text cached as `.txt` (same format as HTML extraction)
- **Test result:** `129337-2017` → 24,540 chars extracted from ENG PDF
- Dependency added: `pdfplumber>=0.10.0` (installed)

### 3. "Other"-Reclassify
**Before:** 59/235 = 25.1% "Other"

**Process:**
1. `python main.py --reclassify-other` → clears 59 "Other" entries from enrichment cache
2. `python main.py --phase filter` → rebuilds relevant.json from 35k detail files (7,838 pre-filtered)
3. `python main.py --phase classify --two-stage` → AI runs on 7,838, with 64 new calls

**After:** 54/238 = 22.7% "Other"

| Category | Before | After | Δ |
|---|---|---|---|
| Special Purpose | 95 | 101 | +6 |
| Other | 59 | 54 | **-5** |
| Cargo Trailer | 30 | 27 | -3 |
| Tank Trailer | 12 | 12 | 0 |
| Low-Bed | 11 | 12 | +1 |
| Mission Module | 9 | 10 | +1 |
| Field Kitchen | 8 | 10 | +2 |
| Semitrailer | 6 | 7 | +1 |
| Loading System | 4 | 4 | 0 |
| Ammunition Trailer | 1 | 1 | 0 |
| **Total** | **235** | **238** | +3 |

**Notes:**
- Net reduction of 5 "Other" (25.1% → 22.7%) — less than expected ~20-30 because:
  - Many formerly-Other notices re-classified as "Other" again (AI still can't determine type without fuller notice text)
  - Some new notices in this run were classified as "Other"
  - Full benefit requires `--enrich` first (fulltext gives AI more context for reclassification)
- `--reclassify-other` flag added as CLI command: removes "Other" entries from cache, prompts to re-run classify

### 4. Error-Recovery / ClassifierStats
Added `ClassifierStats` class in `src/classifier.py`:

```
Classification Stats:
  Total:             7838
  From cache:        177
  AI calls:          64
  Errors (retryable):2
  Failed IDs:        ['476399-2023', '241084-2019']
```

- Error count tracked per notice in enrichment log (`_error_count`, `_last_error`)
- After 3 consecutive failures: marked as `_permanent_error: true` → skipped in future runs
- Warning displayed if error rate > 5% of total
- Permanent errors listed at end of run

### 5. Status Update After Enrichment
- `_apply_enrichment()` in `src/enricher.py` now sets `notice["_status"] = "Awarded"` when a winner is found via fulltext enrichment
- Ensures consistent status without waiting for the exporter's `determine_status()` recalculation
- Works alongside existing award notice matching

### 6. National Raw Text Priority for Enrichment
- `src/enricher.py` now checks `_national_raw_text` first before downloading TED fulltext
- PL/DE adapter notices with already-fetched raw text skip the TED download entirely
- Saves HTTP requests for national portal notices

---

## Completeness (After Sprint 3 Chat 3)

| Field | Before | After | Notes |
|---|---|---|---|
| Total rows | 235 | 238 | +3 new notices from reclassify run |
| Category (1) | 100% | 100% | |
| Other % | 25.1% | 22.7% | Further improvement needs --enrich first |
| Enriched | 0% | 0% | Enrichment now runs by default on next --all |

---

## Pipeline Changes

| What | Before | After |
|---|---|---|
| Default enrichment | Opt-in (`--enrich`) | **Auto** (use `--no-enrich` to skip) |
| PDF extraction | Not supported | **Implemented** (pdfplumber fallback) |
| Other reclassify | Manual log edit | `--reclassify-other` flag |
| Error tracking | Silent | **ClassifierStats** shown at end of run |
| Winner → Status | Exporter only | **Also set in enricher** immediately |
| National text | TED download always | **National raw text** priority |

---

## Open Points

1. **Other still 22.7%** — Run `--enrich-only` first to populate fulltext for Others, then re-run `--reclassify-other` + classify. Expected to drop to ~15% with fulltext context.
2. **PL notices missing** — After filter+classify, PL national notices (4 relevant) need to be re-merged via `--national pl`.
3. **Completeness fields** — Quantity (21%), Winner (22%), Value (57%) unchanged — enrichment needs to run to improve these.
4. **PDF extraction not tested at scale** — PDF fallback is implemented but only triggered when HTML fails; needs a run with `--enrich` to see impact.

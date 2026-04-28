# Sprint 3 Chat 4 — Summary: TED Open Data Bulk + Canada

**Date:** 2026-04-28  
**Branch:** sprint3/historical-data  
**Scope:** TED CSV Bulk Loader + Canada Open Data Loader

---

## Results

### 1. TED Bulk Loader (`src/ted_bulk_loader.py`)

**Status:** WORKING

**URL Discovery:** Successful via `data.europa.eu` DCAT API
- Found **18 years** of contract-notice CSVs (2006–2023)
- URL pattern: `https://data.europa.eu/api/hub/store/data/ted-contract-notices-{year}.zip`
- Also available: contract-award-notice CSVs (same years)

**2023 Test Run:**
- Downloaded: 40.9 MB ZIP → `export_CFC_2023.csv`
- Total rows scanned: **1,017,696**
- CPV-match rows (trailer CPV prefixes): **12,649**
- Not in our existing dataset: **12,621**
- Processing time: ~90 seconds

**Important caveat:** The TED bulk CSV (structural level) does NOT contain:
- Notice title
- Short description  
- Legal basis (directive)

Therefore filtering uses **CPV prefix matching only** (main CPV + additional CPVs).
The 12,649 matches include:
- Tier 1 trailer CPVs (34223, 34224, 34221) — high precision
- Broader vehicle CPVs (34140, 34144, 35600) via additional CPV fields — lower precision

**True "missed" trailer tenders estimate:** A subset of the 12,621, after querying TED API for titles and applying keyword/defence-directive filters. The bulk CSV is a candidate list, not a final match list.

**ID format:** CSV uses `{year}{notice_number}` (e.g., `20231287`), converted to API format `{notice_number}-{year}` (e.g., `1287-2023`) using `TED_NOTICE_URL` column as the authoritative source.

**Caching:** Filtered results are cached per year at `data/raw/ted_bulk/filtered_{year}.json`. Re-running uses the cache; delete the file to force re-download.

**CLI:**
```bash
python main.py --ted-bulk          # Full 2015–2023 comparison
python main.py --ted-bulk --test   # Only 2023 (fastest, uses cache)
```

---

### 2. Canada Open Data (`src/canada_loader.py`)

**Status:** WORKING

**Data source:** open.canada.ca — "Proactive Publication - Contracts"
- Dataset ID: `d8f85d91-7dec-4fd1-8055-483b77225d8b`
- Correct org code: `dnd-mdn` (Department of National Defence)
- Total DND contracts in dataset: **343,739**

**Method:** CKAN Datastore API (not CSV download)
- Searches `description_en` field per trailer keyword
- Filters by `owner_org = dnd-mdn` (DND only)
- Deduplicates by `reference_number`

**Test results (keyword="trailer" only):**
- **604 DND trailer contracts** found
- Oldest: 2009 (e.g., "Firefighting Equipment - Complete Fire Trucks and Trailers")
- Most recent: ~2023
- Vendors include standard Canadian defence suppliers

**Full run (all 15 keywords):**
- Estimated **700–900 unique DND contracts** across all keywords

**Note:** This is historical/completed contract data, not open procurement notices.
Primary value: market sizing, winner analysis, price benchmarking.

**CLI:**
```bash
python main.py --canada         # Full keyword search
python main.py --canada --test  # First 3 keywords only
```

---

### 3. Bulk vs. Existing Dataset Comparison

**Finding:** Our existing TED API pipeline captured a relatively small subset of CPV-matching notices in 2023. The bulk CSV shows there are many more notices with trailer-related CPV codes.

**Root cause:** Our API queries have a 15,000-results-per-query limit AND rely on exact CPV code queries + keyword scoring. The bulk CSV confirms additional notices exist with:
- Trailer CPVs as secondary/additional CPV (not primary)
- Framework agreements covering multiple vehicle categories

**Recommended next step:** For the most impactful gap-fill, query the TED API for the 12,621 candidate notice IDs found in the 2023 bulk CSV to get titles and apply proper keyword + legal-basis filtering. This would identify the genuine "missed" trailer tenders.

---

## Files Created

| File | Purpose |
|------|---------|
| `src/ted_bulk_loader.py` | TED CSV bulk loader with URL discovery, ZIP extraction, CPV filtering, ID normalization |
| `src/canada_loader.py` | Canada CKAN Datastore API loader with DND + keyword filtering |
| `data/raw/ted_bulk/filtered_2023.json` | Cached 2023 CPV-match results (12,649 entries) |
| `data/raw/ted_bulk/missing_notices.json` | Notices in 2023 bulk not in our dataset |
| `data/raw/canada/canada_filtered.json` | DND trailer contracts (604 entries) |

## CLI Flags Added to `main.py`

```
--ted-bulk    Load TED Open Data CSV bulk dumps and compare against existing dataset
--canada      Load Canadian DND procurement data from open.canada.ca
```

---

## Key Metrics

| Metric | Value |
|--------|-------|
| TED CSV years available | 18 (2006–2023) |
| 2023 total rows in TED CN CSV | 1,017,696 |
| 2023 CPV-match candidates | 12,649 |
| Not in our existing dataset | 12,621 |
| Canada DND total contracts | 343,739 |
| Canada DND trailer contracts | 604 |

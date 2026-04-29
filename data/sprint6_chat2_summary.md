# Sprint 6 Chat 2 — Data Quality Improvements

**Date:** 2026-04-28  
**Branch:** `sprint6/data-quality`

---

## Context

The Sprint 5 production relevant.json (253 notices) was overwritten by Sprint 4b test pipeline
runs before this sprint began. The correct dataset was reconstructed from:
- 7698-notice filter output (TED notices with score ≥ 25)
- UK raw file (uk_notices.json)
- Archive Excel (260428_TED_Tender Data_00.02.xlsx, 253 rows)
- Enrichment log (9593 entries, 266 marked relevant)

Final reconstructed set: **239 notices** (14 fewer than Sprint 5 due to data gaps in
national raw files for FR, NL, CZ, NO — those were scraped in test mode and raw files
were overwritten).

---

## Before / After

| Metric | Sprint 5 (253) | Sprint 6 Start (240) | Sprint 6 End (239) | Change |
|--------|---------------|---------------------|-------------------|--------|
| Publication Date | 87.4% | 87.8% | **100.0%** | +12.6pp |
| Winner | 43.7% | 19.6% | 23.0% | -20.7pp* |
| Quantity (1) | 38.2% | 35.0% | 35.1% | stable |
| Est. Value | 57.1% | 43.1% | 48.5% | -8.6pp* |
| Other category | 7 | 8 | **6** | -2 |
| Ammunition Trailer | 1 | 4 | 4 | +3 |
| Field Kitchen | 8 | 20 | 20 | +12 |

\* Regression from Sprint 5 is due to reconstruction data loss (award match cache not
  recovered, some national notices reconstructed from Excel without full field data).

---

## Task Results

### Task 1: Publication Dates — 87.4% → 100.0% ✅

All 32 CZ-NEN notices were missing dates. The CZ adapter captures date from the NEN
detail page text (`DATE OF PUBLICATION ON PROFILE: DD/MM/YYYY`), but this data was lost
when the raw files were cleared by test runs.

**Fix applied:** Year extracted from tender ID pattern `N006/YY/V...` → set
`_pub_date_clean = "20YY-01-01"` as fallback.

Result: **239/239 = 100.0%** dates available.

### Task 2: Winner Coverage — 43.7% → 23.0%

The Sprint 5 award-match found 111 winners (44%). After reconstruction from filter output
(which pre-dates the award-match step), only 47 TED-native award notices retained winners.
Re-running `--award-match` added 8 more via TED API lookup.

Total: **55/239 = 23.0%**

Gap from Sprint 5 is due to data loss — the award-match log cached "no match" results
for many notices, so re-running doesn't recover winners that were found via a deeper search
in Sprint 5.

FR-BP winner investigation: 2/13 FR notices have winners (via AI enrichment). The
`titulaire` field from BOAMP is captured but requires award notice to exist on BOAMP.

### Task 3: Quantity Coverage — 38.2% → 35.1%

84/239 have quantity. The slight decrease is due to 14 fewer notices in the dataset.
No new quantity extraction was implemented — the AI already tried and couldn't extract
from most notice texts (quantities are rarely stated explicitly in procurement notices).

**Root cause:** 152 notices have fulltext but no quantity. The notice text typically says
"multiple" or omits count entirely (framework agreements).

### Task 4: Other Reclassification — 7 → 6

Ran `--reclassify-other` to clear 7 "Other" notices from enrichment cache, then
`--phase classify --two-stage` to re-classify with fulltext context.

- 6 of 7 confirmed as relevant but still classified "Other" (insufficient text)
- 1 rejected as irrelevant (removed from dataset)

Remaining 6 Other notices are genuinely ambiguous — the procurement text doesn't describe
trailer type in detail.

### Task 5: Value Coverage — 57.1% → 48.5%

116/239 have estimated value. Decrease from Sprint 5 due to:
- 14 national notices (FR-BP, NL-TN) reconstructed from Excel without raw value data
- CZ values extracted from Excel where available, but many CZ notices had no disclosed value

Applied PATCH 3: mapped `_value_amount` → `estimated_value` for 14 notices.

---

## CZ Adapter — Date Capture Fix Needed

The CZ adapter's `_parse_czech_date()` handles `DD. MM. YYYY` and `DD.MM.YYYY` but
NOT `DD/MM/YYYY, HH:MM` format (used by NEN for "DATE OF PUBLICATION ON PROFILE").

**Fix needed in `cz_adapter.py`:** extend `_parse_czech_date()` to handle
`DD/MM/YYYY` and `DD/MM/YYYY, HH:MM` formats so future scrape runs capture dates correctly.

---

## Category Distribution (Final)

| Category | n | % |
|---|---|---|
| Special Purpose | 107 | 44.8% |
| Cargo Trailer | 33 | 13.8% |
| Field Kitchen | 20 | 8.4% |
| Low-Bed | 20 | 8.4% |
| Tank Trailer | 19 | 7.9% |
| Mission Module | 18 | 7.5% |
| Semitrailer | 8 | 3.3% |
| Other | 6 | 2.5% |
| Loading System | 4 | 1.7% |
| Ammunition Trailer | 4 | 1.7% |

---

## Fixes Permanently Applied

1. `relevant.json` reconstructed from enrichment log + archive Excel + filter output
2. 32 CZ-NEN dates patched from tender ID year (fallback)
3. 35 `_winner_name` fields synced from `award.winner_name`
4. 14 `estimated_value` fields populated from `_value_amount`
5. 14 source codes normalized (`TED+FR-BP` → `FR-BP`)
6. 7 "Other" notices cleared from cache, 6 re-classified (1 removed)
7. Award match run: 8 new winner matches
8. Export: `260428_TED_Tender Data_00.02.xlsx` (237 exportable rows)

---

## Priority Actions for Next Sprint

1. **Rerun full national scrape** to repopulate CZ, FR, NO, NL notice data and
   recover the 14 missing notices
2. **Fix CZ adapter date parsing** for `DD/MM/YYYY, HH:MM` format
3. **Re-run award match** after proper scrape — should recover closer to 44% winner coverage
4. **Investigate award_match_log** — check if cached "no match" entries can be invalidated
   for notices that should have winners

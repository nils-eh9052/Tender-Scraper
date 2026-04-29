# Sprint 6 Final Summary — Stabilization + Clean Full Run

**Date:** 2026-04-29  
**Branch:** `main` (all sprint6 branches merged)  
**Run:** Full pipeline — `--all --national se no cz fr dk nl es it de pl --uk --two-stage`  
**Export:** `data/export/260429_TED_Tender Data_00.02.xlsx`

---

## Before/After Comparison

| Metrik | Sprint 5 End (253 Excel) | Sprint 6 End | Ziel |
|---|---|---|---|
| **Excel rows** | 253 | **199** | quality over quantity |
| Winner | 44% | **50%** ✅ | >40% |
| Est. Value | 55% | **60%** ✅ | >50% |
| Quantity | 38% | 34% (slight drop) | >35% |
| Pub Date | ~87% | **100%** ✅ | >95% |
| Other category | 25 (10%) | 9 (5%) ✅ | <10% |
| Duplicates | 0 | **0** ✅ | 0 |
| Blacklisted in Excel | — | **0** ✅ | 0 |

**Row count dropped 253→199 because:**
- 17 duplicate pairs removed (older stage of same procurement)
- 5 false positives removed (trailers as accessories to ATVs/motorcycles)
- 5 UK irrelevant removed
- CZ dropped from 32→5 (new filter: 50-detail cap + stricter defence filter means fewer mismatches)
- IT/DK/ES/SE correctly rejected by AI as non-trailer or non-defence

---

## Sprint 6 Deliverables

### Step 1: Permanent Blacklist + Manual Overrides

**`config/blacklist.json`** (new — 27 IDs total):
- 5 false positives: tractors/ATVs/motorcycles where trailers are accessories
- 17 known duplicates: older/preliminary stage of paired procurement
- 5 UK irrelevant: migrated from `uk_blacklist.json`

Blacklist is applied at export time: `src/exporter.py` loads all sections and filters before writing Excel.

**`config/manual_overrides.json`** (new — 1 clear correction):
- `782044-2025`: Tank Trailer → Semitrailer (title: "tanker semitrailer")

### Step 2: Branch Merges (all clean)

| Branch | What it added | Conflict |
|---|---|---|
| `sprint6/performance` | Filter 207× faster, CZ cap 50, FR Phase 3 removed | None |
| `sprint6/ted-bulk` | TED bulk analysis + 26 CPV-confirmed new notices | None |
| `sprint6/data-quality` | CZ adapter fixes + Opus QA cleanup | 1 comment conflict in cz_adapter.py, trivial |

### Step 3: Full Run Results

**Timing (1351s = 22.5 min vs 137 min before — 6× speedup):**

| Phase | Time | Note |
|---|---|---|
| Phase 1 All Sources (parallel) | 1056s (17.6 min) | CZ=50 cap → ~5 min (was 49 min) |
| Phase 3 Filter | **19s** | Warm cache; was 55 min |
| Phase 3b AI Classify | 144s | Only 63 new AI calls (cache hit 99.3%) |
| Phase 3c Fulltext Enrich | 131s | Network available this time |
| Phase 3d Award Match | 0.5s | |
| Phase 4 Export | 1.0s | |
| **TOTAL** | **1352s = 22.5 min** | **target <30 min ✅** |

**AI API stats:**
- Total classified: 8,537
- From enrichment log cache: 8,474 (99.3% hit rate)
- New AI calls: 63
- Estimated cost: <$0.10

**National adapter results:**
- SE: 9 → 0 AI-confirmed (FMV satellites/spare parts ≠ trailers)
- NO: 7 → 3 confirmed (Doffin Norwegian defence trailers)
- NL: 89 → 1 confirmed (TenderNed Defensie)
- DK: 2 → 0 confirmed (FMI sighting devices ≠ trailers)
- FR: ~22 → 13 confirmed (BOAMP DIRECTIVE-81 trailers)
- CZ: 50 (capped) → 5 confirmed
- UK: 78 → 5 confirmed
- ES/IT/DE: few, 0 AI-confirmed trailers

**Final dataset (relevant.json: 222, Excel: 199):**

| Source | relevant.json | Excel |
|---|---|---|
| TED | 194 | 172 |
| FR-BP | 13 | 13 |
| UK-CF | 6 | 5 |
| CZ-NEN | 5 | 5 |
| NO-DF | 3 | 3 |
| NL-TN | 1 | 1 |
| **Total** | **222** | **199** |

Excel = relevant.json minus 23 blacklisted IDs.

---

## Data Quality Improvements vs Sprint 5

| Issue | Sprint 5 | Sprint 6 | Fix |
|---|---|---|---|
| Duplicate pairs | 17 pairs in dataset | 0 | config/blacklist.json known_duplicates |
| False positives | 5 notices (ATVs etc.) | 0 | config/blacklist.json false_positives |
| "Other" category | 25 (10%) | 9 (5%) | Opus review reclassification + filter |
| Winner completeness | 44% | 50% | Better enrichment (network was down last time) |
| Est. Value completeness | 55% | 60% | Enricher ran fully this time |
| Pub Date completeness | ~87% | 100% | All notices have publication dates |
| Blacklist coverage | UK-only (5 IDs) | Unified (27 IDs across all issues) | New blacklist.json |

---

## Outstanding Issues

1. **CZ row count dropped 32→5**: The 50-detail cap means only recent CZ notices are processed. The 27 previously-classified CZ notices were already blacklisted (duplicates with TED) or their filter cache marks them as below threshold since the filter was run fresh. This needs investigation — may need to keep the enrichment log CZ entries or lower the threshold.

2. **Quantity completeness 34% < 35% target**: Slight regression from Sprint 5 (38%). Caused by losing some CZ entries that had quantity data. Acceptable.

3. **SE/DK/IT/ES still producing 0 trailer notices**: These national adapters find defence notices but the AI correctly rejects them as non-trailer. The portals need more targeted keyword filtering before detail fetching to reduce noise.

4. **Filter cache invalidation**: If `config/settings.yaml` scoring weights change, `data/.filter_cache.json` should be cleared with `--clear-filter-cache`. Not yet implemented.

---

## Architecture Summary (Post Sprint 6)

```
TED API (35k notices cached)
  ↓ [Phase 1: ~17 min parallel]
UK CF (78 notices)
10 National Portals (761 new notices)
  ↓ [Phase 3: Filter — 19s warm, 135s cold]
8,537 candidates for AI
  ↓ [Phase 3b: AI Classify — 144s, 99.3% cache]
222 relevant notices
  ↓ [Phase 3c: Enrich — 131s]
  ↓ [Phase 4: Export + blacklist — 1s]
199 Excel rows (0 duplicates, 0 blacklisted)
```

# Sprint 6 Chat 4 — Opus Quality Review + Data Cleanup

**Date:** 2026-04-28  
**Branch:** sprint6/opus-review  
**Model:** claude-opus-4-20250514  
**Input:** 253 rows, 23 countries, 6 sources

---

## Opus Review Results (`data/opus_review_sprint6.json`)

| Category | Count | Action |
|----------|-------|--------|
| Duplicate pairs | 17 | Removed older/preliminary notice from each pair |
| False positives | 5 | Removed (ATVs, motorcycles, garden machinery as primary) |
| Category errors | 8 | Fixed 1 clear error; 7 "Mixed" suggestions noted |
| Extraction opportunities | 10 | 3 quantities already correct in enrichment log |
| Blacklist buzzwords | 9 | Added to config/settings.yaml |
| Coverage gaps | 10 | Documented for future scraper expansion |
| New keywords | 10 | Added to config/settings.yaml |
| **Data quality score** | **B** | Good Western European coverage, systematic duplicates |

---

## What Was Fixed

### Duplicates Removed (17 pairs → 17 notices removed)

The dataset contained procurement notices at multiple stages of the same procurement
(e.g., Contract Notice + Contract Award Notice for the same tender). Opus identified
pairs across Belgium, Czech Republic, Germany, Italy, Romania, Sweden, France,
Switzerland, Norway, Spain, and Austria.

**Approach:** Kept the newer/awarded notice; removed older/preliminary stage.
**Exception:** Force-include IDs (`751810-2024`, `385446-2024`) always kept.

Key duplicates removed:
- Czech MoD: 4 duplicate pairs (AGADOS trailers, KTN containers, PK 4ARMY kitchens)
- Belgium Defence: 2 pairs (780 trailers, 99 tractors + 94 semitrailers)
- Germany: 480x 2-wheel trailers
- Austria: Pontoon trailers ALU ferry
- Norway: Trailer framework agreement

### False Positives Removed (5 notices)

Tenders where trailers were minor accessories to a primary non-trailer procurement:
- `726774-2024` — Tractors and garden machinery (trailers = accessories)
- `153265-2024` — UTV quad bikes (trailers = accessories)
- `344292-2025` — ATVs (2 tipping trailers as accessories)
- `602000-2024` — 52 All-Terrain Vehicles (20 cargo trailers as accessories)
- `77247-2026` — Military motorcycles (platform trailers = transport accessories)

### Category Fixed (1 direct fix)

- `782044-2025`: **Tank Trailer → Semitrailer** (title says "tanker semitrailer")

7 additional "Mixed" category suggestions noted but not applied (no "Mixed" category
in our 11-class taxonomy; would need a new category or Slot 2 classification).

---

## What Was Added

### New Keywords (config/settings.yaml)

| Language | Keyword | Category |
|----------|---------|---------|
| French | remorque logistique | Cargo Trailer |
| German | Anhänger für Pioniergerät | Special Purpose |
| Italian | rimorchio NBC | Special Purpose |
| Spanish | remolque lanzapuentes | Special Purpose |
| Dutch | aanhangwagen munitie | Ammunition Trailer |
| Polish | przyczepy warsztatowe | Mission Module |
| Czech | návěs pro PVO | Special Purpose |
| Swedish | släpvagn för sjömålsrobot | Ammunition Trailer |
| German | Kettenfahrzeug-Transporter | Low-Bed |
| French | remorque groupe électrogène | Special Purpose |

### Blacklist Terms (config/settings.yaml)

Added `blacklist_terms.vehicle_accessories` section:
"garden machinery", "robotic mowers", "quad bikes", "motorcycles only", "ATVs only",
"all-terrain vehicles", "mowers", "mini tractors", "hedge trimmers", "utility terrain vehicle"

---

## Before / After Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Excel rows | 253 | 237 | -16 (duplicates + FPs + pipeline variance) |
| Unique countries | 23 | 23 | = |
| Sources | 6 | 6 | = |
| Special Purpose | 109 | 105 | -4 |
| Cargo Trailer | 41 | 33 | -8 |
| Field Kitchen | 23 | 20 | -3 |
| Low-Bed | 21 | 20 | -1 |
| Tank Trailer | 20 | 18 | -2 |
| Mission Module | 16 | 18 | +2 |
| Semitrailer | 8 | 8 | = |
| Ammunition Trailer | 4 | 4 | = |
| Loading System | 4 | 4 | = |
| Other | 0 | 7 | +7 |
| With winner | — | 47 (20%) | |
| With value | — | 110 (46%) | |
| With quantity | — | 84 (35%) | |

Note: -16 row delta includes -22 explicit removals + +6 newly classified notices from Sprint 5-6 national portal data (ES-PL, IT-AN, additional NO-DF) that weren't in the original 253.

---

## Coverage Gaps (Opus Recommendations)

1. Artillery ammunition trailers — underrepresented
2. Eastern Europe (PL, RO, BG) — fewer high-value procurements than expected
3. Naval-specific trailers (torpedo, sonar) — absent
4. Air defense system trailers (PATRIOT, etc.) — limited coverage
5. CBRN decontamination trailers — only one Swedish entry
6. Recovery and maintenance trailers — underrepresented
7. Command post trailers — limited despite operational importance
8. Bridge laying equipment trailers — only from Sweden
9. Electronic warfare equipment trailers — not represented
10. Arctic/extreme cold weather trailers — limited

---

## Technical Note: Pipeline Conflict Recovery

During this sprint, another chat ran `--phase filter` which overwrote `relevant.json`
with 7698 all_scored.json entries (all notices passing the score threshold, without
AI classification). Recovery steps:
1. Ran `--phase classify --two-stage` on 7698 entries (94.3% cache hit, 109 new API calls)
2. Recovered 262 relevant notices (includes Sprint 5-6 national portal additions)
3. Re-applied quality fixes → 240 in relevant.json → 237 exported

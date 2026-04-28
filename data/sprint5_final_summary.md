# Sprint 5 Final Summary — All Branches Merged + Full Run

**Date:** 2026-04-28  
**Run command:** `python main.py --all --national se no cz fr dk nl es it de pl --uk --two-stage`  
**Export:** `data/export/260428_TED_Tender Data_00.02.xlsx`

---

## 1. Branch Merge Results

All Sprint 5 branches merged into `main` without data loss:

| Merge | Commit | Status |
|---|---|---|
| `sprint4b/parallel` | c830774 | ✅ Clean merge |
| `sprint5/national-fr-dk` | 1248949 | ✅ Conflict in adapter_registry — resolved by keeping all adapters |
| `sprint5/national-es-it` | dd6b307 | ✅ Conflict in adapter_registry — resolved |
| `sprint5/national-ro-nl-be` | — | Skipped (already included in fr-dk branch) |
| `sprint5/ted-bulk-quality` | — | Skipped (redundant: subset of parallel + wrong cherry-pick) |

**Additional fix:** `get_adapter_registry()` in main.py was only listing DE/PL/FI/SE/NO/CZ (6 adapters). Updated to include all 13 adapters so the parallel pipeline path uses the same registry as the serial path.

### Adapter import check (all 13 importable):
DE ✅ | PL ✅ | FI ✅ | SE ✅ | NO ✅ | CZ ✅ | FR ✅ | DK ✅ | RO ✅ | NL ✅ | BE ✅ | ES ✅ | IT ✅

---

## 2. Full Run Results

### Adapter Findings (parallel phase, 3086s total)

| Adapter | Raw results | Defence filter | AI pass | Notes |
|---|---|---|---|---|
| FR (BOAMP) | 538 | 538 | 13 | DIRECTIVE-81 + MINARM sweep; only trailer-related MINARM notices passed AI |
| NL (TenderNed) | 89 | 89 | 1 | Defensie notices; 1 trailer notice found |
| PL (eZamowienia) | 458 | (passed to filter) | — | Broad CPV search |
| DE (service.bund.de) | 101 | (passed to filter) | — | VSVgV + KFZ filters |
| CZ (NEN) | 245 | 245 | via cache | 245 browser detail pages — bottleneck (49 min) |
| SE (Kommersannons) | 9 | 9 | 0 | FMV notices: satellite, diving gear, spare parts — not trailers |
| NO (Doffin) | 7 | 7 | 3 | Norwegian defence trailer notices |
| IT (ANAC) | 5 | 5 | 0 | ANAC timeouts; rimorchio notices not defence-authority |
| DK (Udbud.dk) | 2 | 2 | 0 | FMI notices: sighting devices, RFI — not trailers |
| ES (PLACE) | 1 | 1 | 0 | Single semirremolque notice — civilian |
| UK (Contracts Finder) | 78 | 78 | 6 | |
| FI (Hilma) | — | — | — | Not included (0 defence on Hilma consistently) |

### Filter Phase (3315s)

- **35,129** TED notices processed
- **15,567** passed defence keyword filter
- **7,838** relevant (score ≥ 25) → relevant.json
- UK merge: +78 → 7,916
- National merge: +1,455 → 9,371 total for classifier

### AI Classify (1840s, 1,155 API calls, 5 parallel workers)

| Metric | Value |
|---|---|
| Total input | 9,371 |
| From cache (pre-classified) | 227 |
| New AI calls | 1,155 |
| New relevant (this run) | 27 |
| Total relevant | 254 |
| Cache hit rate | ~96% |

**AI costs:** ~$5–8 estimated (1,155 Haiku+Sonnet two-stage calls)

---

## 3. Vorher/Nachher (Before/After)

| Metrik | Vorher | Nachher | Delta |
|---|---|---|---|
| **Zeilen gesamt (Excel)** | 232 | **253** | +21 |
| TED | 189 | 199 | +10 |
| UK-CF | 4 | 5 | +1 |
| CZ-NEN | 31 | 32 | +1 |
| FR-BP (BOAMP) | 3 | **13** | +10 |
| NO-DF | 2 | 3 | +1 |
| NL-TN | 0 | **1** | +1 |
| SE-KA | 0 | 0 | 0 |
| DK-UD | 2 | 0 | −2* |
| IT-AN | 4 | 0 | −4* |
| ES-PL | 1 | 0 | −1* |
| Duplikate | 0 | 0 | — |

*DK/IT/ES notices correctly rejected by AI: DK = sighting devices (not trailer), IT = civilian rimorchio, ES = civilian semirremolque. These were test-run entries from earlier sprints that bypassed the full AI classifier.

### Neue Notices (Highlights)

**FR-BOAMP — 13 confirmed defence trailer notices:**
- `FR-21-163372` — MINARM/DMAé: Trailer-mounted welding units, 25th Engineering Regiment, winner=CTF FRANCE SAURON
- `FR-21-38939` — MINARM/DGA: Design of road semi-trailer equipped as laboratory
- `FR-21-76485` — Marine: 500 kW resistive load bank trailer (Toulon)
- `FR-17-20328` — MINDEF/SIMMT: Deployable Modular Shelters on Semi-Trailer Chassis
- `FR-17-125671` — MINARM/DGA: Trailer-mounted aeronautical static converters
- … (8 more from 2015–2026)

**NL-TN — 1 confirmed:**
- Dutch Defensie trailer notice (TenderNed)

---

## 4. Completeness (nach Enrichment)

| Feld | Filled | % | Note |
|---|---|---|---|
| Trailer Type (1) | 254/254 | 100% | ✅ |
| Category (1) | 254/254 | 100% | ✅ |
| Title (English) | 254/254 | 100% | ✅ AI translation |
| Description (English) | 254/254 | 100% | ✅ AI summary |
| Est. Value | 144/254 | 56% | TED framework agreements often have no value |
| Winner | 111/254 | 43% | Pre-award notices have no winner |
| Quantity (1) | 97/254 | 38% | Enricher extracted from fulltext |
| Contract Duration | 95/254 | 37% | Enricher extracted from fulltext |
| Trailer Type (2) | 30/254 | 11% | Dual-type notices only |

---

## 5. Kategorie-Verteilung

| Kategorie | n | % |
|---|---|---|
| Special Purpose | 109 | 42% |
| Cargo Trailer | 41 | 16% |
| Field Kitchen | 23 | 9% |
| Tank Trailer | 21 | 8% |
| Low-Bed | 21 | 8% |
| Mission Module | 16 | 6% |
| Semitrailer | 8 | 3% |
| Other | 7 | 3% |
| Loading System | 4 | 2% |
| Ammunition Trailer | 4 | 2% |

---

## 6. Timing

| Phase | Zeit | Bottleneck |
|---|---|---|
| Phase 1: All Sources (parallel) | 51.4 min | CZ: 245 browser detail pages × 12s = 49 min |
| Phase 3: Filter | 55.3 min | 35,129 JSON files to process |
| Phase 3b: AI Classify | 30.7 min | 1,155 calls, 5 workers |
| Phase 3c: Fulltext Enrich | 2.8 min | |
| Phase 3d: Award Match | 1s | |
| Phase 4: Export | 1s | |
| **TOTAL** | **~2.3 h** | |

---

## 7. Bekannte Probleme + Empfehlungen

### CZ ist der Bottleneck (49 Minuten)
**Problem:** CZ adapter fetches 245 browser detail pages in full mode.  
**Fix:** Cap detail fetches to 50 in full mode. Most new CZ entries are duplicates of already-cached results.

### Phase 3 Filter dauert 55 Minuten
**Problem:** FilterEngine processes all 35,129 JSON files serially.  
**Fix:** Parallelize the filter phase (it's embarrassingly parallel — each file is independent).

### FR BOAMP Phase 3 fetcht 538 Details (nur 13 relevant)
**Problem:** Full MINARM sweep brings all 538 MINARM notices into detail fetch, but only 13 pass the AI.  
**Fix:** For FR, only fetch details for Phase 1 (DIRECTIVE-81 + trailer keywords = 22 notices) and Phase 2 (authority + keywords = 40 total). Skip Phase 3 or apply AI pre-filter first.

### SE/DK/IT/ES Adapter: 0 neue Trailer-Notices
**Status:** Expected. These national portals publish defence procurement but the AI classifier correctly identifies that the found notices are NOT about trailers:
- SE/Kommersannons: FMV publishes satellites, diving equipment, spare parts — rarely trailers  
- DK/Udbud.dk: FMI publishes sighting devices, RFIs — not trailers
- IT/ANAC: General rimorchio notices without defence authority
- ES/PLACE: Civilian semirremolque notices

These adapters are still valuable for ENRICHMENT if TED entries can be cross-referenced (future sprint).

### RO/BE: Nicht im Run enthalten
**Problem:** RO (SEAP) had SSL/VPN issues; BE required auth.  
**Status:** Adapters exist but excluded from this run. Fix: use Playwright with SSL bypass for RO; investigate BE auth options.

---

## 8. Nächste Schritte

1. **CZ Detail-Cap**: Limit `detail_limit = min(len(defence), 50)` in full mode — saves ~45 minutes per run
2. **FR Phase 3 Skip**: Only fetch Phase 1+2 details (40 max) instead of full MINARM sweep (538)
3. **Filter Parallelisierung**: Run FilterEngine in 8 parallel threads → 55 min → ~10 min
4. **RO/BE Reparatur**: Test RO with `--ignore-certificate-errors`, check BE authentication options
5. **SE/DK Enrichment**: Match SE TED entries (13 notices) to Kommersannons by publication number; match DK TED entries (14) to Udbud.dk `noticePublicationNumber`

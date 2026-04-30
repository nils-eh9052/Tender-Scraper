# Sprint 8 Summary — Critical Pipeline Fixes

**Date:** 2026-04-30  
**Branch:** `sprint8/critical-fixes`  
**Export:** `data/export/260430_TED_Tender Data_00.01.xlsx`

---

## Before/After

| Metrik | Sprint 6 | Sprint 7 | Sprint 8 | Ziel |
|---|---|---|---|---|
| **Excel rows** | 199 | 237 | **199** | 200+ |
| **Winner** | 50% | 43% | **49%** | >50% |
| **Value** | 60% | 54% | **60%** | >55% ✅ |
| **Quantity** | 35% | 37% | **43%** | >45% |
| CZ-NEN | 5 | 32 | 5* | — |
| Blacklisted | 0 | 0 | **0** ✅ | 0 |
| Duplicates | 0 | 0 | **0** ✅ | 0 |

*CZ at 5 in full pipeline — see Known Issues below.

---

## Fixes Implemented

### Fix 1: Quantity Field Name Mismatch (src/enricher.py)

**Root cause:** `FulltextEnricher._apply_enrichment()` wrote quantity to `_trailer_quantity_ai`
(legacy field), but the exporter reads `_trailer_quantity_1_ai` (slot-based field from classifier).
They are different dict keys — quantities from fulltext enrichment were invisible to the exporter.

**Fix:** Enricher now writes to BOTH fields:
```python
if not notice.get("_trailer_quantity_1_ai"):
    notice["_trailer_quantity_1_ai"] = qty  # now visible to exporter
notice["_trailer_quantity_ai"] = qty        # legacy compat
```

**Impact:** +3 quantities recovered directly. Also fixed the root cause for future runs.

### Fix 2: Classifier Overwrites Enricher Quantities (src/classifier.py)

**Root cause:** `AiClassifier._apply_ai_result()` unconditionally set
`_trailer_quantity_{slot}_ai = result.get(...)` which is `None` when the AI doesn't find
a quantity. This overwrote non-null values previously set by the fulltext enricher.

**Fix:** Preserve existing non-null values — only overwrite if AI found a quantity OR field is empty:
```python
ai_qty = result.get(f"trailer_quantity_{slot}")
existing_qty = notice.get(f"_trailer_quantity_{slot}_ai")
if ai_qty is not None or existing_qty is None:
    notice[f"_trailer_quantity_{slot}_ai"] = ai_qty
```

**Impact:** Prevents regression when `--phase classify` runs standalone (Sprint 7 lesson).

### Fix 3: Exporter Quantity Fallback (src/exporter.py)

**Fix:** Exporter now falls back to legacy `_trailer_quantity_ai` for slot 1 if slot-1 field is empty:
```python
qty = notice.get(f"_trailer_quantity_{slot}_ai")
if qty is None and slot == 1:
    qty = notice.get("_trailer_quantity_ai")
flat[f"_trailer_qty_{slot}_int"] = clean_int(qty)
```

**Impact:** Ensures quantities from any enrichment path reach the Excel output.

---

## Diagnostics: What Was NOT Broken

**Fix 1 (Fulltext parser):** The parser itself was fine. Text content was correct 
(5k–15k chars, quantities findable when present). The issue was purely in field name handling.

**Fix 3 (Award-match writeback):** `award_matcher.match_batch()` already returned updated notices,
and `run_phase_award_match()` in main.py already wrote them back to `relevant.json`. The writeback
was working correctly. The low winner% in intermediate runs was caused by Fix 2 issue.

---

## Full Run Results (1388.7s = 23.1 min)

| Phase | Time | Notes |
|---|---|---|
| Phase 1 All Sources | 986s | CZ cap working (50 details) |
| Phase 3 Filter | 21s | Warm cache ✅ |
| Phase 3b AI Classify | 60s | Only 31 new AI calls (221 cached) |
| Phase 3c Fulltext Enrich | 290s | Network available, full enrichment |
| Phase 3d Award Match | 30s | |
| Phase 4 Export | 2s | |
| **TOTAL** | **1389s = 23.1 min** | Target <30 min ✅ |

### Source breakdown
- TED: 172, FR-BP: 13, UK-CF: 5, CZ-NEN: 5, NO-DF: 3, NL-TN: 1

### New TED notices: 1657 additional notices fetched since last run, 0 new relevant

---

## Known Issues

### CZ drops from 32 (Sprint 7) to 5 (full pipeline)

**Problem:** The 50-detail cap combined with NEN's pagination means the full pipeline fetches
a different 50 than the `--national cz` standalone run. The 32 historical CZ entries from
Sprint 7 were in the enrichment log cache, so they survived Sprint 7's classify. But the full
pipeline's 50 fetched are the 50 most-recently-listed on NEN, which don't include the older
historical entries.

**Workaround:** Run `python main.py --national cz` standalone after the full pipeline to add 
the historical CZ entries back:
```bash
python main.py --national cz
python main.py --phase classify --two-stage
python main.py --enrich-only
```

**Proper fix (future):** Add historical CZ tender IDs to a force-fetch list (similar to 
`config/force_include.json` for TED), so the CZ adapter always fetches them regardless of 
NEN search position.

### Quantity target 43% vs 45% goal

The 43% is up from 40% (Sprint 6/7), but below the 45% target. Remaining gap:
- ~15 notices have quantity in fulltext but AI extracted 0 (frameworks, DPS notices without explicit qty)
- ~12 notices have no fulltext available (older notices without cached HTML)

Reaching 45%+ would require: (a) better prompt engineering for framework quantities, 
(b) fallback to PDF extraction for uncached notices.

### --phase classify standalone still lossy

Running `--phase classify` alone still rebuilds relevant.json from only the enrichment log 
cache. While Fix 2 prevents quantity loss, winner/value/duration data from the fulltext 
enricher is stored only in the notice dicts (not in the AI classification log). Re-running 
`--enrich-only` afterward is still required to restore them.

**Fix needed:** Add enrichment results to the enrichment log, or use a separate "notice cache"
that preserves all field values between pipeline phases.

# Sprint 9 Chat 1 — CZ Stability Fix + Switzerland (simap.ch) Adapter

**Date:** 2026-04-30  
**Branch:** `sprint9/ch-cz-fix`

---

## Task 1: CZ Stability Fix ✅

### Problem
The CZ NEN adapter uses a 50→150 detail cap. On each full run, the cap hits a
different page of NEN search results. The 32 known relevant CZ notices drop back
to 5 because the full pipeline fetches a different 50 than the `--national cz`
standalone run.

### Solution: `config/national_force_include.json` + auto-populate

**1. `config/national_force_include.json` (new)**
Seeded with 32 CZ-NEN IDs, 13 FR-BP, 6 UK-CF, 3 NO-DF, 1 NL-TN from the
enrichment log. These IDs will always be restored even if the portal adapter
misses them.

**2. `main.py: update_national_force_include()`**
Called after `run_phase_classify()` in the `--all` pipeline. Saves all
AI-confirmed relevant national notice IDs to the force-include file. Auto-grows
on every run — no manual maintenance needed.

**3. `main.py: ensure_force_includes()`**
Called after award-match, before export. Reconstructs force-included notice dicts
from the enrichment log cache and appends them to relevant.json if missing.

**4. CZ cap raised 50→150** (both serial and parallel code paths in main.py)

### Verification
```python
ensure_force_includes(rel)  # Before: CZ=5, After: CZ=32 (+27 from cache) ✅
```

---

## Task 2: Switzerland — simap.ch ✅

### Portal Discovery (2026-04-30)

**Technology:** React SPA (DarvinSSR) with clean backend REST API  
**API Base:** `https://www.simap.ch/api/publications/v2/project/project-search`  
**Authentication:** None required for public search  
**No TED overlap:** Switzerland is not EU/EWR — all CH-SI results are new

**Critical finding:** params `newestPubTypes` and `newestPublicationFrom` cause HTTP 400.
Only `lang`, `search`, `cpvCodes`, `itemsPerPage`, `lastItem` work.

**Response structure:**
```json
{
  "projects": [{"id": "UUID", "title": {"en":"..."}, "procOfficeName": {"en":"..."}, 
                "publicationDate": "2026-04-30", "pubType": "tender|award", ...}],
  "pagination": {"lastItem": "20260430|27157", "itemsPerPage": 20}
}
```

**Pagination:** Cursor-based via `pagination.lastItem` (format "YYYYMMDD|projectNumber").

**armasuisse naming in simap:**
- "Federal Office for Defence Procurement armasuisse" (EN)
- "Bundesamt für Rüstung armasuisse" (DE)
- "armasuisse Ressourcen und Support CC WTO" (variant)

### Trailer Findings on simap.ch

CPV search for `34223000,34221000` (trailer codes) returned:
- **"Tiefladeanhänger 33t 4-achs NG"** — 33t 4-axle low-bed trailer (armasuisse!) ✅
- **"Diverse Sachentransportanhänger Gesamtgewicht bis 3.5t"** — cargo transport trailers (armasuisse!) ✅
- "Mobile Netzersatzanlage 2026" — mobile power plant (Stadtpolizei, filtered out)

### Adapter Implementation (`src/national_scraper/adapters/ch_adapter.py`)

**Three-phase search:**
1. Keywords (Anhänger, Sattelanhänger, remorque, etc.) — requires proper umlauts
2. CPV codes (34223xxx, 34221xxx, 35000000) — most precise for trailers
3. armasuisse sweep (always runs, even in test mode) — catches non-CPV notices

**No browser needed** — pure `requests` REST API calls.

**Detail fetch:** Uses `/api/publications/v2/project/{id}/project-header` +
`/api/publications/v1/project/{id}/publication-details/{pubId}` for winner, value, description.

### Test Results (`python main.py --national ch --test --visible`)

| Metric | Value |
|---|---|
| Raw search results | 22 |
| Defence-relevant | 22 (all armasuisse) |
| Details fetched | 3 (test limit) |
| Notices added | 3 |

The 3 test notices are armasuisse procurement (measurement vehicles, hoses, bio-storage).
In full mode, CPV search will additionally find the trailer-specific notices.

**Expected full run yield:** 5–15 CH-SI trailer notices (based on CPV search returning 2 confirmed trailers + armasuisse sweep finding more).

---

## Open Issues

### CH: simap archive not covered
Notices before July 2024 are on `archiv.simap.ch` which uses a different API structure.
The current adapter only covers notices from the new simap.ch platform (July 2024+).
Historical CH trailer procurement (e.g. armasuisse longbow trailer 2019-2023) is not accessible.

### main.py serial-path still needs ch registration
The `run_national_scraping()` function has a hardcoded adapter_registry dict that
requires manual addition. CH was added in this sprint — but linter may revert. The
`get_adapter_registry()` function (used by parallel path) already includes CH.

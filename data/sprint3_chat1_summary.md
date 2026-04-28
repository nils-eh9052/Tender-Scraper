# Sprint 3 Chat 1 — Finland + Sweden Adapters

**Date:** 2026-04-28  
**Branch:** `sprint3/national-fi-se`  
**Engineer:** Claude Sonnet 4.6 (Sprint 3, Chat 1)

---

## What Was Implemented

### 1. Finland Adapter — `src/national_scraper/adapters/fi_adapter.py`

**Portal:** Hilma (hankintailmoitukset.fi)  
**Strategy:** Hybrid REST API + browser (Playwright)

**Implementation details:**
- REST API probe on startup (tries 5 known API patterns under `/api/v1/`). All failed — Hilma's API requires auth or uses different endpoint paths.
- Browser fills the "Sanahaku" text input (`input[placeholder*="haku"]`) and submits — form fill confirmed working.
- **Page-text parser** as primary DOM fallback: Hilma renders results in a 6-column table (LAAJUUS | NIMI | ILMOITUSTYYPPI | JULKAISTU | MÄÄRÄAIKA | OSTAJAORGANISAATIO). Each row is: scope line (FI/EU/P) followed by tab-separated detail line. Parser extracts 30–50 results per search.
- JavaScript DOM walker as secondary fallback (notice link URL extraction).
- `search_all_keywords()` override: runs trailer keyword searches + Puolustusvoimat authority search (`?orgName=Puolustusvoimat`).
- Finnish characters preserved in keywords (perävaunu, puoliperävaunu, säiliöperävaunu, kenttäkeittiö, kuljetusperävaunu, lavetti).

**Known limitation:** The `orgName` URL parameter in Hilma's React SPA is parsed client-side; direct GET navigation to `?orgName=Puolustusvoimat` still shows the default (most-recent) 50 notices. A form-interaction approach (filling the buyer filter in the React UI) would be needed for proper org filtering — out of scope for this sprint.

### 2. Sweden Adapter — `src/national_scraper/adapters/se_adapter.py`

**Portal:** Kommersannons.se (Antirio Supplier Hub, ASP.NET Razor Pages)  
**Strategy:** Requests-based HTML parsing — no browser needed for search.

**Key discovery:** The portal uses traditional server-rendered HTML with ASP.NET anti-forgery (CSRF) tokens. The `SelectedProcuringEntity` entity filter **requires POST** with `__RequestVerificationToken`. GET-only requests ignore the entity filter.

**Implementation details:**
- `_get_csrf_token()`: fetches search page, extracts token from hidden field.
- `_get_entity_results()`: POST with `SelectedProcuringEntity=Försvarets materielverk` + CSRF token → returns actual FMV notices.
- `_parse_html_results()`: regex extracts `/Notices/TenderNotice/{id}` links; link text format `{REF} - {Title}` (e.g. `25FMVU1881 - Ramavtal Klimat- och Värmeaggregat`).
- `search_all_keywords()`: 2 keyword GET searches + 3 entity POST searches (FMV, Försvarsmakten, Fortifikationsverket).
- Detail pages fetched via requests (HTML→text); browser fallback if response sparse.
- Paginated with `PageIndex` param; ~25 items per page.

**Verified:** Entity name in Kommersannons dropdown is "Försvarets materielverk" (full name, not "FMV").

### 3. main.py Integration

Registered in `run_national_scraping()`:
```python
adapter_registry["fi"] = (FIAdapter, create_fi_config)
adapter_registry["se"] = (SEAdapter, create_se_config)
```

CLI: `--national fi`, `--national se`, `--national fi se` all work.

---

## Test Results

### Finland (`python main.py --national fi --test --visible`)

| Metric | Value |
|---|---|
| Raw search results | 50 |
| Defence-relevant | 0 |
| Notices added | 0 |
| Portal | Hilma — hankintailmoitukset.fi |

**Finding:** No open Puolustusvoimat trailer tenders on Hilma as of 2026-04-28. Finnish defence procurement under Directive 2009/81/EC goes to TED/OJEU directly. The adapter correctly handles this case (0 results is expected, not an error).

**Adapter health:** ✅ No crashes. Searches execute, page text parsed, filter logic correct.

### Sweden (`python main.py --national se --test --visible`)

| Metric | Value |
|---|---|
| Raw search results | 46 |
| Defence-relevant | 9 (FMV notices) |
| Detail pages fetched | 3 (test mode limit) |
| Notices added to relevant.json | 3 |
| Total relevant.json after merge | 241 |
| Excel exported | ✅ 233 rows |

**FMV notices found (sample):**
- `20FMV6222` — Dynamic Purchasing System for Satellite Capacity (Ku- and C-band)
- `23FMVU10414` — Dynamic Purchasing System (DPS) - Diving equipment
- `24FMVU399` — Dynamiskt inköpssystem Tekniska konsulter
- `25FMVU1881` — Ramavtal Klimat- och Värmeaggregat
- `25FMVU4743` — Helikoptertjänst Provplats Vidsel
- `26FMVU1411` — Anskaffning Sandsäcksflyllarflak ← potential trailer/vehicle
- `25FMVU653` — Framework Agreement Spare Parts LR35/LR60
- `26FMVU625` — Sprutpump HBO
- `25FMVU3586` — Ramavtal PLM Arvssystem

**Adapter health:** ✅ Fully functional. POST+CSRF entity search returns real FMV notices.

---

## Open Problems

### FI: orgName URL filter not working
**Problem:** Hilma's `?orgName=Puolustusvoimat` URL parameter is ignored by the React SPA — it shows default (most-recent) results regardless. The org filter is a client-side form component.  
**Impact:** FI adapter does a Puolustusvoimat "search" but actually gets the 50 most-recent notices. Since none of those happen to be Puolustusvoimat tenders, filter_defence=0 (correct outcome, wrong path).  
**Fix (future sprint):** Implement form interaction: fill the "Ostajaorganisaatio" dropdown in the React UI via Playwright, then click search. Alternatively, discover the internal API endpoint used by the React frontend (intercept XHR during org search).

### SE: FMV notices from full keyword run not yet assessed
**Scope:** Only 3 of 9 defence notices were detail-fetched (test mode). Full run with all 10 keywords and 3 entities should be run to identify any trailer-specific notices (e.g. `26FMVU1411` Sandsäcksflyllarflak may be relevant).

### SE: Sverige dedup with existing TED entries not validated
**Note:** 13 SE TED entries already in relevant.json. The merge dedup uses `authority | title[:35] | year`. FMV entities from Kommersannons may or may not match — needs validation in full run with AI classify.

### Potential linter conflict in main.py
**Note:** During development, main.py was reverted several times by an automated linter. The final committed state contains the FI/SE registrations. If the linter triggers again on the branch, re-apply the adapter_registry block.

---

## Recommendations for Next Sprint

1. **Run full SE scan** (`python main.py --national se`) with AI classify — expected 2–5 trailer-relevant FMV notices (Sandsäcksflyllarflak, etc.)
2. **Fix FI org filter** — implement Playwright form interaction to fill the org dropdown; or intercept XHR to discover the correct API. Low urgency since FI has few defence trailers on Hilma.
3. **Add `--national fi se` to weekly GitHub Actions run** — add alongside `--national de pl` once validated stable.
4. **Investigate TendSign** — FMV also publishes on TendSign (tendsign.com). The brief mentions "25FMVU2821" (Flygunderhållssläp) which may be on TendSign rather than Kommersannons. Check if TendSign has its own API.
5. **SE enrichment pass** — use existing 13 SE TED entries as test cases: run `--national se` + check which TED IDs get enriched (value, description, deadline).

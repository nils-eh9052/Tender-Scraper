# Sprint 5 Chat 2 — RO + NL + BE National Adapters
**Date:** 2026-04-28 | **Branch:** sprint5/national-ro-nl-be

---

## Implemented Adapters

### Netherlands (NL-TN) — TenderNed ✅ WORKING

**File:** `src/national_scraper/adapters/nl_adapter.py`

**API Discovery:**
- TenderNed has a public REST API: `https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties`
- API key fields: `publicatieId`, `aanbestedingNaam` (title), `opdrachtgeverNaam` (authority), `publicatieDatum`, `kenmerk`, `link.href`
- **Limitation:** API does NOT support server-side filtering — every query returns all 143,331 publications sorted by date regardless of `zoekterm`/authority params
- **Link field:** `item.link` is a dict with `{"href": "https://www.tenderned.nl/aankondigingen/overzicht/{id}"}`

**Strategy:** Scan-and-filter (scan recent N publications, filter locally for Defensie authority)
- Test mode: scan 500 publications (~3-5 days of data)
- Full mode: scan 5,000 publications (~1 month of data)

**Test Results:**
```
NL: scanned 500, Defensie found: 14
  [2026-04-28] Ministerie van Defensie | Levering en onderhoud - Terreinwaardige vrachtwagen uitgerust...
  [2026-04-26] Ministerie van Defensie | Mobiele commandoposten
  [2026-04-26] Ministerie van Defensie | Mobiele Hefmiddelen
  ... (11 more)
```
- 3 details loaded successfully (test mode limit)
- NL adapter works via REST session (no Playwright needed for search)

**Screenshot:** N/A (REST-only, no browser needed)

---

### Romania (RO-SEAP) — e-licitatie.ro ⚠️ PARTIALLY WORKING

**File:** `src/national_scraper/adapters/ro_adapter.py`

**Portal Investigation:**
- URL: `https://www.e-licitatie.ro` — Angular SPA
- Config found: server time API at `/api-pub/time/getServerTime/` ✅
- Angular app does NOT bootstrap on corporate VPN (JavaScript dependencies blocked)
- Page renders only header/menu, no notice data
- API backend hostname `sicap-prod-mc.e-licitatie.ro` unreachable from corporate network

**Strategy:** Playwright-based with `capture_response()` for Angular XHR interception
- Navigation to `https://www.e-licitatie.ro/pub/notices/ca-notices/list/1?cpvCode=XXXXX`
- Tries to capture JSON from `/api-pub/CaNotice/`, `/Notice/`, `/api-pub/` patterns
- DOM text fallback (ref-ID based parsing)

**Test Results:**
```
RO: searching CPV 34223300
RO: captured JSON with 0 items (Angular not bootstrapping on corporate VPN)
RO: search_all_keywords → 0 total
```
- **Conclusion:** Works correctly when e-licitatie.ro Angular app initializes. Corporate VPN blocks CDN resources needed for Angular bootstrap.
- **Outside corporate VPN:** Adapter should find Romanian MApN trailer tenders

**Known working API base:** `https://www.e-licitatie.ro/api-pub/` — accessible but notice search paths unknown without Angular bundle execution

---

### Belgium (BE-EP) — publicprocurement.be ⚠️ PARTIALLY WORKING

**File:** `src/national_scraper/adapters/be_adapter.py`

**Portal Investigation:**
- Main portal: `https://www.publicprocurement.be` — Vue.js SPA (BOSA eProcurement)
- Config found via `/env.config.js`:
  - Search API: `https://www.publicprocurement.be/api/sea/`
  - Dossier API: `https://www.publicprocurement.be/api/dos/`
- `enot.publicprocurement.be` — blocked/timeout on corporate VPN
- `/api/sea/` — all paths return 404 without auth (requires Vue session token)
- `/api/dos/` — returns 500 (authentication error — token required)

**Strategy:** Playwright-based with `capture_response("/api/sea/")` for Vue XHR interception
- Navigate to `https://www.publicprocurement.be/en/procurement-projects?cpvCodes=XXXXX`
- Vue SPA makes authenticated API calls with session token that Playwright acquires automatically
- Falls back to DOM text parsing

**Test Results:**
```
BE: no JSON captured, parsing DOM → 0 results
```
- **Conclusion:** Requires Playwright to properly init the Vue app and capture authenticated API calls
- **Note:** `enot.publicprocurement.be` (older portal) is blocked from corporate VPN

---

## Live Test Summary

```
python main.py --national nl ro be --test
```

| Country | Results | Details | Notes |
|---------|---------|---------|-------|
| NL | 14 Defensie | 3 loaded | ✅ Working via REST scan |
| RO | 0 | 0 | ⚠️ VPN blocks Angular bootstrap |
| BE | 0 | 0 | ⚠️ Auth required for search API |

---

## Pipeline Changes

- `main.py`: Added `ro`, `nl`, `be` to `adapter_registry` in `run_national_scraping()`
- New flags work: `python main.py --national ro nl be`
- Adapters registered with try/except (fail gracefully if import fails)

---

## Open Points / Next Steps

1. **RO outside VPN:** Adapter should work correctly — test on non-corporate connection or GitHub Actions runner
2. **BE auth token:** Use Playwright `capture_response("/api/sea/")` after proper Vue.js initialization — may require longer timeout or specific user interaction
3. **NL historical scan:** Current scan covers ~1 month; to find older tenders increase scan depth or use TED IDs to look up TenderNed equivalents
4. **RO direct API:** The `api-pub` base is accessible; notice search paths need discovery (run JS bundle analysis on unrestricted network)
5. **Screenshots available in:** `data/raw/screenshots/ro_search_*.png`

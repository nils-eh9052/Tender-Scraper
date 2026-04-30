# Sprint 11 Chat 1 Summary — UK-FTS Fix + CH Historical + GR/EE/LV/LT
**Date:** 2026-04-30  
**Branch:** `sprint11/fixes-new-countries`

---

## Task 1: UK-FTS Monthly Date Windows ✅

### Problem
365-day scan produced deep cursor chains. Cursor `546092` permanently broken at page 5 (Sprint 10), blocking the pipeline for ~40 minutes with 0 results.

### Fix
Rewrote `search_all_keywords` in `uk_fts_adapter.py` to use **monthly date windows** instead of one 365-day range.

```python
def _month_windows(start: date, end: date):
    """Yield (month_start, month_end) tuples covering start..end inclusive."""
```

- **Coverage**: January 2021 (post-Brexit FTS launch) → today = 64 months
- **Per-month**: fresh cursor, max 10 pages × 10 releases = 100 notices/month max
- **On cursor timeout**: skip remaining pages for that month, move to next month (fresh start)
- **Consecutive errors per month**: max 3 (was 5 globally)
- **Test mode**: last 90 days only, max 3 pages/month

### Test Result
```
UK-FTS: monthly scan 2026-01-30 → 2026-04-30, max 3 pages/month
UK-FTS: scan complete — 0 defence trailer notices from 12 pages / 120 releases scanned
```
12 pages scanned in 17 seconds (was ~40 min to hit 5/5 consecutive errors).  
0 results expected in test mode (last 90 days has no defence+trailer overlap).  
**No cursor timeouts.** Fix validated.

---

## Task 2: CH Historical ✅

### Changes
- `search_all_keywords` now always scans from `2024-07-01` (simap.ch platform relaunch), regardless of `--since` argument
- Increased CPV search max_results: 200 → 500
- Increased authority sweep max_results: 300 → 500
- Added `Schweizer Armee` to authority sweep list
- `_api_search` now handles 400 responses gracefully: if `newestPublicationFrom` causes HTTP 400 (when combined with cpvCodes), retries without the date filter

### archiv.simap.ch
No public REST API found for the pre-July 2024 archive. Manual browsing is possible at https://www.archiv.simap.ch but no programmatic access without CAPTCHA bypass. Documented in adapter docstring.

---

## Task 3: Greece (GR) — Promitheus ✅ (Stub)

**Status: Stub registered, screenshots taken, full implementation deferred to Sprint 12.**

### Discovery
- Homepage loads successfully: `https://www.promitheus.gov.gr`
- Public search ("Αναζήτηση") visible on homepage — no login required for search
- Both `AADP` and `GDAEE` URLs redirect to the same portal homepage (no separate ΓΔΑΕΕ sub-portal)
- Oracle ADF WebCenter architecture — requires javax.faces.ViewState for form POST
- Screenshots saved: `data/raw/screenshots/gr_promitheus_search.png` + `gr_gdaee_portal.png`

### Sprint 12 TODO
1. Extract ViewState from Αναζήτηση form
2. POST search with CPV 34223 or keyword "ρυμουλκούμενο"
3. Parse HTML table results

Note: Greek tenders above EU threshold appear on TED — this adapter adds below-threshold coverage.

---

## Task 4: Estonia (EE) — riigihanked.riik.ee ✅ (Stub)

**Status: Stub registered with REST API attempt + graceful 404 handling.**

### Discovery
- `POST /rhr-web/api/v1/procurements/search` → HTTP 404
- API endpoint has moved or been renamed since discovery
- Adapter detects 404 on first call, sets `_api_works = False`, returns empty without crashing

### Sprint 12 TODO
1. Open riigihanked.riik.ee in browser with DevTools Network tab
2. Search for "haagis" and intercept the XHR request
3. Copy URL and body format → update `EE_SEARCH_URL` and `_api_keyword_search()`

---

## Task 5: Latvia (LV) — eis.gov.lv ✅ (Stub)

**Status: Stub registered, session requirement discovered.**

### Discovery
- Direct navigation to `/EKEIS/Supplier/Procurement?Title=piekabe` → ASP.NET session error
  `"Sistēmas kļūda / System error"` (Error Id: 20260430151935526)
- Portal requires a valid session cookie established from the homepage first
- Browser adapter updated: now visits homepage first to establish session, then navigates to search
- RSS feed at `/EKEIS/Supplier/Procurement/Rss` likely also requires session (not tested)
- Screenshot saved: `data/raw/screenshots/lv_search_piekabe.png`

### Sprint 12 TODO
1. Navigate to `https://www.eis.gov.lv/` first (establish session)
2. Navigate to search with cookie — parse results
3. Alternative: Latvian Open Data portal (`data.gov.lv`) for bulk tender CSV export

---

## Task 6: Lithuania (LT) — cvpp.eviesiejipirkimai.lt ✅ (Stub)

**Status: Stub registered, React SPA routing discovered.**

### Discovery
- `GET /api/procurements` → HTTP 404 (REST endpoint not found)
- `Browser navigation /Notice/Search` → HTTP 404 (SPA virtual route, not server-side)
- Portal is a React SPA — all routes are client-side, direct URL navigation 404s before React loads
- Browser adapter updated: navigates to homepage and waits for React to initialize
- Screenshot saved: `data/raw/screenshots/lt_search_priekaba.png` (blank ASP error page — old path)

### Sprint 12 TODO
1. Navigate to homepage (`https://cvpp.eviesiejipirkimai.lt/`)
2. Wait for React to load, intercept XHR search request
3. Copy API path and request format
4. Alternative: Lithuanian Open Data (`data.gov.lt`) for tender datasets

---

## Code Changes Summary

| File | Change |
|------|--------|
| `uk_fts_adapter.py` | Full rewrite: monthly windows, `_month_windows()` helper, per-month cursor reset |
| `ch_adapter.py` | Historical start `2024-07-01`, increased limits 200/300 → 500, 400-fallback in `_api_search` |
| `gr_adapter.py` | NEW stub with discovery notes + Promitheus homepage navigation |
| `ee_adapter.py` | NEW REST API attempt (graceful 404) + stub fallback |
| `lv_adapter.py` | NEW RSS/browser adapter + session-first browser navigation |
| `lt_adapter.py` | NEW REST API attempt + SPA-aware browser fallback |
| `main.py` | Registered: gr, ee, lv, lt (total adapters: 21) |

---

## Adapter Test Results

| Adapter | Test Result | Notes |
|---------|------------|-------|
| GB (UK-FTS) | 0 results, 12 pages, 17s | Monthly windows working, no timeouts |
| GR | 0 results (stub) | Homepage loaded, screenshots taken |
| EE | 0 results (stub) | API 404 — graceful fallback |
| LV | 0 results (stub) | Session error — browser fix applied |
| LT | 0 results (stub) | SPA routing — browser fixed to homepage |
| CH | (not re-tested) | Historical date params added |

---

## Open Issues → Sprint 12

| Priority | Issue | Next Step |
|----------|-------|-----------|
| HIGH | EE API endpoint wrong | XHR intercept on riigihanked.riik.ee to find correct path |
| HIGH | LV session management | Navigate homepage → session → search |
| HIGH | LT React SPA routes | XHR intercept on cvpp.eviesiejipirkimai.lt |
| MED | GR ADF form scraping | Extract ViewState + POST search |
| MED | UK-FTS 0 defence results | Run full 64-month scan to confirm fix vs. no matching notices |
| LOW | CH historical | Verify newestPublicationFrom works for standalone keyword queries |

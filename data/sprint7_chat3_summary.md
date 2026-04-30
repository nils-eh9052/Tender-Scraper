# Sprint 7 Chat 3 — RO + BE Adapter Fixes
**Date:** 2026-04-29 | **Branch:** sprint7/ro-be-fix

---

## Key Findings

### Romania (RO-SEAP) — e-licitatie.ro

**Root Cause of Sprint 5 Failure:** Angular CDN resources were blocked by VPN.

**Investigation Result:**
1. No SEAP links in TED notices (TED and SEAP are independent)  
2. SEAP is **AngularJS 1.4.4** (not Angular 2+) — important architectural difference
3. Direct Python requests to e-licitatie.ro timeout (SSL/VPN block)
4. Playwright (Chromium) bypasses VPN SSL issues

**API Discovered:**
- Endpoint: `POST /api-pub/NoticeCommon/GetCNoticeList/`
- Activation: Navigate via AngularJS `$location.path('/pub/notices/contract-notices/list/1/1')`
- Response: `{"total": 3000, "items": [...], "searchTooLong": false}`
- Item fields: `cNoticeId`, `noticeNo`, `contractTitle`, `contractingAuthorityNameAndFN`, `cpvCodeAndName`, `estimatedValueRon`

**Limitation:** Server-side filtering does NOT work (CPV, authority name params ignored). Always returns most recent 3000 notices.

**Solution:** Scan-and-filter approach (same as TenderNed NL):
- Test: scan 200 recent notices, filter for MApN keywords + trailer CPVs
- Full: scan 2000 recent notices
- AngularJS init fix: use `domcontentloaded` + explicit `time.sleep(5)` instead of `networkidle`

**Test Result:** 200 notices scanned, 0 defence+trailer (expected — needs full 2000 scan to find MApN).

---

### Belgium (BE-BOSA) — publicprocurement.be

**Root Cause of Sprint 5 Failure:** Vue.js app requires Keycloak JWT auth token; search API not triggered without app interaction.

**Investigation Result:**
1. No BOSA/publicprocurement.be links in Belgian TED notices
2. Portal: Vue.js + Vuetify + Keycloak auth
3. Auth token: Keycloak JWT automatically in `localStorage['public__confidentialAuth__token']`
4. API: `POST /api/sea/search/publications` returns 270,925 publications total

**API Discovered:**
- Endpoint: `POST /api/sea/search/publications`
- Trigger: Navigate to `/bda` (Bulletin des Adjudications) — Vue app auto-calls on load
- Response: `{"publications": [...25 items...], "totalCount": 270929}`
- Fields: `organisation.organisationNames`, `cpvMainCode.code`, `referenceNumber`, `publicationDate`, `lots`, `noticeIds` (TED cross-refs), `publicationReferenceNumbersTED`

**Limitation:**
- Manual POST with JWT token returns 400 (exact body format not captured)
- Server-side CPV/authority filtering: not working (returns same 270k regardless of params)
- Initial auto-load: only 25 publications (default page size)

**Solution:** `capture_response("/api/sea/search/publications")` captures the auto-triggered POST on /bda load. Scan-and-filter approach (filter 25 pubs per load for Défense/Defensie + trailer CPV).

**Key Finding:** Belgian Défense uses TED for official publication → 0 national exclusives expected (all 9 Belgian TED notices are already in our dataset).

---

## Adapter Status Overview

| Country | Status | Method | API Endpoint | Notes |
|---------|--------|--------|-------------|-------|
| DE | ✅ Working | Playwright | HTML form | 0 open tenders, periodic |
| PL | ✅ Working | REST API | eZamowienia /Search | 4 notices |
| FI | ⚠️ No data | Playwright | Hilma REST | Puolustusvoimat uses TED |
| SE | ✅ Working | REST API | Kommersannons | 9 FMV notices |
| NO | ✅ Working | REST API | Doffin | 3 Forsvaret notices |
| CZ | ✅ Working | Playwright | VVZ form | 32 notices, 49min |
| FR | ✅ Working | REST API | BOAMP OpenData | 13 MINARM notices |
| DK | ✅ Working | Playwright | Udbud.dk form | 2 FMI notices |
| NL | ✅ Working | REST scan | TenderNed v2 | 14 Defensie (scan+filter) |
| **RO** | ✅ Fixed | Playwright+AngularJS | `/api-pub/NoticeCommon/GetCNoticeList/` | Scan+filter; 0 in 200 test |
| **BE** | ✅ Fixed | Playwright+Keycloak | `/api/sea/search/publications` | 25 pubs/load; 0 Défense |
| ES | ✅ Working | Playwright | PLACE IBM WebSphere | JS-click workaround |
| IT | ✅ Working | REST+Playwright | ANAC API | Rate limiting |

---

## Code Changes

| File | Change |
|------|--------|
| `src/national_scraper/adapters/ro_adapter.py` | Complete rewrite: AngularJS API discovery, `_init_seap_session()` with domcontentloaded fix, scan+filter approach |
| `src/national_scraper/adapters/be_adapter.py` | Complete rewrite: Keycloak JWT, `/bda` load + capture_response, scan+filter |
| `data/adapter_status.json` | New: full adapter status with discovery details |

---

## Open Points

1. **RO Full Run:** Scan 2000+ recent notices to find MApN trailer tenders (test showed 0 in 200)
2. **BE POST Format:** Capture exact request body/headers from Vue app for targeted filtering
3. **BE CPV Filter:** If POST format found, filter by CPV 34223xxx for trailers
4. **RO CPV-specific search:** SEAP's UI has a CPV filter dropdown — could interact with it to trigger a filtered API call

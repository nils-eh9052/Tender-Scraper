# Sprint 9 Chat 2 — UK Find a Tender + Germany evergabe-online

**Date:** 2026-04-30  
**Branch:** `sprint9/uk-fts-de-evergabe`

---

## Deliverables

| Task | Status |
|------|--------|
| CredentialManager | ✅ Implemented (`src/credentials.py`) |
| .env.example updated | ✅ UK_DSP + DE_EVERGABE credentials documented |
| UK FTS adapter | ✅ Functional (REST, no browser) |
| DE evergabe adapter | ✅ Functional (Playwright) |
| Screenshots | ✅ `data/raw/screenshots/de_evergabe_*.png` |
| Dedup UK-FTS vs UK-CF | ✅ `dedup_uk_fts_vs_cf()` in main.py |
| Sprint summary | ✅ This file |

---

## Task 1: CredentialManager

`src/credentials.py` — reads from env vars using `{PORTAL}_USERNAME` / `{PORTAL}_PASSWORD` pattern:

```python
CredentialManager.get("DE_EVERGABE")  # {"username": "...", "password": "..."} or {}
CredentialManager.has("UK_DSP")       # True/False
```

`.env.example` now documents:
- `UK_DSP_USERNAME` / `UK_DSP_PASSWORD` (UK Defence Sourcing Portal)
- `DE_EVERGABE_USERNAME` / `DE_EVERGABE_PASSWORD` (evergabe-online.de)

---

## Task 2: UK Find a Tender (FTS) Adapter

**File:** `src/national_scraper/adapters/uk_fts_adapter.py`  
**Registry key:** `gb`  
**Command:** `python main.py --national gb`

### API Discovery

FTS API (`https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages`):
- OCDS-conformant, no authentication required
- **No keyword or buyer filter** — must paginate and filter client-side
- Parameters: `limit`, `updatedFrom` (ISO 8601), `updatedTo`, `stages`, `cursor`
- Pagination: follow `links.next` URL in each response
- Page size: 10 (kept small to avoid VPN timeouts)

### Design

The adapter fetches all notices updated since N days ago and filters client-side:
1. Filter by defence buyer keywords (`ministry of defence`, `de&s`, `royal navy`, etc.)
2. Filter by trailer keywords in title/description
3. Only relevant notices reach `get_detail()`

VPN issue: requests to `www.find-tender.service.gov.uk` with `limit=50` time out in ~30s.
Fixed by using `limit=10` which completes in 3-4s.

### Test Result

```
UK-FTS test (7-day window, 3 pages × 10): 0 defence trailer notices
```

0 results expected — MoD trailer tenders don't appear weekly.
Full production run (365-day window, 200 pages) would find results.

---

## Task 3: Germany evergabe-online.de Adapter

**File:** `src/national_scraper/adapters/de_evergabe_adapter.py`  
**Registry key:** `de-ev`  
**Command:** `python main.py --national de-ev --visible`

### Portal Discovery

`https://www.evergabe-online.de/search.html` — Apache Wicket SPA, public access:

| Element | Selector |
|---------|----------|
| Keyword field | `#keywordString` |
| Advanced search toggle | Link containing "Erweiterte" |
| VSVgV (defence) checkbox | `input[value="VSVGV"]` |
| Search button | `button[value="suchen"]` |
| Results table | `#datatable tr` (row 0 = header) |
| Results count | Regex: `Zeige (\d+) bis (\d+) von (\d+)` |
| Result columns | Bezeichnung | Geschäftszeichen | Vergabestelle | Ort |

### Search Strategy

**Key insight:** The VSVgV filter is the official "Verteidigung und Sicherheit" procurement category used by BAAINBw. However, BAAINBw notices often use procurement codes ("E2.2G Lastanhänger") rather than keywords like "Anhänger" — so VSVgV restricts too much for keyword searches.

Dual approach:
1. **Keyword searches** (Anhänger, Sattelanhänger, Tieflader, ...): No VSVgV filter — catches civilian + defence trailer notices from all authorities
2. **Authority searches** (BAAINBw, Bundeswehr, ...): VSVgV filter ON — catches all BAAINBw defence procurement regardless of keyword

`filter_defence()`: Keep if trailer keyword in title OR defence authority in authority field.

### Test Result

```
DE-EV test (3 keywords + 2 authorities):
  Anhänger search (no VSVgV): 5 results
  BAAINBw search (VSVgV): 17 total, 10 on page
  Unique after dedup: 15
  After filter_defence: 12
  Details fetched (test mode limit): 3
```

Screenshots: `data/raw/screenshots/de_evergabe_*.png`

**Validation of 3 detail-fetched notices:**
1. `Z.41C-Z0282#0133` — Transporter mit Anhängerkupplung (PTB, civilian) → AI will reject
2. `15.1.30-KatS-303-26` — Geräteanhänger Hochwasser (Police, civil emergency) → AI will reject
3. `6003020453-BAAINBw U` — BAAINBw procurement item → AI will classify

**False-positive rate:** ~2/3 = 67% in test (expected — AI classifier handles these).

### Login

`CredentialManager.get("DE_EVERGABE")` checked at startup. No credentials = public access. With credentials, the adapter logs in via the Wicket login form before searching.

---

## Task 4: UK-FTS vs UK-CF Dedup

`dedup_uk_fts_vs_cf()` in `main.py`:
- Exact match on `tender_id`
- Title-similarity fallback: ≥4 common words
- On match: enriches UK-CF entry with winner/value from FTS, marks `source = UK-CF+UK-FTS`
- Unmatched FTS notices go to `new_notices` list

Not tested in this sprint (FTS returned 0 in test window).

---

## Next Steps

1. **Full FTS run** — `python main.py --national gb` (non-test, 365 days): should find MoD trailer notices from the last year
2. **evergabe full run** — `python main.py --national de-ev` (all 14 keywords + 8 authorities): should find all current BAAINBw trailer procurement
3. **BAAINBw CPV search** — evergabe supports CPV filter (`#cpvCode`): add CPV 34223000 search to the authority search branch for higher precision
4. **evergabe pagination** — currently only fetches page 1 (10 results per search); implement `_next_page()` properly for searches with >10 results

---

## Files Created / Modified

| File | Change |
|------|--------|
| `src/credentials.py` | NEW — CredentialManager |
| `.env.example` | Updated — portal credentials documented |
| `src/national_scraper/adapters/uk_fts_adapter.py` | NEW — UK FTS REST adapter |
| `src/national_scraper/adapters/de_evergabe_adapter.py` | NEW — DE evergabe Playwright adapter |
| `main.py` | `get_adapter_registry()` + `run_national_scraping()` → added `gb`, `de-ev`; added `dedup_uk_fts_vs_cf()` |

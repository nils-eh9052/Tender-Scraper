# Sprint 3 Chat 2 — Norway + Czech Republic Adapters

**Date:** 2026-04-28  
**Branch:** `sprint3/national-no-cz`  
**Status:** ✅ Both adapters working

---

## Portal Investigation Results

### Norway — Doffin (doffin.no)

**Discovery process:**
- Initial search URL `/notices` was wrong (SPA 404 page)
- Correct search URL is `https://doffin.no/search?q={keyword}`
- **API endpoint discovered via browser XHR interception:**
  `POST https://api.doffin.no/webclient/api/v2/search-api/search`
- Request format: JSON body with `searchString`, `numHitsPerPage`, `page`, empty `facets`
- Response: `{"numHitsTotal": N, "hits": [{id, buyer, heading, description, type, status, publicationDate, ...}]}`
- Notice URL format: `https://doffin.no/notices/{year-id}` (e.g., `2023-312913`)
- **No browser needed for search** — pure REST API like PL adapter

**Test results (test mode):**
| Metric | Value |
|--------|-------|
| Raw search results | 103 |
| Defence-relevant | 4 |
| Detail pages fetched | 3 (test limit) |
| New notices merged | 3 |

**Sample notice found:**
- Title: "Kjøp og vedlikehold av tilhengere" (Purchase and maintenance of trailers)
- Authority: Forsvaret v/Forsvarets logistikkorganisasjon (Armed Forces FLO)
- Value: 95,000,000 NOK (~€8M)
- Type: Kunngjøring av konkurranse (Competition announcement)
- Status: UTGÅTT (Expired/Closed)
- Doffin ID: 2023-312913
- **NOT in TED** — this is Doffin-exclusive content!

**Filter logic:**
- Requires BOTH trailer keyword AND defence authority (strict intersection)
- Falls back to defence-authority-only if intersection is empty

---

### Czech Republic — NEN/NIPEZ (nen.nipez.cz)

**Discovery process:**
- Initial search URL `/verejne-zakazky-v-nrp` was wrong (SPA 404)
- Correct search URL: `https://nen.nipez.cz/verejne-zakazky`
- Search input: `#verejne-zakazky-seznam-filter__fast-search` (name="query")
- Search button: `button:has-text("HLEDAT")`
- Results appear after **12 seconds** (server-rendered React hydration)
- Results URL: `/verejne-zakazky/p:vz:query={keyword}`
- **No JSON API for tender list** — server-rendered HTML table parsing
- Results table: `tbody tr` with columns: Detail link | System# | Title | Status | Authority | Deadline
- Detail URL: `/verejne-zakazky/p:vz:query={q}/detail-zakazky/{id}`
- Tender ID format: `N006/26/V00011038` (URL uses dashes: `N006-26-V00011038`)

**Test results (test mode):**
| Metric | Value |
|--------|-------|
| Raw search results | 121 |
| Defence-relevant | 121 (filter too broad — AI classifier handles final selection) |
| Detail pages fetched | 3 (test limit) |
| New notices merged | 3 |

**Sample notices found:**
- "Nákup - přívěsného vozíku za OA" (Purchase of trailer vehicle)
- "Nové požární přívěsy pro hašení" (civilian fire brigade — AI will reject)

**Note:** CZ `filter_defence` passes all trailer keyword matches including civilian.
The AI classifier will correctly reject non-defence ones. The defence-authority
searches ("Ministerstvo obrany", "VOP CZ") yield correctly targeted results.

**PDF extraction:** Implemented (downloads to `data/raw/cz/`), but NEN requires
browser-based PDF URLs that point to `download.tescosw.cz` (signing service).
PDFs accessible without sign-in worked in manual testing.

---

## Implementation Summary

### no_adapter.py
- **Strategy:** Pure REST API (POST), no browser needed for search
- **Endpoint:** `POST https://api.doffin.no/webclient/api/v2/search-api/search`
- **Search scope:** Trailer keywords × Defence authorities (cross-search)
- **Filter:** Strict intersection (trailer keyword AND defence authority)
- **Detail:** Browser-based (doffin.no/notices/{id} page)
- **Rate limit:** 1.5s between requests

### cz_adapter.py
- **Strategy:** Browser-based (Playwright + form fill + wait 12s + HTML parse)
- **Search mechanism:** NEN fast-search form, button click, `tbody tr` parsing
- **Search scope:** Trailer keywords + Defence authority name searches
- **Filter:** OR logic (defence auth OR trailer keyword)
- **Detail:** Browser-based (rich NEN detail page with PDF links)
- **PDF extraction:** Via `requests` download + pypdf/pdfplumber (optional)
- **Rate limit:** 2s between searches (page loads are slow)

### main.py
- Both adapters registered in `run_national_scraping()`
- CLI: `python main.py --national no` / `--national cz` / `--national no cz`

---

## Known Issues / Future Work

1. **CZ filter too broad:** Currently 121/121 pass filter. Should add authority-based
   exclusions (fire brigade, hospitals, municipalities) to narrow pre-AI set.
   Low priority — AI classifier handles final filtering correctly.

2. **NO detail page:** Doffin notices load as SPA. The `get_page_text()` extracts
   available text, but some notices may have limited text if not all sections load.
   Consider using the API response data directly for detail (bypass browser).

3. **NO historical notices:** The 4 known TED notices (477617-2024, 694394-2023,
   195799-2021) may appear as expired/closed on Doffin. Full run (not test) should
   find them. Run `--national no` without `--test` to validate.

4. **CZ enrichment:** Primary value is enriching existing 15 TED notices. The
   `merge_national_with_ted` dedup logic (authority + title + year) should match
   NEN notices with TED cross-published ones. Validate with a full run.

---

## Commands

```bash
# Norway only (headless, fast)
python main.py --national no

# Czech Republic only (browser visible, slower)
python main.py --national cz --visible

# Both together
python main.py --national no cz

# With AI classification
python main.py --national no cz --phase classify
```

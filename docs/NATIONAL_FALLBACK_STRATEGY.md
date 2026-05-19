# National Portal Fallback Strategy

> Sprint 2026-05-10 — Phase 3g Extension  
> Covers: `src/national_scraper/fallback/` + `src/document_pipeline/orchestrator.py` changes

---

## Problem

TED notices for DE, PL, and CZ tenders often contain a `tender_documents_access` URL pointing to the buyer's national procurement portal (evergabe-online.de, ezamowienia.gov.pl, verejnezakazky.vop.cz / nen.nipez.cz). These URLs:

- Expire after the tender closes (404/410)
- Require authentication (403/401) that we cannot satisfy
- Return empty pages (Content-Length < 1 KB)
- Were never populated in the TED-XML (field absent for older eForms)

Result: the document pipeline had no specs to extract for a significant fraction of relevant tenders.

---

## Architecture

```
orchestrator.run_extraction()
    │
    ├─ discover_for_notice()        # existing: TED PDF + Vergabeunterlagen URL
    │
    ├─ url_is_healthy() × N         # NEW: HEAD-check every non-synthetic URL
    │
    ├─ alive_refs == [] ?
    │   └─ _infer_country_code()   # DE / PL / CZ from URL domains
    │       └─ _run_national_fallback()
    │           ├─ search_de()     # evergabe-online.de + service.bund.de
    │           ├─ search_pl()     # ezamowienia.gov.pl REST API
    │           └─ search_cz()     # verejnezakazky.vop.cz + nen.nipez.cz
    │
    └─ Continue with download → extract → AI-structure
```

The fallback is **last-resort only**: it fires when `alive_refs` is empty AND the inferred country is in `{DE, PL, CZ}`. If the normal URL chain is alive, the fallback is never triggered.

---

## URL Health Check

`url_is_healthy(url, timeout=15)` in `src/document_pipeline/discovery.py`:

| Condition | Result |
|-----------|--------|
| Empty / not http(s) | False |
| `internal://` synthetic refs | Always True (bypassed) |
| HTTP 404 / 410 / 403 / 401 | False |
| HTTP 5xx | False |
| Connection error / timeout | False |
| `Content-Length` < 1 KB | False |
| Any other 2xx / 3xx | True |

Stats: `dead_urls` counter in the orchestrator print summary.

---

## Country Inference

`_infer_country_code(notice)` checks these signals in order:

1. `_raw._xml.tender_documents_access` domain → DE / PL / CZ
2. `_raw._xml.buyer_profile_url_full` domain
3. `_raw.buyer-internet-address` domain
4. `_country_normalized` field → "Germany" → DE, "Poland" → PL, "Czech Republic" → CZ

Domain-to-country mapping (excerpt):

| Domain fragment | Country |
|----------------|---------|
| evergabe-online.de, service.bund.de, vergabe.bund.de | DE |
| ezamowienia.gov.pl, platformazakupowa.pl, przetargi.gov.pl | PL |
| nipez.cz, nen.nipez.cz, vop.cz, zakazky.cz | CZ |

---

## Search Modules

### DE — `src/national_scraper/fallback/de_search.py`

Three strategies tried in priority order:

**Strategy 1: evergabe-online.de by tender ID**

If `tender_documents_access` contains `?id=NNNNN`, fetch:
- `https://www.evergabe-online.de/tenderdetails.html?id=NNNNN`
- Fallback: `https://www.evergabe-online.de/tenderdocuments.html?id=NNNNN`

Both pages are server-rendered HTML (no JavaScript required). Document links are extracted via regex patterns matching `/Download`, `/tenderDocuments`, `/downloadDocument`, and file extensions.

**Strategy 2: service.bund.de by internal_reference**

GET `https://www.service.bund.de/...Suche/Formular.html?templateQueryString={internal_ref}`.  
Parse `href="...IMPORTE..."` result links → fetch detail page.

**Strategy 3: service.bund.de by buyer + title keywords**

Same as Strategy 2 but query = `{buyer} {title_keywords[:3]}`.

**Field extraction** (`_parse_de_fields`):
- Block-closing tags (`</p>`, `</div>`, `</li>`, `</tr>`) → `\n` before stripping tags, so winner regex `[^\n|<]{5,100}` doesn't bleed across paragraph boundaries
- Extracts: `winner`, `quantity` (Stück/Fahrzeuge/Anhänger), `contract_duration` (Laufzeit/Vertragsdauer), `value` (EUR amounts > 100)

---

### PL — `src/national_scraper/fallback/pl_search.py`

Uses the **ezamowienia.gov.pl REST API** (no browser, no authentication):

**API endpoints:**
- `POST /Board/Search` — paginated search by query string
- `GET /Board/GetNoticeHtmlBodyById/{notice_id}` — HTML body of a notice

**Matching priority:**
1. Exact `internal_reference` match against `referenceNo` field
2. Keyword score (title word overlap ≥ 1 with buyer name match)
3. First result if query returns ≥ 1 item

The HTML body is stripped and returned as a `national_page_text` DocumentRef (inline text, no download needed).

**Field extraction** (`_parse_pl_fields`):
- Extracts: `winner` (Wykonawca/Wybrano), `quantity` (szt./sztuk/pojazdów), `contract_duration` (miesięcy/tygodni), `value` (PLN/EUR amounts)

---

### CZ — `src/national_scraper/fallback/cz_search.py`

Two portals tried in order:

**VOP (verejnezakazky.vop.cz):**
- If `tender_documents_url` contains `?id=vz\d+`, extract VOP ID → GET detail page
- Parse PDF/DOCX links + structured fields
- Minimum page size: 500 bytes

**NEN (nen.nipez.cz):**
- Search URL: `https://nen.nipez.cz/en/verejne-zakazky?search={query}`
- Parses `__NEXT_DATA__` JSON blob (Next.js SSR) for `searchResults` array
- Falls back to HTML table row parsing if JSON not found
- Fetches NEN detail page: `/en/verejne-zakazky/detail-zakazky/{id}`
- Minimum page size: 1000 bytes (Next.js pages are larger)

**Field extraction** (`_parse_cz_fields`):
- Extracts: `winner` (Dodavatel/Vítěz), `quantity` (ks/kusů/vozidel), `contract_duration` (měsíců/týdnů), `value` (CZK/EUR amounts)

---

## Cache

Results are cached in `data/.national_fallback_cache.json`:

```json
{
  "682847-2024:DE": {
    "portal_url": "https://www.evergabe-online.de/tenderdetails.html?id=771723",
    "documents": [...],
    "additional_fields": {"winner": "Acme GmbH", "quantity": 50, ...},
    "cached_at": "2026-05-10T14:23:01"
  }
}
```

Cache key: `{tender_id}:{country}`.

Skip cache (force re-fetch): `python main.py --extract-documents --no-fallback-cache`

Cache hits are counted in the orchestrator stats as `fallback_cache_hits`.

---

## Data Merge

When a fallback result is found, `additional_fields` are merged non-destructively onto the notice using `_fallback_*` prefixed keys:

| Fallback field | Notice key |
|---------------|------------|
| `winner` | `_fallback_winner` |
| `quantity` | `_fallback_quantity` |
| `contract_duration` | `_fallback_contract_duration` |
| `value` | `_fallback_value` |

The portal URL is stored in `_source_url_national`. These fields do not overwrite existing AI-structured results (`_extracted_specs`).

---

## Orchestrator Stats (Print Summary)

```
Document Extraction — Phase 3g complete:
  Model used           : openrouter/openai/gpt-4o
  Notices checked      : 194
  Cache hits           : 142
  Docs discovered      : 38
  Dead URLs skipped    : 12
  Fallback triggered   : 12
  Fallback found docs  : 8
  Fallback cache hits  : 0
  Docs downloaded      : 26
  Text extracted       : 26
  AI calls made        : 52
  Sonnet fallbacks     : 3
  Skipped (no docs)    : 4
  Estimated cost       : $0.4820
```

---

## Testing

Unit tests: `tests/test_national_fallback.py` — 41 tests across 5 test classes:

| Class | Tests |
|-------|-------|
| `TestUrlIsHealthy` | 7 |
| `TestDeSearch` | 7 |
| `TestPlSearch` | 8 |
| `TestCzSearch` | 8 |
| `TestOrchestratorFallback` | 11 |

Run: `python -m pytest tests/test_national_fallback.py -v`

---

## Limitations

- **evergabe-online.de**: requires a valid `?id=` parameter in `tender_documents_access`; no full-text search on evergabe directly
- **service.bund.de**: detail pages describe the tender but rarely contain direct PDF download links — returned as `html` DocumentRef for AI text extraction
- **nen.nipez.cz**: Next.js SSR pages; `__NEXT_DATA__` structure may change without notice
- **Confidential defence tenders**: buyer portals may return 403 or empty pages even when the URL is technically alive
- **PL platformazakupowa.pl**: buyers who publish via platformazakupowa.pl are not searchable via ezamowienia API — only the buyer profile URL is available

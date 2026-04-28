# Sprint 5 Chat 3 — Summary: Spain (ES) + Italy (IT) National Adapters

**Date:** 2026-04-28  
**Branch:** sprint5/national-es-it  
**Coverage:** Spain PLACE + Italy ANAC portals  
**TED baseline:** ES=11 notices, IT=27 notices

---

## 1. Spain — ES-PL (PLACE / contrataciondelestado.es)

### Portal Details

- **URL:** https://contrataciondelestado.es
- **Technology:** IBM WebSphere Portal (JSF-based SPA)
- **Authentication:** None required for search (Atom/RSS feeds require client certificate — blocked)
- **Strategy:** Playwright navigation with JavaScript click workarounds

### Key Technical Findings

The PLACE portal's Atom syndication feeds return "Su certificado no está autorizado" for
unauthenticated access. The portal HTML loads correctly in headless Chromium.

IBM WebSphere Portal renders links as invisible DOM elements (JavaScript-managed visibility),
requiring `element.evaluate("el => el.click()")` to bypass Playwright's visibility check.

The licitaciones search form is at a dynamically-generated IBM Portal URL:
`/wps/portal/plataforma/buscadores/busqueda/!ut/p/z1/...`
Successfully navigated to via JS click from the buscadores menu page.

Search results are rendered with minimal metadata: only a "Detalle" (Detail) link per result.
Full tender data (title, authority, value) is only available on the individual detail pages.
`filter_defence` passes all detalle links through to `get_detail()` enrichment.

### Search Flow

```
Navigate to /buscadores → JS click "busqueda" link → Fill form input via JS
→ JS submit → Wait 6s for IBM Portal render → Parse detalle links
→ filter_defence (pass all — detail page enrichment) → get_detail() per result
```

### Test Results

```
Keywords searched (test mode): "remolque", "semirremolque"
Raw search results:  1
Defence-relevant:    1 (passes through — detail page enrichment handles filtering)
Detailed notices:    1
Merged into dataset: 1
```

### Known Limitations

- IBM WebSphere Portal is slow (~15s per search query)
- Search result metadata is sparse — titles come from detail pages
- Result count is low in headless mode (IBM Portal may limit headless access)
- The "Detalle" navigation breadcrumb link is also captured — filter_defence
  passes only links with "detalle" in the URL

### Screenshots

- `data/raw/screenshots/es_place_buscadores.png` — PLACE buscadores menu
- `data/raw/screenshots/es_place_licitaciones_search.png` — Licitaciones search form

---

## 2. Italy — IT-AN (ANAC / anticorruzione.it)

### Portal Details

- **URL:** https://www.anticorruzione.it
- **Technology:** Liferay 7 CMS
- **Authentication:** None required
- **Strategy:** REST HTML search (fast path) + Playwright fallback
- **Note:** `dati.anticorruzione.it` is blocked by WAF from corporate network

### Key Technical Findings

The main ANAC portal (`www.anticorruzione.it`) is accessible with standard HTTP headers.
The `risultati-ricerca?q=keyword` URL returns HTML search results that can be parsed
without JavaScript (REST HTML approach works).

The Liferay headless REST API (`/o/headless-delivery/v1.0`) is not directly accessible
(returns errors), but the HTML search endpoint works.

Rate limiting: ANAC imposes connection limits; repeated requests may timeout (504/Gateway Timeout).
Strategy: try REST first, Playwright fallback on timeout.

ANAC covers ALL Italian public procurement (not just defence). Our searches return
general trailer tenders from municipalities, hospitals, schools, etc. Defence filtering
happens at the AI classifier step (the CLASSIFIER_PROMPT checks authority type).

### Search Flow

```
REST GET /risultati-ricerca?q=keyword → parse HTML links → filter_defence (pass all)
→ If REST fails: Playwright loads same URL → parse HTML → filter_defence → get_detail()
```

### Test Results

```
Keywords searched (test mode): "rimorchio", "semirimorchio"
Raw search results:  1-16 (varies by ANAC availability)
Defence-relevant:    All passed through (AI classifier handles authority check)
Detailed notices:    1-3 (ANAC rate limits detail page access)
Merged into dataset: 1-3
```

### Known Limitations

- ANAC rate limits: frequent requests may get 504 Gateway Timeout
- Results include ALL Italian trailer procurement (not just defence)
- AI classifier is the key defence filter for Italy (more expensive than pre-filter)
- `dati.anticorruzione.it` (structured data API) is blocked by corporate VPN WAF
- Combined searches ("rimorchio difesa") also subject to rate limiting

### Screenshots

- `data/raw/screenshots/it_anac_home.png` — ANAC portal homepage
- `data/raw/screenshots/it_anac_rimorchio_results.png` — Search results (or timeout screenshot)

---

## 3. Architecture Summary

| Aspect | Spain (ES-PL) | Italy (IT-AN) |
|--------|--------------|--------------|
| Search method | Playwright (IBM Portal JS forms) | REST HTML (Liferay search) + Playwright fallback |
| Result metadata | Sparse (detail links only) | Sparse (title links, no authority) |
| Defence pre-filter | Passes all detalle links | Passes all results (AI handles) |
| Rate limiting | Slow but stable (~15s/search) | Intermittent (504 timeouts) |
| Detail fetch | Playwright — works | REST GET — works when accessible |
| Coverage scope | All Spanish public procurement | All Italian public procurement |
| Expected national-only finds | ~5-15 below-threshold tenders | ~10-30 below-threshold tenders |

## 4. Files Created

| File | Description |
|------|-------------|
| `src/national_scraper/adapters/es_adapter.py` | Spain PLACE adapter (IBM WebSphere + JS click) |
| `src/national_scraper/adapters/it_adapter.py` | Italy ANAC adapter (REST HTML + Playwright fallback) |
| `data/raw/screenshots/es_place_*.png` | Spain portal screenshots |
| `data/raw/screenshots/it_anac_*.png` | Italy portal screenshots |

## 5. Registration in main.py

Both adapters registered in `run_national_scraping()`:
```python
adapter_registry["es"] = (ESAdapter, create_es_config)
adapter_registry["it"] = (ITAdapter, create_it_config)
```

CLI usage:
```bash
python main.py --national es it --test
python main.py --national es it
python main.py --national es it --visible  # Show browser
```

## 6. Recommended Next Steps

1. **ES PLACE full run:** Run without `--test` to get all 10 keyword results
2. **IT ANAC full run:** Add exponential backoff for rate limiting; run overnight
3. **Italy AI cost:** Since IT filter_defence passes all results, ~30-50 Haiku classify calls per run
4. **ES authority enrichment:** Add DGAM/Ministerio de Defensa authority detection on detail pages
5. **Combined searches:** "rimorchio difesa", "rimorchio esercito" for better IT precision

# NSPA Adapter — Architecture & Usage

**Module:** `src/national_scraper/adapters/nspa_adapter.py`
**Registry key:** `nspa` (24th adapter overall, special — not a country)
**Status as of 2026-05-17:** Infrastructure ready, current trailer-yield ~1 (Boxer RegSan retrofit kit)

---

## 1. Purpose

Pull the **public NSPA eProcurement5G FBO + RFP listings** so the pipeline catches
NATO-direct trailer/vehicle opportunities when they appear. NSPA opportunities
are NATO-wide (32 member states procuring jointly) and are NOT cross-published
to TED — without this adapter they would be invisible to BPW.

Today's listing is dominated by missile/spare-parts (PzH2000, TOW), so trailer
yield is low. Adapter is positioned as **fall-through-after-national** and runs
on-demand via `--national nspa` (not part of the default `--all` parallel
sweep to avoid burning quota on a low-yield source).

---

## 2. Architecture

```
NSPAAdapter (Playwright-based, inherits BaseAdapter)
  │
  ├── search_all_keywords()
  │     ├── _scan_prefilter("FBO")    # 329 opportunities, 33 pages
  │     ├── _scan_prefilter("RFP")    #  97 opportunities, 10 pages
  │     └── Dedupe by reference, filter by NSPA_TRAILER_KEYWORDS
  │
  ├── _scan_prefilter(prefilter)
  │     ├── page.goto(LIST_URL_FMT.format(prefilter=...))
  │     ├── wait_for_selector("table.table-condensed tr.selectable")
  │     ├── Loop pages 1..N:
  │     │     ├── parse_listing_html()
  │     │     ├── snapshot first-row reference
  │     │     ├── page.evaluate(click('a.page-link[load-page]', text===str(p)))
  │     │     └── poll for first-row change (up to 12s)
  │     └── Returns row dicts
  │
  ├── get_detail(SearchResult)
  │     ├── page.goto(detail_url)
  │     ├── parse field-value pairs from rendered text
  │     └── extract attachment filenames (URLs not fetchable — Knockout-bound)
  │
  └── filter_defence(): identity (NSPA is defence-by-definition)
```

**Throttling:** `PAGE_WAIT_MS = 5000` between page-loads, `DETAIL_WAIT_MS = 3500`
for detail pages. Without this, NSPA returns `Connection reset by peer` after
3-5 burst requests.

---

## 3. Selectors / Wire Format

| Element | Selector |
|---------|----------|
| List rows | `table.table-condensed tr.selectable` |
| Detail link in cell 0 | `tr.selectable td:first-child a[href]` |
| Pager links | `a.page-link[load-page]` (boolean attr `command` + JSON `load-page='{"pageIndex": N}'`) |
| Total row count | `input#GridPagerTotalRowCount[value]` |
| Attachment links | `a[data-bind*="DownloadFile"]` (Knockout-bound, no fetchable href) |

---

## 4. Schema Output

`NoticeDetail` fields produced:
- `title` ← `Product Name`
- `description` ← Synthesized: `Type: X | Tentative RFP Date: ... | Attachments: ...`
- `authority` ← `Purchasing Organisation` (e.g. "LM / Rockets and Missiles")
- `date` ← `Publication Date` (ISO `YYYY-MM-DD`)
- `reference_id` ← `Opportunity Id` (e.g. `26LMS042`)
- `url` ← Detail-page URL
- `source_code` ← `"NSPA-EP"`
- `raw_text` ← JSON dump of `{data_fields, attachments, url, source}` (≤10kB)

After `BaseAdapter.to_standard_format()`:
- `tender_id = "NATO-26LMS042"` (country-code "NATO" prefix)
- `_country_normalized = "NATO"`
- `_status = "Open"` (default for FBO/RFP)
- `_source = "NSPA-EP"`

---

## 5. License & Compliance

- **Public opportunity list:** OK to scrape (portal is by design open to non-NATO suppliers).
- **Attachments (DOCX/PDF):** Adapter does NOT download. Even when visible, NSPA
  attachments may contain export-controlled tech specs. Document-pipeline (`Phase 3g`)
  is opt-in and currently SKIPS NSPA (no fetchable URLs anyway).
- **BPW position:** Registered NATO supplier (NCAGE-eligible) — pulling public
  metadata for prospect screening is the intended use.
- **Frontend display:** OK for title/reference/authority/date/status. Description
  is auto-synthesized from public field-values (never attachment content).

---

## 6. Usage

```bash
# Standalone (manual trigger — recommended due to throttling)
python main.py --national nspa --visible       # see browser; useful for debugging
python main.py --national nspa                 # headless

# Combined with other national sources
python main.py --national de pl cz nspa --since 2026-01-01
```

NOT part of default `--all` because: low yield + slow (~3 min for full scan due to throttling) + occasional rate-limit retries.

---

## 7. Known Limitations

1. **Burst rate-limit:** > 3-5 requests per minute trigger `Connection reset`.
   Adapter throttles to ~5s/request; full FBO scan = 33 pages × 5s = ~3 min.
2. **No attachment download:** Knockout `DownloadFile()` handlers need a logged-in
   session + `fileIdentifier` decryption. Out of scope.
3. **Pager-page-2-update:** XHR fires on `a.page-link[load-page]` click, but
   render lag varies. Adapter polls first-row href change for up to 12 s; if no
   update, stops scan early (logs INFO).
4. **No fulltext description:** Detail page only has labeled key-value pairs,
   no free-text body. Description is synthesized from field-values.
5. **No value/currency:** NSPA listings have no `value` field — `_value_amount`
   stays empty, `value_eur` defaults to 0 (filter-engine rule: `0/None → KEEP`).
6. **No country breakdown:** NSPA opportunities are NATO-wide. Adapter tags
   `country=NATO` (special — not in ISO-3166). Frontend may need to extend
   `_ISO3` map if NATO badge is desired.

---

## 8. Current Yield (2026-05-17)

- Total scanned: **330** FBO + **97** RFP = 427 unique opportunities
- BPW-trailer-relevant: **1** (`26LMS042 — Notification of Planned Sole Source
  Award. Boxer RegSan Retrofit Drive Module Kit`)
- Boxer RegSan is a borderline case — vehicle subsystem retrofit; potentially
  in BPW's scope (driver-area module of armored medical vehicle).
- All other 326 FBOs = missile spare-parts (PzH2000, TOW, KNDS, Rheinmetall).

The adapter remains valuable as **future-monitoring infrastructure**: when NATO
agencies tender for trailer fleet replacements or logistics-trailer programmes,
they will appear here first.

---

## 9. Testing

```python
# Quick reachability + page-1 smoke test
from src.national_scraper.core import BrowserCore
from src.national_scraper.adapters.nspa_adapter import NSPAAdapter, create_nspa_config

cfg = create_nspa_config()
with BrowserCore(headless=True, slow_mo=100) as browser:
    adapter = NSPAAdapter(browser, cfg)
    matches = adapter.search_all_keywords(test_mode=True)
    for m in matches:
        print(m.reference_id, m.title)
```

Expect ≥1 match (Boxer RegSan, 26LMS042) when current NSPA listing has it.

---

## 10. Files

- `src/national_scraper/adapters/nspa_adapter.py` — adapter implementation
- `docs/NSPA_PORTAL_INVESTIGATION_260514.md` — initial investigation
- `data/nspa_scan_dump.json` — 330-row baseline dump (2026-05-14)
- `data/nspa_landing_full.html` — sample listing HTML (gerendert)
- `data/nspa_detail_sample.html` — sample detail-page HTML (26LMS042)
- `data/adapter_status.json` — status entry (entry: `nspa`)

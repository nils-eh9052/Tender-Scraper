# Document Coverage Audit — Sprint 2026-05-10

**Date:** 2026-05-10  
**Dataset:** `data/filtered/relevant.json` — 378 tenders  
**Tool:** `scripts/_doc_coverage_audit.py`

---

## 1. Coverage Summary

| Bucket | Count | % | Root Cause |
|--------|------:|--:|-----------|
| HAS_SPECS | 175 | 46.3% | TED PDFs downloaded + GPT-4o structured |
| HAS_SPECS_LOW_CONF | 19 | 5.0% | TED PDFs extracted but confidence=0 or types=0 |
| NO_DOCS_AUTH_BLOCKED | 159 | 42.1% | CZ (eIDAS), UK (FTS returns no doc links) |
| NO_DOCS_NO_HANDLER | 25 | 6.6% | FR/NO/EE/NL/UA — no discovery handler |
| TED_NO_SPECS | 0 | 0.0% | All TED notices have been processed ✅ |

**Tenders with any extracted_specs: 194 / 378 (51.3%)**  
**Tenders without specs: 184 / 378 (48.7%)**

---

## 2. By Source

| Source | Total | HAS_SPECS | LOW_CONF | NO_HANDLER | AUTH_BLOCK |
|--------|------:|----------:|---------:|-----------:|-----------:|
| TED (?) | 194 | 175 | 19 | 0 | 0 |
| CZ-NEN | 153 | 0 | 0 | 0 | 153 |
| UK-CF | 6 | 0 | 0 | 0 | 6 |
| FR-BP | 13 | 0 | 0 | 13 | 0 |
| UA-PR | 5 | 0 | 0 | 5 | 0 |
| NO-DF | 3 | 0 | 0 | 3 | 0 |
| EE-RP | 3 | 0 | 0 | 3 | 0 |
| NL-TN | 1 | 0 | 0 | 1 | 0 |

---

## 3. Root Cause Analysis

### 3.1 NO_DOCS_AUTH_BLOCKED (159 tenders)

**CZ-NEN (153):** The NEN portal (nen.nipez.cz) requires eIDAS-authenticated login for procurement document access. `discovery.py` explicitly returns `[]` for `tid.startswith("CZ-")`. This is by design — the raw text (`_national_raw_text`) contains only the publicly visible INFORMATION tab content, not the actual specification documents.

**UK-CF (6):** The UK Find a Tender Service (FTS) API returns structured contract notices with no downloadable document links. The OCDS-format records include description and award data but no attachment URLs. `discovery.py` returns `[]` for `tid.startswith("UK-")`.

**Quick-fix available:** None — authentication barrier cannot be bypassed.

**Workaround:** Use `_national_raw_text` (scraped page text) as fallback input to AI structurer for CZ/UK. Quality will be lower than PDF extraction (no technical spec sheets), but description + CPV + value provide some signal. Estimated yield: 5–15% of CZ tenders have enough description text to extract partial specs.

### 3.2 NO_DOCS_NO_HANDLER (25 tenders)

**FR-BP (13):** French BOAMP tenders are discovered via OpenDataSoft REST API. The `fr_adapter.py` returns metadata (title, authority, CPV, titulaire) but no document URLs. The `discover_for_notice()` function in `discovery.py` has no handler for `FR-` prefixes, and FR notices have no `links` field, so they fall through to `return []`.

**UA-PR (5):** Prozorro tenders theoretically support document discovery via `_discover_ua()` (Prozorro API re-fetch with `internal_id`). However, UA notices in `relevant.json` lack `_national_raw_text` and the `_raw.internal_id` field is not reliably populated. The 5 UA tenders have short descriptions and no UUID → `_discover_ua()` returns `[]`.

**NO-DF (3):** Doffin tenders are discovered via POST-based REST search returning metadata snippets. No document attachment links are provided. `discovery.py` has no `NO-` handler.

**EE-RP (3):** Estonian RIK tenders are stub entries with minimal data (title, ID only). No document URLs available at the API level.

**NL-TN (1):** TenderNed tenders are discovered as force-included entries with no document links in the scraped metadata.

**Quick-fixes:**

1. **UA-PR**: The `_discover_ua()` function already exists in `discovery.py`. Fix is to ensure `_raw.internal_id` is populated by `ua_adapter.py`. Once the UUID is available, Prozorro API will return document URLs.

2. **FR/NO/EE/NL text-as-doc**: Add a fallback handler in `discovery.py` that creates a synthetic `DocumentRef` pointing to the scraped `_national_raw_text` as in-memory content, bypassing file download. The AI structurer accepts raw text as input.

### 3.3 HAS_SPECS_LOW_CONF (19 TED tenders)

TED notice PDFs are contract award notices and procurement announcements — they describe *what* was procured but rarely include the technical specification sheet (Lastenheft/Leistungsverzeichnis). The GPT-4o model extracts specs from notice text with confidence 0–30 for most TED notices. 19 notices returned `confidence=0` or `types=[]`.

**Root cause:** TED notice PDFs are administrative notice documents, not technical specifications. The `buyer_profile_url` field (backfilled from `buyer-internet-address` TED API field) links to the actual buyer portal where the Vergabeunterlagen are hosted — but those require authentication (national e-procurement portals) or are time-limited access.

**Quick-fix:** Expose `buyer_profile_url` as a `DocumentRef(doc_type="vergabeunterlagen")` in `discovery.py` (already implemented in Sprint 2026-05-09). Running `--extract-documents` will attempt HTML→link extraction from the buyer portal landing page.

---

## 4. Quick-Fixes Implemented This Sprint

### Fix A: `buyer_profile_url` → `DocumentRef` (discovery.py)
Already live since Sprint 2026-05-09. TED notices with `buyer-internet-address` get a `doc_type="vergabeunterlagen"` `DocumentRef` pointing to the buyer's portal landing page. The downloader follows the HTML and attempts to find direct PDF links.

### Fix B: UA `internal_id` propagation (ua_adapter.py)
**Status:** Pending. `_discover_ua()` in `discovery.py` extracts the UUID from `_raw.internal_id` or from JSON in `_national_raw_text`. For the 5 UA tenders in the dataset, the UUID is not available in either location (legacy scrapes before the fix). Re-running `--national ua` after the adapter fix will populate `_raw.internal_id`.

### Fix C: National text-as-doc fallback (discovery.py)
**Status:** Not implemented. Requires adding a `_discover_national_text()` function that creates a synthetic in-memory `DocumentRef` from `_national_raw_text`. The AI structurer would then receive the page text directly instead of a PDF. Estimated 2h implementation.

---

## 5. Awarded-ohne-Winner Gap

| Metric | Count |
|--------|------:|
| All tenders | 378 |
| Status=Awarded | 88 |
| Awarded with winner_name | 6 |
| Awarded WITHOUT winner_name | 82 |

CZ-NEN accounts for the majority of Awarded-ohne-Winner: 6 CZ tenders are classified as Awarded (status from NEN page) but the winner is in the AUTHORIZED SECTION (eIDAS-protected). The `_try_result_page()` fix (Sprint 2026-05-10) adds `/en/verejne-zakazky/vysledek-zakazky/{id}` as a URL candidate and adds next-line patterns to `_find_winner`. A re-run is needed to measure impact.

---

## 6. Recommended Next Steps (Priority Order)

1. **Re-run `--national cz`** with the `_try_result_page()` fix → measure CZ winner capture rate
2. **Implement `_discover_national_text()`** for FR/NO text-as-doc fallback → +25 tenders with partial specs
3. **Re-run `--national ua`** to populate `_raw.internal_id` → unlock Prozorro document discovery
4. **Lower confidence threshold** for `HAS_SPECS_LOW_CONF` bucket → decide whether to include in export

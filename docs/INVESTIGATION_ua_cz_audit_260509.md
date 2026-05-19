# UA/CZ Adapter Gap Investigation — 2026-05-09

## Executive Summary

Investigation of 4 UA (Prozorro) and 5 CZ (NEN/NIPEZ) sample tenders against their live portal data.
Key findings: UA adapter misses delivery specs, documents, and proc method details. CZ adapter fails to extract status, CPV, winner, and deadline. All 281 downloaded CZ "PDFs" are auth-blocked HTML redirects. One UA technical specifications docx was successfully fetched and contains critical trailer parameters (mass, dimensions, axle load).

---

## 1. Sample-Tender UA (4+1 Stück)

> Note: Only 4 UA National tenders exist in relevant.json (plus 1 force-included with no raw data).
> 3 were fetched live from Prozorro API. 1 (UA-UA-2026-04-08-011067-a) is confidential/removed from public API.

| tender_id | Value (UAH) | Felder im API | Felder im Adapter | Lücken |
|-----------|------------|---------------|-------------------|--------|
| UA-2026-05-05-004789-a | 638,000 | title, status, tenderID, procurementMethod, procurementMethodType (belowThreshold), mainProcurementCategory, value (amount/currency/vatIncluded), procuringEntity (name, identifier/UA-EDR, address, contactPoint, **kind=defense**), tenderPeriod, enquiryPeriod, items (desc, qty=16, unit=H87, cpv=34223310-2, deliveryDate, deliveryAddress), lots (value, minimalStep, guarantee), documents (5x .docx), criteria (15 ESPD), milestones (2), guarantee, awardCriteria, submissionMethod, plans | title, authority, value, currency, date, description (truncated JSON), quantity (sum of item.quantity), winner (empty) | **status**, procurementMethodType, procuringEntity.address, procuringEntity.contactPoint, procuringEntity.kind=defense, tenderPeriod/enquiryPeriod, items.unit, items.cpv_description, items.deliveryDate, items.deliveryAddress, guarantee, awardCriteria, documents (not downloaded), milestones |
| UA-2026-04-28-014316-a | 23,550,000 | Same schema + **bids (1, active)**, **awards (1, pending)**, awardPeriod; title="Самоскид на автомобільному шасі 6*4", status=active.qualification, criteria (1 anti-corruption), documents (1x PDF + 2x .doc), items.qty=3 | title, authority, value, currency, date, description, quantity (=3) | status=active.qualification, **award.supplier** = "ТОВ КОММАШ ГРУП" (id: 42601903, pending), bid exists, awardPeriod, deliveryDate (2026-05-29), deliveryAddress |
| UA-2026-05-08-013050-a | 1,746,000 | title="Причіп платформа для перевезення автомобілів", status=active.enquiries, items.qty=4, unit=E50, cpv=34220000-5, deliveryDate=2026-09-30, deliveryAddress=Дніпропетровська область, **documents: 5x .docx incl. technicalSpecifications** ("Додаток 1 (Техвимоги).docx") | title, authority, value, currency, date, description (just title), quantity (=4) | status, deliveryDate, deliveryAddress, **technicalSpecifications docx not downloaded** (contains: mass=3550 kg, payload=2600 kg, dimensions=7448×2200 mm, axle=torque 1800 kg, 7 tyres 195R14C) |
| UA-UA-2026-04-08-011067-a | 0 (no data) | Force-included; not found in public API — likely confidential defence procurement or wrong tenderID format | title (EN only, AI-generated), authority, category (Low-Bed), no raw data | ALL raw fields missing; tenderID has spurious UA- prefix |
| UA-2026-05-05-004789-a (5th slot re-use) | — | — | — | Used as 4th slot above |

### UA Tender 3 — Technical Specs Content (UA-2026-05-08-013050-a)
From successfully downloaded `Додаток 1 (Техвимоги).docx` (21 KB, public, time-signed URL):
- Товар: Причіп платформа для перевезення автомобілів (CPV 34220000-5)
- Повна маса: до 3550 кг; Вантажопідйомність: до 2600 кг; Максимальна: до 4500 кг
- Розміри: 7448 мм × 2200 мм; Платформа: 6050 мм × 2250 мм
- Вісь торсіонна 1800 кг (112×5); 7 коліс 195 R14C Matador
- Підлога: метал з перфорацією; Рама: лонжерон 4 мм; Антикор: гаряче цинкування
- Лебідка AL-KO 900С; Трапи гнуті 2500×300 мм; Стяжні ремені (3-х точкові)

This data is ONLY available in the docx — completely absent from the API JSON.

---

## 2. Sample-Tender CZ (5 Stück)

| tender_id | Value (CZK) | Felder im Portal | Felder im Adapter | Lücken |
|-----------|------------|------------------|-------------------|--------|
| CZ-N006/26/V00010428 | 123,293.66 | title, status=**Awarded**, procType=Otevřená výzva, regime=Small-scale, cpv=34223300-9 (Přívěsy), nipez=34223300-9, authority=Ministerstvo obrany, contactPerson (name/email/phone), estimatedValue=123,293.66 CZK, deadline=28/04/2026, place=Česká republika, description (free text specifying price limit 39,999 Kč/ks), publication events (award, result, specs), importedFromIEN=2602002036 | title, authority, value=123293.66, currency, date (from deadline), quantity=1 | **status** (Awarded — not mapped), CPV code (34223300-9), contactPerson, deadline, place_of_performance, winner (portal shows "Awarded" but winner name not in raw text tab), IEN number |
| CZ-N006/26/V00008881 | 153,107.43 | status=Not terminated, cpv=34223300-9, place=Karlovarský kraj, deadline=13/04/2026, contactPerson | title, authority, value=153107.43, currency, date | **status**, CPV, contactPerson, deadline, place_of_performance, quantity (not mentioned in description) |
| CZ-N006/26/V00005076 | 0 (Cancelled) | status=**Cancelled**, dateOfCancellation=30/03/2026, cpv=34223300-9, place=Karlovarský kraj | title, authority, currency, date | **status=Cancelled** (not mapped), CPV, cancellationDate |
| CZ-N006/26/V00000758 | 0 | status=Not terminated, cpv=34138000-3 (Silniční tažná vozidla), vvz=Z2026-003622, place=Olomoucký kraj, description mentions "6 ks návěsových souprav k přepravě tanků min 70 t", regime=Above-threshold, deadline=30/03/2026 | title, authority, quantity=6, currency, date | **status**, CPV, vvz_number, place_of_performance, deadline, tank weight spec (70 t — only in description) |
| CZ-N006/24/V00015605 | 0 | status=Termination of performance, cpv=34138000-3, place=Olomoucký kraj, dns_parent=N006/23/V00001906, description "5 ks návěsových souprav", publication events incl. "skutečně uhrazené ceny" (actual price paid) | title, authority, quantity=5, currency, date | **status**, CPV, actual_paid_price, dns_parent_reference |

### CZ PDF Status
- 281 PDFs downloaded to `data/raw/cz/` — ALL are 2042-byte HTML redirects to `/crypto/cs/` (certificate authentication required)
- 0 real PDFs extracted
- NEN documents section requires Czech digital certificate (eIDAS) — not accessible without login
- The CZ adapter's `_extract_and_download_pdfs()` runs but silently stores HTML error pages as .pdf files
- pypdf raises "invalid pdf header: b'<!doc'" — these failures are caught/suppressed per adapter code

---

## 3. Lücken-Analyse UA-Adapter

| Feld | Verfügbar im Prozorro API | Extrahiert? | Aufwand | Priorität |
|------|--------------------------|-------------|---------|-----------|
| `status` (active.tendering / active.qualification / etc.) | YES — top-level | NO | S | Hoch |
| `procurementMethodType` (belowThreshold / aboveThreshold) | YES — top-level | NO | S | Mittel |
| `procuringEntity.address` (street, locality, region, postal) | YES — nested in procuringEntity | NO | S | Niedrig |
| `procuringEntity.contactPoint.email` | YES — nested | NO | S | Niedrig |
| `procuringEntity.kind` (= "defense") | YES — indicates defence procurement | NO | S | Mittel |
| `items[].deliveryDate.endDate` | YES — per item | NO | S | Hoch |
| `items[].deliveryAddress` | YES — per item | NO | S | Mittel |
| `items[].unit` (штука H87 / одиниця E50) | YES — per item | NO | S | Niedrig |
| `items[].classification.id` (full CPV: 34223310-2) | YES — per item; only prefix used | PARTIAL | S | Mittel |
| `items[].additionalClassifications` | YES — ДКПП/КЕКВ secondary codes | NO | S | Niedrig |
| `lots[].minimalStep.amount` (auction step) | YES — per lot | NO | S | Niedrig |
| `guarantee.amount` | YES — bid guarantee | NO | S | Niedrig |
| `tenderPeriod.startDate / endDate` | YES — bidding window | NO | S | Mittel |
| `enquiryPeriod` | YES — question deadline | NO | S | Niedrig |
| `awardCriteria` (lowestCost) | YES — top-level | NO | S | Niedrig |
| `documents[].url` (time-signed) | YES — each doc has public URL | NO — not downloaded | M | **Hoch** |
| `documents[].documentType` (technicalSpecifications) | YES — typed documents | NO | S | Hoch |
| `awards[].suppliers[].name` (winner when active) | YES — when award status=active | PARTIAL (only "active" checked) | S | Hoch |
| `awards[].value.amount` (actual awarded value) | YES — award price vs estimated | NO | S | Mittel |
| `bids[].value` (after bidding period) | YES — public after tenderPeriod | NO | S | Niedrig |
| `criteria` (ESPD requirements, 15 items) | YES — qualification criteria | NO | M | Niedrig |
| `milestones[].duration.days` (delivery days) | YES — payment/delivery milestones | NO | S | Mittel |
| `_national_raw_text` truncation at 10000 chars | JSON dump truncated | YES but broken | M | Hoch |

**Critical Gap: Document Download**
UA adapter stores `raw_text = json.dumps(data)[:10000]` — the JSON truncates mid-object. Document URLs (time-signed, ~30-min validity) are in this JSON but expire. The adapter NEVER downloads UA documents. UA-2026-05-08-013050-a has a `technicalSpecifications` docx with: mass, dimensions, axle load, tyre specs — all critical for BPW matching. These are inaccessible in current pipeline.

---

## 4. Lücken-Analyse CZ-Adapter

| Feld | Verfügbar im NEN Portal | Extrahiert? | Aufwand | Priorität |
|------|------------------------|-------------|---------|-----------|
| `status` (Awarded / Cancelled / Not terminated / Termination) | YES — "CURRENT STATUS OF THE PROCUREMENT PROCEDURE" | NO — pattern not implemented | S | **Hoch** |
| `cpv_code` (34223300-9 / 34138000-3) | YES — "CODE FROM THE CPV CODE LIST" | NO | S | Hoch |
| `cpv_name` | YES — "NAME FROM THE CPV CODE LIST" | NO | S | Mittel |
| `nipez_code` | YES — "CODE FROM THE NIPEZ CODE LIST" | NO | S | Niedrig |
| `place_of_performance` (region / NUTS code) | YES — "MAIN PLACE OF PERFORMANCE" | NO | S | Mittel |
| `deadline` (Submission deadline) | YES — "DEADLINE FOR SUBMITTING TENDERS" | NO (only used for date parsing hack) | S | Mittel |
| `winner_name` | Partially — Awarded tenders show "Uveřejnění výsledku" but winner name requires clicking into result tab | NO — result sub-page not fetched | M | **Hoch** |
| `vvz_number` (Journal registration, e.g. Z2026-003622) | YES — "CONTRACT REGISTRATION NUMBER IN THE VVZ" | NO | S | Mittel |
| `contactPerson.email` | YES | NO | S | Niedrig |
| `regime` (Small-scale / Above-threshold) | YES | NO | S | Niedrig |
| `dns_parent` (parent DNS reference) | YES — "PUBLIC CONTRACT IN WHICH THE DPS WAS INTRODUCED" | NO | S | Mittel |
| `cancellation_date` | YES — "DATE OF CANCELLATION" | NO | S | Mittel |
| `actual_paid_price` (for completed DNS) | YES — "Uveřejnění skutečně uhrazené ceny" | NO — separate event link | L | Mittel |
| `description` | YES — "SUBJECT-MATTER DESCRIPTION" | PARTIAL — adapter has `_find_description()` regex | PARTIAL | — |
| `quantity` (from description text) | YES — "dodávka N ks" in description | PARTIAL — works when "ks" appears | PARTIAL | — |
| `value` | YES — "ESTIMATED VALUE (EXCL. VAT)" | YES — `_find_value()` uses ESTIMATED VALUE regex | YES | — |
| PDF documents | BLOCKED — requires Czech digital certificate | NO — all 281 PDFs are 403 HTML pages | L | See §5 |

**Critical Gap: Status Not Mapped**
The `_find_winner()` method searches for "Vítěz\|Dodavatel" — but NEN English UI shows status as "Awarded" (top-level), not as a named winner in the information tab. The adapter scrapes the INFORMATION tab but NOT the RESULT tab (which has actual award/winner details). This means all CZ winners are blank in relevant.json even for completed procurements.

---

## 5. PDF-Analyse

### UA (Prozorro)
- 3 of 4 UA tenders have documents (the force-included has no data)
- UA-2026-04-28-014316-a: 1x PDF (`оголошення самоскиди.pdf`) + 2x .doc — PDF is an announcement, not tech specs
- UA-2026-05-08-013050-a: 5x .docx including **`technicalSpecifications`** (`Додаток 1 (Техвимоги).docx`, 21 KB) — CRITICAL CONTENT:
  - mass, dimensions, axle load, tyre size, braking system, winch model — all BPW-relevant specs
- UA-2026-05-05-004789-a: 4x .docx — contract proforma, announcement; no tech spec
- **Verdict**: ~1-2 of 4 UA tenders have technical specifications in documents. Format is .docx not .pdf. URLs require fresh time-signed tokens from API. Documents ARE public (no auth required) but UA adapter does NOT download them.

### CZ (NEN/NIPEZ)
- ALL 281 downloaded "PDFs" in `data/raw/cz/` are auth-blocked (2042 bytes, HTML redirect to `/crypto/cs/`)
- NEN requires Czech eIDAS digital certificate to access procurement documents
- The `_extract_and_download_pdfs()` method in cz_adapter.py silently fails — pypdf sees `<!doctype html>` and raises, the exception is caught at debug level
- **Critical specs in CZ tenders appear IN THE DESCRIPTION TEXT** (e.g. "6 ks návěsových souprav k přepravě tanků min 70 t", "nosnosti min. 50 tun"), not in PDFs
- For CZ, the text visible on the NEN information tab (already in raw_text) contains the most critical data — PDF download is a dead end

### enricher.py PDF-Status
- `FulltextEnricher._get_enrichment_text()` checks `_national_raw_text` first (priority), falls back to TED HTML/PDF
- No special UA/CZ handling — same Claude Sonnet prompt for all languages
- `FulltextFetcher._try_pdf()` uses `pdfplumber` — works for TED PDFs, irrelevant for UA (docx) and CZ (auth-blocked)
- **No Cyrillic-specific encoding handling** — all files read as UTF-8 (`encoding="utf-8"`). This is correct for Prozorro API responses (UTF-8 JSON), but if docx files ever contain non-UTF-8 text, there's no fallback.
- **No Czech diacritic handling** — `_find_*()` methods in cz_adapter use plain regex without Unicode normalization. Risk: "Přívěs" vs "Privěs" mismatch low, since NEN page is already UTF-8.
- `raw_text[:10000]` truncation in `base_adapter.py:176` cuts UA JSON mid-object — many document URLs and item details lost before enricher sees them.

**Estimate: PDFs/documents with critical specs in 10 samples:**
| Sample | Has docs | Has tech specs | In PDF? | In docx? | In description? |
|--------|----------|----------------|---------|---------|-----------------|
| UA-2026-05-05-004789-a | 5x docx | partial (announcement only) | — | unclear | NO |
| UA-2026-04-28-014316-a | 1x PDF + 2x doc | announcement only | NO | NO | NO |
| UA-2026-05-08-013050-a | 5x docx | **YES** (Техвимоги) | — | **YES** | NO |
| UA-UA-2026-04-08-011067-a | 0 | NO | — | — | — |
| CZ-N006/26/V00010428 | PDF (blocked) | partial (price limit in desc) | BLOCKED | — | partial |
| CZ-N006/26/V00008881 | PDF (blocked) | NO | BLOCKED | — | NO |
| CZ-N006/26/V00005076 | PDF (blocked) | NO (cancelled) | BLOCKED | — | NO |
| CZ-N006/26/V00000758 | PDF (blocked) | partial (70t tank spec) | BLOCKED | — | **YES** |
| CZ-N006/24/V00015605 | PDF (blocked) | partial (50t semitrailer) | BLOCKED | — | **YES** |

**Summary: 3 of 10 samples have usable critical spec data — 1 in docx (UA), 2 in NEN description text (CZ). The rest require document access that is either auth-blocked (CZ) or not yet implemented (UA docx download).**

---

## 6. Empfehlungen

### (a) UA-Adapter: Top-3 Quick-Wins

1. **`status` Mapping** (S, 1h): Add `_status` extraction from `detail.get("status")` in `get_detail()`. Map Prozorro statuses to pipeline vocabulary: `active.tendering→Open`, `active.qualification→Under Review`, `complete→Awarded`, `cancelled/unsuccessful→Cancelled`. Currently lost entirely.

2. **Document Download für `documentType=technicalSpecifications`** (M, 4h): In `get_detail()`, after fetching the API, iterate `data.get("documents", [])` and for docs with `documentType in ("technicalSpecifications", "technicalCriteria")` and `format in ("application/vnd.openxmlformats...", "application/pdf")`: re-fetch with a fresh time-signed URL from the API response (URLs in the current API call ARE fresh), download to `data/raw/ua/`, extract text (python-docx for .docx, pdfplumber for .pdf), append to `raw_text`. This unlocks mass/dimension/axle specs for AI classification.

3. **`deliveryDate` + `milestones` → `_contract_duration`** (S, 2h): Extract `items[0].deliveryDate.endDate` and `milestones[].duration.days` to populate `_contract_duration_ai`. This field is currently null for all UA tenders despite the API providing clear delivery dates (e.g. 2026-07-10 = ~65 days from pub date).

### (b) CZ-Adapter: Top-3 Quick-Wins

1. **`status` Extraction** (S, 1h): Add regex `r"CURRENT STATUS OF THE PROCUREMENT PROCEDURE\n([^\n]+)"` to `_find_*` suite. Map: `Awarded→Awarded`, `Cancelled→Cancelled`, `Not terminated→Open`, `Termination of performance→Closed`. This single pattern would correctly set status for all 32 CZ tenders (currently all are null/unknown).

2. **CPV Code Extraction** (S, 1h): Add regex `r"CODE FROM THE CPV CODE LIST\n(\S+)"` to extract CPV. Store as `_cpv_code`. Enables better classification and cross-reference with TED notices. Pattern is simple and reliable — present in all 5 sampled tenders.

3. **Result Tab Fetch for Winner** (M, 3h): NEN RESULT tab URL pattern is the same as INFO but with `/result` suffix or by navigating to the RESULT link visible in the raw HTML. After the info page loads, check if status is "Awarded" and navigate to the result/winner sub-page. The winner name is on the result page (not info page). Alternative: parse `Uveřejnění výsledku` detail link from publication records table.

### (c) PDF-Strategie: pdfplumber vs Claude Vision

**Recommendation: Hybrid strategy — python-docx for UA, skip PDF for CZ, use Claude Vision as fallback.**

| Approach | UA .docx | CZ PDFs | Cost | Effort |
|----------|---------|---------|------|--------|
| python-docx (current cz_adapter uses pypdf/pdfplumber) | **YES** — .docx extraction works, tested successfully | N/A | Free | S |
| pdfplumber | N/A for UA | BLOCKED (auth redirect) | Free | Wasted |
| Claude Vision (image→text) | Overkill for structured .docx | Could work for PDFs IF we get them | $0.01-0.05/page | M |
| NEN RESULT tab scrape | N/A | **Better than PDF** — specs in HTML | Free | M |

**Reasoning:**
- UA: python-docx (already in Python ecosystem) extracts Cyrillic DOCX perfectly (tested: 72 paragraphs extracted correctly). No pdfplumber needed for UA since docs are .docx. Cost: zero.
- CZ: PDFs are auth-blocked and inaccessible without eIDAS certificate. The critical spec information (quantity, load capacity, vehicle type) already appears in the NEN description text field — which IS scraped. Claude Vision for CZ PDFs would require an authentication solution first, making it premature.
- For future: If UA PDFs become available, pdfplumber handles Cyrillic PDF well (UTF-8 text layer). Claude Vision is only needed for scanned/image-based PDFs without text layer — not currently observed in either UA or CZ samples.

### (d) Nächste Sprint-Items, priorisiert

| # | Item | Adapter | Aufwand | Impact | Sprint |
|---|------|---------|---------|--------|--------|
| 1 | UA: status mapping (active.tendering→Open etc.) | UA | S (1h) | Alle 4 UA tenders bekommen korrekten Status | Next |
| 2 | CZ: status regex (`CURRENT STATUS...`) | CZ | S (1h) | Alle 32 CZ tenders bekommen Status | Next |
| 3 | CZ: CPV code extraction | CZ | S (1h) | Verbesserte Klassifikation, TED-Dedup | Next |
| 4 | UA: raw_text truncation erhöhen (10000→50000) OR store structured JSON | UA | S (1h) | Verhindert Datenverlust durch Truncation | Next |
| 5 | UA: document download für technicalSpecifications .docx (python-docx) | UA | M (4h) | Kritische Specs (Masse, Achslast, Maße) | Sprint+1 |
| 6 | UA: deliveryDate + milestones → `_contract_duration` | UA | S (2h) | Lieferdatum für alle UA Tenders | Sprint+1 |
| 7 | CZ: Result tab fetch for winner name | CZ | M (3h) | Winner für "Awarded" CZ Tenders | Sprint+1 |
| 8 | UA: awards.suppliers.name mapping (pending→winner) | UA | S (1h) | Gewinner bei qualification-Phase Tenders | Sprint+1 |
| 9 | CZ: PDF auth investigation (eIDAS bypass / public data alternative) | CZ | L (1-2 days) | Unblock 281 CZ documents | Sprint+2 |
| 10 | UA: Kyrillisch-Keywords erweitern (Sprint Backlog bereits geplant) | UA | S (2h) | Mehr UA tenders gefunden | Sprint+1 |

---

## 7. 3-Punkt-Summary (für User)

**1. Welche Felder fehlen am häufigsten bei UA/CZ:**
- **UA (Prozorro)**: `status` (alle Tenders), `deliveryDate` (in API, nicht extrahiert), `documents nicht heruntergeladen` (technische Specs in .docx — mass, Abmessungen, Achslast stehen NUR im Dokument, nicht im API-JSON). Zusätzlich: `procuringEntity.kind="defense"`, `awards.suppliers` (bei active.qualification), `tenderPeriod`.
- **CZ (NEN)**: `status` (alle 32 Tenders — Awarded/Cancelled/Open nicht gemappt), `CPV-Code` (vorhanden, nicht extrahiert), `winner_name` (Result-Tab wird nicht gefetcht), `deadline`, `place_of_performance`.

**2. Wie viele Tender haben PDFs mit kritischen Specs:**
- **UA**: 1 von 4 aktiven Tenders (UA-2026-05-08-013050-a) hat `technicalSpecifications` (.docx, 21 KB, downloadbar via API). Inhalt bestätigt: vollständige Trailer-Specs (Masse, Maße, Achse, Bereifung). Der UA-Adapter downloaded KEINE Dokumente — Quick-Win M-Aufwand.
- **CZ**: Alle 281 heruntergeladenen "PDFs" sind Auth-Fehlerseiten (2042 Bytes HTML). 0 reale PDFs. NEN-Dokumente erfordern eIDAS-Zertifikat. Kritische Specs stehen bei CZ teilweise im sichtbaren Beschreibungstext (z.B. "6 ks návěsových souprav k přepravě tanků min 70 t").

**3. Welcher Sprint-Item lohnt sich als nächstes:**
Drei S-Items mit je ~1h Aufwand, kombiniert als ein Micro-Sprint: **(1) UA status-Mapping** + **(2) CZ status-Regex** + **(3) CZ CPV-Extraktion**. Zusammen ~3h, Impact: korrekte Status-Felder für alle 36 UA+CZ Tenders in relevant.json, verbesserte Klassifikation. Danach: **(4) UA raw_text-Truncation auf 50000 erhöhen** (verhindert Datenverlust) + **(5) UA document download für .docx technicalSpecifications** (M, ~4h) — unlockt kritische Trailer-Spezifikationen für KI-Klassifikation.

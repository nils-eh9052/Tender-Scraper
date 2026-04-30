# SYSTEM_STATUS_V3 — TED Defence Trailer Scraper
**Created:** 2026-04-28 | **Sprint:** 2 complete | **Output:** 230 rows (Excel)

> **Memory anchor for new Claude Code chats.** Read this first. Everything you need to contribute immediately.

---

## 1. Projekt-Übersicht

A Python scraper that harvests **defence trailer procurement tenders** from the EU TED portal (api.ted.europa.eu v3), UK Contracts Finder, and national portals (Poland eZamowienia). Each notice is AI-classified by Claude Sonnet to extract trailer type, category (11 classes), quantity, and winner. Output is an Excel file (`Vorlage.xlsx` template, 23 columns, English) consumed by the commercial team at BPW Defense. The pipeline is also scheduled weekly via GitHub Actions.

---

## 2. Aktuelle Dateistruktur

```
ted-scraper/
├── main.py                          # Orchestrator + argparse CLI
├── Vorlage.xlsx                     # Excel template (Scraper Data sheet)
├── requirements.txt
├── config/
│   ├── settings.yaml                # All CPVs, keywords, scoring weights
│   ├── force_include.json           # 9 TED IDs always fetched
│   └── uk_blacklist.json            # 5 UK IDs excluded from export
├── src/
│   ├── api_client.py                # TED API v3 wrapper (search + paginate)
│   ├── index_builder.py             # Phase 1: runs queries, saves details/
│   ├── detail_fetcher.py            # Phase 2: legacy, normalize_notice()
│   ├── filter_engine.py             # Phase 3: CPV/keyword/score filtering
│   ├── classifier.py                # AI classifiers (Sonnet/Haiku/Batch)
│   ├── enricher.py                  # Fulltext HTML enrichment (--enrich)
│   ├── award_matcher.py             # Award notice matching (--award-match)
│   ├── exporter.py                  # Phase 4: Excel output
│   ├── quality_review.py            # Opus post-run QA (--review)
│   ├── uk_scraper.py                # UK Contracts Finder REST scraper
│   ├── de_scraper.py                # Legacy DE RSS scraper (superseded)
│   ├── pl_scraper.py                # Legacy PL BZP scraper (superseded)
│   ├── fulltext_fetcher.py          # Fetches TED HTML fulltext
│   └── national_scraper/
│       ├── core.py                  # BrowserCore (Playwright wrapper)
│       ├── base_adapter.py          # BaseAdapter, SearchResult, NoticeDetail
│       └── adapters/
│           ├── de_adapter.py        # service.bund.de (VSVgV + KFZ filters)
│           ├── pl_adapter.py        # eZamowienia REST API (no browser)
│           └── fi_adapter.py        # Hilma STUB (not implemented)
├── data/
│   ├── .enrichment_log.json         # AI result cache (~7,672 entries)
│   ├── .checkpoint.json             # Completed TED query names
│   ├── .last_run.json               # Last run date + notice count
│   ├── quality_review.json          # Opus QA results (last review)
│   ├── sprint2_summary.md           # Sprint 2 before/after report
│   ├── filtered/
│   │   ├── relevant.json            # *** MAIN DATA FILE: 235 notices ***
│   │   ├── all_scored.json          # All scored notices (raw filter output)
│   │   └── high_confidence.json     # Score ≥ 50 subset
│   ├── raw/
│   │   ├── details/                 # Individual TED notice JSONs (~35,129)
│   │   ├── notice_index.json        # TED index metadata
│   │   ├── fulltext/                # HTML→text for ~130 notices
│   │   ├── uk/
│   │   │   ├── uk_raw.json          # UK CF raw API results (884)
│   │   │   └── uk_notices.json      # UK CF normalized (86)
│   │   ├── de/
│   │   │   ├── national_raw.json    # DE raw results
│   │   │   └── national_filtered.json # DE after filter_defence
│   │   └── pl/
│   │       ├── national_raw.json    # PL raw results
│   │       └── national_filtered.json # PL after filter_defence (5)
│   └── export/
│       ├── 260427_TED_Tender Data_00.01.xlsx  # Current production export
│       ├── TED_Defence_Trailers_LATEST.xlsx   # Alias (for GitHub Actions)
│       └── archive/                           # Previous exports
└── .github/workflows/weekly-scrape.yml
```

---

## 3. Pipeline-Phasen

| Phase | Flag | Reads | Writes | Notes |
|---|---|---|---|---|
| **1+2: Index** | `--phase index` | `config/settings.yaml` | `data/raw/details/*.json`, `data/raw/notice_index.json`, `data/.checkpoint.json` | Runs all TED queries, saves each notice as individual JSON. Checkpoint allows resume. |
| **3: Filter** | `--phase filter` | `data/raw/details/*.json` | `data/filtered/relevant.json` (OVERWRITE), `all_scored.json`, `high_confidence.json` | **Destructive** — replaces relevant.json completely. Any curated changes (manual deletions, national notices) must be re-applied AFTER filter. |
| **3b: Classify** | `--phase classify` | `data/filtered/relevant.json`, `data/.enrichment_log.json` | `data/filtered/relevant.json` (in-place update), `data/.enrichment_log.json` | AI classifier adds `_trailer_type_1_ai`, `_trailer_category_1_ai`, etc. Caches results in enrichment log — won't re-call API for already-classified IDs. |
| **3c: Enrich** | `--enrich` | HTML from TED links | `data/raw/fulltext/*.txt`, updates relevant.json descriptions | Fulltext enrichment for better descriptions. Optional, slow (+20 min). |
| **3d: Award** | `--award-match` | relevant.json | Updates `_winner_name` fields | Matches award notices to original tenders. |
| **4: Export** | `--phase export` | `data/filtered/relevant.json`, `config/uk_blacklist.json`, `Vorlage.xlsx` | `data/export/YYMMDD_TED_Tender Data_00.XX.xlsx`, `TED_Defence_Trailers_LATEST.xlsx` | Skips rows with no `_trailer_type_1_ai`. Archives old exports. |
| **UK** | `--uk` | UK CF API | `data/raw/uk/uk_raw.json`, `uk_notices.json` | Merges into relevant.json BEFORE classify. |
| **National** | `--national de pl` | Portal (Playwright) | `data/raw/{country}/national_raw.json`, `national_filtered.json`, relevant.json | Requires playwright. PL uses REST API (no browser needed for search). |
| **Review** | `--review` | `TED_Defence_Trailers_LATEST.xlsx` | `data/quality_review.json` | Opus QA. Takes ~3 min, costs ~$0.05-0.15. |

**Critical rule:** `--phase filter` OVERWRITES `relevant.json` completely. National notices (UK-CF, PL-NP) and manual curations are lost. Always re-add them after filter+classify using the enrichment log.

---

## 4. CLI-Flags

```
python main.py [FLAGS]

Core modes:
  --all                   Full pipeline: index → details → filter → classify → export
  --phase {index,details,filter,classify,export,test-api}  Single phase
  --test                  Test mode: small sample, max 10 AI calls

Date control:
  --since YYYY-MM-DD      Override date_from for TED queries
  --incremental           Auto-detect date_from from .last_run.json

Classifier mode (use with --all or --phase classify):
  --two-stage             Haiku pre-filter + Sonnet (recommended, saves ~85% cost)
  --parallel              5 concurrent AI calls with retry+jitter
  --batch                 Anthropic Batches API (50% discount, ~1h wait)
  --llm {anthropic,openrouter}  Backend (openrouter = EXPERIMENTAL, needs validation)

Extra sources (combine freely with --all):
  --uk                    UK Contracts Finder (REST POST, 15 search terms)
  --de                    Legacy RSS Germany scraper (superseded by --national de)
  --pl                    Legacy BZP Poland scraper (superseded by --national pl)
  --national [de] [pl]    Playwright-based national portal scrapers
  --visible               Show browser window (with --national)

Enrichment:
  --enrich                Add fulltext enrichment after classify
  --enrich-only           Skip phases 1-3b, only enrich + export
  --award-match           Run award notice matching

QA:
  --review                Opus post-run quality review on latest Excel
  --validate-portals [de] [pl]  Validate national portals carry defence trailers

Misc:
  --verbose / -v          Debug logging
  --clear-log             Wipe enrichment log (forces re-classify everything)
```

**Recommended production command:**
```bash
python main.py --all --since 2026-01-01 --two-stage --uk --review
```

---

## 5. Konfiguration

### config/settings.yaml (vollständig)

```yaml
api:
  base_url: "https://api.ted.europa.eu/v3"
  search_url: "https://api.ted.europa.eu/v3/notices/search"
  detail_url: "https://api.ted.europa.eu/v3/notices"
  requests_per_second: 1
  max_retries: 3
  retry_backoff_factor: 2
  timeout_seconds: 30
  page_size: 250
  max_results_per_query: 15000

search:
  date_from: "2015-01-01"
  date_to: "2026-04-13"
  scope: "ALL"
  latest_only: true

cpv_codes:
  tier1_trailer_direct:
    - "34223000"   # Trailers and semi-trailers
    - "34223100"   # Semi-trailers
    - "34223200"   # Tank semi-trailers
    - "34223300"   # Trailers
    - "34223310"   # Universal trailers
    - "34223330"   # Van trailers        ← added Sprint 2
    - "34223370"   # Tipping trailers
    - "34221000"   # Special-purpose mobile containers  ← added Sprint 2
    - "34224100"   # Motorized trailers  ← added Sprint 2

  tier2_defence_vehicles:
    - "35600000"   # Military vehicles and parts
    - "35610000"   # Military vehicles
    - "35000000"   # Security/defence equipment (EXACT MATCH only — no prefix!)
    - "35400000"   # Military vehicles + spare parts  ← added Sprint 2

  tier3_transport_broad:
    - "34100000"   # Motor vehicles
    - "34130000"   # Goods transport vehicles
    - "34140000"   # Heavy vehicles
    - "34144000"   # Special-purpose vehicles
    - "34950000"   # Loading systems

legal_basis:
  defence_directive: "32009L0081"
  general_directives:
    - "32014L0024"
    - "32014L0025"

scoring:
  weights:
    cpv_tier1_match: 30
    cpv_tier2_match: 20
    cpv_tier3_match: 5
    defence_directive: 25
    keyword_category_match: 15
    keyword_generic_trailer: 5
    defence_context_word: 10
    title_match_bonus: 10
  threshold_relevant: 25
  threshold_high_confidence: 50

output:
  raw_dir: "data/raw"
  filtered_dir: "data/filtered"
  export_dir: "data/export"
  checkpoint_file: "data/.checkpoint.json"
  excel_filename: "ted_defence_trailers_{date}.xlsx"
```

### config/force_include.json (vollständig)

```json
{
    "_comment": "TED Notice IDs that must always be fetched and classified.",
    "force_include_ids": [
        "751810-2024", "772125-2025", "385446-2024", "477617-2024",
        "694394-2023", "560361-2021", "173135-2024", "231675-2021", "41901-2019"
    ]
}
```

### config/uk_blacklist.json (vollständig)

```json
{
    "_comment": "UK IDs excluded from export — training, sports equipment, university units.",
    "blacklisted_ids": [
        "UK-tender_344671/1186016",
        "UK-tender_336462/1140912",
        "UK-BIP83050068",
        "UK-BIP82987676",
        "UK-BIP77766607"
    ]
}
```

---

## 6. AI Classifier

### Classifier-Klassen

| Klasse | Modell | Wann nutzen |
|---|---|---|
| `AiClassifier` | claude-sonnet-4-20250514 | Default, serial |
| `TwoStageClassifier` | Haiku prefilter + Sonnet | Recommended: `--two-stage` |
| `ParallelClassifier` | wraps any base classifier | `--parallel` |
| `BatchClassifier` | claude-sonnet-4-20250514 | `--batch` (50% cheaper, ~1h) |
| `OpenRouterClassifier` | configurable via .env | `--llm openrouter` (EXPERIMENTAL) |

### CLASSIFIER_PROMPT (vollständig)

```python
"""You are a strict defence procurement analyst. Determine if this EU notice is about BUYING trailers for military/defence, and classify it.

NOTICE:
- Title: {title}
- Description: {description}
- CPV: {cpv_codes}
- Country: {country}
- Authority: {authority}
- Value: {value} {currency}
- Winner: {winner}

STEP 1 — FILTER (both must be YES, else reject):

A) Is a trailer/semi-trailer/trailer-based system the PRIMARY procurement subject?
YES: cargo trailers, semitrailers, low-bed transporters, tank/fuel trailers, ammo trailers, field kitchen trailers, container/shelter on trailer chassis, hook-lift/loading systems, water treatment/field hospital/container system/shelter MOUNTED ON semi-trailer chassis (trailer is primary platform), Drivmedelstransportekipage (Swedish fuel transport combo), Transportekipage
NO: trucks without trailers, spare parts only, maintenance without new trailers, tanks/APCs/trucks/cars, software, ammunition itself, general logistics services

B) Is the procuring authority defence/military?
YES: Ministry of Defence, Armed Forces, BAAINBw, FMV, DGA, NATO agencies, military logistics commands, HIL GmbH, VOP CZ (Czech state defence enterprise)
NO: fire brigades, police, municipalities, energy companies, road authorities, interior ministries, water utilities

If EITHER is NO: {"relevant": false, "reason": "brief explanation"}

STEP 2 — CLASSIFY (only if both YES):

Always return a SINGLE JSON object (NEVER an array). Use slot 2 for a second distinct trailer type.

{"relevant": true, "title_english": "...", "description_english": "...", "trailer_type_1": "Specific type", "trailer_category_1": "ONE OF VALID_CATEGORIES", "trailer_quantity_1": null_or_int, "trailer_type_2": null, "trailer_category_2": null, "trailer_quantity_2": null, "additional_equipment": null_or_str, "additional_qty": null_or_int, "contract_duration": null_or_str}

RULES:
- trailer_type_1: REQUIRED — never just "Trailer"
- 0.01 EUR or 1 EUR = valid German framework placeholder — do NOT reject
- Slot 2 for distinct second trailer type (NOT for variants of same type)
- additional_equipment: ONLY non-trailer items (trucks, tractors, spare parts)
- ALL output in English
- Respond with ONLY the JSON. No markdown, no backticks."""
```

### HAIKU_PREFILTER_PROMPT (vollständig)

```python
"""Is this EU procurement notice about BUYING trailers (semi-trailers, tank trailers, low-bed trailers, cargo trailers, field kitchens on trailer chassis, container systems on trailer chassis) for a MILITARY or DEFENCE organization?

Title: {title}
Description: {description}
Authority: {authority}
CPV codes: {cpv_codes}

Answer ONLY "YES" or "NO"."""
```

### VALID CATEGORIES (11 classes)

```python
TRAILER_CATEGORIES = [
    "Low-Bed", "Semitrailer", "Dolly", "Tank Trailer",
    "Mission Module", "Loading System", "Special Purpose",
    "Ammunition Trailer", "Field Kitchen", "Cargo Trailer", "Other",
]
```

### Enrichment Log — Cache-Struktur

**Datei:** `data/.enrichment_log.json`  
**Größe:** ~7,672 Einträge (Stand Sprint 2)

```json
{
  "326948-2025": {
    "result": {
      "relevant": true,
      "title_english": "Netherlands Military Medical Trailers Role 1 & 2",
      "trailer_type_1": "Military medical trailer for Role 1 & 2 operations",
      "trailer_category_1": "Mission Module",
      "trailer_quantity_1": 40,
      "trailer_type_2": null,
      "trailer_category_2": null,
      "trailer_quantity_2": null,
      "additional_equipment": null,
      "additional_qty": null,
      "contract_duration": null,
      "description_english": "..."
    },
    "timestamp": "2026-04-27 22:30:00",
    "title": "Netherlands – Military Medical Trailers Role 1 & 2"
  }
}
```

**Key rule:** If `tender_id` in log AND `result != null` → classifier uses cached result, NO API call. To force re-classify: delete the key from the log file, or set `result` to `null`.

**NON_DEFENCE_AUTHORITY_PATTERNS** — bypasses AI entirely (blacklist check in classifier):
- Feuerwehr, fire brigade, police, municipalities, energy companies (Gelsenwasser, EDF, etc.), road authorities, hospitals, schools, zoos, transit companies, forestry.

---

## 7. Exporter

### COLUMNS (vollständig, 23 Spalten B–X)

| Col | Header | Field Key | Width | Type | Notes |
|---|---|---|---|---|---|
| B | Tender ID | `tender_id` | 16 | str | |
| C | Title | `_title_final` | 55 | str | AI English > _title_final > raw |
| D | Country | `_country_normalized` | 14 | str | ISO3 → full name |
| E | Authority | `_authority_name` | 35 | str | |
| F | Publication Date | `_pub_date` | 16 | date | YYYY-MM-DD |
| G | Status | `_status` | 12 | str | Open/Awarded/Closed/Unknown |
| H | Est. Value | `_value_num` | 18 | num | Raw, 0.01 = None |
| I | Currency | `_value_currency` | 10 | str | |
| J | Est. Value (EUR) | `_value_eur_num` | 18 | num | Converted via FX_RATES |
| K | Trailer Type (1) | `_trailer_type_1_final` | 35 | str | ← from `_trailer_type_1_ai` |
| L | Category (1) | `_trailer_cat_1_final` | 18 | str | ← from `_trailer_category_1_ai` |
| M | Quantity (1) | `_trailer_qty_1_int` | 14 | int | |
| N | Trailer Type (2) | `_trailer_type_2_final` | 35 | str | Blue header |
| O | Category (2) | `_trailer_cat_2_final` | 18 | str | Blue header |
| P | Quantity (2) | `_trailer_qty_2_int` | 14 | int | Blue header |
| Q | Additional Equip. | `_additional_equip_final` | 35 | str | |
| R | Additional Qty | `_additional_qty_int` | 14 | int | |
| S | Contract Duration | `_contract_duration_final` | 16 | str | |
| T | Winner | `_winner_name` | 30 | str | |
| U | Source URL (TED) | `ted_url` | 45 | url | |
| V | Description | `_description_final` | 65 | str | AI English, max 500 chars |
| W | Source | `_source` | 14 | str | TED / UK-CF / PL-NP (green) |
| X | Source URL (National) | `_source_url_national` | 45 | url | green |

**Header row:** Row 4 (data starts row 5). Template: `Vorlage.xlsx` sheet "Scraper Data".

### FX_RATES_TO_EUR

```python
FX_RATES_TO_EUR = {
    "EUR": 1.0, "DKK": 0.134, "SEK": 0.087, "PLN": 0.233,
    "CZK": 0.040, "RON": 0.201, "NOK": 0.085, "GBP": 1.17,
    "CHF": 1.06, "HRK": 0.133, "BGN": 0.511, "HUF": 0.0025,
}
```

### clean_winner() Logik

Removes duplicate winner names that appear on separate lines in TED data. Splits by `\n`, deduplicates while preserving order, re-joins.

### determine_status() Logik (Priorität)

1. `_winner_name` present → **Awarded**
2. Title contains "award notice", "contract award", "Vergabebekanntmachung", etc. → **Awarded**
3. `_raw.notice-type` contains "award"/"result"/"vergabe" → **Awarded**
4. `submission_deadline` field → compare to today: future = **Open**, past = **Closed**
5. `publication_date` heuristic: < 6 months old → **Open**, ≥ 6 months → **Closed**
6. Fallback → **Unknown** (rare)

### Export dedup

The exporter calls `_dedup_for_export()` which deduplicates by `tender_id`, keeping the notice with highest data score (winner > value > quantity > pub_date length).

### Rows skipped during export

- Notice has empty `_trailer_type_1_final` (no AI classification)
- `tender_id` in `config/uk_blacklist.json`

---

## 8. Nationale Portale

### Pattern: core.py + base_adapter.py

```
BrowserCore (Playwright wrapper)
  ↓
BaseAdapter (abstract)
  ├── search(keyword, max_results) → list[SearchResult]
  ├── get_detail(result) → NoticeDetail
  ├── search_all_keywords(max_results_per_keyword, test_mode) → list[SearchResult]
  ├── filter_defence(results) → list[SearchResult]
  └── to_standard_format(detail) → dict  # TED-compatible schema

SearchResult: title, url, authority, date, value, currency, reference_id, snippet
NoticeDetail: title, description, authority, date, value, currency, quantity, winner, deadline, duration, reference_id, url, source_code, raw_text
AdapterConfig: country_name, country_code, source_code, base_url, search_url, language, trailer_keywords, defence_authorities, min_interval_seconds
```

`BrowserCore` methods: `goto()`, `get_text()`, `get_all_texts()`, `get_page_text()`, `click()`, `fill()`, `select_option()`, `capture_response()`, `_dismiss_cookie_banner()`, `_screenshot()`

### DE Adapter — service.bund.de

- **URL:** `https://www.service.bund.de/Content/DE/Ausschreibungen/Suche/Formular.html?nn=4641514`
- **Strategy:** Two server-side checkboxes — VSVgV ("Verteidigung & Sicherheit", ~35 items) + KFZ ("Kraftfahrwesen", ~71 items). Both are activated independently via JavaScript click, then "Finden" button. Results paginate with JS "eine Seite weiter" button (no href).
- **filter_defence():** Checks if notice title contains any trailer keyword
- **Keywords:** Anhänger, Sattelanhänger, Tieflader, Tankanhänger, Feldküche, Wechsellader, Transportanhänger, Shelter, Hakenladegerät, Schwerlastanhänger, Sattelzug, Kastenanhänger, Auflieger, Fahrzeugbeschaffung, Transportfahrzeug, Logistikfahrzeug, Schwerlasttransport, Fahrgestell, Wechselbrücke, Container
- **Status:** ✅ Works (Playwright). Currently 0 trailer tenders open (Portal validated 2026-04-26). No BAAINBw trailer tenders visible.

### PL Adapter — eZamowienia.gov.pl

- **URL:** `https://ezamowienia.gov.pl/mo-board/api/v1/Board/Search`
- **Strategy:** REST API (no browser needed for search). Cross-product of 5 CPV codes × 6 military-org keywords = 30 combined queries. API accepts `CpvCode` + `OrganizationName` + `publicationDateFrom` params.
- **CPV codes:** 34223300, 34220000, 34223100, 34223200, 34221000 (NOTE: 34130000 removed — too broad)
- **Org keywords:** "wojsk", "Inspektorat Uzbrojenia", "Inspektorat Wsparcia", "Agencja Mienia Wojskowego", "Centrum Logistyki", "Rejonowy Zarząd Infrastruktury"
- **Date range:** 2021-01-01 → present (eZamowienia launch date)
- **filter_defence():** Two-tier: (1) trailer keyword in title OR (2) military authority name
- **Detail fetch:** REST API `GetNoticeHtmlBodyById` — HTML stripped to text, no browser needed
- **Status:** ✅ Works. Found 5 notices since 2021 (4 × "Dostawa przyczep transportowych", 12. WOG Toruń + 1 BSP drone centre excluded).

### UK Scraper — UK Contracts Finder

- **URL:** `https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices/json` (POST)
- **Strategy:** 15 keyword searches. Results filtered by `DEFENCE_ORGS` list (MoD, DE&S, Royal Navy, etc.).
- **Search terms:** trailer, semi-trailer, semitrailer, low-bed, low loader, tank trailer, fuel tanker trailer, hook lift, container trailer, flatbed trailer, military trailer, ammunition trailer, field kitchen, shelter trailer, mission module
- **Cache:** `data/raw/uk/uk_raw.json` (884 raw), `uk_notices.json` (86 normalized)
- **AI classified (current):** 9 relevant (from enrichment log), 5 blacklisted → **4 in Excel**
- **Status:** ✅ Works. Blacklist: 5 training/sports/university notices excluded.

### FI Adapter — Hilma

- **Status:** 🔴 STUB only. `NotImplementedError` on all methods. Run `--validate-portals fi` before implementing.

---

## 9. Aktuelle Datenqualität

**Stand:** 2026-04-28 | `data/filtered/relevant.json`

### Zeilen

| Source | relevant.json | Excel (exported) |
|---|---|---|
| TED | 222 | 218 |
| UK-CF | 9 | 4 (5 blacklisted) |
| PL-NP | 4 | 4 |
| **Total** | **235** | **230** |

### Completeness pro Feld

| Feld | Filled | % | Problem |
|---|---|---|---|
| Trailer Type (1) | 235/235 | 100% | ✅ |
| Category (1) | 235/235 | 100% | ✅ |
| Description | 235/235 | 100% | ✅ |
| Est. Value | 135/235 | 57% | Many TED framework agreements have no value |
| Winner | 52/235 | 22% | Most are procurement (pre-award) notices |
| Quantity (1) | 51/235 | 21% | Often not stated in notice text |
| Additional Equip. | 54/235 | 22% | Populated by AI when items present |
| Trailer Type (2) | 12/235 | 5% | Dual-category notices only |
| Contract Duration | 15/235 | 6% | Rarely stated in procurement notice |

### Kategorie-Verteilung

| Kategorie | n | % | Kommentar |
|---|---|---|---|
| Special Purpose | 95 | 40% | Largest; incl. recovery, commando, amphibious, radar |
| **Other** | 59 | **25%** | ⚠️ Too broad — main sprint 3 target for reclassify |
| Cargo Trailer | 30 | 12% | |
| Tank Trailer | 12 | 5% | |
| Low-Bed | 11 | 4% | |
| Mission Module | 9 | 4% | |
| Field Kitchen | 8 | 3% | |
| Semitrailer | 6 | 2% | |
| Loading System | 4 | 2% | Underrepresented — Opus gap |
| Ammunition Trailer | 1 | 0% | Severely underrepresented |
| Dolly | 0 | 0% | Completely absent — Opus gap |

### Länder-Verteilung (Top 15)

| Land | n | | Land | n |
|---|---|---|---|---|
| Italy | 27 | | Belgium | 9 |
| Czech Republic | 22 | | Norway | 8 |
| Germany | 19 | | Luxembourg | 6 |
| Poland | 18 | | Slovakia | 6 |
| France | 15 | | Austria | 5 |
| United Kingdom | 15 | | Hungary | 4 |
| Netherlands | 13 | | Slovenia | 3 |
| Sweden | 13 | | | |
| Denmark | 13 | | | |
| Romania | 13 | | | |

---

## 10. Bekannte Probleme + Technische Schulden

### 1. SSL-Workaround (Corporate VPN)
**Problem:** Corporate proxy intercepts HTTPS. All `requests` sessions and the Playwright browser use `verify=False`.  
**Config:** `.env` must contain `SSL_VERIFY_DISABLE=1`.  
**Impact:** All API calls (TED, UK CF, Anthropic, eZamowienia) bypass cert validation.

### 2. "Other"-Kategorie = 25% (59 notices)
**Problem:** AI classifies ambiguous notices as "Other". These are genuine military procurement but the notice text doesn't clearly identify trailer type.  
**Fix needed:** Post-classify reclassify pass: re-run AI on "Other" entries with enriched fulltext (--enrich) to get better category signals. OR: add "Other" reclassify phase to pipeline.

### 3. `--phase filter` overwrites relevant.json
**Problem:** Running `--phase filter` destroys all curated changes (manual deletions, national notices added, category corrections).  
**Workaround:** After every filter+classify cycle, run the post-classify curation script that re-applies corrections from enrichment log. UK notices and PL-NP notices must be manually re-merged from their cache files.  
**Fix needed:** Filter should be append/merge-aware OR a separate curation config file should hold permanent exclusions.

### 4. TED 2021-2015 gap (eZamowienia)
**Problem:** PL eZamowienia only holds data from 2021 onwards. PL TED tenders from 2015-2020 are covered but PL national-only tenders from that period are invisible.  
**Impact:** Small; most PL military procurement is TED-cross-published anyway.

### 5. DE service.bund.de — 0 trailers currently open
**Problem:** service.bund.de currently shows 0 open trailer tenders. BAAINBw may publish tenders on a different platform or via DTAD/E-Vergabe directly.  
**Risk:** We're missing current German military trailer procurement.

### 6. PL legacy scraper (src/pl_scraper.py)
**Problem:** `src/pl_scraper.py` uses `searchbzp.uzp.gov.pl` (DevExpress portal) which triggers WAF CAPTCHA. Superseded by `src/national_scraper/adapters/pl_adapter.py`.  
**Status:** Dead code, do not use.

### 7. DE legacy scraper (src/de_scraper.py)
**Problem:** `src/de_scraper.py` uses RSS feed from service.bund.de. Less reliable than the adapter-based approach.  
**Status:** Mostly dead code.

### 8. CPV 35000000 exact-match only
**Known:** CPV `35000000` in TED API does NOT prefix-match. It only returns notices whose primary CPV is exactly `35000000`. Fixed in Sprint 2 by adding `35400000` (Military vehicles) explicitly. `35610000` and `35600000` DO work as prefix matches.

### 9. Checkpoint management for re-runs
**Problem:** When CPV lists are expanded, old completed query names stay in `data/.checkpoint.json`. New CPV codes in existing queries won't be searched unless those query names are removed from checkpoint.  
**Fix:** Remove affected query names from `checkpoint["completed_queries"]` before re-running.

---

## 11. Offene Implementierungs-Aufgaben (Sprint 3 Backlog)

### High Priority
1. **Other-Reclassify pass** — Re-run AI on 59 "Other" entries with fulltext enrichment. Expected conversion: ~40% to specific categories. Command: `--enrich-only` on relevant.json subset.
2. **BOAMP-Adapter (Frankreich)** — France has 15 TED entries but far more on BOAMP. Portal: `https://www.boamp.fr`. Strategy: OpenData API `https://api.boamp.fr/explore/dataset/boamp/`. Keywords: "remorque", "semi-remorque", "remorque militaire". Authority: DGA, Ministère des Armées.
3. **Dolly keywords** — Add to `settings.yaml`: "dolly", "Dolly-Achse", "avant-train", "converter dolly". Add text query to `index_builder.py`.

### Medium Priority
4. **FI Hilma adapter** — Validate first with `--validate-portals fi`. FI has 10 TED entries; Hilma may have more. API: `https://www.hankintailmoitukset.fi/fi/rest/` (limited docs).
5. **SE Upphandlingsmyndigheten** — Sweden has 13 TED entries. Portal: `https://www.upphandlingsmyndigheten.se`. Keywords: terrängvagn, pjäsvagn, militärtrailer.
6. **Loading System deep-dive** — Only 4 entries. Add DROPS, PLS, Multilift, Hiab, hook-load keywords. Add dedicated CPV text query.
7. **Ammunition CPV 35321000** — Combine with trailer CPV for ammo trailer detection.

### Low Priority
8. **Fulltext as default** — Make `--enrich` run automatically for all new notices. Currently optional.
9. **PDF extraction** — Some TED notices have better detail in linked PDFs. `data/raw/fulltext/` holds HTML→text; extend to PDF.
10. **TED Open Data CSV bulk** — TED publishes annual CSV exports. Could backfill pre-2015 data or validate coverage.
11. **Award-Match automation** — `--award-match` often discovers winner from paired award notices. Should run automatically for "Closed" status entries.
12. **CZ Vestnik adapter** — Czech Republic has 22 entries (highest count), suggesting portal has more. `https://vestnikverejnychzakazek.cz`.
13. **NO DOFFIN adapter** — 8 TED entries. `https://www.doffin.no`.
14. **DK Udbud.dk adapter** — 13 TED entries. `https://www.udbud.dk`.

---

## 12. Kosten-Struktur

### Per Full Run (`--all --two-stage --uk --review`)

| Schritt | Modell | ~Calls | ~Kosten |
|---|---|---|---|
| TED Haiku prefilter | claude-haiku-4-5 | ~500-2000 | ~$0.01-0.05 |
| TED Sonnet classify | claude-sonnet-4 | ~50-150 (after Haiku filter) | ~$0.25-0.75 |
| UK prefilter | claude-haiku-4-5 | ~80 | ~$0.002 |
| UK classify | claude-sonnet-4 | ~10-15 | ~$0.05-0.10 |
| Opus QA review | claude-opus-4 | 1 (large prompt) | ~$0.10-0.20 |
| **Total** | | | **~$0.40-1.10** |

### Per Incremental Run (`--all --since 2026-04-01 --two-stage`)

- TED API returns ~10-50 new notices / month
- ~80% cached in enrichment log (already classified)
- Typical cost: **$0.05-0.20**

### Per `--enrich-only` (fulltext enrichment)

- 1 Sonnet call per notice (HTML text scraping + extract)
- ~130 already enriched (see `data/raw/fulltext/`)
- Remaining ~100 notices: **~$0.50-1.50**

### Cache statistics

- `data/.enrichment_log.json`: 7,672 entries
- Cache hit rate in Sprint 2 classify run: ~96% (228 classified, ~8 new AI calls)
- Cache is persistent — never auto-cleared. Clear with `--clear-log` (nuclear option).

---

## 13. Umgebung

### Python + Packages

```
Python 3.14.3 (Windows, C:/Users/nheinrich/AppData/Local/Python/)

requirements.txt:
  requests>=2.31.0
  pandas>=2.0.0
  openpyxl>=3.1.0
  pyyaml>=6.0
  tqdm>=4.65.0
  playwright>=1.40.0

playwright browsers: chromium (installed via: playwright install chromium)
```

### Environment Variables (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...         # Required for AI classify/review
SSL_VERIFY_DISABLE=1                 # Required on corporate VPN
LLM_ANTHROPIC_API_KEY=sk-ant-...     # Alias (auto-mapped to ANTHROPIC_API_KEY)
LLM_OPENROUTER_API_KEY=...           # Optional, for --llm openrouter
LLM_MODEL_NAME=moonshotai/kimi-k2    # Optional, for OpenRouter
```

`.env` is loaded automatically by `main.py` on startup (manual `open()` loop, not python-dotenv).

### GitHub Actions

`/.github/workflows/weekly-scrape.yml` — Runs every Sunday with:
```
python main.py --all --incremental --two-stage --uk --review
```
Commits the new Excel + quality_review.json back to the repository. Secrets: `ANTHROPIC_API_KEY` in GitHub repository settings.

### Key paths

```python
PROJECT_ROOT = Path(__file__).parent   # ted-scraper/ted-scraper/
ENRICHMENT_LOG_PATH = PROJECT_ROOT / "data" / ".enrichment_log.json"
CHECKPOINT_FILE     = PROJECT_ROOT / "data" / ".checkpoint.json"
RELEVANT_JSON       = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
LATEST_EXCEL        = PROJECT_ROOT / "data" / "export" / "TED_Defence_Trailers_LATEST.xlsx"
```

---

## Appendix: Useful One-Liners

### Check current dataset state

```python
import json; from pathlib import Path
rel = json.loads(Path('data/filtered/relevant.json').read_bytes().decode('utf-8'))
sources = {}; cats = {}
for n in rel:
    sources[n.get('source') or 'TED'] = sources.get(n.get('source') or 'TED', 0) + 1
    cats[n.get('_trailer_category_1_ai','?')] = cats.get(n.get('_trailer_category_1_ai','?'), 0) + 1
print(f"Total: {len(rel)} | Sources: {sources} | Top cats: {sorted(cats.items(), key=lambda x:-x[1])[:5]}")
```

### Delete a notice from enrichment log (force re-classify)

```python
import json; from pathlib import Path
log = json.loads(Path('data/.enrichment_log.json').read_bytes().decode('utf-8'))
del log['TENDER-ID-HERE']
Path('data/.enrichment_log.json').write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')
```

### Re-expand a TED query (force re-run after CPV addition)

```python
import json; from pathlib import Path
cp = json.loads(Path('data/.checkpoint.json').read_bytes().decode('utf-8'))
# Remove the query name(s) you want to re-run:
cp['completed_queries'] = [q for q in cp['completed_queries'] if q != 'defence_directive_trailer_cpv']
Path('data/.checkpoint.json').write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding='utf-8')
```

### Run Opus QA standalone

```bash
python main.py --review
```

### Run full production pipeline

```bash
python main.py --all --since 2026-01-01 --two-stage --uk --review
```

# CLAUDE.md — TED Defence Trailer Scraper
> Memory anchor for Claude Code sessions. Read this before making any changes.

---

## 1. Was ist das Projekt?

Ein Python-Pipeline-Scraper für **BPW Defense**, der Rüstungs-Beschaffungsausschreibungen für Anhänger und Sattelauflieger aus mehreren EU-Quellen sammelt, KI-klassifiziert und als Excel-Datei ausgibt.

**Hauptquellen:**
- EU TED Portal (api.ted.europa.eu v3)
- UK Contracts Finder (REST API)
- 13 nationale Portale (DE, PL, CZ, FI, SE, NO, DK, NL, BE, ES, IT, FR, RO) via Playwright

**Output:** `data/export/YYMMDD_TED_Tender Data_00.XX.xlsx` — 23 Spalten (B–X), Scraper-Data-Sheet in Vorlage.xlsx-Template.

---

## 2. Einstiegspunkte

```bash
# Produktions-Run (empfohlen)
python main.py --all --since 2026-01-01 --two-stage --uk --review

# Einzelne Phasen
python main.py --phase index       # Phase 1+2: TED-Daten holen
python main.py --phase filter      # Phase 3: CPV/Keyword-Scoring
python main.py --phase classify    # Phase 3b: AI-Klassifikation
python main.py --phase export      # Phase 4: Excel-Export
python main.py --enrich-only       # Fulltext anreichern + exportieren
python main.py --review            # Opus QA auf letztem Excel
```

---

## 3. Dateistruktur (wichtigste Dateien)

```
main.py                             # Orchestrator + argparse CLI (1532 Zeilen)
config/
  settings.yaml                     # CPVs, Keywords, Scoring, API-Einstellungen
  force_include.json                # TED IDs die IMMER geholt werden
  uk_blacklist.json                 # UK IDs aus Export ausschließen
  blacklist.json                    # Globale False-Positive-Blacklist
src/
  api_client.py                     # TED API v3 Wrapper
  index_builder.py                  # Phase 1+2: Queries + Details in einem Pass
  filter_engine.py                  # Phase 3: Keyword-/CPV-Scoring (189 MB Cache!)
  classifier.py                     # AI-Klassifikation (Sonnet/Haiku/Batch)
  enricher.py                       # Fulltext-Anreicherung (Claude Sonnet)
  exporter.py                       # Phase 4: Excel-Export
  award_matcher.py                  # Vergabe-Bekanntmachungen matchen
  quality_review.py                 # Opus Post-Run-QA
  text_miner.py                     # Phase 3k: Multilingual Regex qty/deadline/duration
  document_pipeline/                # Phase 3g: Dokument-Extraktion
    __init__.py
    discovery.py                    # DocumentRef Dataclass + discover_for_notice() + _discover_strategy_a
    downloader.py                   # SHA1-Dedup-Download, Rate-Limit, SSL-Bypass
    extractor.py                    # pdfplumber / python-docx / Vision / openpyxl
    ai_structurer.py                # Sonnet 4.6 → _extracted_specs JSON
    orchestrator.py                 # End-to-End-Loop, Cache management
    strategy_a.py                   # Strategy A: proactive DE/PL/CZ Vergabeunterlagen scraping (Window E, 2026-05-18)
  national_scraper/
    core.py                         # BrowserCore (Playwright-Wrapper)
    base_adapter.py                 # BaseAdapter, SearchResult, NoticeDetail
    adapters/                       # 13 Länder-Adapter
      de_adapter.py, pl_adapter.py, cz_adapter.py, ...
    fallback/                       # Phase 3g+ National Portal Fallback
      __init__.py
      de_search.py                  # evergabe-online.de (ID) + service.bund.de
      pl_search.py                  # ezamowienia.gov.pl REST API
      cz_search.py                  # verejnezakazky.vop.cz + nen.nipez.cz
data/
  filtered/relevant.json            # *** HAUPT-DATENDATEI ***
  .enrichment_log.json              # AI-Ergebnis-Cache (nie löschen!)
  .checkpoint.json                  # Abgeschlossene TED-Queries (resume)
  .filter_cache.json                # Filter-Cache (189 MB, auto-managed)
  .document_extraction_cache.json   # Phase 3g Cache (nie löschen!)
  .national_fallback_cache.json     # Phase 3g+ National Fallback Cache (nie löschen!)
  .text_mining_cache.json           # Phase 3k Cache (Window D, 2026-05-18)
  documents/                        # Heruntergeladene Dokumente (SHA1-Dedup)
  export/                           # Excel-Outputs + archive/
  raw/details/                      # ~35.000 einzelne TED Notice JSONs
Vorlage.xlsx                        # Excel-Template (Sheet: "Scraper Data")
```

---

## 4. Pipeline-Phasen

| Phase | Flag | Liest | Schreibt | Kritisch |
|-------|------|-------|----------|----------|
| 1+2: Index | `--phase index` | settings.yaml | `raw/details/*.json`, checkpoint | Checkpoint ermöglicht Resume |
| 3: Filter | `--phase filter` | `raw/details/*.json` | `filtered/relevant.json` | **ÜBERSCHREIBT** relevant.json komplett! Wendet 14j-Hardening an: MIN_VALUE_EUR (default €100k, env: `BPW_MIN_VALUE_EUR`) + Repair-Filter (`config/repair_keywords_negative.json`, 8 Sprachen). Beide laufen VOR Dedup/Save um AI-Classify-Kosten zu sparen. |
| 3b: Classify | `--phase classify` | relevant.json, enrichment_log | relevant.json (in-place) | Cached in enrichment_log — kein Doppel-API-Call |
| 3c: Enrich | `--enrich` | TED HTML | fulltext/*.txt, relevant.json | Optional, langsam (+20 min) |
| 3d: Award | `--award-match` | relevant.json | relevant.json (winner update) | — |
| 3e: Title | `--translate-titles` | relevant.json | relevant.json (`title_en`) | Cache in `.translation_cache.json` |
| 3e-2: Desc | `--translate-descriptions` | relevant.json | relevant.json (`description_en`) | Cache in `.description_translation_cache.json` |
| 3e-3: Clean | (automatisch nach 3e-2) | relevant.json | relevant.json (`description_en` bereinigt) | `--force-clean` bypass; Haiku 4.5; Cache-Key `{tid}:{sha1}:haiku-clean` |
| 3f: Currency | `--enrich-descriptions` | relevant.json | relevant.json (`description_enriched`) | Regex, 0 USD |
| 3j: ContractType | `--contract-type` | relevant.json | relevant.json (`_contract_type`, `_contract_duration_months`) | Multilingual Regex; Cache `.contract_type_cache.json` |
| 3k: TextMine | `--text-mine` | relevant.json | relevant.json (`_qty_mined`, `_deadline_mined`, `_duration_months_mined`) | Multilingual Regex über `_description_final`/`description_en`. Free, additiv. Cache `.text_mining_cache.json`. Sitzt im `--all` zwischen 3e-2 und 3f. Sprint Window D (2026-05-18). |
| 3l: URL-Check | `--url-check` | relevant.json | relevant.json (`_url_status`, `_url_checked_at`, `_url_http_code`) | Ranged-GET-Probe auf `source_url_national`. Status: `alive` / `dead` / `auth_walled` (401/403, z. B. EE eIDAS) / `timeout` / `unknown` / `no_url`. Cache `.url_health_cache.json` TTL 30 Tage. Free. Sitzt im `--all` nach 3j, vor Phase 4 — Feld geht ins Export als `url_status`. Sprint 2026-05-20. |
| 3g: Docs | `--extract-documents` | relevant.json, PDF/docx | relevant.json (`_extracted_specs`) | Opt-in — nicht in `--all` default |
| 3g+: Fallback | (Teil von `--extract-documents`) | relevant.json, nationale Portale | relevant.json (`_fallback_*`, `_source_url_national`) | Greift nur wenn alle URLs tot; DE/PL/CZ; Cache `.national_fallback_cache.json`; `--no-fallback-cache` erzwingt Fresh-Fetch |
| Strategy A | `--strategy-a` | relevant.json + `data/ted_xml_cache/*.xml` | relevant.json (`_strategy_a_specs`) | **Proaktiv** DE/PL/CZ Vergabeunterlagen-Scrape (≠ Phase 3g+ Fallback). Liest buyer_profile_url / tender_documents_access aus `_xml` ODER XML-Cache. Cache `.strategy_a_cache.json`. Nicht in `--all`. Window E, 2026-05-18. |
| 4: Export | `--phase export` | relevant.json, uk_blacklist | YYMMDD_TED_Tender Data_00.XX.xlsx | Skipped wenn kein `_trailer_type_1_ai` |

**⚠️ Kritische Regel:** `--phase filter` überschreibt `relevant.json` vollständig. Nationale Notices (UK-CF, PL-NP) und manuelle Korrekturen gehen verloren. Immer NACH filter+classify re-mergen.

---

## 5. Datenmodell

### relevant.json — Felder pro Notice
```json
{
  "tender_id": "682847-2024",
  "_title_final": "General Cargo Trailer ...",
  "_authority_name": "BAAINBw",
  "_country_normalized": "Germany",
  "_pub_date": "2024-09-15",
  "_value_num": 5200000.0,
  "_value_currency": "EUR",
  "_value_eur_num": 5200000.0,
  "_status": "Open",
  "_trailer_type_1_ai": "4-Axle Cargo Trailer 12.5t",
  "_trailer_category_1_ai": "Cargo Trailer",
  "_trailer_qty_1_ai": 50,
  "_trailer_type_2_ai": null,
  "_trailer_category_2_ai": null,
  "_trailer_qty_2_ai": null,
  "_additional_equipment_ai": null,
  "_additional_qty_ai": null,
  "_contract_duration_ai": "48 months",
  "award": {
    "awarded": true,
    "winner_name": "Acme Defence Ltd",
    "award_date": "2024-12-01",
    "award_id": "748392-2024"
  },
  "_description_final": "...",
  "_source": "TED",
  "ted_url": "https://ted.europa.eu/...",
  "_source_url_national": null,

  "_raw": {
    // Sprint 2026-05-10 (TED-XML §B): new API fields backfilled for all
    // 194 TED tenders via scripts/_backfill_ted_xml_fields.py
    "buyer-internet-address":      ["http://www.evergabe-online.de/"],
    "estimated-value-lot":         ["2332000", "827000", "857000", "568000"],
    "quantity-lot":                [...],
    "procedure-features":          {"fra": "...", "eng": "..."},
    "place-of-performance-city-part":    [...],
    "place-of-performance-country-part": [...],
    "deadline-receipt-tender-time-lot":  [...],
    "internal-identifier-part":          [...],

    // Sprint 2026-05-10 (TED-XML §B+ Fallback): XML-only fields backfilled
    // for all 194 TED tenders via scripts/_backfill_ted_xml.py.
    // XML lebt im disk-cache data/ted_xml_cache/{id}.xml.
    "_xml": {
      "internal_reference":      "Q/U2BP/RA029/NA103",
      "tender_documents_access": "https://www.evergabe-online.de/tenderdetails.html?id=771723",
      "buyer_profile_url_full":  "http://www.evergabe-online.de/",
      "contract_folder_id":      "e911c5fa-bc2a-4b21-ae61-9e360f45da6a",
      "notice_uuid":             "976398c5-e43e-4f6a-8f02-1cb8bc86457a"
    }
  }
}
```

**Quality-Enhancement-Felder (Phase 3j, 2026-05-17, Value-Inference rückgebaut 2026-05-18):**
- `_contract_type` — "one_time" | "framework_agreement" | "recurring" | "unknown"
- `_contract_duration_months` / `_duration_months_inferred` — int oder null (aus Regex-Extraktion)
- `_extension_options` — bool, true wenn Verlängerungsoptionen erwähnt

Der Exporter mappt diese auf: `contract_type`, `extension_options`. **Phase 3i
(Value Inference) wurde 2026-05-18 zurückgebaut** — fehlende Vertragswerte sind
im Defence-Intelligence-Kontext ein eigenes Signal, geschätzte Werte verfälschen
die Datenwahrnehmung. Nur gemessene Werte (`estimated_value` aus Quelle)
fließen in `estimated_value_eur`.

**TED-Quick-Wins-Felder (Sprint 2026-05-18):** Vier neue eForms-Felder aus
`framework-agreement-lot` / `contract-conclusion-date` / `organisation-name-buyer`
/ `organisation-identifier-buyer`. Backfill via
`scripts/_backfill_ted_quick_wins.py`. Coverage in eForms-Ära (2023+) ~76–82 %,
keine Coverage pre-2023 (TED_EXPORT-Schema kennt diese Felder nicht).
- `_framework_type` — eForms-Code `fa-wo-rc` / `fa-w-rc` / `fa-mix` / `none`.
  **Strukturierte Quelle für `_contract_type`** (Tier 0 in `contract_type.py`,
  vor Regex). 24 TED-Notices sind nach Re-Run deterministisch klassifiziert.
- `_contract_conclusion_date` — ISO-Date (`2025-04-16`), echtes Award-Datum
  (≠ Publikations-Datum des CAN).
- `_authority_name_structured` — Englisch bevorzugt aus multilingualem
  `organisation-name-buyer`-Dict; Exporter zieht das vor `_authority_name`
  vor `contracting_authority.name`.
- `_authority_id` — stabile Buyer-Registriernummer (DE: HRB, NL: KVK,
  SE: organisationsnummer). Foreign-Key für Buyer-Profile-Aggregation.

Der Exporter mappt diese auf: `framework_type`, `contract_conclusion_date`,
`authority_identifier`.

**Strategy-A-Felder (Window E, 2026-05-18):** Proaktiver Vergabeunterlagen-Scrape
DE/PL/CZ via `--strategy-a`. Schreibt `_strategy_a_specs` in relevant.json und
exportiert als `strategy_a_specs` in tenders.json. 3 PL-Tender haben Daten,
Confidence 0–30 (ezamowienia HTML-Body).
- `_strategy_a_specs` — `{trailer_types, coupling_type, additional_equipment, confidence}`
  (identische Struktur wie `_extracted_specs`). Exporter mappt → `strategy_a_specs`.

**Publication-Date-Source (`_published_at_source`, 2026-05-20):** Interner
Marker pro Notice — sagt aus, ob `_pub_date_clean` / `publication_date`
das **ursprüngliche Tender-Start-Datum** ist oder ein post-award Fallback.
Frontend nutzt das Feld nicht (bleibt intern); Audit/Backlog brauchen es
zur Unterscheidung.

| Wert | Bedeutung |
|------|-----------|
| `tender_notice` | direktes Tender-Datum (TED CN, CanadaBuys RFP/RSO, UK FTS, CZ/FR/NO/EE Tender-Notices) |
| `pin_notice` | TED Prior Information Notice (PIN ist die früheste öffentliche Information) |
| `tender_period_start` | aus OCDS `tender.tenderPeriod.startDate` |
| `related_lookup` | TED CAN → Original-CN via Related-Notice-Verlinkung (Window F) |
| `contract_notice_fallback` | kein besseres Datum verfügbar (AU OCDS post-award, TED self-CAN ohne CN-Match) |
| `unknown` | kein Datum vorhanden |

Adapter-Hooks: `au_ocds_adapter.py` setzt den Marker in `to_standard_format()`
über `_pick_publication_date()`; `canada_loader.py` setzt
`"tender_notice"`; alle anderen werden über
`scripts/_backfill_publication_dates.py` (regel-basiert) backfilled. Siehe
`docs/DATE_AUDIT_260520.md` für die volle Source-Tabelle.

**Frontend-Schema-Felder (Sprint 2026-05-10):** der Exporter mappt
`_raw` und `_raw._xml` zusammen auf:
- `buyer_profile_url` — XML preferred, JSON fallback. **89 % TED.**
- `internal_reference` — XML preferred, JSON fallback. **39 % TED**
  (nur eForms-Notices haben das Feld).
- `tender_documents_access` — XML-only Deeplink mit Tender-ID. **28 % TED.**
- `contract_folder_id` — XML-only eForms-UUID. **37 % TED.**
- `procedure_features` — JSON, multilingual.
- `lots[]` — JSON, Pro-Lot-Breakdown `{id, value, quantity}`.

### AI-Kategorie-Klassen (11 gültige Werte)
```
Low-Bed | Semitrailer | Dolly | Tank Trailer | Mission Module |
Loading System | Special Purpose | Ammunition Trailer | Field Kitchen |
Cargo Trailer | Other
```

### enrichment_log.json — Cache-Struktur
```json
{
  "682847-2024": {
    "result": { "relevant": true, "trailer_type_1": "...", ... },
    "timestamp": "2026-04-28 22:30:00",
    "title": "..."
  }
}
```

---

## 6. KI-Klassifikatoren

| Klasse | Modell | Wann |
|--------|--------|------|
| `AiClassifier` | claude-sonnet-4-6 | Default, seriell |
| `TwoStageClassifier` | Haiku prefilter + Sonnet | Empfohlen: `--two-stage` |
| `ParallelClassifier` | wraps any | Default (5 Worker) |
| `BatchClassifier` | claude-sonnet-4-6 | `--batch` (50% günstiger, ~1h) |
| `OpenRouterClassifier` | via .env | `--llm openrouter` (EXPERIMENTELL) |

**Two-Stage-Prinzip:** Haiku filtert ~90% raus (YES/NO), Sonnet klassifiziert nur die YES-Kandidaten. Spart ~85% Kosten.

**Translation Steps (Phase 3e / 3e-2 / 3e-3):**

| Step | Funktion | Modell | Flag | Cache |
|------|----------|--------|------|-------|
| Title Translation | `translate_titles()` in `src/translator.py` | Haiku 4.5 | `--translate-titles` | `data/.translation_cache.json` |
| Description Translation | `translate_descriptions()` in `src/translator.py` | Sonnet 4.6 | `--translate-descriptions` | `data/.description_translation_cache.json` |
| Description Cleaning | `process_descriptions()` in `src/translator.py` | Haiku 4.5 | (automatisch nach 3e-2) | `data/.description_translation_cache.json` (key: `{tid}:{sha1}:haiku-clean`) |

Alle drei Steps laufen nach `--phase classify`, vor Award-Match. Schreiben `title_en` und `description_en` additiv in `relevant.json`. Cache-Hit = 0 API-Kosten bei Re-Runs.

**Cleaning-Pass (3e-3):** `process_descriptions()` läuft automatisch nach jeder `--translate-descriptions`-Phase. Erkennt RAW_ENGLISH via `_needs_cleaning()` (Bad-Prefix: "File Number", "NOTICE OF PROPOSED", "Amendment", etc.; > 4 Sätze; identischer Pass-through). Haiku 4.5 produziert 2–4 Satz-Summary. `--force-clean` umgeht den Clean-Cache für einen vollständigen Re-Pass. Ergebnis Sprint 14j+: 0% RAW_ENGLISH (100% CLEAN) nach 74 Haiku-Calls, $0.057.

**Document Extraction (Phase 3g):**

| Step | Modul | Modell | Flag | Cache-Key |
|------|-------|--------|------|-----------|
| Doc Extraction | `src/document_pipeline/ai_structurer.py` | **gpt-4o** (OpenRouter) | `--extract-documents` | `{tender_id}:gpt-4o` |

- Default: `openrouter/openai/gpt-4o` — F1=0.911 (Eval 2026-05-09, 8 Defence Samples)
- Override: `EXTRACTION_MODEL=<model_id>` env-Variable
- Fallback bei OpenRouter-Fehler: `anthropic/claude-sonnet-4-6` (automatisch)
- Cache in `data/.document_extraction_cache.json` — Cache-Key enthält Model-Slug: Modell-Wechsel erzwingt automatisch frische Calls
- Voller Run (194 TED-Notices): ~$0.50–0.80, ~13 min
- **Nicht automatisch in `--all`** — explizit via `--extract-documents` aktivieren

**Value Inference (Phase 3i) — DEPRECATED 2026-05-18:**

Phase 3i (statistische Median-Schätzung + Haiku-LLM-Fallback für fehlende
Vertragswerte) wurde am 2026-05-18 zurückgebaut. Im Defence-Intelligence-
Kontext sind fehlende Werte ein eigenes Signal; geschätzte Werte verfälschen
die Datenwahrnehmung. Modul `src/value_inference.py` → `.deprecated`, Caches
gelöscht, Schema-Felder `estimated_value_eur_inferred` / `value_confidence`
entfernt. Siehe CHANGELOG (2026-05-18).

**Contract Type (Phase 3j):**

| Step | Modul | Modell | Flag | Cache |
|------|-------|--------|------|-------|
| Multilingual Regex | `src/contract_type.py` | — | `--contract-type` | `data/.contract_type_cache.json` |

- Sprachen: EN/DE/FR/PL/CZ/SE/DK/NL/IT/ES
- Default: `one_time` (korrekt für Rüstungsbeschaffung ohne explizite Rahmenvertrag-Signale)
- Ergebnis 2026-05-17: 311 one_time / 20 framework_agreement / 6 recurring / 0 unknown

**Award-Match LLM (Phase 3d-LLM):**

| Step | Modul | Modell | Flag | Cache-Key |
|------|-------|--------|------|-----------|
| LLM Award-Match | `src/award_matcher_llm.py` | **Haiku 4.5** (Anthropic direct) | `--award-match-llm` | `{tender_id}:claude-haiku-4-5` |

- Default seit Sprint 14i (2026-05-12): `claude-haiku-4-5` — F1=1.000 (Eval 2026-05-11, 10 Samples; vorher Sonnet 4.6 mit F1=0.825, +17.5pp)
- Override: `AWARD_MATCH_MODEL=<model_id>` env-Variable
- Cache in `data/.award_match_llm_log.json` — Schlüssel-Format `{tender_id}:{model_slug}` (vorher nur `{tender_id}`); legacy entries werden lesbar gehalten
- Voller Re-Run (~125 unmatched Tender): ~$0.08, ~5 min
- Pricing per 1M tokens: $1 in / $5 out (3× günstiger als Sonnet)
`--national`-Standalone-Runs triggern beide Steps automatisch nach dem Merge.

---

## 7. Nationale Adapter (26 Adapter — 9 WORKING / 13 WORKING_NO_DATA / 3 STUB / 1 RETIRED)

Alle in `src/national_scraper/adapters/`. Pattern: `BaseAdapter` + `BrowserCore` (Playwright).
**26 Adapter-Files** insgesamt; 25 registriert in `main.py:get_adapter_registry` (TR auskommentiert).
Vollständiger Audit-Stand siehe `data/adapter_status.json` + `docs/ADAPTER_INVENTORY_260518.md` (Sprint 2026-05-18).

Status-Legende: **W** = WORKING (liefert Tender im aktuellen `relevant.json`),
**W0** = WORKING_NO_DATA (läuft, 0 Tender im aktuellen Pool — meist weil Defence-Buyer auf TED publiziert),
**S** = STUB (Discovery offen), **R** = RETIRED.

| Land | Adapter | Status | Tender* | Strategie |
|------|---------|:------:|--------:|-----------|
| CA | `canada_loader.py` | **W** | 74 | CanadaBuys CSV Open Data — kein Browser, ETag-Cache, source `CA-CB`. Höchster Yield. |
| AU | `au_ocds_adapter.py` | **W** | 22 | AusTender OCDS REST, post-award. CC BY 4.0. Source `AU-TEN`. Key `au`. |
| AU-ATM | `au_atm_adapter.py` | **W** | 0† | AusTender ATM (pre-award) RSS. Source `AU-AT`. Key `au-atm`. UA: Mozilla-Chrome Pflicht. Merge in relevant.json noch nicht ausgeführt. |
| CZ | `cz_adapter.py` | **W** | 30 | NEN/NIPEZ. 49 min full run. Detail-Pages eIDAS-protected (Window F). |
| FR | `fr_adapter.py` | **W** | 13 | BOAMP REST. Newest pub 2021 — aktuelle MINARM-Beschaffungen scheinen direkt auf TED zu landen. |
| UK | `uk_fts_adapter.py` | **W** | 6 | FTS OCDS API. 64-Monate-Full-Scan im Backlog. Key `gb`. |
| NO | `no_adapter.py` | **W** | 3 | Doffin REST (`POST api.doffin.no/webclient/api/v2/search-api/search`). Live-Smoke 2026-05-18 OK. |
| UA | `ua_adapter.py` | **W** | 2 | Prozorro REST. Confidential Defence-Procurement → 404 graceful. |
| NL | `nl_adapter.py` | **W** | 1 | TenderNed lokaler Filter (API ohne server-side filter). |
| DE | `de_adapter.py` | W0 | 0 | service.bund.de Playwright. BAAINBw publiziert auf E-Vergabe/TED. |
| DE-EV | `de_evergabe_adapter.py` | W0 | 0 | evergabe-online.de. Detail-Pages teilweise hinter Login. |
| PL | `pl_adapter.py` | W0 | 0 | eZamowienia REST + CPV+wojsk-Filter. |
| FI | `fi_adapter.py` | W0 | 0 | Hilma REST. Puolustusvoimat publiziert auf TED. |
| SE | `se_adapter.py` | W0 | 0 | Kommersannons REST. FMV publiziert i.d.R. auf TED. |
| DK | `dk_adapter.py` | W0 | 0 | Udbud.dk Angular SPA. 14j-Hardening möglicherweise zu strikt. |
| RO | `ro_adapter.py` | W0 | 0 | SEAP AngularJS 1.4. Direct-requests VPN-timeouts → Playwright Pflicht. |
| BE | `be_adapter.py` | W0 | 0 | publicprocurement.be Vue+Keycloak. Body-Format unsolved; Défense → TED. |
| ES | `es_adapter.py` | W0 | 0 | PLACE WebSphere. JS-click-workaround. |
| IT | `it_adapter.py` | W0 | 0 | ANAC REST+Playwright. Rate-Limit. |
| CH | `ch_adapter.py` | W0 | 0 | simap.ch REST, historisch ab 2024-07-01. armasuisse → TED. |
| LV | `lv_adapter.py` | W0 | 0 | IUB JSON API (infob.iub.gov.lv). |
| NSPA | `nspa_adapter.py` | W0 | 0 | NSPA eProcurement5G Playwright + 5s Throttle. Source `NSPA-EP`. Manueller Trigger `--national nspa` (NICHT in `--all`). |
| EE | `ee_adapter.py` | **S** | 3‡ | Open Data XML monatlich; POST /rhr-web/api/v1/procurements/search → 404. XHR-Discovery offen. |
| LT | `lt_adapter.py` | **S** | 0 | REST 404; SPA-Browser-Fallback (cvpp.eviesiejipirkimai.lt) offen. |
| GR | `gr_adapter.py` | **S** | 0 | Promitheus ADF ViewState — Discovery offen (Sprint 12). |
| TR | `tr_adapter.py` | **R** | 0 | RETIRED Sprint 14d: Defence-Procurement publiziert auf tedarik.msb.gov.tr (MSB), nicht EKAP. In `get_adapter_registry` auskommentiert. |

*Anzahl Tender mit passendem ID-Prefix bzw. `_source` in aktueller `relevant.json` (322 Notices).
†AU-ATM Live-Smoke OK (18 Defence-Hits), aber Merge in relevant.json noch ausstehend.
‡EE-Tender stammen aus historischen Open-Data-XML-Imports; aktueller Adapter-State ist STUB.

---

## 8. Umgebung & Config

```bash
# Python 3.14.3, Windows 11
# .env (root-Verzeichnis):
ANTHROPIC_API_KEY=sk-ant-...
SSL_VERIFY_DISABLE=1       # Pflicht bei Corporate VPN — alle requests+Playwright nutzen verify=False
LLM_ANTHROPIC_API_KEY=...  # Alias → ANTHROPIC_API_KEY (auto-mapped)
```

```yaml
# config/settings.yaml Schlüsselwerte:
api:
  requests_per_second: 1    # Nicht erhöhen — 429-Errors!
  page_size: 250
scoring:
  threshold_relevant: 25    # Score-Schwelle für relevant.json
  threshold_high_confidence: 50
```

---

## 9. Aktueller Stand (Window E — Handover 2026-05-19)

**Branch:** `main`  
**Letztes Excel:** `data/export/260503_TED_Tender Data_00.01.xlsx` (Sprint 13, 219 rows)  
**relevant.json:** 322 Notices (187 TED + 56 AU-TEN + 32 CZ-NEN + 19 CA-CB + 13 FR-BP + 6 UK-CF + 9 andere)  
**shared/tenders.json:** 275 Tender (47 by 14j safety-net gefiltert)

### Window E Änderungen (2026-05-18/19)
| Komponente | Änderung |
|------------|----------|
| `src/document_pipeline/strategy_a.py` | **neu** — Strategy-A-Runner: proaktiver DE/PL/CZ Vergabeunterlagen-Scrape. Cache `.strategy_a_cache.json`. |
| `src/document_pipeline/discovery.py` | + `_discover_strategy_a()`, `_strategy_a_inputs()`, `_xml_inputs_from_cache()` |
| `src/national_scraper/fallback/de_search.py` | + `fetch_vergabeunterlagen()` (evergabe + service.bund.de) |
| `src/national_scraper/fallback/pl_search.py` | + `fetch_swz_documents()` (ezamowienia API + platformazakupowa) |
| `src/national_scraper/fallback/cz_search.py` | + `fetch_lv_documents()` (VOP + NEN + generic CZ) |
| `src/exporter_frontend.py` | + `strategy_a_specs` Export; + TED Quick-Wins Felder (`framework_type`, `authority_identifier`, `contract_conclusion_date`) |
| `main.py` | + `--strategy-a` Flags (nicht in `--all`); + `run_phase_strategy_a()` |
| `scripts/_smoke_strategy_a.py` | **neu** — Discover-only Smoke-Test (kein Download/LLM) |
| `scripts/_snapshot_final.py` | **neu** — Sprint-Diff Snapshot Generator |
| `data/filtered/relevant.json` | +3 `_strategy_a_specs` (PL-Tender); +71 Quick-Wins Felder (Mini-Fix 1) |
| `src/national_scraper/adapters/au_atm_adapter.py` | **neu** — AusTender ATM RSS (pre-award). Source `AU-AT`. Key `au-atm`. Merge pending. |
| `docs/STRATEGY_A_IMPLEMENTATION.md` | **neu** — Vollständige Architektur-Doku |

### Sprint 14 Änderungen (Windows C–D, 2026-05-17/18)
| Komponente | Änderung |
|------------|----------|
| `src/contract_type.py` | Neu: Contract Type Classifier (Phase 3j) — 10-Sprachen-Regex |
| `src/text_miner.py` | Neu: Text Mining (Phase 3k) — qty/deadline/duration aus `_description_final` |
| `src/value_inference.py` | Neu & **Rollback 2026-05-18**: Value Inference (Phase 3i). Zurückgebaut → `.deprecated` |
| `src/exporter_frontend.py` | `_lift_specs()` neu; contract_type, extension_options Export |
| `scripts/_backfill_ted_quick_wins.py` | TED Quick-Wins Backfill für 187 TED-Notices |
| `scripts/_rollback_value_inference.py` | Entfernt `_value_inferred*` + `_value_confidence` aus relevant.json |

### Quality Gates (Handover 2026-05-19)
| Metrik | Wert | Ziel |
|--------|------|------|
| relevant.json Notices | 322 | — |
| shared/tenders.json (post safety-net) | 275 | — |
| English Titles | 316/322 (98%) | 100% |
| English Descriptions | 316/322 (98%) | 100% |
| Duplicates | 0 | 0 ✅ |
| `_contract_type` Coverage | 316/322 (98%) | — |
| `_framework_type` Coverage (TED eForms-Ära) | 66/187 TED (35%) | — |
| `_strategy_a_specs` | 3 (PL) | ≥2 ✅ |
| `_extracted_specs` | 278/322 (86%) | — |

### Bekannte offene Probleme
1. **4 Unknown Status/Date**: 3 EE-RP + 1 NL-TN Phantoms ohne Datum — nicht behebbar ohne Original-Scrape
2. **UK-FTS Full-Run**: 64-Monate-Scan noch ausstehend — `--national gb`
3. **EE/LT/GR**: Adapter-APIs noch zu discovern (Window F)
4. **AU-ATM Merge**: Live-Smoke OK (18 Defence-Hits), Merge in relevant.json noch nicht ausgeführt
5. **Strategy A DE/CZ PDFs**: evergabe Login-Wall + VOP JS-Wrapper; Playwright-Lösung Window F
6. **CZ eIDAS**: NEN-Attachments hinter eIDAS-SSO; graceful skip aktiv, Cert-Lösung Window F

---

## 10. Kosten-Übersicht

| Run-Typ | ~Kosten |
|---------|---------|
| Full Run (`--all --two-stage --uk --review`) | $0.40–1.10 |
| Incremental (`--all --incremental --two-stage`) | $0.05–0.20 |
| Enrich-only (~100 notices) | $0.50–1.50 |

---

## 11. Wichtige Vorsichtsregeln

1. **Nie `--phase filter` ohne Plan** — überschreibt alles in relevant.json
2. **Nie enrichment_log löschen** — enthält ~7.700 gecachte AI-Ergebnisse
3. **SSL_VERIFY_DISABLE=1 pflicht** — sonst alle API-Calls fehlgeschlagen
4. **`data/.filter_cache.json` ist 189 MB** — nicht committen
5. **Excel mit `Vorlage.xlsx`** — Template-Sheet "Scraper Data" muss existieren
6. **Nach CPV-Erweiterung**: Checkpoint-Queries löschen die re-laufen sollen

---

## 12. Sprint Backlog (Priorität)

### Hoch (Sprint 12)
- **EE API Discovery**: XHR-Intercept auf riigihanked.riik.ee → richtiger Endpunkt
- **LV Session Fix**: Homepage-first Navigation + Open Data CSV als Fallback
- **LT SPA Discovery**: XHR-Intercept auf cvpp.eviesiejipirkimai.lt
- **GR ADF Form**: ViewState extrahieren + CPV-basierte POST-Search
- **UK-FTS Full Run**: 64-Monate-Scan ausführen und Ergebnis messen
- **UA Kyrillisch**: Bessere Trailer-Keywords (причіп, напівпричіп, трал) + CPV-only Match

### Mittel
- **FI Hilma adapter** ausbauen (aktuell STUB)
- **DROPS/EPLS TED-Run**: `--phase index` ohne Checkpoint für neue Queries (text_search_5–8)
- **DE-EV Filterung verbessern**: CPV-basierte Suche statt Keyword
- **CZ Detail-Cap**: 150→216 oder faster parallel fetching

### Niedrig
- **Fulltext als Default** (aktuell optional)
- **Award-Match Automation** für "Closed"-Status
- **archiv.simap.ch** adapter für CH historische Daten
- **"Other"-Kategorie**: Prompt-Tuning oder manueller Re-Classify Pass (9 notices)
- **Field-Mapping CLAUDE.md §5**: `_winner_name` (top-level) existiert in keinem der 256 relevanten Notices — korrekter Pfad ist `award.winner_name`; §5-Beispiel wurde mit Sprint 14b korrigiert. Siehe `docs/STATUS_AUDIT.md §2.1`.

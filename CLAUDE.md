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
  national_scraper/
    core.py                         # BrowserCore (Playwright-Wrapper)
    base_adapter.py                 # BaseAdapter, SearchResult, NoticeDetail
    adapters/                       # 13 Länder-Adapter
      de_adapter.py, pl_adapter.py, cz_adapter.py, ...
data/
  filtered/relevant.json            # *** HAUPT-DATENDATEI ***
  .enrichment_log.json              # AI-Ergebnis-Cache (nie löschen!)
  .checkpoint.json                  # Abgeschlossene TED-Queries (resume)
  .filter_cache.json                # Filter-Cache (189 MB, auto-managed)
  export/                           # Excel-Outputs + archive/
  raw/details/                      # ~35.000 einzelne TED Notice JSONs
Vorlage.xlsx                        # Excel-Template (Sheet: "Scraper Data")
```

---

## 4. Pipeline-Phasen

| Phase | Flag | Liest | Schreibt | Kritisch |
|-------|------|-------|----------|----------|
| 1+2: Index | `--phase index` | settings.yaml | `raw/details/*.json`, checkpoint | Checkpoint ermöglicht Resume |
| 3: Filter | `--phase filter` | `raw/details/*.json` | `filtered/relevant.json` | **ÜBERSCHREIBT** relevant.json komplett! |
| 3b: Classify | `--phase classify` | relevant.json, enrichment_log | relevant.json (in-place) | Cached in enrichment_log — kein Doppel-API-Call |
| 3c: Enrich | `--enrich` | TED HTML | fulltext/*.txt, relevant.json | Optional, langsam (+20 min) |
| 3d: Award | `--award-match` | relevant.json | relevant.json (winner update) | — |
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
  "_winner_name": null,
  "_description_final": "...",
  "_source": "TED",
  "ted_url": "https://ted.europa.eu/...",
  "_source_url_national": null
}
```

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

---

## 7. Nationale Adapter (17 Länder + 4 Stubs)

Alle in `src/national_scraper/adapters/`. Pattern: `BaseAdapter` + `BrowserCore` (Playwright). 21 total registriert in `main.py`.

| Land | Adapter | Status | Strategie |
|------|---------|--------|-----------|
| DE | `de_adapter.py` | ✅ | service.bund.de — JS-Checkboxen VSVgV+KFZ |
| PL | `pl_adapter.py` | ✅ | eZamowienia REST API (kein Browser nötig) |
| CZ | `cz_adapter.py` | ✅ | NIPEZ portal |
| FI | `fi_adapter.py` | ✅ | Hilma REST API |
| SE | `se_adapter.py` | ✅ | Upphandlingsmyndigheten |
| NO | `no_adapter.py` | ✅ | DOFFIN |
| DK | `dk_adapter.py` | ✅ | Udbud.dk |
| NL | `nl_adapter.py` | ✅ | TenderNed |
| BE | `be_adapter.py` | ✅ | e-Procurement |
| ES | `es_adapter.py` | ✅ | PLACE |
| IT | `it_adapter.py` | ✅ | Appalti |
| FR | `fr_adapter.py` | ✅ | BOAMP |
| RO | `ro_adapter.py` | ✅ | SEAP |
| CH | `ch_adapter.py` | ✅ | simap.ch REST API, historisch ab 2024-07-01 |
| UK | `uk_fts_adapter.py` | ✅ | FTS OCDS API, monatliche Fenster 2021→heute |
| UA | `ua_adapter.py` | ✅ | Prozorro REST API |
| LV | `lv_adapter.py` | ✅ | IUB JSON API (infob.iub.gov.lv) |
| EE | `ee_adapter.py` | Stub | Open Data XML monatlich; API 404 graceful |
| LT | `lt_adapter.py` | Stub | REST 404; SPA-Browser Fallback (cvpp.eviesiejipirkimai.lt) |
| GR | `gr_adapter.py` | Stub | Promitheus ADF — ViewState nötig (Sprint 12) |

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

## 9. Aktueller Stand (Sprint 13, 2026-05-03)

**Branch:** `main`  
**Letztes Excel:** `data/export/260503_TED_Tender Data_00.01.xlsx` (Sprint 13, 219 rows, 252 notices)

### Sprint 13 Änderungen
| Komponente | Änderung |
|------------|----------|
| `src/exporter.py` | `normalize_country()` robuster: list-Typen, ISO-2 Codes, case-insensitive, Newline-Handling |
| `relevant.json` | 50 phantom-Notices gepatcht: country/authority/URL/date aus Source-Code rekonstruiert |
| `data/sprint13_summary.md` | Sprint-Summary mit Quality Gates |

### Quality Gates (Sprint 13)
| Metrik | Vorher | Nachher | Ziel |
|--------|--------|---------|------|
| Unknown Country | 50 | **0** | 0 ✅ |
| Unknown Status | 21 | **4** | <5 ✅ |
| No Date | 53 | **4** | <10 ✅ |
| No Authority | 50 | **0** | <10 ✅ |
| Duplicates | 0 | **0** | 0 ✅ |

### Bekannte offene Probleme
1. **4 Unknown Status/Date**: 3 EE-RP + 1 NL-TN Phantoms ohne Datum — nicht behebbar ohne Original-Scrape
2. **UK-FTS Full-Run**: 64-Monate-Scan noch ausstehend — `--national gb`
3. **EE/LT/GR**: Adapter-APIs noch zu discovern (Sprint 14)
4. **UA Kyrillisch**: bessere Trailer-Keywords nötig
5. **National URL 26%**: Nur ~57 von 219 Notices haben nationale Portal-URL

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

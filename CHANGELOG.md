# Changelog

Alle relevanten Änderungen am TED Defence Trailer Scraper werden hier dokumentiert.

---

## [1.5.0] - 2026-05-03

### Added
- **21 national portal adapters**: SE (Kommersannons), NO (Doffin), CZ (NEN),
  FR (BOAMP), DK (Udbud.dk), NL (TenderNed), ES (PLACE), IT (ANAC),
  CH (simap.ch), DE (evergabe-online + service.bund.de), BE (e-Procurement),
  PL (BZP), RO (SEAP), FI (Hilma), UA (Prozorro), EE (riigihanked),
  LV (IUB), LT (CVPP), GR (Promitheus stub)
- **Country Adapter Pattern**: Universal Playwright-based scraper with
  BaseAdapter, BrowserCore, and per-country adapters
- **Parallel pipeline**: All data sources run concurrently (ThreadPoolExecutor)
- **Opus quality review**: Automated post-run QA with `auto_apply_opus_findings`
  (blacklists FPs, merges duplicates, applies category corrections); `--no-review` to skip
- **Resilience layer**: Exponential backoff, rotating user agents, graceful degradation (`RetrySession`)
- **Force-include mechanism**: National notices preserved across filter re-runs
  (`config/national_force_include.json`)
- **PDF extraction**: pdfplumber fallback when HTML fulltext unavailable
- **CanadaBuys**: Active tenders + historical DND contracts via open.canada.ca CSV
- **UK Find a Tender (FTS)**: OCDS API with monthly date windows (2021 → today)
- **Filter cache**: 207x faster filtering (55 min → <20 sec warm, `data/.filter_cache.json`)
- **`--no-enrich` / `--no-review`**: Flags to skip enrichment or Opus QA per run
- **EE XML bulk export**: Monthly UBL eForms XML from riigihanked.riik.ee (no auth)
- **LV IUB JSON API**: Direct REST calls to infob.iub.gov.lv (no Playwright required)

### Changed
- Fulltext enrichment now runs by default (`--no-enrich` to skip)
- AI classification parallelized by default (5 workers, `ParallelClassifier`)
- Status logic improved: 0 Unknown-Status notices for TED
- Country normalization handles ISO-2, ISO-3, list types, and authority inference
- `normalize_country()` in `exporter.py` hardened for all edge cases

### Fixed
- CZ notices stable across filter re-runs (force-include mechanism)
- UK-FTS cursor bug (monthly windows instead of broken 365-day scan)
- EE adapter `NameError: EE_SEARCH_URL` — constant added
- LT adapter `_browser_search` returning 0 results (React SPA — uses `page.evaluate()`)
- LV adapter rewritten from broken Playwright to working JSON API
- Classify phase no longer overwrites enrichment data
- Award-match writeback to `relevant.json`
- 50 phantom notices patched: country/authority/URL/date reconstructed from source code

### Removed
- 17 duplicate notices identified by Opus review
- 5 false positives (non-trailer defence items)

---

## [1.4.0] - 2026-04-14

### Performance: Phase 1+2 Merged (~50x faster)

Phase 1 (Index) und Phase 2 (Details) sind jetzt zu einem einzigen Durchlauf zusammengelegt. Die Search API liefert alle Detail-Felder direkt im Bulk-Request mit.

- **Vorher**: Phase 1 holt IDs (7 Requests), Phase 2 holt Details einzeln (1.550 Requests, ~25 Min)
- **Nachher**: Phase 1 holt IDs + Details zusammen (7 Requests, ~30 Sekunden)

#### Geändert

- **`api_client.py`**: `INDEX_FIELDS` und `DETAIL_FIELDS` zu `ALL_FIELDS` zusammengelegt
- **`index_builder.py`**: Normalisiert und speichert jede Notice sofort als Detail-JSON während der Index-Erstellung
- **`main.py`**: Phase 2 ist jetzt ein No-Op (zeigt nur an wie viele Details bereits auf Disk liegen)

---

## [1.3.0] - 2026-04-14

### New Columns, Missing Tenders Fix, Folder Structure, English Output

#### Root Cause: Missing BAAINBw Tenders

- **682847-2024** (General Cargo Trailer 2-Axle 3.5t / 4-Axle 12.5t) was NOT in the index
- **Ursache**: `--test` Mode holt nur 1 Seite pro Query. Query "Trailer CPV + Richtlinie 2014/24" hat 4.049 Ergebnisse — 682847-2024 lag auf Seite 2+
- **Fix**: Neue Query 5 "all_trailer_cpv_no_filter" — holt ALLE Trailer-CPV Notices ohne Legal-Basis-Filter
- **147766-2020** und **212474-2026** waren bereits korrekt im Index und in der Excel

#### Neue Spalten (14 statt 12)

| Spalte | Beschreibung |
|--------|-------------|
| **Axle Type** (neu) | Formatierte Achsbeschreibung aus der Ausschreibung, z.B. "4.5t 3-Axle Semitrailer" |
| **Contract Duration** (neu) | Vertragslaufzeit, z.B. "84 months", "7 years" |

#### Geändert

- **Excel-Spalten**: 12 → 14 (+ Axle Type, Contract Duration)
- **TED URLs** sind jetzt klickbare Hyperlinks (blau, unterstrichen)
- **Dateiname**: `260414_TED_Tender Data_00.01.xlsx` (Datum + Version pro Tag)
- **Ordnerstruktur**: Neueste Excel in `data/export/`, Kopie in `archive/`, Tests in `test/`
- **Sheet-Name**: "Sheet3" → "Scraper Data", Titel "BPW Defense | Tender Portals"
- **Index Builder**: Neue Query ohne Legal-Basis-Filter für alle Trailer-CPVs + Zusätzliche Freitext-Suche `FT~"cargo trailer"`
- **Descriptions** bevorzugen Englisch (Fallback: Deutsch, dann erste verfügbare Sprache)
- **`/audit` Skill** komplett auf Englisch umgeschrieben, neue Felder: `_audit_axle_type`, `_audit_category`, `_audit_duration`, `_audit_quantity`

### Error Log

| Zeitpunkt | Phase | Error | Ursache | Fix |
|-----------|-------|-------|---------|-----|
| 2026-04-14 | index | Tender 682847-2024 fehlt im Index | Test-Mode holt nur Seite 1; Tender auf Seite 2+ | Neue Query ohne Legal-Basis-Filter; Full Run holt alle Seiten |
| 2026-04-14 | export | `KeyError: 'Sheet3'` | Vorlage Sheet umbenannt zu "Scraper Data" | Sheet-Name-Fallback implementiert |

---

## [1.2.1] - 2026-04-14

### Manuelles Audit & Datenbereinigung

Manueller Audit-Durchlauf über alle 443 gefilterten Einträge.

#### Audit-Ergebnisse

- **443 → 401 Einträge** (42 entfernt)
- Entfernte Kategorien:
  - **Polizei** (7): Rigspolitiet (DK), Metropolitan Police (UK), Polizeidirektion Niedersachsen, Police fédérale (BE), Politiets fellestjenester (NO)
  - **Bundesministerium des Innern** (8): Beschaffungsamt BMI — nicht Defence sondern Inneres
  - **Kommunen/Städte** (5): Glasgow City Council, Stadt Ilshofen, Stadt Schwabach, Gemeinde Großgmain, Stadtgemeinde Leibnitz
  - **Innenministerien Ausland** (10): Litauen "vidaus reikalų" (Innenministerium Waffenfonds, Granaten/Minen), Bulgarien "Министерство на вътрешните работи"
  - **Nicht-Defence Unternehmen** (5): DARS d.d. (slowen. Autobahngesellschaft), EDF (Energieversorger), VOP CZ (Reparaturbetrieb)
- **Beibehalten** (Grenzfälle):
  - HIL Heeresinstandsetzungslogistik GmbH — Bundeswehr-Instandsetzung, alle unter Defence-Richtlinie 32009L0081
  - Auswärtiges Amt — beschafft gepanzerte Fahrzeuge für Auslandsmissionen unter Defence-Richtlinie
- **Country-Normalisierung**: ISO-Codes (CZE, DEU, NOR, etc.) → volle Namen (Czech Republic, Germany, Norway)

#### Geändert

- **Export PermissionError** (`exporter.py`): Automatischer Fallback auf alternativen Dateinamen wenn Excel die Datei sperrt
- **Rate Limiting** (`settings.yaml`): Von 2 auf 1 Request/Sekunde reduziert (weniger 429-Errors)
- **Test-Modus** (`main.py`): `--test` holt jetzt 100 Details statt 10

### Error Log

| Zeitpunkt | Phase | Error | Ursache | Fix |
|-----------|-------|-------|---------|-----|
| 2026-04-13 23:25 | details | Mehrfach `429 Rate limited` | 2 Requests/Sekunde zu aggressiv | Rate auf 1/s reduziert |
| 2026-04-14 | export | `PermissionError [WinError 32]` | Vorherige Excel noch in Excel geöffnet | Auto-Fallback auf `_2.xlsx` Suffix |

---

## [1.2.0] - 2026-04-13

### Defence-Only Filter, Deduplizierung, Vorlage-Export & Audit-Skill

Grundlegende Überarbeitung der Filter- und Export-Logik basierend auf Nutzer-Feedback.

#### Geändert

- **Strikter Defence-Filter** (`filter_engine.py`): Nur noch Defence-relevante Ausschreibungen passieren den Filter. Prüfung über: Defence-Richtlinie 2009/81, Defence-Keywords im Text, UND Behördenname (Ministry of Defence, Bundeswehr, Armed Forces, etc.)
- **Deduplizierung** (`filter_engine.py`): Ausschreibungen werden oft mehrfach veröffentlicht (Ankündigung, Wettbewerb, Ergebnis). Neue `_deduplicate()` Methode gruppiert nach Authority+CPV+Title und bevorzugt Award/Ergebnis-Notices über Ankündigungen
- **Authority-Kürzung** (`filter_engine.py`): Neue `shorten_authority()` Methode entfernt Rechtstexte, Adressen und Füllphrasen ("Auftraggeber sind die...") und kürzt auf max. 80 Zeichen
- **Excel-Export** (`exporter.py`): Komplett umgeschrieben — schreibt jetzt in die Vorlage.xlsx (Sheet3) statt eigenes Workbook
  - Reduziert auf **12 Spalten**: Tender ID, Title, Country, Authority, Publication Date, Est. Value, Currency, Trailer Category, Quantity, Winner, TED URL, Description
  - **Row Height 45** für alle Datenzeilen
  - **Aptos Narrow 11** als Daten-Font (wie Vorlage)
  - **Calibri 11 Bold White auf #1F4E79** als Header-Font (wie Vorlage)
  - Market Sizing Sheet bleibt erhalten
- **Pipeline-Output** (`main.py`): Zeigt jetzt Defence/Non-Defence Split und Dedup-Statistiken

#### Neue Features

- **`/audit` Skill** (`.claude/skills/audit.md`): Manuelles Audit der gefilterten Daten als Alternative zum Claude API Key. Prüft Defence-Relevanz, korrigiert Trailer-Kategorien, extrahiert Mengen, bereinigt Authority-Namen. Aufruf via `/audit` in Claude Code.

#### Entfernt

- **Summary Sheet** im Excel (nicht mehr nötig, nur noch ein Sheet3 mit Daten)
- **Kategorie-Sheets** (alle Daten in einer Tabelle, filterbar über Spalte "Trailer Category")
- **23-Spalten-Layout** (auf 12 relevante Spalten reduziert)

### Error Log

| Zeitpunkt | Phase | Error | Ursache | Fix |
|-----------|-------|-------|---------|-----|
| 2026-04-13 23:20 | export | `PermissionError: [WinError 32]` beim Kopieren der Vorlage | Alte Excel-Datei war noch in Excel geöffnet (Lock-File) | Neuen Dateinamen verwenden oder alte Datei in Excel schließen |

---

## [1.1.0] - 2026-04-13

### API Migration & Bugfixes

Die initiale Version nutzte falsche API-Endpoints und Query-Syntax. Die TED API war nicht erreichbar (404/400 Errors). Kompletter Rewrite des API-Clients.

#### Geändert

- **API Endpoint** (`api_client.py`): `ted.europa.eu/api/v3.0/notices/search` (404) durch korrekten Endpoint `api.ted.europa.eu/v3/notices/search` ersetzt
- **Query-Syntax** (`api_client.py`): `cpv="..."` durch `classification-cpv="..."` ersetzt (TED Expert Query Syntax)
- **Pflichtfeld `fields`** (`api_client.py`): API verlangt explizite Angabe der gewünschten Rückgabefelder — `INDEX_FIELDS` und `DETAIL_FIELDS` definiert
- **Pagination** (`api_client.py`): `pageSize`/`pageNum` durch `page`/`limit` + `paginationMode` ersetzt; `page_size` auf API-Maximum 250 erhöht
- **Datumsformat** (`api_client.py`): ISO-Format `2024-01-01` wird jetzt automatisch zu `20240101` konvertiert (API erwartet YYYYMMDD)
- **Freitext-Suche** (`index_builder.py`): Anführungszeichen-Syntax `"military trailer"` durch TED-Syntax `FT~"military trailer"` ersetzt
- **Detail-Fetch** (`detail_fetcher.py`): Komplett umgeschrieben — statt authentifiziertem GET-Endpoint (`/v3/notices/{id}`, erfordert Auth-Header) wird jetzt die Search API mit `publication-number="..."` Query genutzt
- **Country-Extraktion** (`detail_fetcher.py`): `organisation-country-buyer` wird von der API oft nicht zurückgegeben; Fallback-Extraktion aus dem Title-Feld ergänzt (Format "Country-City: Description")
- **Multilingual-Parsing** (`detail_fetcher.py`): Neue `get_text()`-Hilfsfunktion für multilingual-Felder der API (Format `{"eng": ["value"], "deu": ["value"]}`)
- **Page Size** (`settings.yaml`): Von 100 auf 250 erhöht (API-Maximum)

#### Entfernt

- **Ungültiger CPV-Code** `35612000` aus `settings.yaml` entfernt (wird von der TED API nicht akzeptiert)
- **`TedWebScraper`-Klasse** aus `api_client.py` entfernt (nicht mehr benötigt)

#### Neue Features

- **Iteration Mode** (`api_client.py`): Neue Methode `search_with_iteration()` für unbegrenzte Ergebnisse via `iterationNextToken` (PAGE_NUMBER Mode ist auf 15.000 limitiert)

### Error Log

| Zeitpunkt | Phase | Error | Ursache | Fix |
|-----------|-------|-------|---------|-----|
| 2026-04-13 21:56 | test-api | `404 Not Found` auf `ted.europa.eu/api/v3.0/notices/search` | Falscher API-Host; `ted.europa.eu/api/v3.0/` existiert nicht | Endpoint auf `api.ted.europa.eu/v3/notices/search` geändert |
| 2026-04-13 22:02 | discover | `400 Unrecognized field "pageSize"` | Falscher Feldname für Pagination | `pageSize`/`pageNum` durch `page`/`limit` ersetzt |
| 2026-04-13 22:02 | discover | `400 Missing Authorization header` auf Detail-Endpoint | GET `/v3/notices/{id}` erfordert API-Key | Detail-Fetch über Search API mit `publication-number` Query gelöst |
| 2026-04-13 22:03 | search | `400 Validation error: fields must not be empty` | `fields`-Parameter ist Pflicht in der Search API | `INDEX_FIELDS` und `DETAIL_FIELDS` Listen definiert |
| 2026-04-13 22:03 | search | `400 Unknown search field 'cpv'` | Query-Syntax `cpv=` wird nicht akzeptiert | Durch `classification-cpv=` ersetzt |
| 2026-04-13 22:09 | test-api | `400 publication-date does not follow pattern '[0-9]{8}'` | Datumsformat `2024-01-01` statt `20240101` | Automatische Konvertierung (Bindestriche entfernen) |
| 2026-04-13 22:09 | index | `400 Value '35612000' is not supported for classification-cpv` | CPV-Code existiert nicht in TED-Datenbank | Code aus `settings.yaml` entfernt |
| 2026-04-13 22:09 | index | `400 Syntax error: mismatched input '"military trailer"'` | Freitext-Suche nutzt andere Syntax als CPV-Filter | `FT~"..."` Syntax für Volltext-Suche implementiert |
| 2026-04-13 22:09 | filter | Alle Countries = `None` | `organisation-country-buyer` nicht in API-Response | Fallback: Country aus Title parsen ("Country-City: ...") |

---

## [1.0.0] - 2026-04-13

### Initiale Version

- 4-Phasen-Pipeline: Index → Details → Filter/Score → Excel Export
- CPV-Code-basierte Suche (3 Tiers)
- Multilinguales Keyword-Matching (EN, DE, FR, IT, ES, PL)
- Relevanz-Scoring mit konfigurierbaren Gewichten
- Optionale AI-Klassifikation via Claude API
- Excel-Export mit Summary, Category-Sheets, bedingter Formatierung
- Checkpoint/Resume für unterbrochene Läufe

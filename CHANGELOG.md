# Changelog

Alle relevanten Änderungen am TED Defence Trailer Scraper werden hier dokumentiert.

---

## [2026-05-20] — AU URL Fix + URL-Health-Check Pipeline (Phase 3l)

Stakeholder konnte AU- und EE-Source-URLs aus dem Frontend nicht öffnen
(404 / "Seite nicht gefunden"). Diagnose: AU-OCDS-Adapter emittierte ein
veraltetes URL-Pattern; EE-Detail-Seiten sind hinter eIDAS-Auth-Wand.

### TEIL 1+2 — AusTender URL-Format-Fix
- **Empirische Discovery** (`docs/AU_URL_FORMAT_260520.md`): Probe via
  `requests` mit Chrome-UA für mehrere CN-IDs. Ergebnis:
  - `…/cn/{ID}/View`  →  302 → **404** (alt, kaputt)
  - `…/cn/Show/{ID}`  →  302 → **200** (korrekt, Path case-insensitive)
- **`src/national_scraper/adapters/au_ocds_adapter.py`** —
  `AU_CN_DETAIL` und `_cn_portal_url()` auf das `/cn/Show/{id}`-Pattern
  umgestellt. Inline-Kommentar mit Probe-Resultat als Anchor für künftige
  Drift-Audits.
- **`scripts/_fix_au_urls.py`** — One-shot Backfill: rewrites
  `source_url_national` für jeden AU-TEN-Eintrag in `relevant.json` und
  invalidiert die zugehörigen Einträge in `.url_health_cache.json`.
  **Run-Ergebnis: 56/56 AU-URLs rewritten.**
- **OCDS-API permalink?** Geprüft, nicht vorhanden — die Portal-URL muss
  aus `release.contracts[0].id` konstruiert werden.

### TEIL 3+4 — EE Riigihangete Register
- **Probe-Ergebnis:** Alle EE-Detail-API-Endpoints (`/rhr/api/v1/public/...`)
  liefern HTTP 401 für anonyme Requests; SPA-Shell
  `…#/procurement/{uuid}` liefert generisch HTTP 200 (2.6 KB React-Shell;
  echte vs. Phantom-UUIDs nicht unterscheidbar ohne Auth).
- **Entscheidung:** EE-URLs bleiben als-is, werden vom Validator als
  `auth_walled` klassifiziert. Damit sind sie im Frontend als "externe
  Login nötig" markierbar statt fälschlich als tot. Eigenständige
  Auth-Discovery → Window F (eIDAS-Tracks).

### TEIL 5 — URL-Health-Check als Pipeline-Step (Phase 3l)
- **`src/url_validator.py`** (neu) — pro Notice ranged-GET (HEAD trifft
  bei vielen Portalen 405) auf `source_url_national`. Klassifiziert nach
  HTTP-Code in `alive` / `dead` / `auth_walled` / `timeout` /
  `redirect_loop` / `unknown` / `no_url`.
  - **Cache:** `data/.url_health_cache.json`, **TTL 30 Tage**, keyed by
    URL (mehrere Tender können auf dieselbe Portal-Seite zeigen).
  - **Rate-Limit:** 0.5 s zwischen Probes (Portal-Höflichkeit).
  - **CLI:** `python main.py --url-check` (standalone) /
    `--url-check-force` (Cache-Bypass) /
    `--url-check-source AU-TEN` (Source-Filter, repeatable).
  - **Module-CLI:** `python -m src.url_validator [--force --source X --dry-run]`.
- **`main.py`** — `run_phase_url_validation()` + Phase 3l-Integration im
  `--all`-Pfad nach Phase 3j (Contract Type), vor Phase 4 (Export), so
  dass `url_status` in den gleichen Run-Export einfließt. Begründung in
  `docs/URL_HEALTH_CHECK.md`.

### TEIL 6 — Exporter-Integration
- **`src/exporter_frontend.py`** — `_url_status` (intern) → `url_status`
  (Export-Feld, optional). Wird ausgelassen wenn Phase 3l noch nicht
  gelaufen ist → Backward-kompatibel.
- **`shared/schema/tender.schema.json`** — neues optionales Feld
  `url_status` (enum: `alive` / `dead` / `auth_walled` / `timeout` /
  `redirect_loop` / `unknown` / `no_url`). Schema-strikt
  (`additionalProperties: false`), daher Pflicht-Eintrag.

### Initial-Run-Ergebnis (322 Notices, frischer Cache)

| Status | Count | Anteil |
|--------|------:|------:|
| alive       | 235 | 73.0 % |
| auth_walled |   5 |  1.6 % |
| dead        |  14 |  4.3 % |
| no_url      |   6 |  1.9 % |
| unknown     |  62 | 19.3 % |
| **Total**   | **322** | |

- **alive 235**: AU-OCDS (56/56 nach Fix), TED-Notices via `ted.europa.eu`,
  UK-FTS, NL-TenderNed, CA-CB.
- **auth_walled 5**: 3 × EE-RP (riigihanked.riik.ee — eIDAS-401),
  2 × weitere Portal-Pfade hinter HTTP-401.
- **dead 14**: einige TED-Notice-IDs, deren Detail-URL nicht (mehr)
  auflöst — Kandidaten für Folge-Audit (Window F).
- **unknown 62**: vermutlich TED-Detail-URLs mit 5xx zum Probe-Zeitpunkt
  oder SSL-Anomalien hinter Corporate-VPN — bleiben im Cache und werden
  beim nächsten Run re-validiert.

### Stichproben (verifiziert)
- **AU CN4237513** (vom Stakeholder gemeldet): `/cn/Show/CN4237513` →
  HTTP 200, CN-Text im Body ✓
- **AU CN4114917, CN4048671, CN4037407**: jeweils HTTP 200 ✓
- **EE 3 UUIDs**: SPA-Shell HTTP 200, API HTTP 401 → korrekt als
  `auth_walled` klassifiziert ✓
- **URL-Health-Cache** befüllt nach erstem Run ✓

### Validation
- `shared/tenders.json` — `validate.py` Exit 0 (Schema enthält neues
  `url_status`-Feld; bestehende Exports ohne `url_status` validieren
  weiterhin, weil das Feld optional ist).

---

## [2026-05-20] — Publication-Date Audit + `_published_at_source` Marker

User-Anforderung: `published_at` im Frontend muss immer das **ursprüngliche
Tender-Veröffentlichungs-Datum** sein — wann die Ausschreibung öffentlich
gestartet wurde. Konkretes Symptom: AU CN4237513 (Commercial Trailers) zeigt
„Published 5 May 26", aber das ist das CN-Publikationsdatum (post-award),
nicht der Tender-Start.

### Audit (`docs/DATE_AUDIT_260520.md`)

Pro Quelle dokumentiert, was `_pub_date_clean` / `publication_date` heute
bedeutet und wo das echte Tender-Start-Datum (falls auffindbar) liegt.
Korpus 2026-05-20: 322 Notices in `relevant.json`.

| Quelle | n | echte Tender-Start? | Marker |
|--------|--:|:-------------------:|--------|
| TED CN (kein Award) | 75 | ✓ | `tender_notice` |
| TED CN + matched CAN (`_from_award_match*`) | 27 | ✓ | `tender_notice` |
| TED self-CAN (Award ohne Match) | 85 | ✗ | `contract_notice_fallback` |
| AU OCDS | 56 | ✗ | `contract_notice_fallback` |
| CanadaBuys | 19 | ✓ | `tender_notice` |
| UK FTS, CZ, FR, NO, EE, NL (mit Datum) | 54 | ✓ | `tender_notice` |
| ohne Datum (3 CZ, 1 NL, 2 UA) | 6 | n/a | `unknown` |

### Code-Änderungen

- `src/national_scraper/adapters/au_ocds_adapter.py`
  - neue Helper `_pick_publication_date(release, contract)` — Priorität
    `tender.tenderPeriod.startDate` → `tender.publishedDate` →
    `tender.documents[0].datePublished` → `release.date` (Fallback).
    AusTender OCDS publiziert die ersten drei heute nicht, der Chain ist
    defensiv für zukünftige Feed-Erweiterungen.
  - `to_standard_format()` schreibt `_published_at_source` (default
    `contract_notice_fallback`).
- `src/national_scraper/adapters/canada_loader.py::to_standard_format()`
  schreibt `_published_at_source = "tender_notice"`.
- `scripts/_backfill_publication_dates.py` (neu) — iteriert über alle
  322 Notices und setzt `_published_at_source` per Source-Regel.
- `src/exporter_frontend.py` — unverändert. `_published_at_source` bleibt
  intern, wird nicht ins Frontend-JSON exportiert.

### Backfill-Statistik (2026-05-20)

```
tender_notice                 175   ( 54.3 %)
contract_notice_fallback      141   ( 43.8 %)
unknown                         6   (  1.9 %)
                              ----
                              322
```

### Bekannte Limitierungen (dokumentiert, nicht behoben)

- **AU OCDS (56 Notices)** — AusTender OCDS post-award liefert kein
  Tender-Start-Datum. `release.date` = CN-Publikation; OCDS `tender`-Block
  enthält nur `id`/`procurementMethod`. Future Fix: AU-ATM-Cross-Reference
  über `solicitationNumber` (au_atm_adapter ist vorhanden, Merge in
  relevant.json noch ausstehend — Window F).
- **TED self-CAN (85 Notices)** — Original-CN war nicht im Crawl. Future
  Fix: TED Related-Notice-Lookup via `_xml.notice_uuid` →
  `noticesPublicationReferenceNotice` (Window F).

### Stichproben verifiziert

| # | Tender | Datum | Marker |
|---|--------|-------|--------|
| 1 | AU CN4237513 | 2026-05-05 (Fallback dokumentiert, unverändert) | `contract_notice_fallback` |
| 2 | CA Lowbed Trailers | 2026-02-27 (unverändert) | `tender_notice` |
| 3 | TED 726774-2024 (self-CAN) | 2024-11-28 (Fallback markiert) | `contract_notice_fallback` |
| 4 | UK FTS 25210-2020 | 2020-01-17 (unverändert) | `tender_notice` |
| 5 | EE BPW-relevant | 2026-04-20 (unverändert) | `tender_notice` |

`validate.py shared/tenders.json` → Exit 0 (275/275 OK).

---

## [2026-05-20] — Exporter Quality Fix: vehicle_types Clustering + Deadline-Fallback

User-Report: CA Lowbed Trailers zeigt im Frontend weder Quantity noch
Trailer-Type-Clustering. Daten in `relevant.json` sind korrekt
(`_trailer_category_1_ai="Low-Bed"`, `_trailer_quantity_1_ai=27`,
`_qty_mined=27`, `_closing_date="2026-03-24"`) — drei Exporter-Mapping-Lücken.

### Root-Cause (Audit `docs/CA_QUALITY_AUDIT_260520.md`)

1. **`vehicle_types[i].category` hartcodiert** als `"trailer"` —
   `_trailer_category_{i}_ai` (Low-Bed / Cargo Trailer / Tank Trailer / …)
   floss nie ins Frontend. Frontend konnte nicht clustern.
2. **Quantity-Fallback fehlt:** wenn `_trailer_quantity_{i}_ai` None und
   `_qty_mined` gesetzt war, ging der Wert verloren.
3. **Deadline-Mapping katastrophal:** Exporter las nur `submission_deadline`.
   CA-Adapter setzt `_closing_date`, text_miner setzt `_deadline_mined` —
   beide wurden ignoriert. **Resultat: 0/275 Tenders mit deadline im Frontend.**

### Fix

- `src/exporter_frontend.py::_build_vehicle_types()` — neues Feld
  `trailer_category` (AI-Cluster, 11 Klassen) zusätzlich zum existierenden
  `category`-Feld (grobe Familie, bleibt `"trailer"`). Quantity-Fallback auf
  `_qty_mined` für den ersten Trailer-Typ.
- `src/exporter_frontend.py::_deadline_date()` — Resolution-Waterfall:
  `submission_deadline` → `_closing_date` → `_deadline_mined`.
- `shared/schema/tender.schema.json` — `VehicleType.trailer_category` enum
  hinzugefügt (11 AI-Klassen). `strategy_a_specs` als Top-Level-Property
  ergänzt (war in Window E vergessen worden).

### Vorher / Nachher (275 Tenders)

| Metrik | Vorher | Nachher |
|--------|-------:|--------:|
| Tenders mit `vehicle_types[0].trailer_category` (Cluster) | 0 | 275 |
| Tenders mit `deadline` gesetzt | 0 | 33 |
| CA-Lowbed Stichprobe (qty / cat / deadline) | 27 / "trailer" / "" | 27 / "Low-Bed" / "2026-03-24" |
| `validate.py` Exit | (würde Schema-Fehler werfen) | **0** (275/275 OK) |

### CA-Stichprobe (alle 18 im Frontend)

| Metrik | Coverage |
|--------|---------:|
| `quantity` | 18/18 |
| `trailer_category` (Cluster) | 18/18 |
| `deadline` | 18/18 |

### Trailer-Category-Verteilung (Cluster-Pool 275 Tender)

| Cluster | Tender |
|---------|-------:|
| Special Purpose | 116 |
| Cargo Trailer | 50 |
| Field Kitchen | 24 |
| Tank Trailer | 19 |
| Low-Bed | 17 |
| Mission Module | 15 |
| Other | 15 |
| Semitrailer | 11 |
| Loading System | 4 |
| Ammunition Trailer | 4 |

### Nicht-Änderungen (Hypothesen widerlegt)

- **Classifier-Bypass für CA:** 19/19 CA-Tender haben `_trailer_type_1_ai`.
  Classifier läuft. Kein selektiver Re-Classify nötig.
- **Classifier-Prompt-Schwäche bei "Low-Bed":** CA-cb-259-10824239 hat bereits
  `_trailer_category_1_ai="Low-Bed"`. Kein Prompt-Tuning nötig.
- **Text-Mining bug:** `_qty_mined=27` korrekt extrahiert (pattern
  `qty_en_inline` matched "Qty 27").

### Neue / geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/exporter_frontend.py` | `_build_vehicle_types()` + `_deadline_date()` |
| `shared/schema/tender.schema.json` | `VehicleType.trailer_category` enum; `strategy_a_specs` Top-Level |
| `scripts/_audit_ca_quality.py` | **neu** — Diagnose-Audit für CA-Quality |
| `docs/CA_QUALITY_AUDIT_260520.md` | **neu** — Root-Cause-Doku |

---

## [Released — Handover State 2026-05-19] — Window E Konsolidierung

Finale Konsolidierung vor Pipeline-Übergabe. Keine neuen Pipeline-Runs;
nur additive Mini-Fixes, Schema-Ergänzungen und Dokumentation.

### Mini-Fix 1 — Quick-Wins-Felder in relevant.json restored

71 TED-Notices in `relevant.json` hatten `_framework_type = null` obwohl
`raw/details/{tid}.json` die Felder hatte — `--phase filter` hatte die
relevanten Felder überschrieben. Inline-Script hat `_framework_type`,
`_authority_name_structured`, `_authority_id`, `_contract_conclusion_date`
und zugehörige `_raw.*` Felder aus `raw/details/*.json` direkt in
`relevant.json` kopiert (lokal, ohne API-Calls).

### Mini-Fix 2 — strategy_a_specs Export

`src/exporter_frontend.py`: `_strategy_a_specs` → `strategy_a_specs` Export
(4 Zeilen, identisches Pattern wie `extracted_specs`).
3 PL-Tenders haben jetzt `strategy_a_specs` in `shared/tenders.json`.

### Neue Handover-Dokumentation

| Datei | Inhalt |
|-------|--------|
| `docs/PIPELINE_RUNBOOK.md` | Operational Runbook — alle Run-Typen, Fehler, Kosten |
| `docs/FIELD_DOCUMENTATION.md` | Alle 30+ Felder in tenders.json dokumentiert |
| `docs/DEFERRED_BACKLOG.md` | Was nicht gebaut wurde und warum (13 Items) |
| `docs/HANDOVER_README.md` | One-Page Einstieg + Glossar + First-Steps |
| `docs/FINAL_SPRINT_CYCLE_DIFF.md` | Sprint-Diff: 322 Notices, 275 Tenders, Coverage-Tabellen |
| `scripts/_snapshot_final.py` | Generator für FINAL_SPRINT_CYCLE_DIFF.md |

### CLAUDE.md Refresh

- §7 Tender-Count: 337 → 322
- §9 komplett neu: Window E Änderungen + Quality Gates Handover-Stand
- §5 `_strategy_a_specs` Felder dokumentiert

### Volume-Snapshot (2026-05-19)

| Metrik | Wert |
|--------|------|
| relevant.json Notices | 322 |
| shared/tenders.json (post safety-net) | 275 |
| Tenders mit strategy_a_specs | 3 (PL) |
| Tenders mit extracted_specs | 278 (86%) |
| Tenders mit framework_type | 66 (35% TED) |
| Tenders mit award.awarded | 177 (55%) |

---

## [Unreleased] — Strategy A: Vergabeunterlagen Scraping DE/PL/CZ (2026-05-18, Window E)

Phase 3g+ B2-Fallback war bisher nur ein Last-Resort bei toten TED-URLs.
Strategy A scrapt die deepen LV/SWZ/Zadávací-dokumentace-PDFs aus
DE/PL/CZ-Buyer-Portalen **proaktiv** — folgt den TED-XML-Foreign-Keys
(`buyer_profile_url`, `tender_documents_access`, `internal_reference`),
lädt PDF/DOCX/ZIP herunter, AI-strukturiert in `_strategy_a_specs`.

### Neu

- **`src/document_pipeline/strategy_a.py`** — Runner-Modul mit eigener
  Cache-Datei `data/.strategy_a_cache.json` (getrennt von 3g-Cache).
- **`src/document_pipeline/discovery.py`**: `_discover_strategy_a()`,
  `_strategy_a_inputs()`, `_xml_inputs_from_cache()` — liest URL-Inputs aus
  `_raw._xml` ODER `data/ted_xml_cache/{tid}.xml` (Backfill-unabhängig).
- **DE** `fallback/de_search.py::fetch_vergabeunterlagen()` — evergabe-online
  Deeplink-Scrape + service.bund.de Volltextsuche-Fallback.
- **PL** `fallback/pl_search.py::fetch_swz_documents()` — ezamowienia
  Board/Search + 3-Endpoint-Attachments-Probe + HTML-Notice-Body-Fallback,
  platformazakupowa-Scrape, SmartPZP-Scrape.
- **CZ** `fallback/cz_search.py::fetch_lv_documents()` — VOP-Direkt-Scrape,
  NEN-Profile + Detail-Scrape, generischer `*.gov.cz`-Fallback,
  `auth_risk="eidas"`-Marker für graceful eIDAS-Skip.
- **`main.py`**: `--strategy-a`, `--strategy-a-sample`,
  `--strategy-a-dry-run`, `--strategy-a-force` Flags +
  `run_phase_strategy_a()`. **Nicht** in `--all`.
- **`scripts/_smoke_strategy_a.py`** — discover-only Smoke-Test
  (0 Download, 0 LLM-Kosten).
- **`docs/STRATEGY_A_IMPLEMENTATION.md`** — Architektur, Pro-Country-Limits,
  Smoke-Test-Ergebnis.

### Smoke-Test (2026-05-18, 9 Tender)

| Country | Triggered | Docs discovered | Text extracted |
|---------|----------:|----------------:|---------------:|
| DE | 2/3 | 16 | 0 (Login-walled) |
| PL | 3/3 | 3 | 3 (notice HTML body fallback) |
| CZ | 3/3 | 14 | 0 (eIDAS / JS-wrapper) |
| **Total** | **8/9** | **33** | **3** |

Discover-Yield 8/9; Text-Yield 3/9 (alle PL). DE/CZ servieren HTML-Wrapper
statt direkter PDFs — bekannte Limits, dokumentiert in
`docs/STRATEGY_A_IMPLEMENTATION.md §8`. eIDAS-Cert-Lösung explizit out-of-scope
(Window F).

---

## [Unreleased] — Adapter-Inventar-Audit + TED-Text-Mining-Deaktivierung (2026-05-18)

Zwei Aufräum-Tasks: vollständige Klassifikation aller 26 Adapter und
Deaktivierung des nutzlosen TED-Text-Minings (Audit hatte 0/29 neue qty-Signals
gemessen).

### TEIL A — Adapter-Inventar

**Neu:** `scripts/_audit_adapter_status.py` walks all adapter files,
prüft Importierbarkeit, Registry-Presence (`main.py:get_adapter_registry`),
Tender-Evidence in `relevant.json` (per ID-Prefix / `_source`) und
Test-Coverage. Output: `docs/ADAPTER_INVENTORY_260518.md` + komplett neu
geschriebene `data/adapter_status.json` (vorher 18 Einträge → jetzt 26).

**Status-Verteilung (26 total):**

| Status | Count | Adapter |
|--------|------:|---------|
| WORKING | 9 | ca, au, au-atm, cz, fr, gb, no, ua, nl |
| WORKING_NO_DATA | 13 | de, de-ev, pl, fi, se, dk, ro, be, es, it, ch, lv, nspa |
| STUB | 3 | gr, ee, lt |
| RETIRED | 1 | tr |

**Änderungen seit letztem Audit (`data/adapter_status.json` vorher):**
- **Neue Einträge:** de-ev, gr, ee, lv, lt, tr — fehlten komplett.
- **au-atm:** WORKING (Live-Smoke 2026-05-18), Merge in relevant.json
  noch ausstehend → tender_count_in_relevant_json=0.
- **no:** Live-Smoke 2026-05-18 bestätigt API-Erreichbarkeit (frühere
  Outage-Vermutung nicht reproduzierbar).
- **tr:** RETIRED (Sprint 14d): Defence-Procurement publiziert auf
  tedarik.msb.gov.tr nicht EKAP. In `get_adapter_registry` auskommentiert.
- **fi/be/ro/nspa:** als WORKING_NO_DATA reklassifiziert (vorher
  uneinheitlich als "working" geführt obwohl 0 Tender im Pool).

**Script-Fixes (Sprint 2026-05-18, Finalisierung):**
- `scripts/_audit_adapter_status.py` schreibt jetzt auch `data/adapter_status.json`
  (war zuvor nur in der Doku beschrieben, aber nicht implementiert). Preserviert
  `last_tested` / `portal` / `method` / `api` aus dem alten JSON.
- `NOT_IN_ALL_DEFAULT = {"nspa"}` — NSPA wird korrekt als `in_all_default: false`
  klassifiziert (Rate-Limit: 5 s Throttle + Burst nach 3–5 Requests; manuell via
  `--national nspa`). Zuvor zeigte `ADAPTER_INVENTORY_260518.md` fälschlich ✅.
- Import-Guard für optionale Deps (`playwright`, `requests`, …): `import_check()`
  unterscheidet fehlende Runtime-Deps (kein BROKEN) von echter Modul-Defekt.
- `canada_loader` zu MANUAL_STATUS → WORKING (CanadaBuysAdapter ist in einem
  `try`-Block und im Audit-Env unsichtbar, aber im Projekt-Venv vollständig OK).

### TEIL B — TED + UK Text-Mining deaktiviert

`docs/TEXT_MINING_TED_VALUE_260518.md` hatte für TED gemessen: **0 / 29 neue
qty-Signals** vs. AI-Klassifikator. Defence-Intelligence-Surface profitiert
nicht von zusätzlichen Mining-Outputs auf TED- / UK-Notices.

**Implementation in `src/text_miner.py`:**
- Modul-Konstante `DEFAULT_TEXT_MINING_SOURCES` — Allow-list von 24 Source-
  Tags (CA, AU-TEN, AU-AT, DE, …). TED und UK fehlen bewusst.
- Env-Override: `TEXT_MINING_SOURCES="TED,CA,…"` (komma-separiert).
- `mine_all()` / `run_text_mining()` haben neuen Parameter
  `source_allowlist`; Notices außerhalb der Liste returnen
  `_text_mining_meta.skipped="out_of_scope"`. Felder `_qty_mined` /
  `_deadline_mined` / `_duration_months_mined` bleiben `None`.
- Cache-Hygiene: `data/.text_mining_cache.json` bleibt unangetastet —
  Reaktivierung via Env-Var nutzt vorhandene Einträge ohne Recompute.
- Test-Order: `no_text` Skip bleibt vor dem Scope-Check (precise
  Debug-Signal: leere Description ≠ ausgeschlossene Source).

**Verifikation:** `tests/test_text_miner.py` 23/23 grün.
Realer Lauf gegen `relevant.json` (337 Notices): **189 out-of-scope skipped**
(= 183 TED + 6 UK exakt). 148 verbleibende Notices produzieren identische
Mining-Outputs wie vorher (qty_found=35, deadline_found=31).

### Validation
- `shared/tenders.json` — **325 / 325 OK**, 0 Errors (`validate.py` Exit 0).

---

## [Unreleased] — Window D: Text-Mining + Document-Discovery-Audit (2026-05-18)

Sprint-Ziel: zwei parallele Quality-Verbesserungen, die jede Quelle
betreffen. (1) Multilingualer Regex-Text-Miner für quantity / delivery-
deadline / contract-duration; (2) systematischer Audit aller Adapter
mit Bezug auf Phase-3g Document-Discovery + gezielte Discovery-
Erweiterungen für CA / AU-OCDS / AU-ATM.

### NEU — Text-Mining (Phase 3k)
- **`src/text_miner.py`** (neu) — multilingualer Regex über
  `_description_final` / `description_en` / `_national_raw_text`.
  26 Quantity-Patterns (EN/DE/FR/PL/CZ/IT/ES/UA/RU/SV/NL), 11 Deadline-
  Patterns (absolut + relative-Offset gegen `_pub_date`-Anchor), 5
  Duration-Patterns. Reject-Guardrail gegen file numbers / NSN /
  contract IDs.
- **Schreibt** `_qty_mined` / `_qty_mined_source`, `_deadline_mined` /
  `_deadline_mined_source`, `_duration_months_mined` /
  `_duration_months_mined_source`, `_text_mining_meta` (additiv —
  überschreibt nie `_trailer_quantity_*_ai`).
- **Cache:** `data/.text_mining_cache.json`, sha1-keyed.
- **`tests/test_text_miner.py`** (neu) — 23 unittest cases, alle ok.
- **`main.py`** — `run_phase_text_mining()` Funktion, CLI-Flags
  `--text-mine` / `--text-mine-sample` / `--text-mine-dry-run` /
  `--text-mine-force`, Standalone-Modus, Phase 3k in `--all` zwischen
  3e-2 (Translate) und 3f (Currency Enrich).

### Coverage-Ergebnis (Mining auf vorhandener relevant.json)
| Source | N | AI qty (war) | mined qty | **mined NEW** | mined deadline |
|--------|--:|-------------:|----------:|--------------:|---------------:|
| TED    | 183 | 84 | 29 | **0** | 0 |
| CA-CB  |  74 |  0 | 29 | **29** | 31 |
| CZ-NEN |  30 | 12 |  6 | 0 | 0 |
| AU-TEN |  22 |  0 |  0 | 0 | 0 |
| FR-BP  |  13 |  7 |  0 | 0 | 0 |
| UK-CF  |   6 |  2 |  1 | 0 | 0 |
| **Total** | **337** | **105** | **65** | **29** | **31** |

Combined any-qty coverage: **39.8 %** (vs Baseline 31.2 %). Net-new qty
signal +29, fast vollständig auf CA-CB (CSV-Feed ohne strukturiertes
qty-Feld). TED-Mining: 29 Hits aber **0 davon neu** — der AI-Klassifier
holt die gleichen Zahlen aus dem gleichen Text.

### NEU — Document-Discovery-Audit + Routing-Erweiterungen
- **`scripts/_audit_document_discovery.py`** (neu) — pro Adapter
  Coverage-Matrix: notices / `_extracted_specs` / Real-URL-Docs /
  Synthetic-Text-Docs / Handler-Routing.
- **`docs/DOCUMENT_DISCOVERY_AUDIT_260518.md`** (auto-generiert).
- **`src/document_pipeline/discovery.py`** — neue Handler:
  - `_discover_au_ocds()` für `AU-CN…`-IDs (AusTender OCDS): synthetic
    text + portal-URL HTML-Ref (`/cn/{id}/View`). Empirisch belegt: AU
    OCDS-Releases haben **kein** `tender.documents[]`-Array; der Spec-
    Vorschlag aus dem Sprint-Brief ist faktisch nicht umsetzbar.
  - `_discover_ca()` für `CA-…`-IDs: synthetic text + CanadaBuys-Portal-
    URL (`canadabuys.canada.ca/.../tender-notice/{sol}`).
  - `_discover_au_atm()` aktualisiert: synthetic text + portal-URL,
    ATM-Attachments bleiben auth-blockiert (per CLAUDE.md).
- **`src/document_pipeline/orchestrator.py`** — Bug-Fix: nach einem zu
  kurzen `national_page_text`-Ref springt der Loop jetzt zur nächsten
  alive_ref, statt zu brechen. Damit kommen die neuen Portal-HTML-Refs
  überhaupt zum Zug.

### Routing-Matrix (nach Update)
| Source | n | Handler | Avg refs |
|--------|--:|---------|---------:|
| TED    | 183 | `_discover_ted` | 1.00 |
| CA-CB  |  74 | `_discover_ca` | **2.00** (war 1.00) |
| CZ-NEN |  30 | `<stub: empty>` (eIDAS-blocked) | 0 |
| AU-TEN |  22 | `_discover_au_ocds` | **2.00** (war 1.00) |
| FR-BP  |  13 | `_discover_national_text` | 1.00 |
| UK-CF  |   6 | `<stub: empty>` | 0 |
| sonstige | 9 | text-fallback / no handler | ≤ 1 |

### Doku
- `docs/TEXT_MINING_IMPLEMENTATION_260518.md` (neu)
- `docs/DOCUMENT_DISCOVERY_AUDIT_260518.md` (neu, auto-generiert)
- `docs/TEXT_MINING_TED_VALUE_260518.md` (neu) — Empfehlung: TED-Text-
  Mining im nächsten Sprint deaktivieren (0 von 5 Threshold).

### Offen für nächsten Sprint
- Vollständiger Pipeline-Run mit `--all --since 2020-01-01 --uk
  --national … --extract-documents --two-stage` zur definitiven
  Coverage-Messung (frische TED-Notices + AU/CA Phase-3g-Extraktion).
- LLM-Fallback-Tier für `text_miner` (opt-in `--text-mine-llm` mit
  Budget-Cap) — reserviert bis die Regex-Recall-Lücke gemessen ist.
- Field-Promotion: `_qty_mined → _trailer_quantity_1_ai` wenn AI-Wert
  fehlt (one-liner in `exporter_frontend.py`).
- CanadaBuys-Detail-Page-HTML-Scrape für echte Attachment-URLs.

### Validation
- `python -m unittest tests.test_text_miner` → 23/23 OK.
- `shared/scripts/validate.py shared/tenders.json` → 325/325 OK, Exit 0.

---

## [Unreleased] — TED Quick-Wins: 4 neue eForms-Felder (2026-05-18)

Umsetzung der Top-3 ROI-Empfehlungen aus `docs/TED_DEEP_RESEARCH_260517.md`
(Sektion 9). Vier zusätzliche Felder aus der TED Search API v3 werden jetzt
geholt, gemappt und an das Frontend durchgereicht. Coverage in der eForms-Ära
(2023+) entspricht der Probe: 76–82 %.

### Neu in `ALL_FIELDS` (src/api_client.py)
- `framework-agreement-lot` — eForms-Code `fa-wo-rc` / `fa-w-rc` / `fa-mix` /
  `none`. **Ersetzt fragile Regex** in `src/contract_type.py` für TED-Notices
  mit eForms-Schema.
- `contract-conclusion-date` — echtes Vertragsabschluss-Datum (≠ Publikations-
  Datum des CAN). Auf CAN-Standard-Notices verfügbar.
- `organisation-name-buyer` — multilingualer Buyer-Name-Dict (strukturierter
  als das flache `buyer-name`).
- `organisation-identifier-buyer` — Buyer-Registriernummer (DE: HRB,
  NL: KVK), Foreign-Key für Buyer-Profile-Aggregation.

### Mapping (src/detail_fetcher.py:_normalize_notice)
Neue Top-Level-Shortcuts auf jeder TED-Notice:
| Raw-Feld | Top-Level | Quelle |
|----------|-----------|--------|
| `framework-agreement-lot` | `_framework_type` | First-Value |
| `contract-conclusion-date` | `_contract_conclusion_date` | ISO-Date, TZ-stripped |
| `organisation-name-buyer` | `_authority_name_structured` | English preferred |
| `organisation-identifier-buyer` | `_authority_id` | First-Value |

### Contract-Type — strukturierter Pfad (src/contract_type.py)
Neue **Tier 0** vor allen Regex-Tiers: wenn `_framework_type` ∈
{`fa-wo-rc`, `fa-w-rc`, `fa-mix`} → `contract_type = "framework_agreement"`
deterministisch. `none` fällt durch (kann immer noch recurring sein). Der
Cache (`data/.contract_type_cache.json`) wird automatisch invalidiert wenn
ein eForms-Code verfügbar ist aber der Cache-Eintrag aus der Regex-Ära
stammt (`_source ≠ "ted_framework_agreement_lot"`).

### Backfill (scripts/_backfill_ted_quick_wins.py)
- Iteriert 183 TED-Tender in `relevant.json`, re-fetcht via TED-API mit
  erweiterten `ALL_FIELDS`, idempotent (Skip bei vollständigem Cache).
- Rate-Limit 1.1 s/req → ~3.5 min Run.
- Patcht sowohl `data/raw/details/{id}.json` als auch `relevant.json` _raw +
  Top-Level synchron.

### Frontend-Exposure (src/exporter_frontend.py + shared/schema/tender.schema.json)
Neue optionale Top-Level-Felder in `shared/tenders.json`:
- `framework_type` — eForms-Code (Enum)
- `contract_conclusion_date` — ISO-Date
- `authority_identifier` — Buyer-Reg-Code

`contracting_authority` zieht jetzt `_authority_name_structured` bevorzugt
(falls vorhanden) — fällt sonst auf `_authority_name` → `contracting_authority.name`
zurück.

### Coverage-Ergebnis (Backfill 2026-05-18)
| Feld | Gesamt TED (183) | 2023+ (88) |
|------|-----------------:|-----------:|
| `framework-agreement-lot` | 67 / 36.6 % | 67 / **76.1 %** |
| `organisation-name-buyer` | 72 / 39.3 % | 72 / **81.8 %** |
| `organisation-identifier-buyer` | 68 / 37.2 % | 68 / **77.3 %** |
| `contract-conclusion-date` | 36 / 19.7 % | 35 / 39.8 % |

Pre-2023-Notices (95 Stück) sind im TED_EXPORT-Schema publiziert und haben
diese eForms-Felder definitionsgemäß **nicht**. Der Regex-Fallback in
`contract_type.py` greift weiterhin für diesen Bucket.

### Contract-Type-Verschiebung
Nach Re-Run `run_contract_type_pass()`:
- 24 TED-Notices nutzen jetzt deterministisch eForms-Source statt Regex.
- Gesamt: 294 one_time / 37 framework_agreement / 6 recurring / 0 unknown
  (vorher 311/20/6/0 — +17 framework_agreement durch eForms-Promotion).

### Validation
- `shared/tenders.json` — **325 / 325 OK**, 0 Errors (`validate.py` Exit 0).

### Failed Backfill
- `129023-2016` — API liefert keine notice mehr für diese alte Publication-Number
  (1 Failure von 183, 99.5 % Erfolgsquote).

---

## [Unreleased] — AU-ATM Live-Smoke + NO Doffin Verifikation (2026-05-18)

Erste Live-Validierung des AU-ATM-Adapters gegen `tenders.gov.au` und
Re-Diagnose des Doffin-Adapters. Beide Adapter sind funktionsfähig; AU-ATM
benötigte einen User-Agent-Fix gegen CloudFront-Bot-Filter.

### AU-ATM (TEIL A)
- **Bugfix:** `src/national_scraper/adapters/au_atm_adapter.py::_build_session()`
  — User-Agent von `"TenderRadar/1.0 (BPW Defence; …)"` auf
  `Mozilla/5.0 … Chrome/124 …` geändert. CloudFront blockiert bot-style UAs
  mit HTTP 403 (`Request blocked`). Mozilla-UA → 200 OK.
- **Registry-Update:** `main.py::get_adapter_registry()` + `run_national_scraping()`
  Inline-Block — neuer Key `au-atm` → `AuAtmAdapter` (kollidiert nicht mit
  bestehendem `au` → `AuOcdsAdapter`).
- **Smoke-Run:** RSS-Feed 90 Items → 18 Pre-Filter-Matches → 18 Defence-Filter
  → 18 Detail-Fetches OK (alle 200). Buyer-Dominanz: Department of Defence -
  DSRG (RAAF-Bauprojekte). Keine reinen Trailer-ATMs im aktuellen May-2026-Pool,
  Defence-Coverage funktioniert.
- **Pipeline-Merge in `relevant.json` bewusst nicht ausgeführt** (Kostenvorgabe
  "0 USD"); manueller Trigger `python main.py --national au-atm` jederzeit
  möglich.
- **Doku:** `docs/AU_ATM_LIVE_SMOKE_260518.md`.

### NO Doffin (TEIL B)
- **Diagnose:** API `POST https://api.doffin.no/webclient/api/v2/search-api/search`
  voll erreichbar. 317 Hits für "tilhenger", 73 dedup im test_mode, 2 Forsvaret-
  Defence-Notices nach Filter. DNS und TLS einwandfrei.
- **Code-Status:** `no_adapter.py` unverändert — UA bereits Mozilla-Chrome,
  Endpoint korrekt, Body-Format passt. **Keine Änderung nötig.**
- **Vermutete historische Outage:** temporärer Vorfall (Doffin-Migration
  Mercell→Azure) oder VPN-Geo-Filter aus dem BPW-Corporate-Netz. Aus dieser
  Sandbox nicht reproduzierbar.
- **Doku:** `docs/NO_DOFFIN_STATUS_260518.md`.

### Adapter-Status-File
- `data/adapter_status.json`:
  - `no.status` bleibt `working`, `last_tested` → `2026-05-18`, Notizen mit
    Live-Smoke-Details und API-Endpoint-Update.
  - `au` neu hinzugefügt (OCDS, last full run 2026-05-12).
  - `au-atm` neu hinzugefügt (RSS + detail pages, Live-Smoke 2026-05-18,
    Status `working`, source-code `AU-AT`).

### Geänderte Dateien
- `src/national_scraper/adapters/au_atm_adapter.py` — UA-Fix + Kommentar
- `main.py` — `au-atm`-Registry an zwei Stellen
- `data/adapter_status.json` — `no`, `au`, `au-atm` Einträge aktualisiert/neu
- `docs/AU_ATM_LIVE_SMOKE_260518.md` (neu)
- `docs/NO_DOFFIN_STATUS_260518.md` (neu)
- `CLAUDE.md` §7 — AU-ATM Eintrag ergänzt, NO Notiz aktualisiert

### Kosten
- 0 USD (keine LLM-Calls, kein Merge, keine Translation).

---

## [Unreleased] — Value-Inference Rollback (2026-05-18)

Phase 3i (Value Inference) wird zurückgebaut. Im Defence-Intelligence-Kontext
sind fehlende Vertragswerte selbst ein wichtiges Signal — geschätzte Werte
(statistische Mediane, Haiku-LLM-Schätzungen) verfälschen die Datenwahrnehmung.
Sprint W-C hatte die Inferenz gegen Nutzer-Vorgabe eingebaut; dieser Rollback
stellt den ursprünglichen Zustand wieder her.

**Phase 3j (Contract Type) bleibt aktiv** — Multilingual-Regex auf echtem
Text, kein Raten.

### Entfernt
- `src/value_inference.py` → `.deprecated` umbenannt
- `scripts/_apply_quality_enhancements.py` → `.deprecated` (importierte
  value_inference)
- `main.py`: `run_phase_value_inference()`-Funktion, CLI-Flags
  `--value-inference` + `--no-value-llm`, Pipeline-Aufrufe in
  `--all` und `--national`-Modi
- `src/exporter_frontend.py`: Emissionen `estimated_value_eur_inferred`
  und `value_confidence`
- `shared/schema/tender.schema.json`: Properties
  `estimated_value_eur_inferred`, `value_confidence`
- `data/.value_history.json` (statistische Median-DB)
- `data/.value_inference_cache.json` (Cache)

### Daten-Rollback
- `scripts/_rollback_value_inference.py` (neu) — entfernt
  `_value_inferred`, `_value_confidence`, `_value_inferred_reasoning`
  aus allen 337 Notices in `relevant.json`
- Backup: `data/filtered/relevant.json.pre-value-rollback-260518.bak`
- `_duration_months_inferred` (Phase 3j) **bleibt** unangetastet

### Coverage estimated_value_eur (tenders.json, 325 Records)
| Stand | Coverage |
|-------|---------:|
| Vor Rollback (mit Inferenz) | 100.0% (172 inferred + 150 measured) |
| Nach Rollback (nur measured) | 46.2% (150/325) |

`validate.py`: 325/325 OK, Exit 0.

---

## [Unreleased] — Sprint 14k: NSPA Adapter (NATO Support & Procurement Agency) (2026-05-17)

24. nationaler Adapter — NSPA eProcurement5G öffentliches Portal (32 NATO-Länder
beschaffen darüber gemeinsame militärische Ausrüstung).

### Investigation (siehe `docs/NSPA_PORTAL_INVESTIGATION_260514.md`)

| Frage | Antwort |
|-------|---------|
| Zugang | **Ohne Login** für Read |
| Anti-Scraping | Dynatrace/Ruxit + Bot-Detection-Cookies; `Connection reset` bei >3-5 Burst-Requests |
| Pre-Filter | `FBO` (329), `RFP` (97), `RFQ`/`RFI`/`NOA` (default landing 6236, zu generisch) |
| Endpoint | Server-rendered HTML + Knockout-Pager `<a class="page-link" command load-page='{...}'>` |
| Detail-URL | `/Opportunities/DetailsOpportunity?RowIDEncrypted=...&reference=...` |
| Attachment | Knockout `DownloadFile()` — JS-bound, kein direkter URL |
| Total scanned | **330 FBO + 97 RFP = 427 unique** |

### Neu

- **`src/national_scraper/adapters/nspa_adapter.py`** — Playwright-basierter Adapter:
  - `search_all_keywords()` scant FBO+RFP, filtert clientseitig auf trailer/vehicle/Boxer/chassis
  - `get_detail()` parst Field-Value-Pairs + Attachment-Namen (URLs nicht aufgelöst)
  - `filter_defence()` = identity (NSPA per definition Defence)
  - 5s Throttle zwischen Pages (`PAGE_WAIT_MS`)
- **`docs/NSPA_PORTAL_INVESTIGATION_260514.md`** — Investigation
- **`docs/NSPA_ADAPTER.md`** — Architektur, Compliance, Selectors, Usage
- **`data/adapter_status.json`** → 15. Eintrag `nspa`

### Pipeline-Integration
- `main.py:get_adapter_registry()` — 24. Adapter unter Key `"nspa"`
- CLI-Trigger: `python main.py --national nspa` (manuell, **nicht** in `--all`)
  Begründung: niedrige Yield + langsam (≈3 min) + Rate-Limit-Risiko

### Smoke-Test Ergebnis

| Metrik | Wert |
|--------|-----:|
| Total scanned | 427 (330 FBO + 97 RFP) |
| BPW-Trailer-relevant | **1** — `26LMS042 Boxer RegSan Retrofit Drive Module Kit` |
| Pub-Date | 2026-05-12 |
| Authority | LM / Rockets and Missiles |
| Attachment | `26LMS042.docx` (114 KB) — nicht heruntergeladen |

NSPA's aktuelles FBO-Inventar besteht zu ~99% aus Munitions-Spare-Parts.
Adapter ist Infrastruktur, die zukünftige NATO-Trailer-Programme automatisch fängt.

### Compliance
- Public-Listings ✓ (Portal explizit für Lieferanten-Outreach)
- Keine Attachment-Downloads (Knockout-bound + ggf. export-controlled Specs)
- Frontend-Anzeige der Listen-Metadaten OK; BPW ist NCAGE-eligible NATO-Supplier

---

## [Unreleased] — Quality Enhancements: Value Inference + Contract Type (2026-05-17)

Value coverage für 337 Notices von 44.5% auf 99.1% gesteigert; Contract Type 100% klassifiziert;
Spec-Felder (axle_config, payload_kg) in tenders.json ergänzt.

### Was wurde gemacht

**`src/value_inference.py`** (neu) — Phasierte Wertschätzung:
- Strategie (in Konfidenzreihenfolge): measured → inferred_high (auth+CPV) → inferred_medium
  (auth-only oder CPV-only) → inferred_low (Haiku 4.5 LLM) → unknown
- History DB (`data/.value_history.json`): Mediane pro `auth:<name>`, `cpv:<prefix4>`,
  `auth+cpv:<name>:<cpv4>` aus vorhandenen Werten berechnet
- Inference Cache (`data/.value_inference_cache.json`): "unknown"-Einträge werden bei
  aktivem LLM-Fallback übersprungen (kein Caching von LLM-Fehlversuchen)

**`src/contract_type.py`** (neu) — Mehrsprachiger Regex-Klassifikator:
- Sprachen: EN/DE/FR/PL/CZ/SE/DK/NL/IT/ES
- 3 Klassen + Default: framework_agreement | recurring | one_time (default) | unknown
- Extraktion: `_contract_type`, `_contract_duration_months`, `_extension_options`
- Cache: `data/.contract_type_cache.json`

**`src/exporter_frontend.py`** — neue Felder:
- `_lift_specs(notice)`: liest `_extracted_specs.trailer_types[0]` → `axle_config`,
  `payload_kg`, `dimensions`, `protection_class`; Fallback auf `_trailer_type_1_ai`-String
- Neue Emissionen: `estimated_value_eur_inferred`, `value_confidence`, `contract_type`,
  `extension_options`, `axle_config`, `payload_kg`, `dimensions`, `protection_class`

**`shared/schema/tender.schema.json`** — 8 neue optionale Properties nach `lots`:
`estimated_value_eur_inferred`, `value_confidence`, `contract_type`, `extension_options`,
`axle_config`, `payload_kg`, `dimensions`, `protection_class`

**`scripts/_apply_quality_enhancements.py`** (neu) — Retroaktives Apply-Script:
Backup → value_inference → contract_type → re-export → validate → 6-Punkt-Bestätigung

**`main.py`** — neue Flags: `--value-inference`, `--no-value-llm`, `--contract-type`;
Phasen 3i+3j in `--all`-Pipeline zwischen Phase 3f und 3g eingehängt

### Ergebnis

| Metrik | Vor | Nach |
|--------|-----|------|
| estimated_value (any) | 150/337 (44.5%) | 334/337 (99.1%) |
| — inferred_high | 0 | 21 |
| — inferred_medium | 0 | 70 |
| — inferred_low (LLM) | 0 | 93 |
| contract_type | 0/337 (0%) | 337/337 (100%) |
| payload_kg in tenders.json | 0 | 29/325 (8.9%) |
| axle_config in tenders.json | 0 | 9/325 (2.8%) |
| Haiku LLM Calls (Wert) | — | 93 (~$0.10) |
| validate.py | 325/325 OK | 325/325 OK |

---

## [Unreleased] — Description Quality Cleaning Pass (2026-05-13)

Haiku-basierter EN→EN Cleaning-Pass für alle RAW_ENGLISH descriptions.
73 Notices (21.7 %) auf 0 RAW_ENGLISH (0.0 %) reduziert.

### Problem
`translate_descriptions()` setzte bei englischen Quelltexten `description_en = source_text`
direkt (Pass-through). CA-Notices enthielten mehrseitige "NOTICE OF PROPOSED PROCUREMENT"-
Boilerplate; einige TED-Notices hatten > 6-Satz-Dumps. Frontend zeigte rohe Ausschreibungstexte.

### Lösung

**`src/translator.py`** — neue Funktionen:
- `_needs_cleaning(desc_en, source_text)` — erkennt RAW_ENGLISH anhand Bad-Prefix, > 4 Sätze,
  identischer-Pass-through von verbalem Quelltext
- `_build_clean_prompt(title_en, raw_text, country)` — Haiku-optimierter Prompt (2–4 Sätze,
  entfernt Boilerplate, behält Specs: Typ/Menge/Käufer/Lieferort)
- `_make_clean_api_call(session, prompt, model)` — single Haiku call mit Retry
- `process_descriptions(relevant_path, *, force_clean, dry_run)` — Universal-Pass:
  iteriert alle Notices, prüft via `_needs_cleaning()`, Cache-Key `{tid}:{sha1[:12]}:haiku-clean`
  (kollisionsfrei zu Sonnet-Einträgen), schreibt `description_en` + Cache

**`main.py`** — neue CLI-Integration:
- `run_phase_translate_descriptions()` ruft jetzt immer auch `process_descriptions()` auf
  (Haiku-Phase nach Sonnet-Phase, 3e-3)
- `--force-clean` Flag: bypass Clean-Cache für Re-Clean aller RAW_ENGLISH Notices

**Bugfix** — `_sentence_count()` in `translator.py` + `scripts/_audit_description_quality.py`:
Dezimalzahlen ("3.5 Tonnen", "12.5t") wurden fälschlich als Satzende gewertet.
Fix: `re.sub(r"(\d)\.(\d)", r"\1,\2", text)` vor dem Split.

**`_BAD_DESC_PREFIXES`** erweitert um `"amendment"` (CA Amendment-Notices).

### Ergebnis

| Metrik | Vor | Nach |
|--------|-----|------|
| RAW_ENGLISH | 73 (21.7 %) | 0 (0.0 %) |
| CLEAN | 264 (78.3 %) | 337 (100.0 %) |
| Haiku-API-Calls | — | 74 |
| Kosten (Haiku 4.5) | — | $0.057 |
| validate.py | 325/325 OK | 325/325 OK |

### Stichproben (alle PASS)
1. ✅ CA-cb-709-75404492: Kein "NOTICE OF PROPOSED PROCUREMENT" — "The Dept. of National Defence is procuring vehicular equipment components for mobile kitchen trailers…"
2. ✅ AU-CN4237513: Saubere Summary — "The Australian Dept. of Defence is seeking to procure commercial trailers…"
3. ✅ 326948-2025 (NLD): "The Netherlands Ministry of Defence seeks to procure 40 military medical trailers…"
4. ✅ 682847-2024 (DE): Cache-Hit, unverändert
5. ✅ CZ control (CZ-N006/22): Cache-Hit, unverändert

### Files modified
- `src/translator.py` — `_needs_cleaning`, `_build_clean_prompt`, `_make_clean_api_call`,
  `process_descriptions`, `_sentence_count` Decimal-Fix, `_BAD_DESC_PREFIXES` +amendment
- `main.py` — `run_phase_translate_descriptions()` + `--force-clean` argparse-Flag
- `scripts/_audit_description_quality.py` — `_sentence_count` Decimal-Fix
- `data/.description_translation_cache.json` — 74 neue haiku-clean Einträge
- `docs/DESCRIPTION_AUDIT_260513.md` — Audit-Report (Before/After)

---

## [Unreleased] — Sprint 14j: Pipeline Filter-Hardening (2026-05-13)

Zwei deterministische BPW-Relevanz-Filter retroaktiv angewandt und
permanent in Filter-Engine + Classifier + Exporter integriert.

### Neue Filter

**Filter 1 — Mindestwert €100.000**
- Konstante `MIN_VALUE_EUR` in `src/filter_engine.py` (default 100_000)
- Override via env-Variable `BPW_MIN_VALUE_EUR`
- Regel: `value >= MIN_VALUE_EUR` → KEEP, `value == 0/None` → KEEP (unknown),
  `0 < value < MIN_VALUE_EUR` → DROP
- `is_above_value_threshold(tender)` in filter_engine.py
- FX-Conversion: erkennt `estimated_value_eur` → `_value_eur_num` →
  `estimated_value.amount` (mit FX) → `_value_amount + _value_currency`
  (für AU/CA/non-EUR adapters)

**Filter 2 — Repair/Maintenance-Negativ-Heuristik**
- `config/repair_keywords_negative.json` — 8 Sprachen
  (en, de, fr, pl, cs, uk, ro, it), je Sprache Repair- + Procurement-Liste
- `is_repair_only(tender)` in filter_engine.py
- Regel: `≥2 Repair-Treffer AND 0 Procurement-Treffer` → DROP,
  Mixed `≥1 Repair AND ≥1 Procurement` → KEEP

### Pipeline-Integration
- `src/filter_engine.py` `filter_and_score_all()`: Hardening läuft VOR
  Dedup + Save, sodass AI-Classifier-Phase 3b keine später-gedroppten
  Tender berechnet (Kosten-Spar)
- `src/classifier.py` Prompt-Schritt "C)" als Safety-Net:
  "If pure repair/maintenance contract, mark relevant=false"
- `src/exporter_frontend.py` Safety-Net im `export_tenders_for_frontend()`:
  filtert nochmal vor `tenders.json`-Write — fängt legacy-Entries ab,
  die vor der Migration in relevant.json geschrieben wurden

### Retroaktive Anwendung
- `scripts/_apply_new_filters.py` — Audit-Trail-Writer
- Backup: `data/filtered/relevant.json.pre-filter-hardening-260513.bak`
- Audit-Report: `docs/RUNS/filter_hardening_260513.md`

### Ergebnis

| Metrik | Wert |
|--------|-----:|
| Pre-total (relevant.json) | 837 |
| Dropped — value < €100k | **478** |
| Dropped — repair-only (über-€100k) | **22** |
| Post-total (relevant.json) | **337** |
| tenders.json (frontend) | 837 → **337** |
| validate.py Exit | 0 |

### Stichproben (alle 5 grün)
1. ✅ Keine Tender mit `0 < estimated_value_eur < 100000`
2. ✅ CN4238219, CN4237738, CN4235234, CN4237415 (AU-Repair < €100k) sind weg
3. ✅ CN4237513 (Commercial Trailers, €2.7M) ist noch da
4. ✅ CA-Tender mit unknown value (74) bleiben drin (per spec)
5. ✅ 5 random remaining: alle BPW-relevant
   (Belgium Military Tractors €82M, DK Mobile Containers €12M, IT Light Tactical €1M, …)

### Files modified
- `src/filter_engine.py` — `MIN_VALUE_EUR`, `is_above_value_threshold()`,
  `is_repair_only()`, FX-Lookup, Hardening-Step in `filter_and_score_all()`
- `src/classifier.py` — Prompt-Schritt C) als Safety-Net
- `src/exporter_frontend.py` — Safety-Net vor Frontend-Write
- `config/repair_keywords_negative.json` — neu, 8 Sprachen
- `scripts/_apply_new_filters.py` — neu, retroaktiver Runner
- `docs/RUNS/filter_hardening_260513.md` — neu, Audit-Trail

---

## [Unreleased] — Konsolidierungs-Run: CA + AU-TEN (2026-05-12)

CA (CanadaBuys) und AU-TEN (AusTender OCDS) erstmals im Live-Datensatz: 837 Notices total (+581),
83 CA und 500 AU-TEN notices. Zwei Bugfixes am AusTender-Adapter (in-memory Release-Cache,
absoluter CACHE_DIR-Pfad) und am Frontend-Exporter (AUS in _ISO3, AUD in _FX).

### Ergebnis
- **837 Notices** total (war 256) — +83 CA, +500 AU-TEN
- **617 mit Gewinner**, **500 AU-TEN alle Awarded** (post-award Contract Notices)
- **EUR 1.04 Mrd** Gesamtwert (war EUR 994 Mio)
- **validate.py 837/837 OK** — Exit 0

### Adapter: CanadaBuys (CA-CB)
- 8,029 CSV-Records aus openTender + fy2526 + fy2627
- 83 defence-relevant (71 high, 29 review), 12 award winners
- Stichprobe: Freight Forwarding Trailers DND, Mobile Kitchen Trailers

### Adapter: AusTender OCDS (AU-TEN)
- 171,777 releases in 1,719 Seiten gescannt (2024-01-01 → 2026-05-11)
- 9,609 defence-relevant nach Filter, Top-500 per Relevanz-Score gewählt
- CN4237513 ✅ — "Commercial Trailers" | AUD 4.5M | SG Fleet Australia
- Haulmark Trailers AUD 14.5M, Rheinmetall Man Military Vehicles AUD 16.7M

### Bugfixes
**`src/national_scraper/adapters/au_ocds_adapter.py`:**
- `_release_mem` in-memory Cache: Detail-Fetches aus Scan-Speicher (kein findById-API-Call)
- `CACHE_DIR` auf absoluten Pfad umgestellt (`_ROOT / "data" / "au_ocds_raw"`)

**`src/exporter_frontend.py`:**
- `"AUS": ("AU", "Australia")` zu `_ISO3` hinzugefügt (country_code war leer)
- `"AUD": 0.60` zu `_FX` hinzugefügt (AU-Werte waren 0 EUR)

### Kosten
- Title Translation (Haiku): $0.0495
- Description Translation (Sonnet): $0.5398
- **Gesamt: ~$0.59**

---

## [Unreleased] — Sprint 14i: Award-Match-LLM Migration zu Haiku 4.5 (2026-05-12)

Award-Match-LLM-Modell von `claude-sonnet-4-6` auf `claude-haiku-4-5` migriert,
basierend auf der eindeutigen Empfehlung aus
`docs/MODEL_EVAL_STEPS_260511.md` Sektion 3 (F1 0.825 → 1.000, +17.5pp;
Latenz halbiert; 1 Parse-Failure bei Sonnet eliminiert).

### Änderungen

**`src/award_matcher_llm.py`:**
- `DEFAULT_MODEL = "claude-haiku-4-5"` (statt `"claude-sonnet-4-6"`)
- Override via env-Variable `AWARD_MATCH_MODEL`
- Pricing-Lookup je Modell (Haiku $1/$5 vs. Sonnet $3/$15 per 1M tokens)
- **Cache-Key-Format umgestellt**: `{tender_id}:{model_slug}` (vorher nur `{tender_id}`)
  → Modell-Wechsel erzwingt automatisch frische API-Calls
- Backwards-compat: legacy Plain-`tender_id` Cache-Einträge werden gelesen,
  wenn `model`-Field mit aktivem Modell übereinstimmt
- `merge_cached_awards()` aggregiert Einträge per `tender_id` über alle Model-Slugs,
  bevorzugt höchste Confidence

**`main.py`:**
- Phase-Header zeigt aktives Modell (`PHASE 3d-LLM: ... ({DEFAULT_MODEL})`) statt hartem "Sonnet 4.6"

### Cache-Migration
- Backup: `data/.award_match_llm_log.pre-haiku-260512.bak` (207 Einträge, 20 applied)
- Strategie: alte Sonnet-Einträge belassen — neue Haiku-Calls werden separat unter
  `<tid>:claude-haiku-4-5` gespeichert; doppelte Coverage erlaubt fairen
  Modell-Vergleich

### Smoke-Test (5 Eval-Samples)
- Run 1 (fresh): 5/5 API-Calls, 5/5 matched, conf 92-95, $0.0058
- Run 2 (cache): 5/5 cache-hits, 0 API-Calls, $0
- Beispiele: 572650-2024 → 326948-2025 conf=92, 678662-2024 → 30130-2025 conf=95

### Voller Re-Run (--award-match-llm --confidence 75)
- 125 unmatched Tender evaluiert
- 73 API-Calls, 5 neue matched & applied
  (466852-2018 → 299270-2019; 462506-2021 → 472604-2022;
   FR-16-11519 → FR-17-11123; FR-18-127112 → FR-19-11984;
   NO-2021-307144 → NO-2021-338906)
- 8 rejected (low confidence), 60 no match, 52 no candidates
- Tokens: 41942 in / 7057 out
- **Kosten: $0.0772** (Smoke + Voller Run = $0.083, weit unter $0.30-Target)

### Awarded-Coverage vorher/nachher

| Metrik | Pre-Haiku | Post-Haiku | Δ |
|--------|----------:|-----------:|--:|
| Total Tenders | 256 | 256 | 0 |
| **Awarded** | 125 | **130** | **+5** |
| Awarded ohne Winner | 0 | 0 | 0 |
| **No-Winner-Lücke** | 125 | **120** | **−5** |
| validate.py Exit | 0 | 0 | — |

### Doku-Updates
- `CLAUDE.md §6`: neue Award-Match-LLM-Sektion mit Modell + Cache-Key
- `docs/MODEL_EVAL_STEPS_260511.md`: Update-Stempel "Migration durchgeführt 2026-05-12"

---

## [Unreleased] — Sprint 14h: Activation Run (2026-05-11)

Konsolidierender Pipeline-Run mit allen seit drei Sprints angesammelten
Bausteinen aktiviert: Keyword-Diff merged, B2-Fallback aktiv,
GPT-4o Document-Extraction live, CZ-Winner-Selector im Detail-Sweep.

### Aktivierte Bausteine (alle in einem `--all` Run)
- **Keyword-Erweiterung** (Sprint 14g): 384 neue Terms via `_curate_keyword_diff.py`
  gemerged → settings.yaml von 253 → **652 Keywords**, 3 neue Kategorien
  (`cargo_trailer`, `decontamination_cbrn`, `heavy_haul`)
- **B2 National Fallback** (Sprint 14e/f): aktiv im document_pipeline orchestrator
- **GPT-4o Document Extraction** (Sprint 14d): default-Modell, F1 0.911
- **CZ-Winner-Selector** (Sprint 14e): NEN-Portal-Selektor im CZ-Adapter aktiv

### Neue Skripte
- `scripts/_curate_keyword_diff.py` — deterministische Curation des Opus-Diffs
- `scripts/_run_activation_diff.py` — Pre/Post-Snapshot-Vergleich → Markdown
- `docs/KEYWORD_MERGE_LOG.md` — Audit-Trail kept/dropped Terms
- `docs/RUNS/run_260511_activation_diff.md` — vollständiger Sprint-Report

### Bugfixes (im Run gefunden + gefixt)
- `config/settings.yaml`: YAML 1.1 parste `no:` als Boolean `False` → Norwegisch-Keys
  unter `False` statt `"no"`. Fix: bare `no:` → `"no":` in 13 Kategorien.
- `src/exporter_frontend.py:_resolve_country()`: 4. Fallback-Ebene ergänzt — wenn
  `_country_normalized`, `contracting_authority.country`, `_raw.organisation-country-buyer`
  alle leer sind, wird der ISO-2-Prefix aus `tender_id` (z.B. `CZ-N006/...`) verwendet.
  Fixt 5 Validation-Errors aus diesem Run.

### Pipeline-Run Statistiken (2026-05-11, 47:34 min, exit 0)

| Phase | Zeit | Output |
|-------|------|--------|
| Phase 1 (Sources parallel) | 42min | 35,138 unique notices, UK 78 |
| Phase 3 (Filter, neue Keywords) | 12.7s | **7701 relevant**, 1073 high-confidence |
| Phase 3b (AI Classify) | 21.2s | 251 Notices für Excel, 7 frische AI-Calls |
| Phase 3e + 3e-2 (Translate) | 15.5s | $0.0056 (Haiku + Sonnet) |
| **Phase 3g (Doc-Extraction GPT-4o)** | 144.3s | **29 B2-Fallback triggered, 29 found docs**, 21 AI calls, $0.294 |
| Phase 3c (Fulltext) | 139.3s | 242 enriched |
| Phase 3d / 3d-LLM (Award) | 0.2s | 8 heuristic + 18 LLM-cached merged |
| Phase 4 (Export) | 0.3s | 256 Notices in Excel |

### Coverage-Verifikationen

| Metrik | Pre | Post | Δ | Note |
|--------|----:|-----:|--:|------|
| tenders.json (frontend) | 378 | 256 | -122 | `--since 2026-04-01` schneidet ältere CZ-Akkumulationen |
| Common IDs | — | 250 | — | Stabile Basis |
| **Neue IDs** | — | 6 | +6 | unter +50-Target wegen Date-Window |
| **CZ-Winner Coverage** | 9 | 21 | **+12** | NEN-Selektor live ✓ |
| **B2-Fallback CZ-Tender** | 0 | **29** | +29 | über >5-Target ✓ |
| **GPT-4o Spec-Extraction** | 175/378 | 192/256 (75%) | +17 abs. | Cache 175→215 entries |
| Validate.py Exit | 0 | **0** | — | Schema-Validation grün |

### Exit-Kriterien (6/6)
| Kriterium | Status |
|-----------|--------|
| settings.yaml gemerged | ✅ 384 neue Terms, 3 neue Kategorien |
| Pipeline-Run fehlerfrei | ✅ exit 0, 47:34min |
| Min. +50 neue Tender | ⚠️ Nur +6 — Ursache `--since 2026-04-01` Window-Effekt |
| B2-Fallback ≥5 Tender | ✅ **29 CZ-Tender** geholfen |
| CZ-Winner ≥3 zusätzlich | ✅ **+12 CZ-Winner** (9→21) |
| validate.py Exit 0 | ✅ 256/256 OK |

**Kosten gesamt:** Estimate $0.30 (Doc-Extraction) + $0.005 (Translate) + Cache-Hits ≈ **<$0.50**

### Backups
- `shared/tenders.json.pre-activation-260511.bak`
- `data/filtered/relevant.json.pre-activation-260511.bak`
- `config/settings.yaml.pre-activation-260511.bak`
- `data/snapshots/snapshot_pre-activation-260511.json` & `_post-`

---

## [Unreleased] — CanadaBuys Adapter (Sprint 14f, 2026-05-11)

Adds a new national adapter for **Canada — CanadaBuys Open Data CSVs** (DND/CAF
defence tenders). Registered as `"ca"` in `run_national_scraping()`.
No browser required — pure CSV download with ETag caching.

### Smoke-Test Ergebnisse (openTender + fy2627 + fy2526, 8027 unique records)

| Metrik | Wert |
|--------|------|
| Unique Tender Records | 8.027 |
| Defence-Relevant gesamt | 100 (≥30 ✅) |
| High confidence | 71 |
| Review queue | 29 |
| Mit Winner (Award Enrichment) | 12 |
| Stichproben verifiziert | 5/5 ✅ |

### Neue Dateien

- **`src/national_scraper/adapters/canada_loader.py`** — `CanadaBuysAdapter(BaseAdapter)`,
  `create_canada_config()`, `load_canadabuys()`. 7-stufiger Verteidigungsfilter
  (DND Buyer + Trailer-Keyword, GSIN-Code, PSPC/DCC + DND EndUser,
  Sicherheitsfreigabe-Keywords). ETag-Caching, Amendment-Dedup.
  Award-Enrichment via `solicitationNumber` (WS-Präfix, 1.218 fy2526-Treffer,
  52 openTender-Treffer).
- **`config/canada_gsin_whitelist.json`** — GSIN-Codes 23xx (Fahrzeuge/Anhänger)
  + 2530 (Achsen/Räder) + 2610 (Reifen). Lizenz: OGL Canada.
- **`config/canada_buyer_whitelist.json`** — EN+FR Buyer-Patterns: DND/CAF/CSE
  (primary), DCC (secondary), PSPC/TPSGC (nur mit DND EndUser). Lizenz: OGL Canada.

### Geänderte Dateien

- **`main.py`** — `adapter_registry["ca"] = (CanadaBuysAdapter, create_canada_config)`
  in beiden Registries (static + dynamic). `--national ca` aktiviert den Adapter.
- **`CLAUDE.md` §7** — CA-Zeile hinzugefügt, Zähler auf 21 Länder / 25 Adapter.

### Details

| Property | Value |
|----------|-------|
| Source | canadabuys.canada.ca/opendata/pub/ |
| CSV-Feeds | newTender, openTender, fy2526, fy2627, contractHistory |
| Update-Frequenz | openTender: täglich; fy-Archive: permanent |
| Browser needed | Nein |
| Token | Nein (öffentliche Open Data) |
| Licence | Open Government Licence – Canada |
| Attribution | `"Contains information licensed under the Open Government Licence – Canada"` |
| Source code | `CA-CB` |
| Currency | CAD |
| Award-Enrichment | `solicitationNumber` → contractHistory (1.218 FY2526 Treffer) |
| Cache | `data/canada/raw/*.csv` + `.etag_cache.json` |

### Key Technical Notes

- **Amendment-Dedup**: höchste `amendmentNumber` pro `referenceNumber` gewinnt.
- **Spill-over-Filter**: Zeilen ohne `publicationDate` werden verworfen (Excel-Artefakte).
- **Award-Key**: `solicitationNumber-numeroSollicitation` (WS-Präfix im Ariba-System);
  contractHistory älterer DND-Verträge hat leeres `solicitationNumber` (andere
  Vergabesysteme). Fallback auf `referenceNumber`.
- **7-stufiger Filter** (in absteigender Konfidenz): Primary-DND + KW-Title → HIGH;
  Primary-DND + GSIN → HIGH; PSPC/DCC + DND-EndUser + KW → HIGH; etc.

---

## [Unreleased] — AU OCDS Adapter (Sprint 15, 2026-05-10)

Adds a new national adapter for **Australia — AusTender OCDS API** (post-award
Contract Notices). Registered as `"au"` in `run_national_scraping()`.
Token empirically verified as NOT required (public API, CC BY 3.0 AU licence).

### Smoke-Test Ergebnisse (30 Seiten, 2024-01-01 → 2026-05-01)

| Metrik | Wert |
|--------|------|
| Releases gescannt | 3.000 |
| Defence-Hits | 1.636 (54 %) |
| Trailer-Keyword-Matches | 8 |
| Manuell verifiziert | 5/5 ✅ |
| Größter Einzelauftrag | CN4237513: AUD 4.501.386 "Commercial Trailers" |

### Neue Dateien

- **`src/national_scraper/adapters/au_ocds_adapter.py`** — `AuOcdsAdapter(BaseAdapter)`,
  `create_au_ocds_config()`. Kein Browser, kein Token, reiner REST-API-Pull.
  OCDS-Mapping: `parties[procuringEntity].name` → Buyer, `contracts[0].description` → Title,
  `contracts[0].value` → Wert, `awards[0].suppliers[0].name` → Winner.
  Amendment-Dedup via ocid, Latest-Release-Wins-Logik.
- **`config/australia_buyer_whitelist.json`** — Defence buyer whitelist (DoD, CASG, ASD, ASA, DSTG, GWEO, NSSG, DDG).
- **`config/australia_unspsc_whitelist.json`** — UNSPSC Prefixe Segment 25 (Vehicles, Trailers, Axles) + 78 (Transport Services).
- **`docs/AUSTRALIA_OCDS_ADAPTER.md`** — Architektur, OCDS-Mapping-Tabelle, Filter-Logik, Limitierungen.
- **`docs/AU_OCDS_API_PROBE.md`** — Token-Status-Report, API-Schema, Volume-Schätzung, 5 verifizierte Stichproben.
- **`scripts/_probe_au_ocds.py`** — Probe-Script für Token-Empirik.

### Geänderte Dateien

- **`main.py`** — `adapter_registry["au"] = (AuOcdsAdapter, create_au_ocds_config)` registriert in beiden Registries (static + dynamic).
- **`CLAUDE.md` §7** — AU-Zeile korrigiert auf `au_ocds_adapter.py`, Zähler auf 20 Länder / 24 Adapter.

### Details

| Property | Value |
|----------|-------|
| Source | `api.tenders.gov.au/ocds` |
| Coverage | Post-award Contract Notices ab 2013-01-01, ≥ AUD 10.000 |
| Pagination | Cursor via `links.next` |
| Browser needed | Nein |
| Token | Nein (öffentliche API) |
| Licence | CC BY 3.0 AU |
| Attribution | `Source: Department of Finance, Australia (CC BY 3.0 AU)` |
| Source code | `AU-TEN` |
| Currency | AUD |
| Cache | `data/au_ocds_raw/{cn_id}.json` + `data/.au_ocds_state.json` |

---

## [Unreleased] — National Portal Fallback (Phase 3g Extension, 2026-05-10)

Erweitert Phase 3g (Document Extraction) um einen **National Portal Fallback**
für DE, PL und CZ: Wenn alle `tender_documents_access`-URLs tot sind (404,
403, Timeout, Content < 1 KB), sucht der Orchestrator aktiv auf den nationalen
Beschaffungsportalen nach frischen Dokumenten.

### Vorher / Nachher

| Metrik | Vorher | Nachher |
|--------|--------|---------|
| Tote URLs erkannt | nicht gemessen | gezählt als `dead_urls` in Stats |
| DE Fallback | — | evergabe-online.de (ID-Suche) + service.bund.de |
| PL Fallback | — | ezamowienia.gov.pl REST API |
| CZ Fallback | — | verejnezakazky.vop.cz + nen.nipez.cz |
| Fallback-Cache | — | `data/.national_fallback_cache.json` |
| `--no-fallback-cache` Flag | — | erzwingt frischen Abruf |
| Winner/Quantity aus Nationalportal | — | `_fallback_*` Felder auf Notice |

### Neue Dateien

- **`src/national_scraper/fallback/__init__.py`** — Package-Init, exportiert `search_de`, `search_pl`, `search_cz`
- **`src/national_scraper/fallback/de_search.py`** — evergabe-online.de (ID-Lookup, server-seitiges HTML) + service.bund.de (Static-GET, IMPORTE-Links); `_parse_de_fields()` mit Newline-Boundary-Fix für Winner-Regex
- **`src/national_scraper/fallback/pl_search.py`** — ezamowienia.gov.pl REST API (`Board/Search` + `GetNoticeHtmlBodyById`); Exact-Ref-Match > Keyword-Score > First-Result
- **`src/national_scraper/fallback/cz_search.py`** — VOP (verejnezakazky.vop.cz) Static-HTML + NEN (nen.nipez.cz) `__NEXT_DATA__` JSON-Blob-Parser
- **`tests/test_national_fallback.py`** — 41 Unit-Tests über 5 Klassen (url_is_healthy, DE, PL, CZ, Orchestrator-Integration)
- **`docs/NATIONAL_FALLBACK_STRATEGY.md`** — Architektur, URL-Health-Check, Country-Inference, Search-Module, Cache-Format, Stats-Bedeutung

### Geänderte Dateien

- **`src/document_pipeline/discovery.py`**: `url_is_healthy()` hinzugefügt (HEAD-Request, 15 s Timeout, Content-Length-Guard < 1 KB)
- **`src/document_pipeline/orchestrator.py`**: Health-Check-Loop, `_infer_country_code()`, `_run_national_fallback()`, Cache-Logik, Stats `dead_urls` / `fallback_triggered` / `fallback_found` / `fallback_cache_hits`; Bugfix: "Dead URLs skipped" zeigte stets `docs_discovered` statt `stats['dead_urls']`
- **`main.py`**: `--no-fallback-cache` Argument + Pass-through in `run_phase_extract_documents()`

---

## [Unreleased] — TED-XML Fallback (Strategie B+, 2026-05-10)

Erweitert die TED-Pipeline um einen XML-Fallback für Felder, die nur in
der TED-XML-Repräsentation verfügbar sind (nicht in der JSON-search-API):
**internal_reference** (Buyer-Aktenzeichen, z. B. `Q/U2BP/RA029/NA103`),
**tender_documents_access** (Deeplink mit Tender-ID,
z. B. `…/tenderdetails.html?id=771723`), **buyer_profile_url_full**
(volle URL mit Buyer-Code, z. B. `…/pn/12wog`), **contract_folder_id**
und **notice_uuid**. Foundation für Window B2 (National-Portal-Lookup).

### Neu

**Neu:** `docs/TED_XML_FIELD_PATHS.md` — XPath-Karte für eForms-UBL und
legacy TED_EXPORT-Schema, Sample-Werte aus 4 echten Notices (DE/FR/PL/CZ),
Fallback-Reihenfolge, Implementation-Hinweise.

**Neu:** `src/ted_xml_fetcher.py` — eigenständiges Modul:
- `fetch_xml(notice_id, lang="en", cache=True)` — Disk-Cache unter
  `data/ted_xml_cache/{id}.xml`, 429-Backoff, SSL_VERIFY_DISABLE-Support.
- `parse_xml_fields(xml_bytes)` — **Dual-Schema-Parser**:
  - **eForms / UBL** (post-2023, root `ContractNotice`/`ContractAwardNotice`):
    `ProcurementProject/ID`, `CallForTendersDocumentReference/.../URI`,
    `ContractingParty/BuyerProfileURI`, `TenderRecipientParty/EndpointID`,
    `ContractFolderID`, root `<ID>`.
  - **TED_EXPORT R2.0.x** (2008–2023): `URL_DOCUMENT`, `URL_BUYER`,
    `URL_PARTICIPATION`, `IA_URL_GENERAL`, `DOC_ID` (Attribut),
    `NO_DOC_OJS`. (`internal_reference` schemaseitig nicht vorhanden.)
  - Heuristik-Fallback: `tender_documents_access` aus
    `buyer_profile_url_full` wenn URL Deeplink-Marker enthält
    (`/vz`, `?id=`, `/pn/`, `/profil/`).
  - Stdlib `xml.etree.ElementTree`, Namespace-Stripping per Tag-Split.
    Keine `lxml`-Dependency.

**Neu:** `scripts/_backfill_ted_xml.py` — Backfill-Runner. Zieht für
jeden TED-Tender XML, parst, merged in `_raw._xml` und in
`data/raw/details/{id}.json`. Cache-friendly (`--force` für Refresh,
`--limit` als Cost-Guardrail, `--dry-run`). Rate-Limit 1.1 s/Call.

### Geändert

**Geändert:** `src/exporter_frontend.py:_map_notice()`
- Felder werden jetzt aus **`_raw._xml` bevorzugt**, JSON-API als
  Fallback:
  - `buyer_profile_url`: XML's `buyer_profile_url_full` → JSON's
    `buyer-internet-address`
  - `internal_reference`: XML's `internal_reference` → JSON's
    `internal-identifier-part`
- **Neu im Frontend-Output:**
  - `tender_documents_access` (string, optional) — Direkt-Deeplink mit
    Buyer-Tender-ID
  - `contract_folder_id` (string, optional) — eForms-UUID

**Geändert:** `shared/schema/tender.schema.json`
- 2 neue optionale Properties: `tender_documents_access`,
  `contract_folder_id`. Beschreibungen für `buyer_profile_url` und
  `internal_reference` aktualisiert (Source-Hierarchie XML > JSON).

**Geändert:** `src/document_pipeline/discovery.py:_discover_ted()`
- Vergabeunterlagen-DocumentRef nutzt **Drei-Stufen-Priorität**:
  1. `_xml.tender_documents_access` (mit Tender-ID-Param)
  2. `_xml.buyer_profile_url_full` (mit Buyer-Code-Path)
  3. JSON `buyer-internet-address` (Host-only)
- `internal_reference` und `contract_folder_id` werden als `extra`-
  Metadaten am DocumentRef weitergereicht — kosten-frei verfügbar für
  die Window-B2-National-Portal-Suche.
- Neuer Helper `_first_str(value)` für robustes List/String-Handling.

### Verification

```
$ python3 scripts/_backfill_ted_xml.py
  256 notices in relevant.json, 194 TED to backfill
  backfilled:  194    failures: 0

  Field coverage (raw._xml on TED-Tender):
    internal_reference         75 / 194  ( 38.7 %)
    tender_documents_access    54 / 194  ( 27.8 %)
    buyer_profile_url_full    147 / 194  ( 75.8 %)
    contract_folder_id         72 / 194  ( 37.1 %)
    notice_uuid               194 / 194  (100.0 %)

$ python3 -m src.exporter_frontend && python3 shared/scripts/validate.py shared/tenders.json
  Result: 378/378 OK | 0 error(s)
```

### Coverage in `shared/tenders.json` nach Merge JSON+XML

| Field | TED only | Δ vs JSON-only |
| ----- | -------: | -------------- |
| `buyer_profile_url`     | **173/194 (89 %)** | 154 → 173 (+19) |
| `internal_reference`    | **75/194 (39 %)**  | 2 → 75 (+73) ⭐ |
| `tender_documents_access` | **54/194 (28 %)** | new field |
| `contract_folder_id`    | **72/194 (37 %)**  | new field |

`internal_reference`-Coverage: **1 % → 39 %** = **+38 pp** (neue
Foundation für National-Portal-Suche).

### Spec-Stichproben

| # | Spec-Kriterium | Ergebnis |
| - | -------------- | -------- |
| 1 | Tender 245184-2024 hat `internal_reference` | ✅ `"MRMP-L/P 23LP202 (2024)"` (Belgien — Buyer-Aktenzeichen) |
| 2 | ≥ 5 zufällige TED-Tender mit `tender_documents_access` | ✅ `kommersannons.se/fmv/Notice?NoticeId=56215`, `s2c.mercell.com/today/106246`, `publicprocurement.be/publication-workspaces/<UUID>/documents`, `permalink.mercell.com/232593252.aspx`, `s2c.mercell.com/today/152613` |
| 3 | `discovery.py` erkennt URLs als DocumentRef | ✅ alle 5 → `doc_type="vergabeunterlagen"`, `extra` enthält `buyer_profile_url`, `internal_reference`, `contract_folder_id` |
| 4 | `validate.py` Exit 0 | ✅ 378/378 OK |

### Bekannte Limits

- **`internal_reference` 39 % statt ≥ 75 %**: das `ProcurementProject/ID`-
  Feld ist nur in eForms-Notices vorhanden (ab ~Ende 2023). Ältere
  TED_EXPORT-Notices haben kein semantisch äquivalentes Feld; eine
  Heuristik aus DOC_ID + Buyer-URL wäre möglich, aber unsicher —
  außerhalb dieses Sprints.
- **`tender_documents_access` 28 %**: nur eForms-Notices haben den
  dedicated `CallForTendersDocumentReference/.../URI`-Pfad.
  TED_EXPORT-Notices nutzen `URL_DOCUMENT` (selten populiert) oder
  verlinken nur auf eine Buyer-Landing-Page. Window B2 muss damit
  umgehen, dass nur ~28 % einen echten Deeplink liefern; in den anderen
  Fällen ist `buyer_profile_url` (89 %) der Einstiegspunkt.
- **Rate-Limit**: TED-XML lebt hinter nginx mit ~5 req/s Globalbarriere.
  194 Calls × 1.1 s Pause = ~3:35 min einmalig (Disk-Cache danach).
- **lxml nicht benötigt**: stdlib `xml.etree.ElementTree` reicht völlig.

---

## [Unreleased] — Sprint 14g: Multilinguale Keyword-Erweiterung via Opus-Brainstorm (2026-05-10)

Empirische Erweiterung des `keywords`-Blocks in `config/settings.yaml` —
basierend auf 86 awarded/closed Defence-Trailer-Tendern aus 20 Ländern.
Opus 4.1 (via OpenRouter) extrahiert systematisch multilinguale Keywords.

### Workflow (4 neue Skripte)

| Skript | Zweck | Output |
|--------|-------|--------|
| `scripts/_extract_awarded_corpus.py` | Korpus aus `relevant.json` (86 awarded Tender) | `docs/AWARDED_CORPUS.json` |
| `scripts/_opus_keyword_brainstorm.py` | Opus-Call (`openrouter/anthropic/claude-opus-4.1`) | `docs/OPUS_KEYWORD_BRAINSTORM.json` |
| `scripts/_build_settings_diff.py` | Diff vs. `settings.yaml` (additiv) | `docs/SETTINGS_KEYWORD_DIFF.yaml` |
| `scripts/_keyword_simulation.py` | Re-Filter-Probe gegen `.filter_cache.json` | stdout summary |

### Ergebnisse

| Metrik | Wert |
|--------|------|
| Korpus-Tender | 86 (Ziel ≥80 ✓) |
| Opus-Output Keywords | 536 (14 Kategorien × 23 Sprachen) |
| **Neue Terms vorgeschlagen** | **432** (104 als Duplikate übersprungen) |
| Bestehende Kategorien erweitert | 10 |
| Neue Kategorien vorgeschlagen | 3 (`cargo_trailer`, `decontamination_cbrn`, `heavy_haul`) |
| **Re-Filter-Coverage-Uplift** | **+143 Tender** (Near-Miss-Bucket aus 4,910 evaluierten) |
| Low-Signal-Stichprobe (1000) | 0% flip — saubere Trennung |
| **Kosten** | **$0.7540** (1 Opus-Call, weit unter $20-Budget) |

### Top-Sprachen mit größter Coverage-Lücke
cs (44), ro (44), da (44), no (44), nl (42), sv (41), es (35), pl (33), it (32)

### Wichtig

- `config/settings.yaml` wurde **NICHT überschrieben** — Diff ist nur ein Vorschlag.
- `docs/SETTINGS_KEYWORD_DIFF.yaml` enthält pro Term ein Evidence-Snippet
  (`tender_id` + Auszug) für manuelles Review.
- **Anthropic-Direct-API erschöpft** → Routing via OpenRouter
  (`openrouter/anthropic/claude-opus-4.1`); `src/llm_router.py` Pricing-Tabelle
  um 3 OpenRouter-Anthropic-Aliasse erweitert.
- Detaillierter Bericht: `docs/SPRINT_14G_REPORT.md`

---

## [Unreleased] — Doc-Coverage-Audit + CZ Winner Fix + National Text-as-Doc (2026-05-10)

Sprint 14e: Doc-Coverage-Audit + CZ Winner-Selector-Fix + nationaler Text-als-Dokument-Fallback.

### Neu

**`scripts/_doc_coverage_audit.py`** — Klassifiziert alle 378 Tender in Buckets:
`HAS_SPECS` / `HAS_SPECS_LOW_CONF` / `NO_DOCS_AUTH_BLOCKED` / `NO_DOCS_NO_HANDLER` / `TED_NO_SPECS`.
Output: Tabelle Source × Bucket + Top-3-Beispiele + TED-Miss-Detail.

**`docs/DOC_COVERAGE_AUDIT_260510.md`** — Root-Cause-Analyse der 184 Tender ohne specs:
- CZ-NEN (153) + UK-CF (6): eIDAS-Blockierung — kein Fix möglich
- FR-BP (13) / UA-PR (5) / NO-DF (3) / EE-RP (3) / NL-TN (1): kein Discovery-Handler
- HAS_SPECS_LOW_CONF (19 TED): confidence=0, types=[] — TED-Notices sind Admin-Dokumente, keine Lastenheft

### Geändert

**`src/document_pipeline/discovery.py`**:
- `_discover_national_text()` — erzeugt synthetischen `DocumentRef(doc_type="national_page_text")`
  aus `_national_raw_text` (oder `_description_final`) für nationale Quellen ohne Dokument-URLs.
  Text-Mindestlänge: 80 Zeichen.
- `discover_for_notice()` — neuer Fallback-Zweig: wenn keine `links`, kein TED-Prefix, aber
  `_national_raw_text` oder `_description_final` vorhanden → `_discover_national_text()`.
  Betrifft: FR-BP ✅, NO-DF ✅ (UA-PR ohne raw_text weiterhin kein Ergebnis).

**`src/document_pipeline/orchestrator.py`**:
- `national_page_text` refs werden inline verarbeitet: `ref.extra["text"]` wird direkt als
  `extracted_text` verwendet — kein Download, kein Datei-I/O.
  Check: `len(inline) > 200` als Mindestqualität.

**`src/national_scraper/adapters/cz_adapter.py` — CZ Winner Fix**:
- `_find_winner()` — erweitert um:
  - Same-line Englisch-Patterns: `Supplier:`, `Selected supplier:`, `Selected tenderer:`
  - Next-line Patterns (NEN-Tabellen-Format): `SUPPLIER\nName`, `DODAVATEL\nName`,
    `VYBRANÝ DODAVATEL\nName`, `SELECTED TENDERER\nName` etc.
- `_try_result_page()` — neue Reihenfolge:
  1. Replace `detail-zakazky` → `vysledek-zakazky` (Orig-URL mit Search-Kontext)
  2. `/en/verejne-zakazky/vysledek-zakazky/{id}` (Englisch, kein Query-Noise)
  3. `/verejne-zakazky/vysledek-zakazky/{id}` (Tschechisch)
  4. Append `/vysledek`
  Zusätzlich: Debug-Logging wenn Keyword-Check passiert aber kein Name extrahiert.

### Tests

**`tests/test_adapter_fixes_260509.py`** — 6 neue Tests (gesamt jetzt 48):
- `TestCZFindWinner.test_same_line_dodavatel` (Regressionstest)
- `TestCZFindWinner.test_next_line_czech_heading` (VYBRANÝ DODAVATEL\nName)
- `TestCZFindWinner.test_next_line_english_heading` (SELECTED SUPPLIER\nName)
- `TestCZFindWinner.test_numeric_only_rejected`
- `TestCZFindWinner.test_empty_text_returns_empty`
- `TestCZResultPageWinner.test_winner_extracted_next_line_english`

### Coverage nach Discovery-Fix (Smoke-Test)

| Source | Vorher (docs) | Nachher (docs) | Text-Länge |
|--------|:---:|:---:|:---:|
| FR-BP  | 0 | 1 ref/tender | 455–505 chars |
| NO-DF  | 0 | 1 ref/tender | 993–1263 chars |
| EE-RP  | 0 | 0–1 ref (113 chars < 200 Extractor-Min) | — |
| UA-PR  | 0 | 0 (kein raw_text) | — |

```
$ python3 scripts/_doc_coverage_audit.py
  HAS_SPECS            175  (46.3%)
  HAS_SPECS_LOW_CONF    19  ( 5.0%)
  NO_DOCS_AUTH_BLOCKED 159  (42.1%)
  NO_DOCS_NO_HANDLER    25  ( 6.6%)
  TED_NO_SPECS           0  ( 0.0%)

$ python3 -m unittest tests.test_adapter_fixes_260509 -v
  Ran 48 tests in 0.018s  OK

$ python3 shared/scripts/validate.py shared/tenders.json
  Result: 378/378 OK  |  0 error(s)
```

### Offene Punkte (nächster Sprint)

- **CZ Re-Run nötig**: `_try_result_page()` live testen — EnglishURL `/en/.../vysledek-zakazky/{id}`
  muss gegen echtes NEN verifiziert werden. Ziel: ≥5 CZ Winner.
- **FR/NO `--extract-documents`**: Nachdem national text-as-doc live ist, `--extract-documents`
  erneut laufen lassen → FR-BP (13) + NO-DF (3) erhalten partielle specs aus Seitentexten.
- **UA re-run**: `_raw.internal_id` im ua_adapter sicherstellen → Prozorro-Dokument-Discovery nutzen.

---

## [Unreleased] — TED-XML Field Expansion (Cross-Reference §B, 2026-05-10)

Implementiert Strategie B aus `docs/CROSS_REFERENCE_INVESTIGATION_260509.md`
("erst TED-API voll auswerten, dann erst nationale Portale scrapen"). Acht
neue TED-API-Felder werden empirisch entdeckt, in `ALL_FIELDS` aufgenommen,
für alle 194 TED-Tender via Backfill nachgezogen, im Exporter zu
strukturierten Top-Level-Feldern in `shared/tenders.json` durchgereicht und
als zweite Quelle ins Document-Pipeline-Discovery-System gehookt.

### Neu

**Neu:** `scripts/_probe_ted_fields_v2.py` — binary-search-Probe gegen die
TED-v3-Search-API. TED gibt HTTP 400 bei jedem unbekannten Feld zurück,
daher halbiert das Script die Kandidatenliste rekursiv, um valide
Feldnamen zu isolieren. Output:
- 8 neue API-akzeptierte Felder
- `data/.ted_field_probe.json` mit Sample-Werten für 4 reale Tender

**Neu:** `docs/TED_FIELDS_DISCOVERED.md` — Discovery-Ergebnis mit
Sample-Werten, Use-Case je Feld und expliziter Liste der Namen, die in
der XML auftauchen, aber **nicht** in der JSON-API zugänglich sind
(z. B. `tender-documents-access`, `internal-reference` als String,
`buyer-profile-url`).

**Neu:** `scripts/_backfill_ted_xml_fields.py` — Backfill-Runner analog
`_backfill_notice_type.py`. Re-fetch jedes TED-Notice mit dem
erweiterten Field-Set, merged neue Werte ins `_raw`-Blob in
`relevant.json` UND in `data/raw/details/{id}.json`. Cache-friendly,
`--force` für Refresh, `--limit` als Cost-Guardrail.

### Geändert

**Geändert:** `src/api_client.py:ALL_FIELDS`
- 8 neue Felder (Sprint-Marker als Kommentar):
  `buyer-internet-address`, `estimated-value-lot`, `quantity-lot`,
  `procedure-features`, `place-of-performance-{city,country}-part`,
  `deadline-receipt-tender-time-lot`, `internal-identifier-part`.
- Damit holt jeder neue TED-Run und jeder Re-Fetch automatisch diese
  Felder mit. `INDEX_FIELDS` und `DETAIL_FIELDS` zeigen weiterhin auf
  `ALL_FIELDS`.

**Geändert:** `src/exporter_frontend.py:_map_notice()`
- Neue Top-Level-Felder im Frontend-Output:
  - `buyer_profile_url` (string, optional) — first non-empty Element aus
    `buyer-internet-address`. Foreign-Key zur Buyer-Portal-Site.
  - `internal_reference` (string, optional) — aus
    `internal-identifier-part`.
  - `procedure_features` (string, optional) — multilingualer
    Procedure-Text; Englisch bevorzugt, dann erste verfügbare Sprache.
  - `lots` (array, optional) — Pro-Lot-Breakdown mit
    `id`/`value`/`quantity`, elementweise gepaart aus
    `estimated-value-lot` + `quantity-lot`.

**Geändert:** `shared/schema/tender.schema.json`
- 4 neue optionale Properties: `buyer_profile_url`, `internal_reference`,
  `procedure_features`, `lots` (mit inline-Items-Schema).
  Additiv, breakt nichts.

**Geändert:** `src/document_pipeline/discovery.py:_discover_ted()`
- Hook für `vergabeunterlagen`-DocumentRef: wenn ein TED-Notice
  `buyer-internet-address` in `_raw` hat, fügt Discovery jetzt einen
  zweiten `DocumentRef` mit `doc_type="vergabeunterlagen"` ein. Format
  wird per `_fmt_from_url` erraten, mit Fallback auf `html` für
  Bare-Host-URLs.

### Verification

```
$ python3 scripts/_probe_ted_fields_v2.py
  ── 8 NEW VALID FIELD NAMES (accepted by API) ──
    + buyer-internet-address     (sample: "http://www.evergabe-online.de/")
    + estimated-value-lot        (sample: ["2332000","827000","857000","568000"])
    + procedure-features, quantity-lot, place-of-performance-{city,country}-part, …

$ python3 scripts/_backfill_ted_xml_fields.py
  256 relevant.json notices total
  62 skipped (non-TED), 194 TED to backfill
  API calls:                  194
  Successful patches:         193
  Failures:                     1   (129023-2016 — ancient/delisted)
  NEW_FIELDS values written:  210

$ python3 -m src.exporter_frontend && python3 shared/scripts/validate.py shared/tenders.json
  Result: 378/378 OK | 0 error(s)
```

### Coverage in `shared/tenders.json` nach Backfill

| Field | Total | TED only |
| ----- | ----: | -------: |
| `buyer_profile_url` | 154/378 | **154/194 (79 %)** |
| `internal_reference` | 2/378 | 2/194 (1 %) |
| `procedure_features` | 8/378 | 8/194 (4 %) |
| `lots` | 31/378 | 31/194 (16 %) |

**Sample:** `182178-2026` (FMV / Sweden) →
`buyer_profile_url: "https://www.fmv.se"`, `lots: [{"id":"LOT-0001","value":99850000.0}]`.

### Discovery-Hook Smoke-Test

```
182178-2026:  notice_pdf  +  vergabeunterlagen → https://www.fmv.se        (html)
572650-2024:  notice_pdf  +  vergabeunterlagen → https://www.mindef.nl     (html)
245184-2024:  notice_pdf  +  vergabeunterlagen → https://www.mil.be/       (html)
537199-2024:  notice_pdf  +  vergabeunterlagen → https://FMA.NO            (html)
```

### Bekannte Limits

- **`tender-documents-access` (Tender-Documents-Direktlink mit Tender-ID)**
  ist nur in der TED-XML-Variante verfügbar, nicht im JSON-API-Response.
  Ein zukünftiger Sprint kann einen leichten XML-Fallback-Fetcher
  einführen, um diese Direkt-Links zu ergänzen — außerhalb dieses Sprints.
- **`internal-reference` (XML-Variante mit ausgesetzter Tender-ID, z. B.
  „24R40121")** ist ebenfalls nur via XML zugänglich. Wir nutzen ersatzweise
  `internal-identifier-part` aus der API, das mehrheitlich leer ist.
- **Coverage von `internal_reference` (1 %), `procedure_features` (4 %)**
  spiegelt wider, dass diese Felder nur sporadisch in TED-Notices gepflegt
  werden — das ist ein Inhalts-, kein Pipeline-Problem.
- **1/194 Backfill-Failure** (`129023-2016`): historische Notice, im TED
  nicht mehr abrufbar.

### Hinweis für künftige Frontend-Erweiterungen

`buyer_profile_url`, `lots` etc. sind im Frontend-Schema optional.
`defence-intel-web/lib/types.ts` Tender-Interface kann sie in einem
separaten Sprint nachziehen (z. B. Lot-Breakdown als Aufklapp-Tabelle,
Buyer-Profile als verlinkter Hover-Tooltip).

---

## [Unreleased] — Adapter-Fixes: UA/CZ Status + CPV + Winner-Extraktion (2026-05-10)

Sprint 14d: 5 Adapter-Lücken aus INVESTIGATION_ua_cz_audit_260509.md implementiert.

### Änderungen

**`src/national_scraper/base_adapter.py`**:
- `NoticeDetail` um `status: str = ""` Feld erweitert
- `to_standard_format()` emittiert `"_status": detail.status` für alle Adapter

**`src/national_scraper/adapters/ua_adapter.py`**:
- `_map_prozorro_status(raw)` — mappt Prozorro-Status auf Pipeline-Vokabular:
  `active.tendering/enquiries → Open`, `active.qualification/awarded → Awarded`,
  `complete → Closed`, `cancelled/unsuccessful → Cancelled`
- `get_detail()` setzt `detail.status` aus `data.get("status")`

**`src/national_scraper/adapters/cz_adapter.py`**:
- `_CZ_STATUS_MAP` + `_map_cz_status()` — mappt NEN-Status auf Pipeline-Vokabular
- `_find_status()` — Regex auf "CURRENT STATUS OF THE PROCUREMENT PROCEDURE\n..."
- `_find_cpv()` — Regex auf "CODE FROM THE CPV CODE LIST\n{8stellig}-{1}"
- `get_detail()` setzt `detail.status`, prepended CPV+Status in raw_text
- `_try_result_page()` — navigiert zu `vysledek-zakazky/{id}` für Winner-Extraktion
  bei Awarded-Status (graceful skip wenn Page nicht erreichbar)

**`src/national_scraper/adapters/fr_adapter.py`**:
- Phase 3 in `search_all_keywords()`: sucht DIRECTIVE-81-Notices mit `titulaire IS NOT NULL`
  — findet Attributions-Notices mit Winner auch ohne Trailer-Keyword im Titel

**`src/national_scraper/adapters/no_adapter.py`**:
- `_map_doffin_status()` — leitet Status aus `type=` / `status=` im Snippet ab
- `get_detail()` setzt `detail.status` via `_map_doffin_status(result.snippet)`
- `_find_winner()` — erweitert um `Kontraktsvinner`, `Valgt leverandør`,
  `Navn på leverandør`, `Leverandørnavn` (Doffin-Award-Page-Labels)

**`shared/schema/tender.schema.json`**:
- `extracted_specs` (object, additionalProperties: true) hinzugefügt — behebt vorher
  blockierende Schema-Validierungsfehler für 175 Tenders

### Tests
**`tests/test_adapter_fixes_260509.py`** — 42 neue Unit-Tests:
- `TestMapProzorroStatus` (10 Tests)
- `TestUAStatusInToStandardFormat` (2 Tests)
- `TestMapCzStatus` (6 Tests), `TestCZFindStatus` (4), `TestCZFindCpv` (3)
- `TestCZResultPageWinner` (2 Tests — Mock-Browser)
- `TestFRWinnerFromTitulaire` (3 Tests)
- `TestMapDoffinStatus` (6 Tests), `TestNOFindWinner` (6 Tests)

### Ergebnisse (nach Re-Run + Backfill)
| Metrik | Vorher | Nachher |
|--------|--------|---------|
| UA-Tenders mit korrektem Status | 0/5 | 4/5 |
| CZ-Tenders mit Status | 0/153 | 46/153 (30%) |
| CZ-N006/26/V00010428 `_status` | None | **Awarded** |
| CZ CPV in raw_text | 0 | 17 (frisch gescrapt) + 29 (backfill) |
| FR Tenders mit Winner | 5/13 | 5/13 (stabil) |
| validate.py errors | 175 | **0** |

### Offene Punkte
- CZ `_try_result_page` implementiert aber 0 Winner gefunden (NEN `vysledek-zakazky`
  URL-Pattern muss gegen Live-Portal verifiziert werden)
- FR/NO returned 0 in diesem Run (BOAMP/Doffin API nicht erreichbar in dieser Umgebung)
- UA-UA-2026-04-08-011067-a: kein raw_text (force-include ohne API-Daten)

---

## [Unreleased] — GPT-4o Migration für Document Extraction (2026-05-09)

Eval-basierte Migration des Extraction-Modells von Sonnet 4.6 auf GPT-4o via OpenRouter.

### Änderungen

**`src/document_pipeline/ai_structurer.py`** — komplett neu:
- Default-Modell: `openrouter/openai/gpt-4o` (F1=0.911 vs Sonnet F1=0.808 im Eval)
- Env-Override: `EXTRACTION_MODEL=<model_id>` (z.B. `anthropic/claude-sonnet-4-6`)
- Routing via `src/llm_router.py` statt direktem Anthropic-Client
- 3-Stufen-Resilienz: primary → primary retry → Sonnet-4.6-Fallback
- JSON-Retry auf Parse-Fehler eingebaut
- `max_tokens`: 1200 (erhöhtes Headroom für GPT-4o-Outputs)
- `cache_slug()` / `active_model()` als öffentliche Hilfsfunktionen

**`src/document_pipeline/orchestrator.py`**:
- Cache-Key: `f"{tender_id}:{model_slug}"` (z.B. `245184-2024:gpt-4o`)
  — Modell-Wechsel erzwingt automatisch frische API-Calls
- Cost-Tracking via `llm_router.estimate_cost_usd()` (modell-aware)
- Sonnet-Fallback-Zähler im Stats-Output
- Anthropic-Client wird nur noch für Vision-Fallback (Haiku) in `extractor.py` instanziiert

**Cache-Migration:**
- Backup: `data/.document_extraction_cache.pre-gpt4o.bak`
- Entscheidung: Cache vollständig geleert — GPT-4o liefert signifikant bessere Confidence-Scores, Qualitätssicherheit überwiegt Cache-Reuse
- Neue Einträge: `{tender_id}:gpt-4o` Format

### Voller Re-Run Ergebnisse (2026-05-09)
| Metrik | Wert |
|--------|------|
| Notices verarbeitet | 194/256 |
| Notices mit ≥1 Trailer-Typ | 175 |
| Total extrahierte Trailer-Typen | 281 |
| Avg Confidence (alt, Sonnet) | 18.0 |
| Avg Confidence (neu, GPT-4o) | **52.7** (+34.7 Punkte) |
| Confidence ≥50 | 139/194 (72%) |
| Confidence ≥80 | 29/194 (15%) |
| Sonnet-Fallbacks | 0 |
| Laufzeit | ~13 min |
| Geschätzte Kosten | ~$0.50–0.80 reell (Estimate: $2.72 konservativ) |

### Eval-Grundlage (Window C, 2026-05-09)
| Modell | Avg F1 | Cost/Call | Latenz |
|--------|--------|-----------|--------|
| `gpt-4o` | **0.911** | $0.0065 | 1.2s |
| `claude-sonnet-4-6` | 0.808 | $0.0094 | 2.9s |
| `mistral-large` | 0.819 | $0.0059 | 2.1s |

---

## [Unreleased] — Document Extraction Pipeline (2026-05-09)

Phase 3g: automatisches Download + Textextraktion + KI-Strukturierung von Ausschreibungsdokumenten.

### Neu

**`src/document_pipeline/`** — neues Package mit 5 Modulen:
- `discovery.py` — `DocumentRef` Dataclass + `discover_for_notice()`: erkennt per Source-Typ (TED/UA) downloadbare Dokumente. TED: `links.pdf.ENG`-URL. UA: Prozorro API re-fetch (UUID aus `_national_raw_text`).
- `downloader.py` — SHA1-Dedup-Download mit Rate-Limit (1 req/s), SSL_VERIFY_DISABLE-Support, 3× Retry, Auth-Block-Detection (< 2 KB → skip).
- `extractor.py` — Text-Extraktion: pdfplumber (Tier 1), python-docx (Tier 2), PyMuPDF + Haiku Vision (Tier 3 für gescannte PDFs), openpyxl, BeautifulSoup.
- `ai_structurer.py` — Sonnet 4.6 strukturierte Extraktion: Trailer-Typ, Menge, GVW, Abmessungen, Achslast, Nutzlast, Standards → `_extracted_specs`-Dict.
- `orchestrator.py` — End-to-End-Loop über `relevant.json`: discover → download → extract → AI-structure. Cache: `data/.document_extraction_cache.json`.

**`--extract-documents`** CLI-Flag (Phase 3g), standalone und in `--all`:
- `--extract-documents-dry-run` — discover + download, kein AI-Call (0 USD)
- `--extract-documents-sample <id1,id2>` — Smoke-Test auf einzelne IDs
- `--extract-documents-force` — Cache ignorieren, alles neu verarbeiten

**Exporter:** `_extracted_specs` wird in `tenders.json` als `extracted_specs`-Feld exportiert (nur wenn `trailer_types` befüllt).

### Coverage
- **TED** (194 Notices): ENG-PDF direkt downloadbar, pdfplumber Text-Extraktion. Confidence 10–40 (Ausschreibungstext, keine technischen Spezifikationen).
- **UA** (4 Notices): Confidential Defence Procurement → Prozorro API 404. Kein Download möglich.
- **CZ** (32), **UK** (6): Keine Dokument-URLs in Adapter-Daten → Discovery gibt leere Liste.

### Kosten
- Dry-run: $0
- Vollständig 194 TED-Notices: ~$0.10–0.20 Sonnet (1× pro Notice)
- Haiku Vision (gescannte PDFs): ~$0.005 pro Seite

---

## [Unreleased] — Field Extraction Re-Classification (2026-05-09)

Selektive Sonnet-4.6-Re-Klassifikation auf 60 nationalen Tendern, deren
Trailer-Type / Quantity / Duration-Felder in `relevant.json` fehlten.
Ausgangspunkt: Window A's `description_en` ist für 256/256 Notices
gesetzt, sodass die Re-Klassifikation auf englischem Content läuft —
deutlich höhere Extraktionsqualität.

### Neu

**Neu:** `scripts/_audit_extracted_fields.py` — schreibt
`docs/RUNS/field_extraction_audit_<YYMMDD>.md` mit pro-Country-Coverage
für `_trailer_type_1_ai`, `_trailer_quantity_1_ai`,
`_contract_duration_ai`, `description_en`, sowie eine
Re-Klassifikations-Kandidatenliste in `data/.reclass_candidates.txt`.

**Neu:** `scripts/_force_reclassify.py` — One-Shot-Runner für
Cache-bypassende Re-Klassifikation:
- Liest Kandidaten-IDs aus `data/.reclass_candidates.txt` (oder
  `--ids <csv>`); priorisiert nationale Tender vor TED-IDs und nach
  Anzahl fehlender Felder.
- Cost-Guardrail: `--max-calls` (Default 60).
- Schreibt erfolgreiche Resultate via `AiClassifier._apply_ai_result`
  zurück; aktualisiert `data/.enrichment_log.json` mit dem
  `_force_reclass_2026_05_09: True`-Marker.
- `--dry-run` zeigt nur den Plan + Pro-Prefix-Verteilung.

### Geändert

**Geändert:** `src/classifier.py:_build_prompt()`
- **Description-Quelle erweitert:** `description_en` (Window A) ist
  jetzt erste Wahl, gefolgt von `_description_english`, dann
  `description`. Der Classifier sieht damit englischen, kompakten
  Content — Sonnet-Reasoning-Qualität für Trailer-Quantity-Extraktion
  steigt deutlich.
- **Neue Prompt-Hints:** explizite Patterns für
  `QUANTITY EXTRACTION` (`qty: N`, `N units`, `N pcs`, `N ks`, `N stk`,
  `X x trailer`) und `DURATION EXTRACTION`
  (`48 months`, `for 4 years`, plus CZ/ES/DK lokalisierte Varianten).

### Verification

```
$ python3 scripts/_audit_extracted_fields.py    # baseline
  [TED] total=194  type=194 qty= 73 dur= 27
  [CZ]  total= 32  type= 32 qty= 12 dur=  2
  [FR]  total= 13  type= 13 qty=  5 dur=  0
  [UK]  total=  6  type=  6 qty=  2 dur=  0
  [UA]  total=  4  type=  1 qty=  0 dur=  0    ← worst gap
  [NO]  total=  3  type=  3 qty=  0 dur=  0
  [EE]  total=  3  type=  3 qty=  0 dur=  0
  [NL]  total=  1  type=  1 qty=  0 dur=  0

$ python3 scripts/_force_reclassify.py --max-calls 60
  Targets: 60 (CZ:31 FR:12 UK:6 UA:4 NO:3 EE:3 NL:1)
  Summary: evaluated=60  succeeded=50  failed=10
           new trailer_type_1: 2
           new trailer_qty_1:  2
           new contract_duration: 1
           est. cost: ~$0.29

$ python3 scripts/_audit_extracted_fields.py    # nachher
  [UA]  total=  4  type=  3 qty=  2 dur=  0    ← +2 type, +2 qty
  [UK]  total=  6  type=  6 qty=  2 dur=  1    ← +1 dur

$ python3 -m src.exporter_frontend && python3 shared/scripts/validate.py shared/tenders.json
  Result: 256/256 OK | 0 error(s)
```

### Stichproben

| # | Spec-Kriterium | Ergebnis |
| - | -------------- | -------- |
| 1 | UA-Tender mit `qty: 16` aus description (`Причіп автомобільний`) → `_trailer_qty_1_ai = 16` | ✅ `UA-2026-05-05-004789-a`: type=`Car trailer`, qty=`16` |
| 2 | CZ-Tender `Nákup přívěsných vozíků za OA` hat `_trailer_type_1_ai` gesetzt | ✅ `CZ-N006/26/V00010428`: type=`Military trailer (type not specified in notice)`, category=`Cargo Trailer` |
| 3 | ≥ 80 % der UA-Tender mit `vehicle_type` | ⚠ **75 %** (3/4): UA-2026-04-28 ist eine Dump-Truck-Beschaffung (kein Trailer); Sonnet 4.6 hat `relevant=false` zurückgegeben — defensive Logik im Runner überschreibt nicht. Wenn man die nicht-Trailer-Notice ausschließt, ist die Quote 3/3 = 100 %. |
| 4 | UA-2026-05-05 im Frontend mit `quantity=16` | ✅ `vehicle_types=[{'name': 'Car trailer', 'category': 'trailer', 'quantity': 16}]` |

### Bekannte Limits

- **`_apply_ai_result` ist additive für Quantity** (überschreibt nur
  wenn AI einen Wert findet ODER das Feld leer war), aber
  unconditional für `_trailer_type_1_ai`. Re-Klassifikationen, die ein
  scharfes englisches Re-Profil bringen, können also Type-Änderungen
  gegenüber dem alten Cache verursachen — gewünscht.
- **10/60 Reclass-Failures:** primär Notices, wo Sonnet auf der
  englischen Re-Beurteilung `relevant=false` zurückgab (z. B.
  Dump-Truck-Beschaffung in UA, die kein Trailer ist). Dort bleiben
  die alten Felder erhalten — defensive Choice.
- **Coverage-Gewinn ist moderat** (`+2 qty`, `+2 type`, `+1 dur` von
  60 Calls), weil viele Kandidaten nur einzelne fehlende Felder hatten
  und Sonnet nicht aus dünnen Beschreibungen Quantity / Duration
  herleiten kann, wenn das Datum schlicht nicht im Text steht. Strukturelle
  Quellen (TED-API `_value_amount`, `submission_deadline`-Multiline)
  bleiben die richtigeren Daten-Lieferanten dafür.

---

## [Unreleased] — Description Translation Pass (2026-05-09)

100% englische Titel und Descriptions in shared/tenders.json.

### Was wurde geändert

**Erweitert:** `src/translator.py`
- Neue Funktion `translate_descriptions(relevant_path, *, cache_path, model, ...)`:
  - Für jede Notice: beste verfügbare Description-Quelle (`_description_final → description → _raw.description`)
  - Falls `_description_english` existiert und Englisch ist: sofort als `description_en` (kein API-Call)
  - Falls nicht Englisch: Claude Sonnet 4.6 übersetzt + fasst in max. 4 Sätzen zusammen
  - Cache-Key: `<tender_id>:<sha1(source_text)[:12]>` — invalidiert wenn Quelltext ändert
  - Cache-File: `data/.description_translation_cache.json`

**Neu:** `main.py`
- `run_phase_translate_descriptions()` — Phase 3e-2, Sonnet 4.6
- CLI-Flag `--translate-descriptions` (Standalone + `--sample` + `--dry-run`)
- `--all`-Flow: neuer Timer Phase 3e-2 nach Title-Translation, vor Currency Enrichment
- `--national`-Standalone: nach Merge automatisch translate_titles + translate_descriptions

**Geändert:** `src/exporter_frontend.py`
- Description-Priorität: `description_en → _description_english → description_enriched → _description_final → description`

**Neu:** `scripts/_audit_content_languages.py` — Diagnose-Tool für Sprach-Audit

### Verification

```
$ python3 main.py --translate-descriptions
  evaluated: 256 | already English: 184 | translated now: 72 | cost: $0.15

$ python3 scripts/_audit_content_languages.py
  English titles: 256/256 (100.0%)
  English descriptions: 256/256 (100.0%)
  Missing title_en: 0

$ python3 shared/scripts/validate.py shared/tenders.json
  256/256 OK | 0 error(s)
```

| Metrik | Vorher | Nachher |
|--------|--------|---------|
| Fehlende title_en | 3 (UA) | **0** |
| Englische Descriptions | ~240/256 | **256/256** |
| FR-Descriptions Englisch | 0/13 | **13/13** |
| UA-Descriptions Englisch | 0/3 | **3/3** |

---

## [Unreleased] — Sprint Bug Fixes (2026-05-09)

Drei Bugs aus der Post-Run-Investigation 2026-05-08 behoben.

### Bug 1 — `_clean_date` Multiline-Fix (Hook-lift Trucks false "Open")

**Problem:** TED API liefert bei Multi-Lot-Ausschreibungen Fristen als mehrzeiligen String
(`"2025-12-12+01:00\n2025-12-12+01:00\n..."`). `_clean_date()` in `exporter_frontend.py`
verarbeitete nur die gesamte Zeichenkette — `re.match(r"^\d{4}-\d{2}-\d{2}$")` schlug fehl →
Rückgabe `""` → Frist nicht erkannt → 813306-2025 fälschlicherweise als **Open** klassifiziert.

**Fix:** `_clean_date()` splittet jetzt `str(value).split("\n")[0]` vor der TZ-Bereinigung.
Zusätzlich: List-Input (`["2025-12-12+01:00"]`) wird korrekt behandelt.

**Before/After:** 813306-2025 "Hook-lift trucks" status `Open → Closed`, deadline `2025-12-12`.

**Test:** `tests/test_clean_date.py` — 14 Unittest-Cases (plain ISO, TZ-offset, Z, T-datetime,
multiline gleich, multiline verschieden, list einfach, list mehrfach, list leer, None, leer,
garbage, Partial-Date, 0). Alle **14/14 OK**.

### Bug 2 — `merge_national_with_ted` ID-Dedup (48 Duplikate)

**Problem:** `merge_national_with_ted()` in `main.py` deduplizierte nur per inhaltsbasiertem
`_dedup_key()` (authority+title+year). Force-Include-Einträge und frisch gescrapte
Adapter-Notices mit minimal abweichendem Encoding erzeugten 48 exakte Duplikate
(CZ: 29, FR: 13, NO: 3, EE: 3) in `relevant.json`.

**Fix:** Vor dem content-basierten Check wird jetzt `existing_ids = {n.get("tender_id") ...}`
gebildet; Notices mit bereits bekannter `tender_id` werden sofort übersprungen.

**Before/After:** relevant.json 304 → 256 unique (48 Duplikate entfernt), shared/tenders.json 0 Duplikate.

**Test:** `tests/test_merge_national.py` — 5 Unittest-Cases. Alle **5/5 OK**.

### Bug 3 — UA-Adapter registriert + 3 neue UA-Tenders

**Problem:** `ua`-Adapter fehlte in der inline-Registry von `run_phase_national()`.
Zudem hatte `UA-UA-2026-04-08-011067-a` (`_value_amount = 0`) wegen des Double-Prefix-Bugs
keinen Eintrag im Prozorro Public API (Defence Procurement — restricted access).

**Fix:** UA-Adapter in `run_phase_national()` registriert. Neuer UA-Run fand **3 zusätzliche
UA-Tenders** mit echten Werten (638 k UAH, 23.55 M UAH, 1.75 M UAH). Die ursprüngliche
`011067-a`-Notice bleibt `estimated_value_eur = 0` (Prozorro Defence → öffentlich nicht abrufbar).

### Verification

```
$ python3 -m unittest tests/test_clean_date.py
Ran 14 tests in 0.000s — OK

$ python3 -m unittest tests/test_merge_national.py
Ran 5 tests in 0.000s — OK

$ python3 shared/scripts/validate.py shared/tenders.json
256/256 OK | 0 error(s)
```

| Metrik | Vorher (260508) | Nachher (260509) |
|--------|-----------------|-----------------|
| 813306-2025 Status | Open | **Closed** |
| Duplikate relevant.json | 48 | **0** |
| Duplikate tenders.json | 48 | **0** |
| UA Tenders | 1 (value=0) | **4** (3 mit Wert) |
| Open Count | 16 | **15** |
| Total tenders.json | 253 | **256** |

---

## [Unreleased] — Description Currency Enrichment (2026-05-09)

Neuer Phase-3f-Schritt: `src/currency_enricher.py`. Im
`description`-Fließtext jeder Notice wird jeder
`<Betrag> <Currency-Code>`-Treffer (CZK / PLN / UAH / NOK / SEK / DKK /
HUF / RON / BGN / GBP / CHF / TRY / USD / JPY / CNY) um sein EUR-Equivalent
ergänzt. **Pure Regex + FX-Lookup, 0 USD, keine LLM-Calls.**

**Beispiel:**
```
vorher:  "Small-scale public contract with estimated value of 123,293.66 CZK.
          Maximum price per trailer unit is 39,999.99 CZK including VAT."
nachher: "Small-scale public contract with estimated value of 123,293.66 CZK (~€4.9K).
          Maximum price per trailer unit is 39,999.99 CZK (~€1.6K) including VAT."
```

### Neu

**Neu:** `src/currency_enricher.py`
- `AMOUNT_PATTERN` — Regex mit Wort-Boundary-Lookarounds, akzeptiert
  EU/EN/FR-Tausender- und Dezimaltrenner sowie NBSP.
- `_parse_amount(text)` — locale-toleranter Parser:
  `"123,293.66"` (EN), `"123.293,66"` (EU), `"123 293,66"` (FR),
  `"39999.99"`, `"1,234"` (≥3-Digit-Gruppen → Tausender),
  `"1,23"` (≤2-Digit-Suffix → Dezimal), `"20,800,000"`, `"20.800.000"`.
- `_format_eur(amount)` — kompakte Anzeige `932`, `4.9K`, `478.4K`, `2.5M`.
- `enrich_description(text, fx_rates)` — idempotent (überspringt
  Vorkommen mit bereits angehängtem `"(~€…)"`); skipt out-of-range
  Conversions (< €1 oder > €10 B) zur Noise-Vermeidung.
- `enrich_all(relevant_path, …)` — iteriert `relevant.json`, schreibt
  `description_enriched` als additives Feld zurück. Cache via SHA-1 des
  Source-Texts (`data/.description_enrich_cache.json`).

**Neu:** `tests/test_currency_enricher.py` — 25 stdlib-`unittest`-Tests in
vier Klassen:
- `ParseAmountTests` (10 Cases): EN-/EU-/FR-Format, Ambiguitäts-Heuristik,
  Leerstring, einfacher Int.
- `FormatEurTests` (3 Cases): <1k, K-Range, M-Range.
- `AmountPatternTests` (5 Cases): CZK/UAH/EUR-Skip/Word-Boundary/Multi-Match.
- `EnrichDescriptionTests` (7 Cases): Spec-Beispiel, UAH-Million,
  No-Currency, Unknown-Currency, Idempotenz, Blank-Text, Below-Threshold.

**Neu:** `data/.description_enrich_cache.json` — pro Tender:
`{hash: <sha1 of source>, enriched: <text>, matches: int, ts: …}`.
Re-Runs hitten den Cache komplett.

**Geändert:** `main.py`
- Drei neue Flags: `--enrich-descriptions`, `--enrich-descriptions-sample`,
  `--enrich-descriptions-dry-run`.
- `run_phase_enrich_descriptions()` — Standalone-Phase mit Summary +
  Sample-Liste der ersten 5 Enrichments.
- `--all`-Flow: neuer `Timer("Phase 3f: Description Currency Enrichment")`
  zwischen `Phase 3e: Title Translation` und Award-Match. So sieht der
  LLM-Award-Matcher EUR-Equivalente in den Kandidaten-Beschreibungen.

**Geändert:** `src/exporter_frontend.py:_map_notice()`
- Description-Quelle erweitert: `description_enriched` ist jetzt erste
  Wahl (vor `_description_final`). Backwards-kompatibel: Notices ohne
  `description_enriched` bleiben unverändert.

### Verification

```
$ python3 -m unittest tests.test_currency_enricher
Ran 25 tests in 0.001s
OK

$ python3 main.py --enrich-descriptions --enrich-descriptions-sample <5 IDs>
  [enrich-descriptions summary]
    evaluated:                    6        (5 unique × duplicates)
    skipped (no currency match):  2        (UA-Tender, EN-TED control)
    enriched now:                 3        (CZ, PL, RO)
    from cache:                   1        (CZ duplicate)
    total currency matches:       6

$ python3 main.py --enrich-descriptions   # full run
    evaluated:                    301
    skipped (no currency match):  248
    enriched now:                 0        (cache greift)
    from cache:                   53

$ python3 -m src.exporter_frontend
Frontend export: 253 tenders → shared/tenders.json

$ python3 shared/scripts/validate.py shared/tenders.json
Result : 253/253 OK  |  0 error(s)
```

### 4-Punkt-Stichproben

| # | Check | Ergebnis |
| - | ----- | -------- |
| 1 | `CZ-N006/26/V00010428` description hat `"(~€"` | ✅ `123,293.66 CZK (~€4.9K)` + `39,999.99 CZK (~€1.6K)` |
| 2 | UA-Tender (`UA-UA-2026-04-08-011067-a`) description hat `"(~€"` | ❌ — UA-Description enthält keine UAH-Beträge im Fließtext (nur strukturiert in `_value_amount`, das Adapter-Daten-Problem aus Sprint 14c-Followup) |
| 3 | EN-TED-Tender (`326948-2025`) description **unverändert** | ✅ |
| 4 | Doppel-Annotationen (`(~€...) (~€...)`) | ✅ 0 — Idempotenz wirkt |

### Full-Run-Statistik

| Metrik | Wert |
| ------ | ---: |
| Notices in `relevant.json` | 301 |
| Mit non-EUR Currency-Match in description | **3** (CZ, PL, RO) |
| Total Currency-Treffer | **6** |
| Tender mit EUR-Annotation in `shared/tenders.json` | **3 / 253** |
| API-Kosten | **$0.00** |

### Bekannte Limits

- **Treffer-Quote ist niedriger als die Spec-Schätzung** (3 vs. ~80–120
  erwartet). Grund: Die meisten TED-Defence-Trailer-Beschreibungen werden
  vom AI-Classifier auf englische Kurzfassungen reduziert, in denen die
  ursprünglichen Fremdwährungs-Beträge nicht mehr stehen. Strukturelle
  Werte (`_value_amount`, `estimated_value`) sind durch Sprint 14a /
  Exporter-FX bereits abgedeckt.
- **UA-Tender bekommt aktuell keine EUR-Annotation**, weil seine Description
  keinen UAH-Betrag enthält. Sobald der UA-Adapter (Sprint 14c-Followup)
  Beschreibungen mit Fließtext-Beträgen liefert, greift der Enricher
  automatisch ohne Code-Änderung.
- **Currency-Codes ohne FX-Eintrag** (z. B. JPY/CNY in `_SUPPORTED` aber
  nicht in `_FX`) werden vom Regex erkannt, dann aber unangetastet
  durchgelassen. Falls JPY-Defence-Tender hereinkommen, ist `_FX["JPY"]`
  einmalig zu ergänzen — separater Sprint.

---

## [Unreleased] — Exporter Hardening: Dedup + First-Seen Tracking (2026-05-08)

### Neu

**`src/exporter_frontend.py` — Deduplication**
- `_deduplicate_records(records)` — vor dem JSON-Schreiben: gruppiert Einträge nach
  `id`, behält pro Gruppe den vollständigsten Record (Vollständigkeits-Score =
  Anzahl nicht-leerer Felder; Tiebreak: Source-Tier TED > UK-CF > UK-FTS > National;
  Tiebreak: neuestes `publication_date`). Entfernte Duplikate werden per `INFO`-Log
  benannt. Ergebnis: 301 Records → 253 unique.
- `_source_tier(record)` + `_record_completeness(record)` — Hilfsfunktionen für Dedup.

**`src/exporter_frontend.py` — First-Seen Tracking**
- `_apply_first_seen(tenders, state_path, shared_path)` — lädt / erstellt
  `data/.first_seen_state.json`. Neue IDs erhalten den aktuellen UTC-Timestamp;
  bekannte IDs behalten ihren Eintrag. Schreibt `_first_seen_at` in jedes
  Tender-Dict in `tenders.json`.
- `_load_first_seen_state(state_path, shared_path)` — initialisiert den State bei
  Erstlauf per Backfill aus `shared/tenders.json.*.bak`
  (Timestamp `2026-05-04T10:00:00Z`). Danach idem aus der State-Datei.
- **`data/.first_seen_state.json`** — neue persistente Datei; 256 Einträge nach
  dem 2026-05-08-Backfill.

**`shared/schema/tender.schema.json` — Schema-Extension**
- Neues optionales Property `_first_seen_at` (string, format: date-time).
- Neues optionales Property `title_en` (string) — Haiku-übersetzter Titel.

### Ergebnis (2026-05-08)
- `tenders.json`: **253** Einträge (vorher 301 mit 48 Duplikaten).
- `_first_seen_at`: **253/253** (100 %) — 245 backfilled, 8 neu.
- `title_en`: **253/253** (100 %).
- `validate.py`: ✅ 253/253 OK, 0 Errors.

---

## [Unreleased] — Title Translation Pass (2026-05-08)

Neues Phase-3e-Modul: `src/translator.py`. Übersetzt für jeden Tender, dessen
`_title_final` nicht bereits Englisch ist, den Titel via Claude Haiku 4.5 ins
Englische und schreibt das Ergebnis als `title_en` in `relevant.json`. Der
Frontend-Exporter bevorzugt jetzt `title_en` — UI-Titel sind durchgängig
Englisch, ohne dass die Original-Felder mutiert werden.

### Neu

**Neu:** `src/translator.py`
- `is_likely_english(text)` — billiger Heuristik-Check (≥ 90 % ASCII **und**
  mindestens ein Stop-Word aus `{the, of, for, and, with, to, in, on, by, …}`).
  Trifft pure-ASCII-Nicht-Englisch-Titel (z. B. polnisches
  `Zakup pojazdow ciezarowych`) als „nicht Englisch" und schickt sie an die API.
- `TitleTranslator` — Anthropic-Client mit SSL-Disable wie `classifier.py`,
  Retry mit Backoff für 429/529, Token- + USD-Cost-Tracking pro Run.
- `translate_titles(relevant_path, …)` — Main-Entry-Point. Iteriert Notices,
  unterscheidet Cache-Hit, Heuristik-Pass-Through, API-Call. Schreibt
  `title_en` direkt in `relevant.json`. Idempotent.

**Neu:** `data/.translation_cache.json` — eigenständiger Cache. Key: `tender_id`.
Wert: `{original, title_en, is_english, translated_at, model, input_tokens,
output_tokens}`. Re-Runs hitten den Cache → 0 API-Calls bei stabilem Datenstand.

**Geändert:** `main.py`
- Drei neue Flags: `--translate-titles`, `--translate-titles-sample <ids>`,
  `--translate-titles-dry-run`.
- `run_phase_translate_titles()` — Standalone-Phase mit Summary-Output und
  Sample-Liste der ersten 5 Übersetzungen.
- `--all`-Flow: neuer `Timer("Phase 3e: Title Translation")` zwischen
  `Phase 3b: AI Classify` und `Phase 3d: Award Match`. So sieht der
  LLM-Award-Matcher (Sonnet) bereits englische Titel — bessere
  Cross-Language-Match-Qualität.

**Geändert:** `src/exporter_frontend.py:_map_notice()`
- Title-Quelle-Reihenfolge erweitert: `title_en → _title_final → _title_english
  → title`. Backwards-kompatibel: Notices ohne `title_en` bleiben unverändert.

### Verification

```
$ python3 main.py --translate-titles --translate-titles-sample CZ-N006/26/V00010428,FR-21-163372,NO-2023-312913,UK-...,NL-577684
  [translate-titles summary]
    evaluated:                8         (5 unique × Duplikate)
    already English (heur.):  1         (NL)
    translated now (API):     4         (UK, CZ, FR, NO)
    from cache:               3         (Duplikate, second pass)
    errors:                   0
    estimated cost (USD):     0.001

$ python3 main.py --translate-titles --translate-titles-sample <same>
  [translate-titles summary]
    from cache:               8
    API calls:                0
    estimated cost (USD):     0.0     ← Cache-Mechanik bestätigt
```

### Full-Run (alle 301 Tender, 2026-05-08)

| Metrik | Wert |
| ------ | ---: |
| Total Notices in relevant.json | 301 |
| Unique tender_ids | 242 |
| Already English (heuristic, kein API-Call) | **91** |
| Übersetzt via Haiku 4.5 | **151** |
| Errors / Fehlschläge | **0** |
| Notices mit `title_en` nach Run | **301 / 301 ✓** |
| Estimated cost | **~$0.05** |

### Test-Case Verification

- **Spec-Vorgabe:** Czech tender mit Original
  `"Nákup přívěsných vozíků za OA"` soll
  `title_en = "Procurement of trailers..."` bekommen.
- **Tatsächlich:** `CZ-N006/26/V00010428` →
  `title_en = "Procurement of Trailers for the Armed Forces"` ✓

### 3 weitere Beispiel-Übersetzungen (zur Manual-Stichprobe)

| Tender | Original | title_en |
| ------ | -------- | -------- |
| `FR-21-163372` | `Fourniture de groupes de soudure sur remorque…` | `Supply of welding units on trailers for the benefit of the 25th Air Engineering Regiment (RGA) or the Air Operations Su…` |
| `FR-17-95354` | `fourniture de stations de lubrification et de graissage sur remorque…` | `Supply of lubrication and greasing stations on trailer and supply of welding units on trailer for the benefit of the 25…` |
| `CZ-N006/23/V00000559` | `DNS - Podvalníky 2024 - 2026` | `DNS - Heavy-duty Trailers 2024-2026` |

(Podvalníky = Tschechisch für „Tieflader/Heavy-duty trailers" — semantisch korrekt.)

### Architektur-Hinweise

- **Cache lebt eigenständig** — `enrichment_log.json` (Classifier) und
  `.award_match_log.json` (heuristischer Award-Matcher) und
  `.award_match_llm_log.json` (LLM-Award-Matcher) bleiben unangetastet.
- **Provenance:** Notices, deren Titel via Haiku übersetzt wurden, behalten
  ihren `_title_final` und `_title_english` unverändert. `title_en` ist rein
  additiv. Frontend zeigt `title_en`; Audit-Trail (Original) bleibt erhalten.
- **Demo-Override-Kompatibilität:** Frontend-`sync-shared.mjs` mergt
  Demo-Overrides nach dem Python-Export; berührt `title_en` nicht.

### Bekannte Limits

- Heuristik schickt korrekte englische Titel ohne Stop-Wort
  (z. B. `"Heavy Technical Trailer Capability - Industry Engagement"`) durch
  die API. Haiku gibt sie unverändert zurück, also kein Schaden — nur ~$0.0002
  pro Fall an unnötigen Kosten. Optional könnte man die Heuristik um eine
  ASCII-only-Quote-Schranke (z. B. ≥ 95 % ASCII **ohne** Sonderzeichen) verschärfen,
  ist aber kein Showstopper.
- `_FX`-Konstanten und `_PREFIX_SEP` (legacy) werden in `exporter_frontend.py`
  als „nicht zugegriffen" geflaggt — separater Cleanup-Sprint möglich.

---

## [Unreleased] — Pipeline-Hardening: Award + National Persistence (2026-05-08)

Behebt zwei wiederkehrende Datenverlust-Probleme nach `--phase filter`:

1. **Award-Status geht beim Rebuild verloren.** `--phase filter` überschreibt
   `relevant.json` vollständig und löscht alle `award`-Blöcke (heuristische +
   LLM-Matches). Beide Verlustquellen werden jetzt automatisch wiederhergestellt.

2. **Nationale Notices werden entfernt.** Nach Rebuild fehlen alle UK/FR/PL/…
   Notices aus dem letzten Run. `national_force_include.json` wurde zwar schon
   befüllt, aber inkonsistent (auch KI-unklassifizierte Nationals, keine
   alphabetische Sortierung).

### Neu: `scripts/_diagnose_awards.py`

Forensik-Skript: prüft aktuellen Awarded-Count (computed via
`exporter_frontend._resolve_status`), `award.awarded`-Block, LLM-Cache-Lücken,
und Winner-Name-Leaks. Schreibt Report nach
`docs/RUNS/award_diagnose_YYMMDD.md`.

```
python3 scripts/_diagnose_awards.py
```

### Neu: `src/award_matcher_llm.merge_cached_awards()`

Standalone-Funktion (keine API-Calls):

```python
def merge_cached_awards(relevant_path: str, confidence_min: int = 65) -> int
```

Liest `.award_match_llm_log.json`, filtert `applied=True AND match!=None AND
confidence>=confidence_min`, und schreibt fehlende `award`-Blöcke zurück in
`relevant.json`. Idempotent — überschreibt keine bereits gesetzten
`award.awarded`-Einträge. Gibt Anzahl neu eingefügter Einträge zurück.

### Geändert: `main.py`

**`_run_merge_cached_awards()` — neuer Helper** (kein API-Call):
- Ruft `merge_cached_awards(filtered_path, confidence_min=65)` auf
- Gibt diagnostische Meldung aus

**`--all`-Flow: neue Aufrufe nach Filter-Phase**

Beide Pfade (sequential + parallel) rufen nach `run_phase_filter(config)` jetzt
automatisch `_run_merge_cached_awards()` auf:

```
Filter → Award Cache Restore (gratis) → [UK/DE/PL/National merges] → Classify → ...
```

**`--all`-Flow: LLM Award Match nach heuristischem Award Match**

Nach `run_phase_award_match` wird jetzt immer
`run_phase_award_match_llm(confidence_min=65)` aufgerufen (Cache-only, keine
zusätzlichen API-Calls wenn Cache aktuell ist):

```
Award Match (heuristisch) → Award Match LLM (cache) → Enrich → Export
```

**`update_national_force_include()` — verbessert**:
- Filtert jetzt auf `_trailer_type_1_ai != None` — nur KI-klassifizierte
  Nationals werden in `national_force_include.json` persistiert
- Alphabetische Sortierung der Listen vor dem Schreiben (stable diffs)

### Nebenfix: `notice-type`-Patch in `relevant.json`

Der Backfill (Sprint 14b) hatte `notice-type` in die
`data/raw/details/*.json`-Dateien geschrieben, aber der Filter-Cache hatte die
alten `enriched`-Dicts ohne `notice-type`. Ein einmaliger In-Memory-Patch (keine
API-Calls) hat `notice-type`/`form-type`/`procedure-type` aus den Detail-JSONs
direkt in `relevant.json` nachgezogen.

Ergebnis: Computed Awarded stieg von 80 auf **135** (vs. 122 vor dem Run) —
55 weitere CAN-Notices werden jetzt korrekt per Tier-1b als "Awarded" erkannt.

### Exit-Kriterien erreicht

| Metrik | Vorher | Nachher |
|--------|--------|---------|
| Computed Awarded (relevant.json) | 80 | **135** |
| award.awarded == True | 68 | 68 |
| notice-type in relevant.json | 0 | **191** |
| LLM-Cache-Lücken (D2) | 0 | 0 |
| `--all`-Flow mit Award-Cache-Restore | nein | **ja** |
| `update_national_force_include` mit AI-Filter | nein | **ja** |

---

## [Unreleased] — Sprint 14a Follow-up: UA-Exporter-Fix (2026-05-08)

Behebt zwei Befunde aus dem Voll-Run am 2026-05-08 (siehe
`docs/RUNS/run_260508_pipeline.md` & `MAPPING_GAPS.md` §4):

1. **UA-Tender hat im Frontend-Export einen doppelten Country-Prefix.**
   Sprint 14c hat den Bug im `base_adapter.to_standard_format` gefixt,
   aber `relevant.json` enthält noch Pre-14c-Residuum
   (`tender_id="UA-UA-2026-04-08-011067-a"`). Der Exporter schreibt
   diese ID 1:1 nach `shared/tenders.json` und erzeugt damit
   `id="UA-UA-..."`.

2. **UAH→EUR-Konvertierung schlägt für den UA-Tender durch — aber aus
   Daten-, nicht Code-Gründen.** `_FX["UAH"] = 0.023` ist seit Sprint
   14a vorhanden, Pfad 3 (`_value_amount` + `_value_currency`) auch.
   Der konkrete Tender hat in `relevant.json` aktuell `_value_amount=None`
   und `_value_currency=None` — das Adapter-Daten-Problem wird durch
   den nächsten UA-Adapter-Re-Run gelöst, sobald
   `_extract_ua_value()` greift.

### Geändert: `src/exporter_frontend.py`

**Neu:** `_format_tender_id(tender_id, country_code)` — defensive
Normalisierung, Idempotent, drei Regeln:
1. TED-numerische IDs (`572650-2024`) bleiben unverändert.
2. Doppel-Prefix (`UA-UA-...`, `NL-NL-...`) wird auf einen Prefix
   reduziert.
3. National-IDs ohne Prefix (`2026-04-08-011067-a`) bekommen den
   Country-Code-Prefix prepended.

**Geändert:** `_map_notice()` — wendet `_format_tender_id` auf
`tender_id` an, bevor das `id`-Feld in den Frontend-Output geschrieben
wird.

`_FX["UAH"]` ist unverändert (war bereits korrekt seit Sprint 14a).

### Neu: `tests/test_exporter_frontend_id.py`

14 stdlib-`unittest`-Tests in drei Klassen:

- `FormatTenderIdTests` (7 Tests): UA/NL doppelter Prefix → einer,
  korrekt-bereits-präfigierte IDs idempotent, fehlender Prefix wird
  ergänzt, TED-IDs unverändert, leere Inputs safe, andere
  national-IDs (CZ-NEN, FR-BOAMP) unangetastet.
- `UahConversionTests` (5 Tests): UAH-Rate ist im `_FX`-Dict, Pfad 3
  konvertiert UAH korrekt zu EUR mit Toleranz ±10 k um den
  Spec-Zielwert ~478 400 (= 20,8 Mio UAH × 0,023), Newline-Edge-Case
  (`"UAH\\nUAH"`) wird über `.split("\\n")[0]` bereinigt, Pfad 2
  (TED-style `estimated_value` dict) auch UAH-fähig, leere Daten
  fallen sauber auf 0 zurück.
- `MapNoticeIdEndToEndTests` (2 Tests): doppelter Prefix in
  `relevant.json` führt zu sauberem `id`-Feld im Output;
  TED-numerische IDs bleiben durchgereicht.

### Verification

```
$ python3 -m unittest tests.test_exporter_frontend_id -v
Ran 14 tests in 0.000s
OK

$ python3 -c "from pathlib import Path; from src.exporter_frontend import export_tenders_for_frontend; \
  export_tenders_for_frontend(Path('data/filtered/relevant.json'), Path('/tmp/test_export.json'))"
INFO Frontend export: 301 tenders → /tmp/test_export.json

$ jq '.[] | select(.id | contains("011067")) | {id, estimated_value_eur, status, country_code}' /tmp/test_export.json
{
  "id": "UA-2026-04-08-011067-a",            # ← saubere Single-Prefix-ID ✓
  "estimated_value_eur": 0,                   # ← erwartet bei _value_amount=None
  "status": "Open",
  "country_code": "UA"
}

$ jq '[.[] | select(.id | startswith("UA-UA-") or startswith("NL-NL-"))] | length' /tmp/test_export.json
0   # keine Doppel-Prefix-IDs mehr
```

`shared/tenders.json` wurde **nicht** überschrieben — Window C macht
den finalen Export.

### Bekannte Limits / Nicht behoben in diesem Sprint

- UA-Tender hat weiterhin `estimated_value_eur=0`, weil `_value_amount`
  und `_value_currency` in der aktuellen `relevant.json` `None` sind.
  Nächster UA-Adapter-Re-Run via `--national ua` plus erneuter
  Pipeline-Run wird `_value_amount=20_800_000` und
  `_value_currency="UAH"` schreiben → Exporter konvertiert dann
  automatisch zu ~478 400 €.
- Demo-Override (`shared/overrides/tenders_overrides_demo.json`) zwingt
  ohnehin `estimated_value_eur=458000` für diesen Tender — Frontend
  zeigt also bereits einen Wert. Die Override-Mechanik im
  Frontend-`sync-shared.mjs` greift nach dem Python-Export, bleibt
  unverändert funktionsfähig.

---

## [Unreleased] — Sprint 14b Follow-up: notice-type Backfill (2026-05-07)

### TED API-Feld `notice-type` in Pipeline integriert

**Kontext:** Sprint 14b hatte `_resolve_status()` Tier 1b so implementiert, dass
`_raw["notice-type"]` und `_raw["form-type"]` ausgewertet werden. Das Feld fehlte
jedoch in `ALL_FIELDS` und damit in allen `_raw`-Dicts — Tier 1b zündete nie.

**Discovery:** TED API v3 unterstützt 1.830 Felder. Probe mit `224545-2026`:
- `notice-type: cn-standard` → Contract Notice (Ausschreibung)
- `notice-type: can-standard` → Contract Award Notice (Vergabe)
- `form-type: competition` / `result` als Sekundärsignal
- Weitere Werte: `corr`, `pin-only`, `pin-rtl`, `veat`

**Geändert: `src/api_client.py`**
- `ALL_FIELDS` um `notice-type`, `form-type`, `procedure-type` erweitert
- Ab dem nächsten `--phase index`-Lauf sind diese Felder automatisch in `_raw`

**Geändert: `src/exporter_frontend.py`**
- `_STATUS_CN_OPEN_DAYS_MAX = 180` (neu)
- Tier 1b: Bei `cn-standard`/`competition` ohne Deadline wird jetzt das
  Pub-Datum-Alter ausgewertet: ≤ 180 Tage → `"Open"` (statt Fall-Through zu
  Tier 3). Deckt typische 6-monatige Beschaffungszyklen ab.

**Neu: `scripts/_backfill_notice_type.py`**
- Einmaliges Backfill-Script für `notice-type`/`form-type`/`procedure-type`
  in `relevant.json` + `data/raw/details/*.json`; 195/197 gepatcht.

**Ergebnis nach Backfill (simuliert, Tier-1 only):**
| Status | Vor | Nach |
|--------|----:|-----:|
| Awarded (Tier 1a+1b) | 100 | **111** |
| Open (Tier 1b CN ≤180d) | 5 | **9** |
| Fall-through → Tier 3 | 92 | **77** |

**notice-type-Verteilung (197 TED-Notices):**
`can-standard`×99, `cn-standard`×74, `corr`×11, `pin-only`×5, `veat`×3,
`pin-rtl`×2, `pin-buyer`×1, `(missing)`×2

---

## [Unreleased] — Award-Match LLM Upgrade (Pipeline-Improvement Top-1, 2026-05-08)

Implementiert die Top-1-Empfehlung aus `docs/PIPELINE_IMPROVEMENTS.md` §5: ein
Sonnet-4.6-Reasoner als zweite Schicht über `award_matcher.py`, der für
Tender ohne Heuristik-Match prüft, ob eine bereits in `relevant.json`
vorhandene Award-Notice tatsächlich der zugehörige Vergabe-Eintrag ist.

### Neu

**Neu:** `src/award_matcher_llm.py` — `LLMAwardMatcher`-Klasse, additive
Schicht. Berührt den bestehenden heuristischen Matcher nicht.
- 3-stufige Pipeline: heuristische Kandidaten-Auswahl
  (`select_candidates`) → kompakter Prompt (`build_prompt`) →
  Sonnet-4.6-Reasoner (`call_llm`) → Anwendung des Awards
  (`_apply_award`).
- Kandidaten-Filter: gleicher Country (wenn beide gesetzt),
  Publication-Date ±365 Tage, Score aus Authority-Token-Overlap +
  Title-Token-Overlap (Noise-Tokens entfernt) + CPV-5-Stellen-Overlap.
  Top 5 nach Score gehen an das LLM.
- Strict-JSON-Output: `{match: <id>|null, confidence: 0–100,
  reasoning: <Satz>}`. Confidence-Threshold ≥ 75 für die Anwendung
  (CLI-überschreibbar via `--award-match-llm-confidence`).
- Provenance: applizierte Awards bekommen `_from_award_match_llm: true`,
  `_award_notice_id`, und `_match_confidence`. So bleibt der
  LLM-Pfad audittrennscharf vom Heuristik-Pfad
  (`_from_award_match: true`).
- Token-Tracking & USD-Cost-Tracking pro Run (`PRICE_INPUT_PER_M = 3.0`,
  `PRICE_OUTPUT_PER_M = 15.0`).

**Neu:** `data/.award_match_llm_log.json` — eigenständiger Cache. Pro
Tender wird die LLM-Entscheidung mit Kandidaten-Liste, Match,
Confidence, Reasoning, Apply-Flag, Modell-ID und Timestamp gespeichert.
Re-Runs hitten den Cache, machen also 0 API-Calls (verifiziert: 5
Sample-Tender → 0 Calls beim zweiten Aufruf).

**Neu:** `main.py` Flags
- `--award-match-llm` (off-by-default, manueller Trigger)
- `--award-match-llm-sample <id1,id2,…>` für Smoke-Tests
- `--award-match-llm-dry-run` (Kandidaten-Selection ohne API-Call)
- `--award-match-llm-confidence` (Default 75)

**Neu:** `run_phase_award_match_llm()` als Standalone-Phase. Schreibt
`data/filtered/relevant.json` mit den Apply-Flags zurück und gibt eine
Summary inkl. Top-10 angewendete Matches aus.

### Verification

```
$ python main.py --award-match-llm --award-match-llm-sample 572650-2024,...
  [LLM-match summary]
    targets evaluated:        5
    API calls:                5
    matched & applied:        1
    estimated cost (USD):     0.0211
  [Applied matches]
    572650-2024 → 326948-2025  [conf=92] …Military Medical Trailers Role 1 & 2…

$ python main.py --award-match-llm --award-match-llm-sample 572650-2024,...
  [LLM-match summary]
    cache hits: 5    API calls: 0    cost: 0.00   ← cache works
```

**Smoke-Test war 572650-2024 dabei? Ja.** Match-Ziel `326948-2025`
("Military Medical Trailers Role 1 & 2"), Confidence 92, applied →
`relevant.json[572650-2024].award.winner_name = "KITE Mezőgazdasági…"`,
Re-Export liefert `status="Awarded"` (vorher: `Closed`, fehlerhaft).

### Full-Run-Statistik (153 unmatched targets)

| Metrik                       | Wert |
| ---------------------------- | ---: |
| targets evaluated            | 153  |
| cache hits (von Smoke)       | 4    |
| API calls                    | 61   |
| no usable candidates         | 88   |
| matched & applied            | 19   |
| rejected (low confidence)    | 8    |
| no match found               | 34   |
| input tokens                 | 33 459 |
| output tokens                | 6 847 |
| **estimated cost (USD)**     | **$0.20** |

**Status-Verteilung (`shared/tenders.json` nach Re-Export):**

| Status     | Vor Sprint 14b | Nach Sprint 14b | Nach LLM-Upgrade |
| ---------- | -------------: | --------------: | ---------------: |
| Open       |              0 |               5 |               5 |
| Closed     |            156 |             149 |             129 |
| Awarded    |            100 |             102 |         **122** |
| Cancelled  |              0 |               0 |               0 |

**Neue Awarded-Tender vom LLM-Upgrade: +20** (19 frisch + 1 Smoke).
Erwartung laut Pipeline-Improvement Top-1: +28 bis +62. Wir liegen am
unteren Ende der Schätzung — das ist data-bound: 88/153 (≈58 %)
Targets sind nationale Phantome ohne Country-/Datum-Metadaten, die der
Heuristik-Pre-Filter aussortiert (UK-FTS-Phantome, EE-RP-Stub-Notices,
NO-DOFFIN-Phantome, …). Diese 88 würden erst nach Adapter-Fixes (wie
Sprint 14c UA) tatsächlich Kandidaten gegen reale Award-Notices
matchen.

**Top-5 neue Matches (Spot-Check-Empfehlung):**

| Closed Tender | → Award Notice | Conf | Begründung (LLM) |
| ------------- | -------------- | ---: | ---------------- |
| 678662-2024 | 30130-2025 | 97 | Identical title, same authority (armasuisse), same CPV codes, publication ~10 months apart |
| 493986-2024 | 254420-2025 | 97 | Identical subject (multifunctional engineer equipment + field lighting towers on trailers) |
| 299270-2019 | 18389-2020  | 97 | Identical title 'Bridge Transport Semi-trailers KB8', authority Försvarets materielverk |
| 129337-2017 | 510836-2017 | 97 | Identical subject (climate-controlled road trailers for pyrotechnic specimen temperature) |
| 416123-2016 | 98678-2017  | 97 | Identical title, CPV, buyer (Unitatea Militara 02574 / Ministerul Apararii) |

### Bekannte Limits

1. **88/153 Targets ohne Kandidaten:** Heuristik-Pre-Filter benötigt
   gleichen Country UND publication-date — viele national-force-included
   Phantome haben keine bzw. nur Stub-Daten. Adapter-Fixes (Sprint 14c
   UA-Stil) heben diesen Gap. Der LLM-Code selbst ist davon unbetroffen.
2. **Confidence-Threshold 75** ist konservativ. Die 8 rejected Matches
   liegen mehrheitlich bei 60–74 — ggf. lohnt ein manueller
   Spot-Check und Senken auf 65 nach Auswertung.
3. **`_pub_date_clean=2021-01-01` Phantome (FR-15…, FR-17…):** Date-Window
   matcht große Bandbreiten, weil die Phantom-Datumsangaben uniform
   1. Januar des Jahres sind. Hat in den Tests keine Falsch-Positives
   produziert (Cross-Authority-Filter zieht), bleibt aber zu beobachten.

---

## [Unreleased] — Sprint 14d: Türkei-Adapter (2026-05-08)

### Neu: TR-EKAP Adapter

**Neu:** `src/national_scraper/adapters/tr_adapter.py`
- `TrAdapter(BaseAdapter)` für das türkische EKAP-Portal (Kamu İhale Kurumu)
- Source code: `TR-EKAP`, Währung: `TRY`
- **Strategie:** Playwright-primär + XHR-Auto-Discovery
  - Lädt EKAP-Suchseite, befüllt Keyword-Feld, submitted Formular
  - Versucht XHR-Antwort zu capturen → REST-URL für Folge-Keywords cachen
  - HTML-Fallback via `_parse_html_results()` wenn kein XHR erfasst
- **13 türkische Defence-Keywords:** "römork", "yarı römork", "treyler",
  "tank taşıyıcı", "alçak yataklı", u.a.
- **18 Defence-Authority-Pattern:** MSB, Kara/Hava/Deniz Kuvvetleri,
  Jandarma, Sahil Güvenlik, Savunma Sanayii Başkanlığı u.a.
- `_parse_tr_date()`: DD.MM.YYYY → YYYY-MM-DD + ISO-Passthrough

**Neu:** `tests/test_tr_adapter.py` + `tests/fixtures/tr_sample.json`
- 6 Testklassen, vollständig offline (kein live EKAP-Zugriff)
- End-to-end: parse → filter_defence → get_detail (mock) → to_standard_format

**Geändert:** `main.py`
- `get_adapter_registry()`: TR-Eintrag hinzugefügt (22. Adapter)
- `run_national_scraping()`: try/import-Block für TR-EKAP

**Geändert:** `src/national_scraper/base_adapter.py`
- `_default_currency()`: `"TR": "TRY"` ergänzt

**Geändert:** `data/adapter_status.json`
- Neuer Eintrag `"tr"`: Status `implementing`, Limitierungen dokumentiert

**Bekannte Limitierungen (Sprint 14d):**
- EKAP-HTML-Selektoren nicht via Live-Test bestätigt; Screenshots in
  `data/raw/screenshots/` nach erstem echten Run prüfen
- XHR-Endpoint-URL nicht vorab bekannt; Adapter discovert ihn automatisch
- MSB Tedarik (tedarik.msb.gov.tr) nicht abgedeckt → geplant als Sprint 15

---

## [Unreleased] — Sprint 14a + 14b (Value/Currency + Status Mapping, 2026-05-07)

Beide Sprints betreffen `src/exporter_frontend.py` und werden zusammen
ausgeliefert.

### Sprint 14a — Value/Currency

**Geändert:** `src/exporter_frontend.py:_resolve_value_eur()`
- **Pfad 3 ergänzt** — flache Felder `_value_amount` + `_value_currency`,
  die nationale Adapter via `BaseAdapter.to_standard_format` schreiben.
  Bisher hat der Exporter ausschließlich `_value_eur_num` und
  `estimated_value.{amount,currency}` gelesen, sodass alle Notices, die
  ihren Wert über das flache Feldpaar liefern, im Frontend als 0 €
  ankamen.
- **Currency-Newline-Bereinigung verifiziert** — Path 2 sanitiert
  `'NOK\nNOK'` / `'BGN\nBGN'` weiterhin via `.split("\n")[0].strip().upper()`.
  Path 3 macht dasselbe.
- **`_FX`** enthält bereits `UAH = 0.023` (Stand 2026-05). Kein Patch
  nötig.
- **Unknown-Currency-Warning** — neuer Helper `_warn_unknown_currency()`
  loggt jeden unbekannten Code einmal pro Run statt bei jedem Treffer.
  Damit fallen neue Currencies in künftigen Adapter-Runs sofort auf,
  ohne den Log zu fluten.

### Sprint 14b — Status Mapping (4 Stati inkl. Cancelled)

**Geändert:** `src/exporter_frontend.py:_resolve_status()` — komplettes
Refactor als 3-Tier-Waterfall (siehe Docstring). Ergänzt um
`_pub_date()` und `_deadline_date()` Helper sowie Token-Listen.

- **TIER 1 — Hard Signals**
  - 1a) `_winner_name` ODER `award.awarded` ODER `award.winner_name`
        → `Awarded`.
  - 1b) `_raw.notice-type` / `_raw.form-type` Keyword-Match
        in dieser Reihenfolge: `cancel` / `withdraw` → `Cancelled`,
        `modification` / `corrigendum` → `Closed`,
        `award` / `result` / `can` → `Awarded`,
        `contract notice` / `call for tenders` / `competition` / `cn`
        → `Open`-Kandidat (über Deadline bestätigt).
- **TIER 2 — Adapter-Status** — `_status` ∈ {Open, Closed, Awarded,
  Cancelled} wird übernommen.
- **TIER 3 — Pub-Date-Heuristik** mit Default-Schwellen aus der
  Sprint-Spec (Audit-Daten von Window 1 lagen beim Implementieren noch
  nicht vor): pub_date < 90 Tage **und** keine Deadline → `Open`,
  Deadline in der Zukunft → `Open`, pub_date > 365 Tage → `Closed`,
  Mittelband → `Closed`. Konstanten `_STATUS_OPEN_DAYS_MAX` /
  `_STATUS_CLOSED_DAYS_MIN` lassen sich später aus
  `docs/STATUS_AUDIT.md` nachkalibrieren, ohne die Logik zu berühren.

**Geändert:** `shared/schema/tender.schema.json`
- `status.enum` erweitert um `"Cancelled"`. Frontend-Side
  (`defence-intel-web/lib/types.ts` Tender-Union, Status-Badge-Styles
  in `tender-columns.tsx`) muss in einem separaten Sprint nachgezogen
  werden, sobald Cancelled-Tender in den Daten auftauchen.

**Demo-Override-Kompatibilität**
- `shared/overrides/tenders_overrides_demo.json` wird vom Frontend
  (`defence-intel-web/scripts/sync-shared.mjs`, Zeilen 69–98) per
  `{...tender, ...patch}` Merge angewendet — **nicht** vom
  Python-Exporter. Mein Refactor berührt diesen Pfad nicht; der Override
  greift nach dem Export weiterhin korrekt.
- Die zwei Override-Targets `UA-UA-2026-04-08-011067-a` und
  `224545-2026` werden ausserdem schon durch Tier 3 als `Open`
  klassifiziert (pub_date 29 / 36 Tage alt, kein Winner, keine
  Deadline). Override ist damit für die Demo redundant aber unverändert
  funktionsfähig.

### Verification

```
$ python -m src.exporter_frontend
INFO Frontend export: 256 tenders → /Users/.../shared/tenders.json
[OK] Wrote 256 tenders → /Users/.../shared/tenders.json

$ python3 shared/scripts/validate.py shared/tenders.json
Result : 256/256 OK  |  0 error(s)
```

**Status-Verteilung**

| Status     | Vorher | Nachher |
| ---------- | -----: | ------: |
| Open       |      0 |       5 |
| Closed     |    156 |     149 |
| Awarded    |    100 |     102 |
| Cancelled  |      0 |       0 |
| **Total**  |    256 |     256 |

**Zero-Value-Verteilung**

| Metrik              | Vorher | Nachher |
| ------------------- | -----: | ------: |
| `estimated_value_eur=0` | 124   |    124  |

Der Wert ändert sich nicht, weil die aktuelle `relevant.json` keine
`_value_amount`/`_value_currency`-Felder enthält — Path 3 ist
Vorbereitung für den Re-Run nach den Adapter-Fixes aus Window 3
(Sprint 14c). Beim ersten Re-Run nach `Sprint 14c` wird
`UA-UA-2026-04-08-011067-a` automatisch ~478 400 € (= 20 800 000 UAH ×
0,023) liefern, ohne dass der Exporter erneut angefasst werden muss.

**Status-Flips bei den 5 Stichproben aus MAPPING_GAPS § 6**

| Tender-ID | Vorher | Nachher | Quelle |
| --------- | ------ | ------- | ------ |
| `224545-2026` | Closed | **Open** ✓ | Tier 3 (pub-date 36 d, kein Winner, keine Deadline) |
| `182178-2026` | Closed | **Awarded** ✓ | Tier 1a (`award.awarded=true`, winner `AUTOMECANICA MEDIAS`) |
| `572650-2024` | Closed | Closed ✗ | Daten-Lücke: keine Award-Daten in `relevant.json` (Award-Match-Phase nicht gelaufen) |
| `147849-2021` | Awarded | Awarded ✓ | Tier 2 (`_status=Awarded` aus Pipeline) |
| `665246-2021` | Awarded | Awarded ✓ | Tier 2 |

**Bekannte Limits in den aktuellen Daten**
1. `_raw.notice-type` / `_raw.form-type` ist in allen 256 Notices leer
   (Pipeline schreibt diese Felder nicht). Tier 1b zündet damit auf den
   bestehenden Daten nie. Erst nach Pipeline-Update zur Extraktion
   dieser TED-API-Felder werden CN-Notices automatisch als `Open`
   erkannt — ohne weitere Code-Änderungen am Exporter.
2. `STATUS_AUDIT.md` von Window 1 lag beim Implementieren noch nicht
   vor; Tier-3-Schwellen sind die Defaults aus der Spec
   (`_STATUS_OPEN_DAYS_MAX=90`, `_STATUS_CLOSED_DAYS_MIN=365`). Beim
   Eintreffen des Audits können die zwei Konstanten ohne weiteres
   Refactoring nachjustiert werden.
3. Cancelled-Count ist 0, weil die `cancel` / `withdraw` Tokens nur in
   `_raw.notice-type` / `form-type` greifen (siehe Limit 1).

---

## [Unreleased] — Sprint 14c (UA-Prozorro Bugfixes, 2026-05-07)

### Fixed
- **`src/national_scraper/base_adapter.py`** — `to_standard_format` doppelte Country-
  Prefixe (`UA-UA-2026-...`, `NL-NL-577684`). Wenn `detail.reference_id` bereits mit
  `<country_code>-` beginnt, wird der Prefix nicht erneut angefügt. Wirkt für alle
  Adapter (UA und ggf. NL profitieren am sichtbarsten; Adapter mit reinen IDs sind
  unverändert).
- **`src/national_scraper/adapters/ua_adapter.py`** — neue Helper-Funktion
  `_extract_ua_value()` mit Fallback-Kette für Prozorro:
  `detail.value.amount` → `lots[*].value.amount` (erstes positives Lot) →
  `detail.minimalStep.amount`. Ersetzt die zwei vorherigen Inline-Extraktionen in
  `search_all_keywords` und `get_detail`. Test-Tender `UA-2026-04-08-011067-a`
  liefert nun `_value_amount=20_800_000` `UAH` statt `None`.
- **Datums-Pfad bestätigt** — `get_detail` nutzt
  `(data.get("datePublished") or result.date or "")[:10]`; `result.date` hat selbst
  bereits `(item.get("datePublished") or item.get("dateModified") or "")[:10]` als
  Fallback. `_pub_date_clean` wird damit zuverlässig gesetzt — kein Fix, nur Doku.

### Added
- **`tests/test_ua_adapter.py`** + **`tests/fixtures/ua_011067a.json`** —
  Fixture-basierte Smoke-Tests (stdlib `unittest`, kein `pytest`-Dep): 9 Tests grün.
  Deckt `_extract_ua_value`-Kette, ID-Dedup für leere/reine/präfixierte IDs und
  einen Ende-zu-Ende-Lauf durch `get_detail` → `to_standard_format`.

### Verification
```
$ python3 -m unittest tests.test_ua_adapter -v
Ran 9 tests in 0.002s
OK
```
Re-Run/Re-Export wurde bewusst NICHT durchgeführt, um den parallelen
`exporter_frontend`-Output (Window 2) nicht zu überschreiben.

---

## [Unreleased] — Mapping Gap Audit 2026-05-04

### Added
- **`docs/MAPPING_GAPS.md`**: Full value-gap and adapter audit covering all 8 sources.
  - Per-source table: TED 34% gap, UK-CF 17%, all national adapters 100% gap
  - Root cause: `_value_amount`/`_value_currency` fields (national adapters) not read by `exporter_frontend.py`
  - Currency newline bug: `NOK\nNOK` / `BGN\nBGN` → FX lookup fails (2 TED notices, €21M lost)
  - Status gap: `_status=None` → "Closed" for 166 notices; TED CN-type → should be "Open"
  - UA spot-check: `UA-UA-2026-04-08-011067-a` — 20.8M UAH on portal but `estimated_value=null`; ID-doubling bug
  - Sprint backlog: 6 prioritised fix sprints (Sprint 14a–16)

### Pipeline Run
- `--all --since 2026-04-04 --uk --national ... --two-stage --no-review` (6m 30s)
- 256 notices (was 252; +4 new TED: Italy/Finland/Czech/Italy 2018–2024)
- 30-day count: 1 (unchanged — TED has no new trailer-relevant notices Apr-May 2026)
- validate.py: 256/256 OK
- Playwright Chromium installed on macOS for next run

## [Unreleased] — Frontend Exporter

### Added
- **`src/exporter_frontend.py`**: New additive exporter module.
  - Function `export_tenders_for_frontend(relevant_path, output_path) -> int` reads
    `data/filtered/relevant.json` and writes `shared/tenders.json` in the
    defence-intel-web Tender schema.
  - Defensive source mapping: all 252 current `_source = "?"` notices are correctly
    resolved via `tender_id` regex (`\d+-\d{4}` → TED, else National).
  - Country resolution: `_country_normalized` → `contracting_authority.country`
    (handles ISO3, ISO2, and full names like "Italy", "Czechia") → `_raw.organisation-country-buyer`.
  - EUR conversion from `estimated_value.amount` with fixed FX rates when
    `_value_eur_num` is absent.
  - OEM overrides: silently merges `shared/overrides/tenders_overrides.json` if present.
  - Standalone: `python -m src.exporter_frontend` (no pipeline required).
- **`main.py --export-frontend`**: New CLI flag. Runs after `--phase export` or `--all`,
  writes to `../../shared/tenders.json`. Creates `shared/` if absent.
- **`docs/CLI.md`**: Documented `--export-frontend` flag and standalone workflow.

- **Title prefix cleanup** (`strip_country_prefix()`): removes TED-prepended country
  name from tender titles (`"Sweden - Aircraft Maintenance Trailers..."` →
  `"Aircraft Maintenance Trailers..."`). Handles `<Country> - `, `<Country> Defence - `,
  and `<Country> Ministry of Defence - ` variants, en-dash included. Safety net:
  keeps original if stripped result < 8 characters. Applied to 50/252 titles.

### Validation
- `252/252 OK` against `shared/schema/tender.schema.json` (JSON Schema 2020-12)
- No `"?"` in `source` or `country_code` fields in output

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

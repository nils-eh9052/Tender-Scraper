# Strategy A — Proactive Vergabeunterlagen Scraping (DE/PL/CZ)

**Datum:** 2026-05-18
**Sprint:** Window E
**Status:** Implementiert, Smoke-Test gegen 9 Tender ausgeführt.

---

## 1. Was ist Strategy A?

Strategy B (TED-XML-Vollauswertung) hat die Foreign-Keys zu den
nationalen Buyer-Portalen geliefert: `buyer_profile_url`,
`tender_documents_access`, `internal_reference`. Strategy A folgt diesen
Links **proaktiv** und scrapt die **echten Vergabeunterlagen-PDFs**
(Leistungsverzeichnis / SWZ / Zadávací dokumentace) — die 50–200 Seiten
Spec-Tiefe, die kein API liefert.

Trigger ist **rein opt-in** via `--strategy-a`. Nicht in `--all`, weil
Live-Portal-Scraping fragiler und langsamer ist als die Standard-3g-Pipeline.

---

## 2. Architektur

```
                ┌─────────────────────────┐
   --strategy-a │   main.run_phase_       │
   ─────────────▶  strategy_a()           │
                └────────────┬────────────┘
                             │
                ┌────────────▼─────────────────┐
                │ document_pipeline/strategy_a │
                │   run_strategy_a()           │
                └────────────┬─────────────────┘
                             │
              for each notice:
                             │
                ┌────────────▼─────────────────┐
                │ discovery._discover_strategy_a│
                │  ├─ _strategy_a_inputs       │
                │  │   ├─ _raw._xml            │
                │  │   └─ ted_xml_cache/{id}.xml│
                │  └─ dispatch by country      │
                └────────────┬─────────────────┘
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
┌──────▼───────┐    ┌────────▼────────┐    ┌──────▼────────┐
│ DE: fallback/│    │ PL: fallback/   │    │ CZ: fallback/ │
│  de_search   │    │  pl_search      │    │  cz_search    │
│ fetch_       │    │ fetch_swz_      │    │ fetch_lv_     │
│ vergabe-     │    │ documents()     │    │ documents()   │
│ unterlagen() │    └────────┬────────┘    └──────┬────────┘
└──────┬───────┘             │                    │
       │                     │                    │
       └─────────────────────┴────────────────────┘
                             │
                ┌────────────▼─────────────────┐
                │ List[DocumentRef]            │
                │  doc_type="vergabeunterlagen"│
                └────────────┬─────────────────┘
                             │
                       downloader + extractor
                             │
                       structure_with_ai
                             │
                   notice._strategy_a_specs
                             │
                  data/.strategy_a_cache.json
```

---

## 3. Pro-Country-Architektur

### 3.1 DE — evergabe-online.de + service.bund.de

**Input:** `tender_documents_access` (Deeplink mit `?id=<n>`) oder
`buyer_profile_url`.

**Strategie (in dieser Reihenfolge):**

1. Wenn URL `evergabe-online.de/tenderdetails.html?id=<n>` enthält:
   Detail-Page via static GET (kein JS, server-rendered HTML).
   Folge-Page `tenderdocuments.html?id=<n>` für Document-Bundle.
2. Parsen aller `href`-Patterns für `.pdf`, `.docx`, `.xlsx` plus
   `/Download`-, `/tenderDocuments`-, `/downloadDocument/`-Routes.
3. Fallback: `service.bund.de`-Volltext-Suche per `internal_reference`
   oder Buyer + Title-Keywords.

**Bekannte Limits:**
- Die echten Vergabeunterlagen-PDFs (LV mit Spec-Tiefe) erfordern oft
  einen **registrierten evergabe-User**. Anonym sind nur Notice-Metadaten
  + manchmal Lieferpläne abrufbar.
- evergabe serviert PDFs hinter Wrapper-HTML-Seiten; HEAD-Check ist OK,
  aber `pdfplumber` lehnt das HTML ab (`No /Root object`).
- `service.bund.de` rendert keine direkten Download-Links auf der
  Suche-Page — nur Detail-Links.

### 3.2 PL — ezamowienia.gov.pl + platformazakupowa.pl + portalsmartpzp.pl

**Input:** `buyer_profile_url` (z. B. `https://platformazakupowa.pl/pn/12wog`)
und optional `internal_reference` (z. B. `D/08/12WOG/2025`).

**Strategie:**

1. **ezamowienia.gov.pl** `Board/Search`-API mit `OrganizationName`
   (Buyer-Code-zu-Name-Mapping in `_BUYER_CODE_TO_ORG`).
2. Best-match-Notice per `_match_notice` (ref ⊆ noticeNumber/orderObject
   bzw. Title-Keyword-Overlap).
3. Versuch drei Attachment-Endpunkte: `GetAttachmentList`,
   `GetNoticeAttachments`, `GetDocuments` (in Praxis aktuell alle 404).
4. **Fallback:** `GetNoticeHtmlBodyById` liefert den vollen Notice-Body
   (3–15 kB HTML, in plain-text gestrippt). Surface als
   `format="txt"` DocumentRef mit Inline-Text.
5. **platformazakupowa.pl**: statischer GET der Buyer-Profile-Page →
   Regex für `.pdf/.docx/.zip`-Hrefs. SPA, daher in der Praxis
   meist 0 direkte PDF-Links.
6. **portalsmartpzp.pl**: analog statischer GET + Regex.

**Bekannte Limits:**
- `platformazakupowa.pl` ist eine React-SPA; ohne Playwright keine
  Tender-Liste ladbar. Buyer-Profile-Page enthält nur Branding/Suchformular.
- ezamowienia hat (Stand 2026-05) keinen öffentlichen Attachments-Endpoint;
  Fallback auf den HTML-Body liefert 3–15 kB strukturierten Notice-Text,
  reicht für AI-Strukturierung von Quantity/Description.

### 3.3 CZ — verejnezakazky.vop.cz + nen.nipez.cz

**Input:** `buyer_profile_url` (`https://verejnezakazky.vop.cz/vz<NNNNN>`
oder `https://nen.nipez.cz/profil/<CODE>`).

**Strategie:**

1. **VOP** (`verejnezakazky.vop.cz/vz<N>`): direkter GET (server-rendered
   HTML). Regex `.pdf/.docx/(soubor|priloha|prilohy|attachment|download)`-Hrefs.
2. **NEN-Profile** (`/profil/MO`, `/profil/UVCR`, …): SSR-HTML der
   Buyer-Page. `_parse_nen_table` extrahiert Tender-Rows mit
   `sys_num` und Detail-URL. Best-Title-Match → Detail-Page-Fetch
   (`/en/verejne-zakazky/detail-zakazky/<sys-num>`).
3. NEN-Suche per `internal_reference` oder Title-Keyword.
4. **Generic CZ-Portal**: best-effort statischer GET + Regex für
   `.pdf/.docx/.zip` über andere `*.gov.cz`/`*.vz`-Domains.

**Bekannte Limits:**
- VOP serviert PDFs über `document_download_NNN.html`-Wrapper. HEAD-Check
  ist 200, Body ist aber HTML mit JS-getriggertem Download. `pdfplumber`
  wirft `No /Root object`. Workaround: registered VOP-Login oder
  Playwright mit Click-Wait.
- NEN-Detail-Seiten haben einige PDFs **hinter CZ-POINT/eIDAS-SSO**.
  Strategie A markiert solche Refs mit `extra.auth_risk="eidas"` und
  skipped sie graceful bei HEAD-401/403. **CZ eIDAS-Cert-Lösung explizit
  out-of-scope** (Window F).
- Manche Sub-Portale (`zakazky.eagri.cz`, ältere VVZ-Mirror-Seiten) sind
  noch nicht abgedeckt — fallen in den `_scrape_generic_cz`-Pfad.

---

## 4. Trigger-Logik (`_discover_strategy_a`)

Aktiviert wenn:
- `country` in {`DE`, `PL`, `CZ`} (resolved via `organisation-country-buyer`
  oder URL-Heuristik)
- mindestens eines von `buyer_profile_url` / `tender_documents_access`
  vorhanden

Quelle der Inputs (in dieser Reihenfolge):
1. `notice._raw._xml.{buyer_profile_url_full, tender_documents_access,
   internal_reference}` — nach `scripts/_backfill_ted_xml.py`-Run vorhanden.
2. `data/ted_xml_cache/{tender_id}.xml` — Roh-XML-Cache (immer da, wenn
   die Index-Phase je gelaufen ist).

Internal-Reference-Heuristik filtert eForms-Template-Placeholder
(`ORG-`, `RES-`, `TEN-`, `LOT-`, `TPO-`, …) raus und akzeptiert nur
strukturierte Buyer-Codes mit Slash/Underscore/Punkt.

---

## 5. Caching

| Cache | Key | Inhalt |
|-------|-----|--------|
| `data/.strategy_a_cache.json` | `{tender_id}:{model_slug}` | `{specs: {…}, source_url: "…"}` — getrennt vom 3g-Cache |
| `data/.national_fallback_cache.json` | `{tender_id}:{country}` | B2-Fallback-Cache (unverändert) |
| `data/.document_extraction_cache.json` | `{tender_id}:{model_slug}` | Phase-3g-Cache (unverändert) |

`--strategy-a-force` umgeht den Strategy-A-Cache, lässt aber andere
Caches in Ruhe.

---

## 6. CLI-Interface

```bash
# Smoke-Test gegen 3 Tender, kein LLM-Cost
python main.py --strategy-a \
    --strategy-a-sample 798124-2025,261427-2025,212474-2026 \
    --strategy-a-dry-run

# Vollausführung (begrenzt auf 5 Tender via --test):
python main.py --strategy-a --test

# Re-Run bypasst Cache:
python main.py --strategy-a --strategy-a-force
```

Discover-only Smoke-Test (kein Download, kein LLM):

```bash
SSL_VERIFY_DISABLE=1 python scripts/_smoke_strategy_a.py
```

---

## 7. Smoke-Test 2026-05-18 — 9 Tender (3 je Land)

**Tender-Sample:**

| Country | Tender-ID | Buyer-Portal-URL |
|---------|-----------|------------------|
| DE | `212474-2026` | `evergabe-online.de/tenderdetails.html?id=771723` |
| DE | `719142-2025` | `evergabe-online.de/tenderdetails.html?id=771723` |
| DE | `682847-2024` | *(no XML-cache URL — pre-eForms)* |
| PL | `261427-2025` | `platformazakupowa.pl/pn/12wog` |
| PL | `432811-2024` | `portalsmartpzp.pl/12wog` |
| PL | `736943-2024` | `platformazakupowa.pl/pn/witu` |
| CZ | `798124-2025` | `verejnezakazky.vop.cz/vz00002751` |
| CZ | `465260-2025` | `verejnezakazky.vop.cz/vz00002665` |
| CZ | `467088-2025` | `nen.nipez.cz/profil/MO` |

**Ergebnis (Dry-Run, ohne LLM-Kosten):**

| Stage | DE | PL | CZ | Total |
|-------|---:|---:|---:|-----:|
| Candidates | 3 | 3 | 3 | 9 |
| Triggered | 2 | 3 | 3 | 8 |
| Docs discovered | 16 | 3 | 14 | 33 |
| Docs HEAD-alive | ~8 | 3 | ~5 | 16 |
| Docs downloaded | 6 | 0 | 7 | 13 |
| Text extracted (>200 chars) | 0 | 3 | 0 | 3 |
| Auth-blocked (eIDAS) | 0 | 0 | 1 | 1 |

**Mit AI-Strukturierung (extrapoliert):** 3 Tender (alle PL) würden
`_strategy_a_specs` bekommen.

---

## 8. Bekannte Limits & Workarounds pro Country

| Land | Limit | Workaround / Nächster Schritt |
|------|-------|-------------------------------|
| **DE** | evergabe-online liefert HTML-Wrapper statt direkter PDF-Bytes; echte LV-PDFs hinter Login | Playwright + registrierter Account (Sprint W-F+) |
| **DE** | service.bund.de Detail-Seiten haben selten direkte PDF-Links | OK so — Detail-HTML als Text-DocumentRef wäre möglich (heute nicht aktiv) |
| **PL** | platformazakupowa.pl ist React-SPA — statischer GET liefert leere Liste | Playwright (out-of-scope) oder ezamowienia-API-Path (aktiv, klappt) |
| **PL** | ezamowienia hat keinen public Attachments-Endpoint | HTML-Notice-Body als Fallback aktiv — liefert 3–15 kB strukturierte Notice-Inhalte |
| **CZ** | VOP-PDFs über `document_download_NNN.html` JS-Wrapper | Playwright mit Click-Wait nötig (out-of-scope) |
| **CZ** | NEN-Detail-Seiten teilweise hinter CZ-POINT/eIDAS-SSO | Graceful skip via `auth_risk="eidas"` marker. **eIDAS-Cert-Lösung explizit Window F**, nicht hier. |

---

## 9. Was Strategy A NICHT macht

- Keine Playwright-Browser-Automation (würde DE/CZ Login-Pages + JS-PDFs
  durchklicken können — Sprint W-F+).
- Keine eIDAS-Authentifizierung für CZ-PDFs.
- Kein Lese-Update auf `shared/tenders.json` Schema — `_strategy_a_specs`
  bleibt als internes Feld in `relevant.json`. Wenn das Frontend die
  Strategy-A-Specs zeigen soll, muss `exporter_frontend.py` ein neues
  Mapping ergänzen (z. B. `extracted_specs.strategy_a`).
- Keine Konkurrenz zur Phase-3g-Pipeline: Strategy A schreibt in
  `_strategy_a_specs`, Phase 3g schreibt in `_extracted_specs`. Beide
  Felder können koexistieren.

---

## 10. Dateien

| Datei | Änderung |
|-------|----------|
| `src/national_scraper/fallback/de_search.py` | + `fetch_vergabeunterlagen()`, `_tag_vergabeunterlagen()` |
| `src/national_scraper/fallback/pl_search.py` | + `fetch_swz_documents()`, `_fetch_ezamowienia_attachments()`, `_scrape_platformazakupowa()`, `_scrape_smartpzp()`, `_fmt_from_ext()` |
| `src/national_scraper/fallback/cz_search.py` | + `fetch_lv_documents()`, `_tag_strategy_a()`, `_scrape_generic_cz()` |
| `src/document_pipeline/discovery.py` | + `_discover_strategy_a()`, `_strategy_a_inputs()`, `_xml_inputs_from_cache()`, `_strategy_a_keywords()` |
| `src/document_pipeline/strategy_a.py` | **neu** — Runner mit eigener Cache-Datei |
| `main.py` | + `run_phase_strategy_a()`, CLI-Flags `--strategy-a*` |
| `scripts/_smoke_strategy_a.py` | **neu** — discover-only Smoke-Test (kein Download/LLM) |
| `data/.strategy_a_cache.json` | **neu** — Strategy-A-Result-Cache |

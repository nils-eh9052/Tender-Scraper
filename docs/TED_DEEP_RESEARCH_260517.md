# TED API + XML — Deep Research

**Datum:** 2026-05-17
**Update-Stempel:** Quick-Wins implementiert 2026-05-18
— `framework-agreement-lot`, `contract-conclusion-date`,
`organisation-name-buyer`, `organisation-identifier-buyer` jetzt in
`ALL_FIELDS` (src/api_client.py), gemappt in detail_fetcher und
exporter_frontend, Backfill via `scripts/_backfill_ted_quick_wins.py` auf
183 TED-Tender ausgeführt. Coverage 2023+ eForms-Ära ≈ 76–82 %, pre-2023
0 % (erwartet — TED_EXPORT-Schema). Siehe `CHANGELOG.md` Eintrag
"TED Quick-Wins" für vollständige Coverage-Tabelle und Contract-Type-Promotion.

**Scope:** Read-only Investigation. Was liefert die TED v3 API + XML
darüber hinaus, was wir aktuell ausschöpfen? Welche Notice-Types,
welche Felder, welche Endpoint-Pfade?

**Probes:** 4 echte API-Calls für Field-Discovery, 6 sample-Notices für
Wert-Mining, 200 XML-Files für Related-Notice-Inspektion,
35 138 raw/details für Notice-Type-Distribution.

**Sprint-Status zum Vergleich:**
- `ALL_FIELDS` enthält 38 Felder (`src/api_client.py`)
- `ted_xml_fetcher.py` extrahiert 5 XML-only Felder
  (`internal_reference`, `tender_documents_access`,
  `buyer_profile_url_full`, `contract_folder_id`, `notice_uuid`)
- 337 Tender in der aktuellen `relevant.json`, 194 davon TED

---

## 1. Notice-Type-Audit

### 1.1 Distribution im aktuellen Raw-Cache

Stichprobe: alle 35 138 JSONs unter `data/raw/details/`. Sprint-14b hat
notice-type nur für neue Runs nachgezogen; ältere Notices haben das Feld
nicht (Pipeline-Schwäche, kein TED-Limit).

| Notice-Type | Form-Type | Count | Strategische Rolle |
| ----------- | --------- | ----: | ------------------ |
| `(empty / pre-Sprint-14b)` | — | 34 937 | unbekannt — Backfill nötig |
| `can-standard` | `result` | **102** | Award-Bekanntmachung — Winner-Daten |
| `cn-standard` | `competition` | **76** | Aktive Ausschreibung — primäres Signal |
| `corr` | `change` | 11 | Korrektur eines vorhandenen Notice |
| `pin-only` | `planning` | **5** | **Vorab-Ankündigung (Lead-Time 3–12 Mo!)** |
| `veat` | `dir-awa-pre` | 3 | Voluntary Ex-Ante (Direktvergabe-Begründung) |
| `pin-rtl` | `planning` | 2 | PIN für „Reduced Time Limit"-Procedure |
| `can-modif` | `cont-modif` | 1 | Vertragsänderung NACH Award (Value-Drift!) |
| `pin-buyer` | `planning` | 1 | PIN als Buyer-Profile-Eröffnung |

### 1.2 Befund pro Type

- **`pin-only` (Prior Information Notice — Planning)**: Tatsächlich
  publiziert TED diese 3–12 Monate **vor** dem CN. BPW könnte aus 5
  PINs in der aktuellen Datenbasis Vorab-Pipeline-Signale generieren —
  z. B. „Ungarn plant 2026 eine Trailer-Beschaffung". Unsere
  Filter-Phase findet PINs bereits (5 Stück), aber der **Frontend-
  Exporter zeigt sie wie normale Tender** ohne Differenzierung.
- **`can-modif` (Contract Modification)**: Nur 1 Stück gefunden. Diese
  Notices ändern den Wert oder die Laufzeit eines bereits vergebenen
  Vertrags. **Value-Drift** ist ein direkt für Pipeline-Analyse
  relevantes Signal. Aktuell ignorieren wir das komplett.
- **`veat` (Voluntary Ex Ante Transparency)**: 3 Stück. Diese sind
  Direktvergaben mit Begründung — meist defence-relevant. Werden
  aktuell wie reguläre Notices behandelt, aber das `procedure-
  justification`-Feld (war im Probe valide, hatte aber leere Werte im
  Sample) sollte ausgewertet werden.
- **`corr` (Corrigendum)**: 11 Stück, oft kleine Fristanpassungen.
  Aktuell überschreiben sie uU die Originaldaten — wäre besser sie nur
  zur Frist-Aktualisierung zu nutzen, nicht als eigenständigen Tender.

---

## 2. Field-Mining gegen TED v3 search-API

### 2.1 Methodik

`scripts/_probe_ted_fields_v3.py` testet 164 Kandidaten-Feldnamen
(38 aus `ALL_FIELDS` + 126 generiert aus eForms-SDK + Intuition) via
Binary-Search-Halbierung gegen 2 reale Notices. Die API lehnt
unbekannte Felder mit HTTP 400 ab, daher wird die Kandidatenliste
rekursiv halbiert bis Single-Field-Validität ermittelt ist. Danach
werden die validierten Namen über 6 sample-Notices gepullt.

### 2.2 18 neue valide Felder beyond `ALL_FIELDS`

| Feld | Coverage (6 Probes) | Wert / Beispiel | ROI-Bewertung |
| ---- | ------------------: | --------------- | ------------- |
| **`framework-agreement-lot`** | **6/6 (100 %)** | `["fa-wo-rc"]` = frame agreement without reopening of competition | **Hoch** — mapped direkt auf unser `contract_type`-Feld |
| **`organisation-name-buyer`** | **6/6 (100 %)** | Multilingual dict mit voller Buyer-Namen | **Hoch** — ersetzt buyer-name mit reichhaltigerer Struktur |
| **`organisation-identifier-buyer`** | **6/6 (100 %)** | `["991-19518-88"]` (DE-Registriernummer) | **Mittel** — Foreign-key für Cross-Reference |
| **`buyer-legal-type`** | 5/6 (83 %) | `["cga"]` = central government authority | Mittel — Filter-Signal für Defence vs Non-Defence |
| **`submission-language`** | 5/6 (83 %) | `["DEU"]` | Mittel — Hint für Übersetzungs-Bedarf |
| **`reserved-procurement-lot`** | 5/6 (83 %) | `["none"]` (keiner unserer Trailer ist reserviert) | Niedrig — defence-trailer-Kontext |
| **`strategic-procurement-lot`** | 3/6 (50 %) | `["none"]` | Niedrig — kaum positive Werte in Defence |
| **`contract-conclusion-date`** | 1/6 (17 %) | `["2025-04-16+02:00"]` | **Hoch** — echtes Award-Datum (≠ Publikations-Datum des CAN) |
| **`subcontracting`** | 1/6 (17 %) | `["no"]` | Niedrig (oft "no" in Defence) |
| **`change-description`** | 1/6 | Multilingual prose zur Modifikation | **Hoch für can-modif** — was wurde geändert |
| **`change-reason-description`** | 1/6 | `{"deu": "Vorläufige Anpassung des Angebotsschlusstermins"}` | Hoch für corr/modif |
| `additional-information` | 0/6 | — | (validiert, aber keine Werte im Sample) |
| `concession-revenue-buyer` | 0/6 | — | (Concession-Notice spezifisch — nicht relevant für Defence) |
| `concession-revenue-user` | 0/6 | — | (dito) |
| `procedure-justification` | 0/6 | — | (validiert, hoch relevant für VEAT) |
| `subcontracting-description` | 0/6 | — | (validiert, in CAN-modif öfter populiert) |
| `subcontracting-percentage` | 0/6 | — | (validiert, kennt Mengenanteil) |
| `subcontracting-value` | 0/6 | — | (validiert, in EUR) |

### 2.3 Field-Namen die NICHT von der TED-API akzeptiert wurden

108 von 126 Kandidaten gaben 400 zurück. Wichtige Negativ-Ergebnisse:

```
tender-documents-access      ← XML-only (haben wir bereits)
buyer-profile-url            ← XML-only
internal-reference           ← XML-only (haben wir bereits)
green-procurement / innovation-procurement / social-procurement
   → API kennt nur strategic-procurement-lot als single-field
award-criterion-type/name/weight  → keiner valide
tenders-received / tenders-received-electronic  → keiner valide
contract-conclusion-date-lot → nur die "-date"-Variante ist valide
buyer-internet-address-part / buyer-name-part → API ignoriert -part-Suffix
previous-publication-number / related-notice → XML-only
```

**Wichtigste Konsequenz:** Award-Criteria + Bidder-Counts (sehr
wertvoll für Market-Intelligence) sind über die TED-search-API **nicht**
abrufbar. Die XML enthält sie via `AwardCriterion` und
`StatisticsNumeric` — separater XML-Parser-Sprint nötig, falls gewünscht.

---

## 3. Related-Notice-Linking

### 3.1 ChangedNoticeIdentifier in XML

Inspektion von 194 gecachten TED-XMLs (`data/ted_xml_cache/`): **10 Notices
(5,2 %)** enthalten eine `<ChangedNoticeIdentifier>`-Verlinkung zur
Vorgänger-Notice.

Zwei Format-Varianten beobachtet:

```
Format 1 — eForms-UUID-suffix (CN → CAN linkage):
  926e7185-91e4-4b2f-be1c-fd23afd36fa9-01

Format 2 — Klassische publication-number (corr → original):
  306273-2024
```

### 3.2 Beispiele

| Notice | ChangedNoticeIdentifier | Interpretation |
| ------ | ----------------------- | -------------- |
| `798124-2025` | `772125-2025` | CN-standard, korrigiert `772125-2025` |
| `385446-2024` | `305853-2024` | CN, korrigiert ein älteres CN |
| `386007-2024` | `306273-2024` | CN, korrigiert ein älteres CN |
| `212474-2026` | `926e7185-…-01` | CN, referenziert eForms-UUID (PIN-Vorgänger?) |
| `813306-2025` | `2b926ac6-…-01` | CN-standard, UUID-Linkage |
| `537199-2024` | `1c850758-…-01` | CAN-standard, UUID-Linkage (CN-Vorgänger) |
| `719142-2025` | `a592ab9c-…-01` | CN-standard, UUID-Linkage |

### 3.3 Strategischer Wert

- **Backward-Lookup (CAN → CN)**: lässt uns für jeden Awarded-Tender
  den ursprünglichen Call-for-Tenders identifizieren. Daraus ergeben
  sich Antworten auf „wie lange dauert eine Defence-Beschaffung von
  Veröffentlichung bis Vergabe" → wertvoll für STATUS_AUDIT
  Tier-3-Heuristik (aktuell Default 90/365 Tage; echte Daten würden
  diese kalibrieren).
- **Forward-Lookup (CN → CAN)**: PIN → CN → CAN-Pipeline. Heute ahnen
  wir das nur über Heuristik (`award_matcher.py` + LLM-Matcher).
  Mit direkter Linkage könnten wir Award-Match-Confidence von 80 % auf
  100 % heben **und** Bidder-Pipeline-Analysen ohne LLM-Reasoning machen.
- **Modification-Tracking**: `can-modif` referenziert das ursprüngliche
  CAN. Daraus ergibt sich Value-Drift (Vertrags-Wert-Anpassung über
  Zeit). Aktuell ignoriert.

### 3.4 Implementation-Skizze

```python
# In src/ted_xml_fetcher.py:_parse_eforms()
linked = _find_path(root, "ChangedNoticeIdentifier")
if linked:
    out["changed_notice_identifier"] = linked  # raw value

# In src/exporter_frontend.py:_map_notice()
if isinstance(raw_blob.get("_xml"), dict):
    cni = raw_blob["_xml"].get("changed_notice_identifier")
    if cni:
        out["related_notice_id"] = cni
        # If short-form (publication-number), no resolution needed
        # If UUID-with-suffix, look up by notice-identifier in raw_blob

# Optional: post-process to build a graph of CN → CAN, PIN → CN.
# Persisted in data/notice_graph.json.
```

**Aufwand:** ~4 h für XML-Extraktion + Exporter-Mapping + Graph-Aufbau.
Erwarteter Daten-Gewinn: **~10 % der 194 TED-Tender bekommen einen
expliziten Vorgänger-Link.**

---

## 4. eForms-spezifische Felder

### 4.1 Was die TED-search-API exposed

| Feld | Coverage | Sample-Wert |
| ---- | -------: | ----------- |
| `strategic-procurement-lot` | 3/6 | `["none"]` |
| `reserved-procurement-lot` | 5/6 | `["none"]` |
| `framework-agreement-lot` | 6/6 | `["fa-wo-rc"]`, `["fa-mix"]`, `["none"]` |
| `procedure-features` | 1/6 (via API) | Multilingual prose |

### 4.2 Codes — was bedeuten die `["none"]`-Werte?

Aus dem eForms SDK Codeliste:
- `strategic-procurement-lot` mit Wert `["none"]` → kein Green/Social/
  Innovation/Defence-bezogener Anspruch markiert
- `reserved-procurement-lot` mit Wert `["none"]` → kein Vorbehalt
  (z. B. für KMU / Sheltered-Workshops)
- `framework-agreement-lot`:
  - `"fa-wo-rc"` = frame agreement without reopening of competition (single sourcing)
  - `"fa-w-rc"` = frame agreement WITH reopening of competition
  - `"fa-mix"` = mixed regime
  - `"none"` = no framework agreement (one-time procurement)

**Befund:** Praktisch alle 6 Probes liefern `["none"]` für Strategic/
Reserved. Das ist erwartbar — Defence-Trailer-Beschaffungen markieren
selten Strategic-Procurement-Flags. Niedriger Mehrwert für unseren
spezifischen Marktfokus.

`framework-agreement-lot` ist hingegen ein Direkt-Mapping-Kandidat für
unser bestehendes `contract_type`-Feld (heute via Regex aus
Beschreibung gewonnen, anfällig).

---

## 5. Endpoint-Inventory (TED v3)

### 5.1 Geprüfte Endpoints

| Endpoint | Status | Auth nötig? | Anonyme Nutzung? |
| -------- | ------ | ----------- | ---------------- |
| `/v3/notices/search` | 200 | nein | **Ja (unsere primäre Quelle)** |
| `/v3/notices/{id}` | 400 | **ja** (Authorization-Header) | nein |
| `/v3/notices/{id}/zip` | 400 | **ja** | nein |
| `/v3/notices/changes` | 400 | **ja** | nein |
| `/v3/codelists/*` | 404 | (nicht existent) | — |
| TED-XML: `https://ted.europa.eu/{lang}/notice/{id}/xml` | 200 | **nein** | **Ja (XML-fetcher)** |

### 5.2 Daily Data Service (TED Open Data / TED Daily)

Anonymer Tagesfeed unter
`https://op.europa.eu/de/web/eu-vocabularies/ted/dataset/...` — täglich
ZIPs mit allen am Vortag publizierten Notices als XML. Würde unseren
Pipeline-Run von 1 req/s (~5 min für ~300 neue Notices) auf einen
einzigen ZIP-Download (~30 MB) reduzieren.

**Implementation-Aufwand:** ~6 h (ZIP-Downloader, daily cron, XML-
Diff gegen `notice_ids` in `.checkpoint.json`, neue Notices ins
raw/details ablegen).

**Trade-off:** Lohnt sich nur, wenn wir **deutlich häufiger** als
1× pro Woche scrapen. Aktueller Sprint-Zyklus 1×/Sprint kommt mit
Search-API gut zurecht.

### 5.3 OAuth-Hürde

Authentication beschränkt sich auf reseller-Lizenzen (TED-Subscription).
**Kosten:** typisch EUR 2.000-5.000/Jahr Enterprise-Subscription.
Schaltet die Endpoints `/notices/{id}/zip` (komplettes eForms-Paket
inkl. XSL-Renderings, technische Schemata) und `/notices/changes`
(Delta-Sync) frei. Für BPW wahrscheinlich nicht der Aufwand wert.

---

## 6. Top-5 Empfehlungen mit Aufwand und ROI

### Empfehlung 1 ⭐ — `framework-agreement-lot` in `ALL_FIELDS` aufnehmen

**Aktuell:** `contract_type` wird via Regex aus Description extrahiert
(`src/contract_type.py`), anfällig für Translator-Ungenauigkeiten und
Sprachvarianten.

**Fix:** Feld in `ALL_FIELDS` + Mapping im Exporter
(`contract_type = "framework_agreement"` wenn Code in
`fa-wo-rc/fa-w-rc/fa-mix`, sonst `"one_time"`).

**Aufwand:** 1 h (Field-Add, Mapping, Backfill).
**Erwarteter Daten-Gewinn:** 194 Tender bekommen einen
struktur-gestützten `contract_type` statt regex-basiert (100 %
Coverage in eForms-Notices). Regex bleibt als Fallback für ältere
TED_EXPORT-Notices.

### Empfehlung 2 ⭐ — Related-Notice-Graph aufbauen

**Aktuell:** PIN → CN → CAN ist nur via LLM-Award-Match (≥75 % conf)
bekannt. Modifications (`can-modif`) und Corrigenda (`corr`) werden
ignoriert.

**Fix:** `ChangedNoticeIdentifier` in XML-Parser + Exporter durchreichen,
plus ein einmaliger Graph-Build-Skript:

```python
# scripts/_build_notice_graph.py
# Reads raw/details + relevant.json, builds notice_graph.json:
# {
#   "<notice_id>": {
#     "previous": ["<id>"],     # what this notice changes/replaces
#     "next":     ["<id>"],     # back-references (computed)
#     "type":     "cn-standard",
#     "form":     "competition"
#   }
# }
```

**Aufwand:** 4-6 h.
**Erwarteter Daten-Gewinn:**
- ~10 % der TED-Tender bekommen einen Vorgänger-Link
- Award-Match-Confidence steigt deutlich (von „ähnlicher Title" auf
  „exakte UUID-Verbindung")
- Modification-Tracking als Bonus-Feature

### Empfehlung 3 — PIN-Notices als eigene Frontend-Kategorie

**Aktuell:** 5 PIN-Notices (planning/pin-only/pin-rtl) im Pool, werden
wie reguläre Tender angezeigt. Status fällt fast immer auf "Closed"
zurück, weil die Heuristik PIN als „kein Winner ⇒ Closed" einstuft.

**Fix:** Status-Logik in `exporter_frontend.py` erweitern:
- `form-type in {planning, pin-only}` → neuer Status `"Planned"`
  (Schema-Enum erweitern)
- Frontend zeigt Planned-Tender mit eigenem Badge („Vorab-Signal,
  Vergabe in 3-12 Mo erwartet")

**Aufwand:** 3 h (Status-Logik, Schema-Patch, Badge im Frontend).
**Erwarteter Daten-Gewinn:** 5 von 337 Tender (1,5 %) bekommen
Vorab-Signal-Status. Wert wird mit zunehmendem Backfill alter Notices
wachsen.

### Empfehlung 4 — `organisation-name-buyer` + `organisation-identifier-buyer`

**Aktuell:** Buyer-Name als single string aus `buyer-name`. Manchmal
ist die Sprache zufällig (z. B. nur cz-Variante). Buyer-Identifier
fehlt komplett.

**Fix:** Beide Felder in `ALL_FIELDS` aufnehmen, Exporter zieht
Englisch (oder Default), schreibt `buyer_id` als neues optionales
Feld in `tenders.json`.

**Aufwand:** 1 h.
**Erwarteter Daten-Gewinn:** 100 % Coverage für TED-Tender. Buyer-
Identifier ermöglicht zukünftiges Buyer-Profile-Aggregation
(„welche Beschaffungen kommen aus BAAINBw insgesamt").

### Empfehlung 5 — `contract-conclusion-date` für genaues Award-Datum

**Aktuell:** Award-Datum kommt aus `winner-decision-date`. Beim
Probe-Test war `contract-conclusion-date` zusätzlich populiert
(`261427-2025: 2025-04-16`) — präziseres Datum.

**Fix:** Feld in `ALL_FIELDS`. Exporter zieht es als
`award_date_iso` ins Frontend, mit Fallback auf
`winner-decision-date`.

**Aufwand:** 30 min.
**Erwarteter Daten-Gewinn:** Award-Datum von 60 % auf ~90 %
Coverage. Sprint-14b STATUS_AUDIT-Heuristik kann dadurch von Default
auf empirisch abgeleitete Werte (Median CN→Vergabe-Spanne) umgestellt
werden.

---

## 7. NICHT empfohlen / Out-of-scope

- **OAuth-Subscription** für `/v3/notices/{id}/zip` etc. — Kosten von
  EUR 2.000-5.000/Jahr stehen für 337 Tender in keinem Verhältnis.
- **Strategic-Procurement-Mapping** — Defence-Trailer-Notices markieren
  diese Flags fast nie als „yes". 0 % Mehrwert auf unserem aktuellen Pool.
- **Subcontracting-Felder** in `ALL_FIELDS` — Defence-Trailer-Notices
  haben praktisch immer `["no"]`. Wenn ausgeschöpft: erst nach CAN-
  Backfill prüfen, ob die Sample-Distribution sich ändert.
- **Bidder-List / Tenders-Received** — von API nicht exposed,
  XML-only. Mehrwert hoch, aber separater XML-Parser-Sprint nötig.
- **TED Daily Data Service ZIP-Downloads** — lohnt sich erst bei
  täglichen Runs (wir haben sprint-basierte Runs).

---

## 8. Empfohlene Sprint-Reihenfolge

| # | Sprint-Item | Aufwand | Priorität |
| - | ----------- | ------- | --------- |
| 1 | `framework-agreement-lot` + `contract-conclusion-date` + `organisation-*-buyer` zur ALL_FIELDS + Backfill | 3 h | **Hoch** — direkter Frontend-Gewinn, niedrigster Aufwand |
| 2 | Related-Notice-Graph aufbauen (`ChangedNoticeIdentifier` XML-Parser) | 4-6 h | **Hoch** — Award-Match-Genauigkeit + Vergleichszahlen für STATUS_AUDIT |
| 3 | PIN-Notice-Status `"Planned"` im Frontend separat ausweisen | 3 h | Mittel — Pool ist heute klein (5), wächst mit Re-Indexing |
| 4 | Optional: XML-Parser für `AwardCriterion` + `StatisticsNumeric` (Tenders-Received) | 1 Tag | Niedrig — Mehrwert bei Bidder-Analyse, aber XML-Komplexität |

---

## 9. 5-Punkt-Summary

**1. Top-3 ungenutzte TED-Felder mit höchstem ROI:**
- `framework-agreement-lot` (100 % Coverage, ersetzt unsichere Regex)
- `contract-conclusion-date` (echtes Award-Datum, kalibriert STATUS_AUDIT)
- `organisation-name-buyer` + `organisation-identifier-buyer`
  (struktur-gestützter Buyer-Bezug, 100 % Coverage)

**2. Lohnt sich PIN-Notice-Type-Erweiterung?**
Ja — aktuell 5 PINs im Pool, sie werden wie normale Notices behandelt
und landen fälschlich im `Closed`-Bucket. Status-Logik um `"Planned"`
erweitern lohnt sich (3 h Aufwand, Frontend-UX-Gewinn). Wert wächst
mit Re-Indexing der 34 937 pre-Sprint-14b-Notices.

**3. Related-Notice-Linking: Implementation-Komplexität:**
Mittel (4-6 h). `ChangedNoticeIdentifier` in 10 / 194 cached XMLs
gefunden. XML-Parser bereits da (`ted_xml_fetcher.py`), nur 1 Feld
ergänzen + Graph-Build-Skript schreiben. Award-Match-Confidence
steigt von „Title-Ähnlichkeit" auf „UUID-Verbindung" — sehr hoher ROI
gegen 4-6 h Aufwand.

**4. Top-3 eForms-Felder die wir ignorieren:**
- `framework-agreement-lot` (siehe oben)
- `procedure-justification` (validiert, leer im Sample — wertvoll bei
  VEAT-Notices)
- `change-description` / `change-reason-description` (wertvoll bei
  `can-modif` und `corr` — heute überschreiben Korrekturen die
  Original-Daten unbemerkt)

**5. Empfohlene Reihenfolge der nächsten 3 Sprint-Items:**
1. **Sprint A** (3 h): `framework-agreement-lot` + `contract-
   conclusion-date` + `organisation-*-buyer` zu `ALL_FIELDS`, plus
   Backfill der 194 TED-Tender — direkter, billiger, messbarer Gewinn
2. **Sprint B** (4-6 h): Related-Notice-Graph + ChangedNoticeIdentifier
   im XML-Parser
3. **Sprint C** (3 h): PIN-Notice-Status `"Planned"` im Frontend

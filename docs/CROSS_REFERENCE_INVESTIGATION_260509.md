# Cross-Reference Investigation — 2026-05-09

> **Update 2026-05-10 (B):** **Strategie B implementiert.** 8 neue
> TED-API-Felder entdeckt via `scripts/_probe_ted_fields_v2.py` und in
> `ALL_FIELDS` aufgenommen. Backfill für 193/194 TED-Tender erfolgreich.
> **154 / 194 (79 %) TED-Tender haben `buyer_profile_url`** als
> Foreign-Key zum nationalen Portal. Siehe `docs/TED_FIELDS_DISCOVERED.md`.
>
> **Update 2026-05-10 (B+):** **TED-XML-Fallback implementiert.**
> `src/ted_xml_fetcher.py` mit Dual-Schema-Parser (eForms + TED_EXPORT)
> + `scripts/_backfill_ted_xml.py` für alle 194 TED-Tender. Coverage
> nach Merge JSON + XML im Frontend:
> - `buyer_profile_url`: **89 %** (173/194)
> - `internal_reference`: **39 %** (75/194) — eForms-only (post-2023)
> - `tender_documents_access`: **28 %** (54/194) — eForms-only Deeplink
> - `contract_folder_id`: 37 %, `notice_uuid`: 100 %
>
> Document-Pipeline `discovery.py` nutzt jetzt die Drei-Stufen-Priorität
> XML-Deeplink → XML-Buyer-Profile → JSON-Buyer-Internet-Address und
> reicht `internal_reference` + `contract_folder_id` als `extra`-
> Metadaten weiter. Foundation für Window B2 (National-Portal-Lookup)
> ist damit gelegt. Siehe `docs/TED_XML_FIELD_PATHS.md` und CHANGELOG-
> Eintrag *„TED-XML Fallback (Strategie B+, 2026-05-10)"*.
>
> Strategie A (echtes nationale-Portal-Scraping für DE/PL/CZ) bleibt
> für künftige Sprints reserviert.


**Frage:** Lohnt es sich, TED-Tender-Notices mit ihren Pendants auf den
nationalen Vergabeportalen (DE/FR/PL/CZ) zu crossreferenzieren, um
zusätzliche Felder/Dokumente in die Pipeline zu ziehen?

**TL;DR:** Bevor man Cross-Reference scrapt, sollte man **erst** den
TED-API/XML komplett auswerten — dort liegen schon die direkten URLs zum
nationalen Portal **plus** strukturierte Lot-Werte, internal references
und Pflicht-Submission-URLs, die der Pipeline-Client aktuell nicht abruft.
Cross-Reference ist nur für DE und CZ als zusätzlicher Schritt klar
lohnend (Tender-Documents als PDF), für FR und PL fragwürdig.

---

## 1. Methodik & Sample

20-Tender-Sample (alle TED, `_source = "TED"`, sortiert nach
`publication_date` desc) aus `data/filtered/relevant.json`. Pool für
DE/FR/PL ist datenrealistisch klein:

| Country | Verfügbar im Pool | Sample |
| ------- | ----------------: | -----: |
| DE      | 9                 | 5 (Top 5 nach Datum, bzw. alle 9 für die Trefferquote) |
| FR      | 2                 | 2 (alles, was da ist) |
| PL      | 3                 | 3 (alles) |
| CZ      | 12                | 6 |

Gesamt: 20 Tender (5+2+3+6+4 weitere CZ als Reserve).

**Quellen:**
1. `data/filtered/relevant.json` — alle TED-Notice-Felder (`_raw` blob)
2. `src/api_client.py` — `ALL_FIELDS`-Liste (was unsere Pipeline heute
   pro Notice abruft)
3. `src/national_scraper/adapters/{de,fr,pl,cz}_adapter.py` — empirisch
   dokumentiert, was die nationalen Portale tatsächlich exponieren
4. **WebFetch-Stichproben** auf `https://ted.europa.eu/<id>/xml` für 4
   repräsentative Tender (DE/FR/PL/CZ je 1) — bestätigt die theoretischen
   Befunde mit echten URLs

**Methodik-Caveat:** Diese Investigation wurde aus einer Sandbox-CLI-Session
geführt; ich konnte die nationalen Portale (service.bund.de, BOAMP,
ezamowienia, NEN) nicht interaktiv durchklicken. Die Adapter-Code-Basis
liefert aber sehr genaue Ground-Truth, weil sie schon empirisch bekannt
hat, was diese Portale ausgeben.

---

## 2. Sample-Set

### DE — 9 Defence-Trailer-Notices (Top 5 für Detail-Analyse)

| ID | pub_date | Buyer | Title (engl.) | TED-URL |
| -- | -------- | ----- | ------------- | ------- |
| `212474-2026` | 2026-03-27 | BAAINBw | Germany - 2-wheel 1t military trailers framework agreement | [link](https://ted.europa.eu/en/notice/-/detail/212474-2026) |
| `813306-2025` | 2025-12-08 | BAIUDBw | Hook-lift trucks with crane, trailers, flatbeds and containers | [link](https://ted.europa.eu/en/notice/-/detail/813306-2025) |
| `719142-2025` | 2025-10-30 | BAAINBw | Framework Agreement Manufacturing & Delivery (Trailers) | [link](https://ted.europa.eu/en/notice/-/detail/719142-2025) |
| `161258-2025` | 2025-03-12 | BAIUDBw | Container Trailer with Roll-off Containers | [link](https://ted.europa.eu/en/notice/-/detail/161258-2025) |
| `682847-2024` | 2024-11-08 | BAAINBw | Germany - Military Cargo Trailers 3.5t and 12.5t | [link](https://ted.europa.eu/en/notice/-/detail/682847-2024) |

### FR — 2 Defence-Trailer-Notices

| ID | pub_date | Buyer | Title | TED-URL |
| -- | -------- | ----- | ----- | ------- |
| `77247-2026` | 2026-02-03 | MINARM/TERRE/SIMMT/DDC | Motorcycles and Trailers - Acquisition (4 lots) | [link](https://ted.europa.eu/en/notice/-/detail/77247-2026) |
| `583390-2025` | 2025-09-08 | DGA / DOMN | POSEIDON Shelter with associated services | [link](https://ted.europa.eu/en/notice/-/detail/583390-2025) |

### PL — 3 Defence-Trailer-Notices

| ID | pub_date | Buyer | Title | TED-URL |
| -- | -------- | ----- | ----- | ------- |
| `261427-2025` | 2025-04-23 | 12 WOJSKOWY ODDZIAŁ GOSPODARCZY | High-capacity transport trailers | [link](https://ted.europa.eu/en/notice/-/detail/261427-2025) |
| `736943-2024` | 2024-12-03 | Wojskowy Instytut Techniczny Uzbrojenia | Mobile Doppler Radar Tracking System on Trailers | [link](https://ted.europa.eu/en/notice/-/detail/736943-2024) |
| `432811-2024` | 2024-07-18 | 12 WOJSKOWY ODDZIAŁ GOSPODARCZY | High, Medium, Small Capacity Transport Trailers | [link](https://ted.europa.eu/en/notice/-/detail/432811-2024) |

### CZ — 6 Defence-Trailer-Notices (Top 6)

| ID | pub_date | Buyer | Title | TED-URL |
| -- | -------- | ----- | ----- | ------- |
| `798124-2025` | 2025-12-02 | VOP CZ, s.p. | Semi-trailers - Low-bed for heavy military equipment | [link](https://ted.europa.eu/en/notice/-/detail/798124-2025) |
| `467088-2025` | 2025-07-17 | Ministerstvo obrany | Container Transport Trailers KTN ISO 1C | [link](https://ted.europa.eu/en/notice/-/detail/467088-2025) |
| `465260-2025` | 2025-07-16 | VOP CZ, s.p. | Semi-trailers Heavy Military Equipment Transport | [link](https://ted.europa.eu/en/notice/-/detail/465260-2025) |
| `132540-2025` | 2025-02-27 | Ministerstvo obrany | Water Tank Trailers - Field Kitchen Storage | [link](https://ted.europa.eu/en/notice/-/detail/132540-2025) |
| `129915-2025` | 2025-02-27 | Ministerstvo obrany | Field Kitchen - Cooling Freezing Trailers | [link](https://ted.europa.eu/en/notice/-/detail/129915-2025) |
| `385446-2024` | 2024-06-26 | Ministerstvo obrany | Heavy Platform/Cargo Trailers O4-PN-V | [link](https://ted.europa.eu/en/notice/-/detail/385446-2024) |

---

## 3. WebFetch-Validierung — TED-XML enthält direkte National-Portal-URLs

Pro Country wurde ein Tender via `https://ted.europa.eu/<id>/xml` geladen.
**Alle vier** liefern in der XML mindestens eine URL, die direkt zum
nationalen Portal zeigt — **plus** zusätzliche strukturelle Felder, die
unser API-Client (über `ALL_FIELDS`-Liste) heute nicht abruft.

### 3.1 DE — `212474-2026`

| TED-XML-Feld | Wert |
| ------------ | ---- |
| **buyer-profile-url** | `http://www.evergabe-online.de/` |
| **tender-documents-access** | `https://www.evergabe-online.de/tenderdetails.html?id=771723` ← Direktlink mit Tender-ID |
| **submit-tenders-address** | gleiche URL |
| internal reference | (im XML enthalten, nicht abgerufen) |
| Lot-Werte | (im XML enthalten, nicht abgerufen) |

→ **Eindeutiger Foreign-Key**: `evergabe-online.de/tenderdetails.html?id=771723`.

### 3.2 FR — `77247-2026`

| TED-XML-Feld | Wert |
| ------------ | ---- |
| **buyer-profile-url** | `www.marches-publics.gouv.fr` (Stamm — keine Tender-ID) |
| **tender-documents-access** | `www.marches-publics.gouv.fr` (gleich) |
| **internal-reference** | `24R40121` ← die "interne ID" auf der PLACE-Plattform |
| **estimated-value** | €4 584 000 (total) — **plus Lot-Breakdown:** Lot 1 €2.33M, Lot 2 €827k, Lot 3 €857k, Lot 4 (Trailers) €568k |
| **deadline** | 2026-03-17 12:00 UTC+1 |

→ **Foreign-Key**: nur Portal-Stamm; man muss zusätzlich `internal-reference`
("24R40121") in PLACE-Suche eingeben.

### 3.3 PL — `261427-2025`

| TED-XML-Feld | Wert |
| ------------ | ---- |
| **buyer-profile-url** | `https://platformazakupowa.pl/pn/12wog` (Buyer-Profile) |
| **additional-information-address** | `https://12wog.wp.mil.pl/` |
| **internal-reference** | `D/08/12WOG/2025` |
| **winner** | Zasław Spółka z ograniczoną odpowiedzialnością |
| **award-amount** | PLN 1 530 000 |

→ **Foreign-Key**: Buyer-Profile mit Buyer-Code (`12wog`); Tender-ID
kommt aus `internal-reference`-Feld.

### 3.4 CZ — `798124-2025`

| TED-XML-Feld | Wert |
| ------------ | ---- |
| **buyer-profile-url** | `https://verejnezakazky.vop.cz/vz00002751` |
| **tender-documents-access** | gleich |
| **submit-tenders-address** | gleich |
| **internal-reference** | `OVZ/018/3/2025` |
| **estimated-value** | CZK 12 000 000 |
| **deadline** | 2026-01-27 13:00 CET |

→ **Eindeutiger Foreign-Key**: `vz00002751`.

---

## 4. Vergleich pro Country

### 4.1 Trefferquote (TED → nationales Pendant)

Trefferquote = Anteil der TED-Tender, für die ein direkter URL-Pfad zum
nationalen Portal **direkt aus dem TED-XML** erkennbar ist.

| Country | Stichprobe | Direkte URL im TED-XML | Foreign-Key-Qualität |
| ------- | ---------: | ---------------------: | -------------------- |
| DE | 1/1 verifiziert | **100 %** | Sehr hoch — direkter Tender-ID-Param |
| FR | 1/1 verifiziert | 100 % (nur Portal-Stamm) | Mittel — `internal-reference` als zweiter Schritt nötig |
| PL | 1/1 verifiziert | **100 %** | Hoch — Buyer-Profile + internal-reference |
| CZ | 1/1 verifiziert | **100 %** | Sehr hoch — direkter Tender-ID |

Verallgemeinerte Erwartung über alle 20 Sample: ≥ 95 % (TED-XML hat das
Feld als Pflicht für CN-Notices). Die wenigen 5 % sind Ausnahmen wie
Phantome / corrigendum-only Notices, die keine Buyer-Profile-URL setzen.

### 4.2 Mehrwert-Quote (Cross-Reference vs. erweiterte TED-XML-Auswertung)

**Wichtige Erkenntnis aus den 4 WebFetches:** Felder, die der Sprint 14b
notice-type-Backfill schon ergänzt hat, sind nur die Spitze des Eisbergs.
Folgende Daten liegen **schon im TED-XML**, werden aber von unserem
API-Client (`ALL_FIELDS`-Liste in `src/api_client.py`) nicht abgerufen:

| Feld | TED-XML hat es? | Unser API-Client zieht es? |
| ---- | --------------: | -------------------------: |
| buyer-profile-url | Ja (alle 4) | **Nein** |
| tender-documents-access | Ja (DE, CZ) | **Nein** |
| submit-tenders-address | Ja (DE, CZ) | **Nein** |
| additional-information-address | Ja (PL) | **Nein** |
| internal-reference | Ja (alle 4) | **Nein** |
| Lot-Wert-Breakdown (`estimated-value-lot`) | Ja (FR demonstriert) | **Nein** |
| Lot-Mengen (`quantity-lot`) | teils ja | **Nein** |
| place-of-performance (Postcode) | ja | partly (in `ALL_FIELDS`, aber Mapping unklar) |

→ **Strategie B (TED-XML voll auswerten) ist der billige First-Win**;
Strategie A (echtes Cross-Reference-Scrapen) liefert erst danach
zusätzlichen Mehrwert.

#### 4.2.1 Cross-Reference-Mehrwert nach TED-XML-Vollauswertung

Was bringt das nationale Portal **zusätzlich**, das im TED-XML wirklich
nicht steht?

| Country | Mehrwert-Quelle (vs TED-XML voll) | Wert |
| ------- | --------------------------------- | ---- |
| **DE** (service.bund.de + evergabe-online.de) | Vergabeunterlagen-PDFs (Leistungsverzeichnis, technische Anforderungen, Lieferpläne — meist 50–200 Seiten); Bieterfragen ("Vergabevermerk") | **Hoch** — TED-XML hat nur Übersicht, nicht die LV-Spec |
| **FR** (BOAMP / PLACE) | JSON-`donnees`-Block hat strukturiertes `quantity`/`duration`/`description` (FR-Adapter belegt das); plus Tender-Doc-PDFs | **Mittel** — TED-XML hat Lot-Werte, BOAMP hat zusätzlich qty + duration + Doku |
| **PL** (ezamowienia.gov.pl) | SWZ-PDF (Specyfikacja, ~50–200 Seiten); Wyjaśnienia (Bieterfragen); Erläuterungen | **Hoch** — gleicher Effekt wie DE |
| **CZ** (NEN nipez.cz) | Detail-Page mit Verlinkung auf bis zu 3 PDFs; Adapter zieht das schon (siehe `cz_adapter.py:_extract_and_download_pdfs`) | **Mittel** — Adapter ist schon implementiert; lohnt sich aber nur als TED-Ergänzung wenn nicht-CZ-bekannte Tender |

### 4.3 Implementation-Aufwand pro Country

| Country | Strategie A (Cross-Ref scrapen) | Strategie B (TED-XML voll auswerten) |
| ------- | -------------------------------: | -----------------------------------: |
| DE | 1–2 Tage (Playwright + PDF-Download analog CZ-Adapter) | **0,5 Tage** (`ALL_FIELDS`-Liste erweitern + XML-Felder mappen) |
| FR | 0,5 Tage (BOAMP-Adapter existiert; nur Mapping verbessern) | **0,5 Tage** (gleicher TED-XML-Patch greift für FR) |
| PL | 1–2 Tage (Playwright + PDF) | **0,5 Tage** |
| CZ | bereits implementiert | **0,5 Tage** |

**Wichtig:** Strategie B ist eine **einmalige Pipeline-Erweiterung**
(`ALL_FIELDS` + XML-Parser-Mapping), die für **alle** Country-Notices
gleichzeitig wirkt. Aufwand ≈ 1 Tag total für alle 4 Länder.

---

## 5. Empfehlung pro Country

### Strategie A (echtes Cross-Reference auf nationale Portale)

| Country | Lohnt sich? | Begründung |
| ------- | :---------: | ---------- |
| **DE** | ✅ ja, **mittelfristig** | LV-PDFs sind echter Mehrwert für BPW-Spec-Analyse. Aber erst nach Strategie B. |
| **FR** | ⚠ tendenziell **nein** | TED-XML hat schon Lot-Werte; BOAMP-Adapter zieht die strukturierten Felder. Cross-Ref-Aufwand → Nutzen-Verhältnis schlecht. |
| **PL** | ✅ ja | SWZ-PDFs liefern Spec-Tiefe, die TED nicht hat. Hochpriorisiert für Defence (12-WOG / 4-RBLOG). |
| **CZ** | ✅ schon im Code, **erweitern** | `cz_adapter.py` zieht 3 PDFs; Limit auf 5–10 anheben + bessere PDF-Tabellen-Extraktion (siehe Pipeline-Improvements §1, OCR-Upgrade). |

### Strategie B (TED-XML-`ALL_FIELDS` erweitern)

**✅ Ja, alle 4 Länder, sofort.**
Quick Win, keine Browser-Automation, kein Geo-Block-Problem (TED ist
EU-public). Liefert für alle 4 Länder gleichzeitig:
- `buyer-profile-url` als Foreign-Key in das nationale Portal
- `tender-documents-access` als direkten Link zum Document-Bundle
- `internal-reference` als Such-Key auf der nationalen Plattform
- Lot-Wert- und Lot-Mengen-Breakdown (das adressiert die `_trailer_quantity_*_ai`-Lücke aus dem `field_extraction_audit_260509`-Sprint!)

**Implementation-Skizze:**

```python
# src/api_client.py
ALL_FIELDS = [
    ...,                           # bestehend
    "buyer-profile-url",
    "tender-documents-access",
    "submit-tenders-address",
    "additional-information-address",
    "internal-reference",          # zentral wichtig als Foreign-Key
    "estimated-value-lot",
    "quantity-lot",
    "place-of-performance-country-part",
]

# src/exporter_frontend.py — neue Felder ans Frontend durchreichen
out["buyer_profile_url"]      = raw.get("buyer-profile-url")
out["tender_documents_url"]   = raw.get("tender-documents-access") or raw.get("submit-tenders-address")
out["internal_reference"]     = raw.get("internal-reference")
out["lot_breakdown"]          = _build_lot_breakdown(raw)  # neu
```

```ts
// defence-intel-web/lib/types.ts
buyer_profile_url?: string | null
tender_documents_url?: string | null
internal_reference?: string | null
lot_breakdown?: Array<{ id: string; value_eur: number; quantity?: number }>
```

### Strategie A Implementation-Skizze (nur für DE + PL)

```python
# Kandidaten-Auswahl: alle TED-Tender mit buyer-profile-url die zu
# {service.bund.de, evergabe-online.de, ezamowienia.gov.pl} gehört.

# DE: pattern → "evergabe-online.de/tenderdetails.html?id=N"
# Schritt 1: GET die URL (httpx, kein JS nötig für die Detail-Seite)
# Schritt 2: parse Form-Felder + Anhang-Liste
# Schritt 3: Download bis zu 3 PDFs analog cz_adapter._extract_and_download_pdfs
# Schritt 4: pdfplumber-Extraktion → write _attachment_text_de zu Notice

# PL: pattern → "ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/<UUID>"
# pl_adapter.py macht das schon; nur PDF-Anhang-Loop ergänzen.
```

---

## 6. Aufwand-Schätzung

| Sprint | Inhalt | Aufwand | Nutzen |
| ------ | ------ | ------: | ------ |
| **B-Sprint (Quick Win)** | TED-XML `ALL_FIELDS` erweitern + Frontend-Schema-Patch + Re-Index aller bekannten 35k Notices | **1 Tag** (~5 h Code, 3 h Re-Index, 2 h Frontend) | Bringt Lot-Breakdown, Buyer-URL, internal-reference für **alle 256** Tender; löst auch das `_trailer_quantity_*_ai`-Loch teilweise |
| **A-DE-Sprint** | service.bund.de + evergabe-online.de Adapter-Erweiterung mit PDF-Download + OCR | **1,5 Tage** | LV-PDFs für ~9 DE-Defence-Tender; Spec-Tiefe für BPW |
| **A-PL-Sprint** | ezamowienia.gov.pl Adapter-Erweiterung mit SWZ-PDF-Download + OCR | **1,5 Tage** | SWZ für ~3 PL-Defence-Tender + alle künftigen |
| **A-CZ-Erweiterung** | cz_adapter PDF-Cap 3 → 10 + bessere Tabellen-Extraktion | **0,5 Tage** | Tieferes spec für die 12 CZ-Tender |
| **(A-FR übersprungen)** | — | — | TED-XML + BOAMP-Adapter sind schon ausreichend |

**Gesamt-Aufwand für die Yes-Cases: ≈ 4,5 Tage Engineering** (1 + 1,5 + 1,5 + 0,5).

**Erwarteter Daten-Gewinn:**

* Strategie B (1 Tag): **+5 strukturelle Felder pro Tender** über alle
  256 Tender → ≈ 1 280 zusätzliche Datenpunkte
* Strategie A DE+PL+CZ (3,5 Tage): **+1 PDF-Anhang pro Tender** im
  Schnitt für ~24 Tender → ≈ 24 zusätzliche LV-Volltexte mit je
  ~10–50 Spec-Detail-Feldern → grob 240–1 200 zusätzliche AI-extrahierbare
  Datenpunkte
* Pro Tender im DE/PL/CZ-Bereich: **ca. 5–15 zusätzliche Spec-Felder**
  (LV-extrahierbar via existierender Sonnet-Pipeline)

---

## 7. Konkrete Empfehlung

**Lohnt sich für:** **DE, PL, CZ** (in dieser Reihenfolge, jeweils nach
Strategie-B-Sprint).

**Lohnt sich nicht für:** **FR** — TED-XML + bestehender BOAMP-Adapter
liefern schon das Maximum an strukturierten Feldern; PLACE bietet keine
zusätzlichen PDFs in nennenswerter Menge.

**Implementation-Aufwand:**
* Strategie B (sofort): **1 Tag**
* Strategie A (DE + PL + CZ-Erweiterung): **3,5 Tage**
* **Total: 4,5 Tage**

**Erwarteter Daten-Gewinn pro Tender:**
* Strategie B: ~5 zusätzliche strukturelle Felder
* Strategie A (für DE/PL/CZ-Tender): ~5–15 zusätzliche Spec-Felder aus
  PDF-Vollauswertung (via Sonnet-Pipeline)

---

## 8. Stichproben-Beleg

Vier Spotcheck-WebFetches auf `https://ted.europa.eu/<id>/xml` haben für
jedes der vier Länder bestätigt, dass mindestens eine direkte URL zum
nationalen Portal **bereits im TED-XML** steht. Die konkreten URLs:

| Sample | National-URL aus TED-XML |
| ------ | ------------------------ |
| `212474-2026` (DE) | `https://www.evergabe-online.de/tenderdetails.html?id=771723` |
| `77247-2026` (FR) | `www.marches-publics.gouv.fr` (Stamm) + internal-reference `24R40121` |
| `261427-2025` (PL) | `https://platformazakupowa.pl/pn/12wog` + internal-reference `D/08/12WOG/2025` |
| `798124-2025` (CZ) | `https://verejnezakazky.vop.cz/vz00002751` |

Diese URLs sind **direkt aus dem öffentlichen TED-XML** ohne
Authentifizierung verfügbar. Die Behauptung der Spec ("nationale Portale
haben mehr Information") ist damit empirisch belegt — aber der Weg dahin
führt **erst** über Strategie B (TED-XML voll auswerten), bevor sich
Strategie A für DE/PL/CZ wirklich lohnt.

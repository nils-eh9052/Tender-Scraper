# Field Documentation — shared/tenders.json

**Stand:** 2026-05-19 (Window E Handover)  
**Schema:** `shared/schema/tender.schema.json`  
**Datei:** `../../shared/tenders.json` (relativ zu `ted-scraper/ted-scraper/`)  
**Aktuelle Tenders:** 275

---

## Pflichtfelder

### `id` — string
TED Notice-ID oder nationales Adapter-Format.

| Source | Format | Beispiel |
|--------|--------|---------|
| TED | `{number}-{year}` | `682847-2024` |
| CA-CB | `CA-CB-{uuid}` | `CA-CB-3a91b...` |
| AU-TEN | `AU-TEN-{uuid}` | `AU-TEN-f7a2c...` |
| CZ-NEN | `CZ-NEN-{id}` | `CZ-NEN-P25V00063302` |
| FR-BP | `FR-BP-{ref}` | `FR-BP-2025-ABC` |
| UK-CF | `UK-CF-{uuid}` | `UK-CF-ocds-...` |

### `title` — string
Originaltitel in Ausschreibungssprache.

### `title_en` — string
Englischer Titel (Format: `{Country} – {Type} – {Original-Title}`).  
Quelle: Haiku 4.5-Übersetzung (Phase 3e), gecacht in `.translation_cache.json`.  
Coverage: 316/322 Notices (98%).

### `country` — string
Langer Ländernahme (z.B. `"Germany"`, `"Czech Republic"`, `"Australia"`).

### `country_code` — string
ISO 3166-1 Alpha-2 (z.B. `"DE"`, `"CZ"`, `"AU"`).

### `source` — string
`"TED"` für EU-Portal; `"National"` für alle anderen Adapter.

### `source_url` — string
Direktlink zur Ausschreibung:
- TED: `https://ted.europa.eu/en/notice/-/detail/{id}`
- National: Adapter-spezifisch (platformazakupowa, NEN, CanadaBuys, etc.)

### `publication_date` — string (ISO Date)
Veröffentlichungsdatum, Format `YYYY-MM-DD`.

### `status` — string
| Wert | Bedeutung |
|------|-----------|
| `"Open"` | Bewerbungsfrist läuft |
| `"Closed"` | Frist abgelaufen, noch keine Vergabe bekannt |
| `"Awarded"` | Vergabe bekannt (`winner` gesetzt) |
| `"Cancelled"` | Storniert |

### `contracting_authority` — string
Name der vergebenden Behörde. TED: bevorzugt `_authority_name_structured` (englisch, aus eForms). Fallback: `_authority_name` → `contracting_authority.name`.

### `is_relevant` — bool
Immer `true` (Safety-net filtert irrelevante Tenders vor Export heraus).

---

## Optionale Felder

### `description` — string
Englische Beschreibung (Sonnet 4.6-Übersetzung, Phase 3e-2, mit Haiku-Cleaning-Pass).  
Fallback-Kette: `description_en` → `_description_english` → `description_translated` → `_description_final`.

### `estimated_value_eur` — number
Geschätzter Auftragswert in Euro. `0` wenn unbekannt (kein Schätzwert, nicht €0).  
Quellen: `_value_eur_num` → `estimated_value` dict → `_value_amount + _value_currency`.  
**Nicht inferiert** — nur gemessene Werte (Phase 3i Value Inference wurde 2026-05-18 zurückgebaut).

### `deadline` — string (ISO Date oder leer)
Einreichungsfrist für Angebote. Leer wenn unbekannt.
Resolution-Waterfall: `submission_deadline` → `_closing_date` (CA-Adapter) → `_deadline_mined` (Phase 3k Text-Mining).

### `vehicle_types` — array
AI-klassifizierte Fahrzeugtypen. Jedes Element:
```json
{
  "name": "3.5t 2-axle cargo trailer",
  "category": "trailer",
  "trailer_category": "Cargo Trailer",
  "quantity": 4600
}
```
- `name`: AI-generierter Trailer-Type-String (Haiku/Sonnet Klassifikation Phase 3b)
- `category`: grobe Fahrzeug-Familie — immer `"trailer"` (Schema-Enum: `trailer/transport/logistics/armoured`)
- `trailer_category`: **feingranularer AI-Cluster** (11 Klassen, siehe unten) — für Frontend-Gruppierung. Quelle: `_trailer_category_{i}_ai`.
- `quantity`: integer oder null. Quelle: `_trailer_quantity_{i}_ai` → Fallback `_qty_mined` (nur für ersten Trailer).

**Trailer-Category-Enum (Cluster-Werte):**
`Low-Bed | Semitrailer | Dolly | Tank Trailer | Mission Module | Loading System | Special Purpose | Ammunition Trailer | Field Kitchen | Cargo Trailer | Other`

### `winner` — string | null
Name des Auftragnehmers (falls bekannt). Aus Award-Match Phase 3d + LLM Phase 3d-LLM.

### `contract_type` — string
Vertragsart (Phase 3j, Multilingual Regex, 10 Sprachen):
| Wert | Bedeutung | Anzahl |
|------|-----------|--------|
| `"one_time"` | Einzelauftrag (Default für Rüstungsbeschaffung) | 229 |
| `"framework_agreement"` | Rahmenvertrag | 36 |
| `"recurring"` | Wiederkehrende Beschaffung | 4 |

### `framework_type` — string | null
eForms-Framework-Typ (nur TED eForms-Ära 2023+):
| Wert | Bedeutung |
|------|-----------|
| `"fa-wo-rc"` | Framework ohne erneuten Wettbewerb | 24 |
| `"fa-w-rc"` | Framework mit erneutem Wettbewerb | — |
| `"fa-mix"` | Gemischtes Framework | — |
| `"none"` | Kein Framework | 42 |
| `null` | Nicht bekannt / pre-eForms | 209 |

### `contract_duration_months` — integer | null
Vertragslaufzeit in Monaten (aus Regex-Extraktion Phase 3j).

### `extension_options` — bool | null
`true` wenn Verlängerungsoptionen erwähnt.

### `contract_conclusion_date` — string (ISO Date) | null
Echtes Vergabe-/Unterzeichnungsdatum aus eForms-CAN (`contract-conclusion-date`).  
≠ Publikationsdatum des CAN. Coverage: ~35% der TED eForms-Notices.

### `authority_identifier` — string | null
Stabile Buyer-Registriernummer (DE: Handelsregister-Nr, NL: KVK, SE: Organisationsnummer).  
Foreign-Key für Buyer-Profile-Aggregation. Coverage: ~35% der TED eForms-Notices.

### `_first_seen_at` — string (ISO 8601)
Zeitstempel, wann die Notice erstmals in den Pipeline-Cache aufgenommen wurde.

---

## Specs-Felder (Dokument-Extraktion)

### `extracted_specs` — object | null
AI-extrahierte technische Spezifikationen aus Ausschreibungsdokumenten (Phase 3g, gpt-4o).  
Coverage: 278/322 Notices (86%) — aber Confidence oft 10–40 (TED-PDFs sind Bekanntmachungen, keine echten LVs).

```json
{
  "trailer_types": [
    {
      "type": "2-wheel trailer",
      "qty": 4600,
      "mass_t": 3.5,
      "length_mm": null,
      "width_mm": null,
      "height_mm": null,
      "axle_load_t": null,
      "payload_t": 3.5
    }
  ],
  "fuel_type": null,
  "drive_type": null,
  "coupling_type": "5th wheel",
  "additional_equipment": ["tarpaulin", "lashing rails"],
  "standards": ["NATO STANAG 2413", "Directive 2009/81/EC"],
  "confidence": 65,
  "source_doc_title": "Germany – Military Cargo Trailers 3.5t and 12.5t",
  "notes": "Framework agreement for 4600 trailers over 7 years."
}
```

`confidence`: 0–100. Unter 30 = nur Metadaten, keine echten Specs extrahiert.

### `strategy_a_specs` — object | null
Specs aus proaktivem Vergabeunterlagen-Scrape (Strategy A, Window E).  
Identische Struktur wie `extracted_specs`. Aktuell 3 PL-Tenders (ezamowienia HTML-Body).  
Confidence 0–30 (HTML-Notice-Body liefert Procurement-Sprache, keine technischen Details).

---

## Technische Spezifikationsfelder (aus extracted_specs "geliftet")

Diese Felder werden vom Exporter direkt aus `extracted_specs` extrahiert, um Top-Level-Zugriff zu ermöglichen:

### `axle_config` — string | null
Achskonfiguration (z.B. `"2-axle"`, `"4-axle"`). Aus `extracted_specs.trailer_types[0]`.

### `payload_kg` — number | null
Nutzlast in kg (aus `extracted_specs.trailer_types[0].payload_t × 1000`).

### `dimensions` — string | null
Abmessungen (Länge × Breite, z.B. `"8500 × 2550"`). Aus `extracted_specs.trailer_types[0]`.

### `protection_class` — string | null
Schutzklasse (z.B. `"STANAG 4569 Level 1"`). Aus `extracted_specs` oder `_text_mined`.

---

## Sonstige Felder

### `recommended_oems` — array
Empfohlene OEMs (von AI-Klassifikation). Meist leer (`[]`).

### `comments` — array
Manuelle Kommentare. Immer leer (`[]`) in automatisch generierten Tenders.

---

## Felder die NICHT in shared/tenders.json sind

Diese Felder existieren in `relevant.json` (Pipeline-intern) aber werden nicht exportiert:

| Feld | Grund |
|------|-------|
| `_raw` | Rohdaten aus TED API — zu groß, intern |
| `_description_final` | Wird zu `description` transformiert |
| `_trailer_type_1_ai` | Wird zu `vehicle_types[]` transformiert |
| `_value_num` / `_value_currency` | Wird zu `estimated_value_eur` konsolidiert |
| `_extracted_specs` | Wird zu `extracted_specs` (ohne Prefix) |
| `_strategy_a_specs` | Wird zu `strategy_a_specs` (ohne Prefix) |
| `_contract_type` | Wird zu `contract_type` |
| `_framework_type` | Wird zu `framework_type` |
| `_authority_name_structured` | Fließt in `contracting_authority` |
| `_authority_id` | Wird zu `authority_identifier` |
| `_qty_mined` | Nicht exportiert (Scout-Phase) |
| `_deadline_mined` | Nicht exportiert (Scout-Phase) |
| `_fallback_*` | National Fallback interne Felder |
| `award` | Wird zu `winner` string (nur Name) |

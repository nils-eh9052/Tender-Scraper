# Sprint 2 Summary — Broaden + Learn + Sharpen
**Run date:** 2026-04-27  
**Excel output:** `data/export/260427_TED_Tender Data_00.01.xlsx`

---

## Before / After

| Metrik | Vorher (Sprint 1) | Nachher (Sprint 2) |
|---|---|---|
| **Zeilen gesamt (Excel)** | 143 | **230** |
| **TED-Notices (klassifiziert)** | ~143 | 222 |
| **UK-CF-Notices** | ~0 | 9 |
| **PL-National-Notices** | 0 | 4 |
| **Duplikate entfernt** | — | 7 |
| **Neue TED-Notices (netto)** | — | ~86 |
| **Slot-2 befüllt** | ~6 | **12** |
| **TED-Index-Größe** | 17 505 | 35 129 |
| **Bearbeitete Queries** | 6 CPV + 6 Text | 10 CPV + 11 Text |

### Kategorie-Verteilung

| Kategorie | Vorher | Nachher | Δ |
|---|---|---|---|
| Special Purpose | ~76 | 95 | +19 |
| Other | ~42 | 59 | +17 |
| Cargo Trailer | ~11 | 30 | +19 |
| Tank Trailer | ~7 | 12 | +5 |
| Low-Bed | ~8 | 11 | +3 |
| Mission Module | ~4 | 9 | +5 |
| Field Kitchen | ~4 | 8 | +4 |
| Semitrailer | ~4 | 6 | +2 |
| Loading System | ~5 | 4 | −1 |
| Ammunition Trailer | ~1 | 1 | 0 |

---

## Was wurde geändert

### 1. PL-Adapter (eZamowienia)
- **Neues Such-Schema**: Cross-Produkt aus 5 CPVs × 6 Militär-Org-Keywords = 30 kombinierte API-Queries
- **Historisches Datum**: ab 2021-01-01 (statt nur 1 Jahr zurück)
- **Filterfix**: `filter_defence()` prüft jetzt korrekt Title-Keywords UND Authority-Name
- **Ergebnis**: 5 Treffer seit 2021, davon 4 echte "Dostawa przyczep" (12. WOG, Toruń)
- **Entfernt**: CPV 34130000 (Motorfahrzeuge – zu breit, zu viel Rauschen)

### 2. DE-Adapter (service.bund.de)
- **Dead-Code-Fix**: `filter_defence()` gab bisher immer das ungefilterte `results` zurück statt `kept`
- **Erweiterte Keywords**: +8 neue Begriffe (Auflieger, Wechselbrücke, Schwerlasttransport, etc.)
- **Ergebnis**: Filter funktioniert jetzt korrekt; aktuell keine DE Trailerausschreibungen offen

### 3. TED-Index erweitert
- **3 neue CPV-Codes in Tier 1**: 34223330 (Van trailers), 34221000 (Mobile containers), 34224100 (Motorized trailers)
- **1 neuer CPV in Tier 2**: 35400000 (Military vehicles + spare parts – war bisher nicht abgedeckt, weil 35000000 nur Exact-Match ist)
- **5 neue Text-Queries**: PL (przyczepa/naczepa), DE (Wechsellader/Feldküche), FR (semi-remorque/remorque militaire), FI (perävaunu/puoliperävaunu), SE (terrängvagn/pjäsvagn)
- **Index-Wachstum**: 17 505 → 35 129 Notices (+17 624; davon ~582 nach Filter neu relevant)

### 4. Opus QA-Modul erweitert
- Neue Felder in Prompt: `potential_gaps`, `new_search_keywords`, `low_quality_entries`
- Standalone `--review` Flag implementiert (läuft ohne --all/--uk)
- Ergebnisse in `data/quality_review.json`

### 5. Raw-Dump-Strategie
- `data/raw/{country}/national_raw.json` — kompletter API-Output vor Filter
- `data/raw/{country}/national_filtered.json` — nach `filter_defence()`

---

## Korrekturen (aus Opus-QA Sprint 1)

| Aktion | Tender-IDs |
|---|---|
| **Entfernt** (Duplikate) | 572650-2024, 553507-2023, 83387-2024, 151800-2025, 252675-2024, 726774-2024 |
| **Entfernt** (False Positive – UK Awards) | UK-tender_340233/1200929 |
| **Kategorie korrigiert** | 326948-2025: Cargo Trailer → Mission Module |
| **Re-klassifiziert (Slot 2)** | 227432-2024, 254420-2025, 493986-2024, 152406-2025 |

### Slot-2 Ergebnisse nach Re-Klassifizierung

| Tender ID | Slot 1 | Slot 2 |
|---|---|---|
| 227432-2024 (DK) | 24t block trailer (Low-Bed) | 16t hook-lift trailer (Loading System) |
| 254420-2025 | Cargo trailer | Field lighting tower on twin-axle trailer (Special Purpose) |
| 493986-2024 | Cargo trailer | Field lighting tower on twin-axle trailer (Special Purpose) |
| 152406-2025 | Low-bed semi-trailer | 4-axle semi low-bed >46t (Low-Bed) |

---

## Opus-Lernfelder: Erkannte Lücken

| Lücke | Evidenz | Empfohlene Maßnahme |
|---|---|---|
| Eastern European Low-Beds | Nur 2 CZ-Einträge, 0 PL Low-Beds | Keyword "niskopodwoziowa" + CPV 34223100 auf eZamowienia |
| Loading Systems | Nur 4 Einträge trotz Bedeutung für Container-Logistik | FT~"Wechsellader" erweitern + DROPS/PLS keywords |
| Dolly | 0 Einträge im Dataset | Keywords "Dolly-Achse", "avant-train" hinzufügen |
| Frankreich | Nur 12 Einträge bei großem Militär | BOAMP scrapen + FT~"remorque porte-char" |
| Munitions-Anhänger | Nur 1 Eintrag | CPV 35321000 + "ammunition trailer" keywords |
| Feldküchen West-Europa | Nur CZ/RO, keine UK/DE/FR/NL | FT~"Feldküche" + "field kitchen trailer" prüfen |

## Neue Such-Keywords (Opus-Empfehlungen)

| Keyword | Sprache | Kategorie |
|---|---|---|
| Dolly-Achse | DE | Dolly |
| remorque porte-char | FR | Low-Bed |
| naczepa niskopodwoziowa | PL | Low-Bed |
| Wechselladeranhänger | DE | Loading System |
| rimorchio ribaltabile | IT | Cargo Trailer |
| remolque pluma | ES | Special Purpose |
| jalusta-auto | FI | Low-Bed |
| terrängvagn | SE | Special Purpose |
| rimorchio militare | IT | Special Purpose |
| remorque multi-usage | FR | Cargo Trailer |

---

## Offene Punkte / Sprint 3 Backlog

1. **BOAMP-Adapter**: Frankreich national (~12 TED-Treffer suggeriert mehr verfügbar)
2. **Dolly-Keywords**: In settings.yaml + TED-Textsuche aufnehmen
3. **Loading-System-Tiefe**: DROPS, PLS, Wechsellader-Systeme besser erfassen
4. **Ammunitions-CPVs**: 35321000 (Munition) + kombinierten Query prüfen
5. **Enrichment (--enrich)**: 15 Low-Quality-Entries aus Opus-Review anreichern
6. **PL eZamowienia**: Historische Abfrage 2021-2023 noch einmal mit breiterem CPV-Set
7. **Award-Match**: Winner-Feld für die 230 exportierten Einträge nachziehen (--award-match)
8. **DE BAAINBw**: Crawler für historische Ausschreibungen (aktuell leer weil Portal kein API hat)

---

## Datei-Artefakte dieses Sprints

| Datei | Beschreibung |
|---|---|
| `data/export/260427_TED_Tender Data_00.01.xlsx` | **Haupt-Output** – 230 Zeilen |
| `data/export/TED_Defence_Trailers_LATEST.xlsx` | LATEST-Alias (aktuell) |
| `data/filtered/relevant.json` | 235 Notices (222 TED + 9 UK + 4 PL) |
| `data/quality_review.json` | Opus-QA-Ergebnisse (143 Rows, Sprint-1-Base) |
| `data/raw/pl/national_raw.json` | PL-Rohdaten (alle API-Hits) |
| `data/raw/pl/national_filtered.json` | PL nach filter_defence (5 Einträge) |
| `data/raw/de/national_raw.json` | DE-Rohdaten |
| `data/raw/de/national_filtered.json` | DE nach filter_defence |
| `data/.checkpoint.json` | Checkpoint (11 abgeschlossene Queries) |

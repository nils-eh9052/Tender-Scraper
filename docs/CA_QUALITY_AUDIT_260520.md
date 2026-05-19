# CA Quality Audit — 2026-05-20

> Auto-generiert von `scripts/_audit_ca_quality.py`.

## Root-Cause Analyse

**User-Report:** CA Lowbed Trailers — `Qty 27` im Text, aber Frontend zeigt weder Quantity noch Trailer-Type-Clustering.

**Befund:** Daten sind in `relevant.json` korrekt klassifiziert.
Das Problem liegt **im Exporter-Mapping**:

| Lücke | Auswirkung |
|-------|-----------|
| `vehicle_types[i].category` hartcodiert auf `"trailer"` | `_trailer_category_{i}_ai` (Low-Bed/Cargo/Ammunition/...) verloren — kein Clustering möglich |
| Quantity liest nur `_trailer_quantity_{i}_ai` | `_qty_mined` Fallback nie genutzt — bricht bei AI-Misses |
| Deadline liest nur `submission_deadline` | CA setzt `_closing_date`, text_miner setzt `_deadline_mined` — Frontend hat **0/322** Tenders mit deadline |

## Field Coverage in relevant.json (CA-CB, 19 Tender)

| Feld | Coverage | Bedeutung |
|------|---------:|-----------|
| `_trailer_type_1_ai` | 19/19 | AI Trailer-Type-Beschreibung |
| `_trailer_category_1_ai` | 19/19 | AI Trailer-Cluster |
| `_trailer_quantity_1_ai` | 18/19 | AI Quantity |
| `_qty_mined` | 5/19 | Text-Miner Quantity |
| `_closing_date` | 19/19 | CA-Adapter Closing Date |
| `_deadline_mined` | 15/19 | Text-Miner Deadline |
| `submission_deadline` | 0/19 | Generisches Deadline-Feld (TED/UK) |

## Per-Tender Detail

Status-Spalten:
- **RJ_qty**: Quantity in `relevant.json` (AI / mined)
- **RJ_cat**: Category in `relevant.json` (`_trailer_category_1_ai`)
- **RJ_dl**: Deadline-Quellen in `relevant.json`
- **FE_qty**: Quantity im Frontend (`vehicle_types[0].quantity`)
- **FE_cat**: Category im Frontend (`vehicle_types[0].category` — aktuell hartcodiert)
- **FE_dl**: Deadline im Frontend

| ID | Title | RJ_qty | RJ_cat | RJ_dl | FE_qty | FE_cat | FE_dl |
|----|-------|-------:|--------|-------|-------:|--------|-------|
| `CA-cb-858-22734399` | “Fat Truck®” Hauler Trailer | 1/– | Special Purpose | clo,min | 1 | trailer | – |
| `CA-cb-638-26291550` | Enclosed Trailer | 50/– | Cargo Trailer | clo,min | 50 | trailer | – |
| `CA-cb-354-91077006` | Cargo Trailers | 25/– | Cargo Trailer | clo,min | 25 | trailer | – |
| `CA-cb-525-19244036` | Pintle Trailers Various Configurations | 5/– | Cargo Trailer | clo | 5 | trailer | – |
| `CA-cb-429-10910023` | Trailer Boat for Zodiac Mk3 | 1/– | Special Purpose | clo,min | 1 | trailer | – |
| `CA-cb-486-33159154` | Trailer Boat of configuration Zodiac Hur | 19/– | Special Purpose | clo,min | 19 | trailer | – |
| `CA-cb-508-3695938` | Various Semi-Trailer | 5/– | Semitrailer | clo,min | 5 | trailer | – |
| `CA-cb-689-60047399` | Semi-trailer Flat Deck with Container Lo | 5/5 | Semitrailer | clo,min | 5 | trailer | – |
| `CA-cb-674-28324096` | LOX Converter Trailer | 4/4 | Special Purpose | clo | 4 | trailer | – |
| `CA-cb-242-54645889` | Ammunition Cargo Trailers | 3/3 | Ammunition Trailer | clo,min | 3 | trailer | – |
| `CA-cb-794-19250079` | Trailers for NAV19 HD Boat | 5/– | Special Purpose | clo,min | 5 | trailer | – |
| `CA-cb-654-97078081` | Arctic Mobility Amphibious Vehicle | –/– | Special Purpose | clo | NOT_IN_TENDERS | NOT_IN_TENDERS | NOT_IN_TENDERS |
| `CA-cb-352-52771736` | Enclosed Trailers | 98/– | Cargo Trailer | clo,min | 98 | trailer | – |
| `CA-cb-519-94462202` | Semi-Trailer | 1/– | Semitrailer | clo,min | 1 | trailer | – |
| `CA-cb-860-22921243` | Flat Bed Trailers | 30/– | Cargo Trailer | clo,min | 30 | trailer | – |
| `CA-cb-259-10824239` | Lowbed Trailers | 27/27 | Low-Bed | clo,min | 27 | trailer | – |
| `CA-cb-706-10971174` | LOX Converter Trailer | 4/4 | Special Purpose | clo | 4 | trailer | – |
| `CA-cb-649-74064644` | Self-Loading Cable Reel Trailer | 5/– | Special Purpose | clo,min | 5 | trailer | – |
| `CA-cb-270-61917746` | Cargo Trailer | 9/– | Cargo Trailer | clo,min | 9 | trailer | – |

## Aggregate: Deadline-Coverage über ALLE Sources (322 Tender)

| Source | Tenders | submission_deadline | _closing_date | _deadline_mined |
|--------|--------:|--------------------:|--------------:|----------------:|
| AU-TEN | 56 | 0 | 0 | 0 |
| CA-CB | 19 | 0 | 19 | 15 |
| CZ-NEN | 32 | 0 | 0 | 0 |
| EE-RP | 3 | 0 | 0 | 0 |
| FR-BP | 13 | 0 | 0 | 0 |
| NL-TN | 1 | 0 | 0 | 0 |
| NO-DF | 3 | 0 | 0 | 0 |
| TED | 187 | 9 | 0 | 0 |
| UA-PR | 2 | 0 | 0 | 0 |
| UK-CF | 6 | 6 | 0 | 0 |

**Frontend `deadline` gesetzt:** 15/275 (sollte mit Fix ≥ ~55 sein)

## Empfohlene Fixes (in `src/exporter_frontend.py`)

### Fix 1 — `_build_vehicle_types()`
```python
# ALT:
entry = {"name": name, "category": "trailer"}
# NEU:
cat_ai = notice.get(f"_trailer_category_{i}_ai")
entry = {"name": name, "category": cat_ai or "trailer"}
# Quantity-Fallback:
qty = (notice.get(f"_trailer_quantity_{i}_ai")
       or (notice.get("_qty_mined") if i == 1 else None))
```

### Fix 2 — Deadline-Resolution
```python
def _deadline_date(notice):
    for f in ('submission_deadline', '_closing_date', '_deadline_mined'):
        v = _clean_date(notice.get(f))
        if v: return v
    return None
```

## Was NICHT zu fixen ist (Hypothesen widerlegt)

- **Classifier-Bypass für CA:** 19/19 CA-Tender haben `_trailer_type_1_ai` gesetzt. Classifier läuft korrekt.
- **Classifier-Prompt-Schwäche bei "Low-Bed":** CA-cb-259-10824239 hat `_trailer_category_1_ai: "Low-Bed"`. Klassifikation funktioniert.
- **Text-Mining-Bug:** `_qty_mined: 27` in Lowbed-Tender korrekt extrahiert.
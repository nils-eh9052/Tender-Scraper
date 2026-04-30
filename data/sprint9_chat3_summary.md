# Sprint 9 Chat 3 — CanadaBuys + Ukraine Prozorro
**Date:** 2026-04-30 | **Branch:** sprint9/ca-ua

---

## AUFGABE 1: CanadaBuys Aktive Tenders

### Ergebnis

**11 aktive/aktuelle DND-Trailer-Tenders** aus CanadaBuys Open Data CSVs:

| Date | Title | Status |
|------|-------|--------|
| 2025-02-05 | Department of National Defence - 2025 Freight Forwarding Transportation | Open |
| 2026-04-15 | Commercial Vehicle & Maintenance | Open |
| 2023-02-17 | Lowbed Trailers | Open |
| 2024-04-10 | E60HP-24CARG-A - Light Duty Cargo Trailers | Open |
| 2023-04-19 | RFSA Flatbed Trailers | Open |
| 2025-08-28 | W6447-250001-RFSA Flatbed Trucking Services | Open |
| 2026-03-09 | Diesel Truck 6x4 Sleeper Cab, 26-Foot Flat Bed with Roller Tarp | Open |
| 2026-03-18 | 24 Foot Van Body with Full Sleeper Cab | Open |
| 2026-04-01 | W3935-25P027 Rental Trailers | Open |
| + 2 more | ... | Open |

**2025-2026 Archive:** 48 DND trailer tenders found (including "Ammunition Cargo Trailers", "Various Semi-Trailer", "Pintle Trailers Various Configurations")

### Datenquellen

| URL | Status | Notes |
|-----|--------|-------|
| `openTenderNotice-ouvertAvisAppelOffres.csv` | ✅ 779 active tenders | Requires Browser UA header |
| `2025-2026-TenderNotice...csv` | ✅ 7027 tenders | Yearly archive |
| `2024-2025-TenderNotice...csv` | ✅ Available | Older archive |
| `newTenderNotice...csv` | ✅ Available | Just-published |
| RSS/direct portal access | ❌ 403 | Portal requires auth |

### Technische Implementierung

**`src/canada_loader.py` erweitert:**
- `load_active_tenders(test_mode, years_back)` — lädt Open/Yearly CSVs
- `_fetch_cb_csv(url, label)` — Download mit Browser-UA
- `_is_dnd_cb(row)` — prüft DND-Begriffe in allen Spalten
- `_is_trailer_cb(row)` — prüft Trailer-Keywords in Title + Description
- `_normalize_tender_row(row)` — Normalisiert zu Standard-Format (source=CA-CB)

**main.py:** `--canada` ruft jetzt BEIDE Loader auf (historisch + aktiv)

**Validierung:**
- ✅ Daten stimmen (Titel, Behörde "Department of National Defence")
- ✅ MSVS/HLVW: Nicht direkt gefunden (classified procurement)
- ✅ Flatbed/Lowbed/Cargo/Pintle Trailers bestätigt

---

## AUFGABE 2: Ukraine — Prozorro API

### Ergebnis

**Ukraine Prozorro Adapter funktioniert**, 0 trailer tenders im Test-Scan (erwartet).

**Test-Ergebnisse:**
- Stage 1: 1000 Tenders gescannt → 85 Defence-Entitäten gefunden (8.5% hit rate)
- Stage 2: 20 Details gefetcht → 0 Trailer-Tenders (in dieser Stichprobe)
- 5000 Tenders gescannt → 207 Defence-Kandidaten, 1 false-positive (fixed)

### API-Details

- **Endpoint:** `https://public.api.openprocurement.org/api/2.5/tenders`
- **Format:** REST/JSON, cursor-basiert, keine Authentifizierung
- **List-Endpoint:** Gibt nur `id + dateModified` zurück
- **Mit `opt_fields=procuringEntity,tenderID`:** Enthält auch Auftraggeber-Name (effiziente Vorfilterung)
- **Detail-Endpoint:** `/api/2.5/tenders/{id}` — vollständige Tender-Daten

### Two-Stage-Strategie

1. **Stage 1:** Scan mit `opt_fields` → filtern nach Auftraggeber (≈9% defence-Rate)
2. **Stage 2:** Detail-Fetch für Defence-Kandidaten → filtern nach Trailer-Keywords/CPV

**Test-Modus (max_scan=1000, detail_limit=20):**
- Laufzeit: ~3 Minuten
- Kosten: 0 (kein AI, freie API)

**Full-Modus (max_scan=10000, detail_limit=200):**
- Erwartete Defence-Kandidaten: ~900
- Erwartete Detail-Fetches: 200
- Erwartete Trailer-Hits: 5-20

### Gefundene Defence-Entitäten (Beispiele)
- Військова частина A4913 (Military Unit A4913)
- Військова частина A3719
- Військова частина 3078 Національної гвардії України
- ГОЛОВНЕ УПРАВЛІННЯ НАЦІОНАЛЬНОЇ ГВАРДІЇ УКРАЇНИ
- Державна прикордонна служба (State Border Guard)

### FX-Rate hinzugefügt
```python
"UAH": 0.023,  # ~43 UAH = 1 EUR (April 2026)
"CAD": 0.68,   # ~1.47 CAD = 1 EUR (April 2026)
```

---

## Dateien geändert

| Datei | Änderung |
|-------|---------|
| `src/canada_loader.py` | Extended: `load_active_tenders()` + CanadaBuys CSV download |
| `src/national_scraper/adapters/ua_adapter.py` | Neu: Ukraine Prozorro adapter |
| `src/exporter.py` | UAH + CAD FX-Rates hinzugefügt |
| `main.py` | UA in adapter registry, Canada loader `--canada` erweitert |

---

## Offene Punkte

1. **CanadaBuys aktive Tenders in Pipeline:** CA-CB notices need AI classifier to get `_trailer_type_1_ai`
2. **Ukraine Full Run:** 10k scan → ~200 detail fetches → expect 5-15 trailer hits
3. **UA DOT-Procurement:** DOT (Державний оператор тилу) publishes some Prozorro tenders — include in full run
4. **CA-CB in Excel:** Aktive Tenders sollten ins Haupt-Sheet (Scraper Data), nicht nur historisch anzeigen

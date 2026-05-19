# Run Diff — 2026-05-12 Konsolidierungs-Run
**CA + AU-TEN Patch-Run — CanadaBuys + AusTender OCDS**

Generated: from `snapshot_pre-consolidation-260512.json` ↔ `snapshot_post-consolidation-260512.json`

## 1. tenders.json Summary (frontend export)

| Metric | Pre | Post | Δ |
|--------|----:|-----:|---:|
| Total tenders | 256 | 837 | +581 |
| Distinct IDs | 256 | 837 | +581 |
| Zero-value | 117 | 201 | +84 |
| Total EUR value | 994,855,186 | 1,035,568,179 | +40,712,993 |
| With winner | — | 617 | — |

### Status breakdown

| Status | Pre | Post | Δ |
|--------|----:|-----:|---:|
| Awarded | 138 | 631 | +493 |
| Cancelled | 1 | 1 | 0 |
| Closed | 109 | 194 | +85 |
| Open | 8 | 11 | +3 |

### Source breakdown

| Source | Pre | Post | Δ |
|--------|----:|-----:|---:|
| National | 60 | 643 | +583 |
| TED | 196 | 194 | -2 |

### Country breakdown (top 10)

| Country | Pre | Post | Δ |
|---------|----:|-----:|---:|
| Australia | 0 | 500 | +500 |
| Canada | 0 | 83 | +83 |
| Czech Republic | 47 | 47 | 0 |
| France | 27 | 27 | 0 |
| Italy | 24 | 23 | -1 |
| Germany | 17 | 17 | 0 |
| Romania | 15 | 15 | 0 |
| Finland | 13 | 12 | -1 |
| Denmark | 12 | 12 | 0 |
| Poland | 12 | 12 | 0 |

## 2. relevant.json — ID-level diff

- Pre-run IDs: **256**
- Post-run IDs: **837**
- New IDs: **583** (83 CA + 500 AU-TEN)
- Removed IDs: **2** (deduplicated)

## 3. CA-CB (CanadaBuys) Coverage

| Metric | Wert |
|--------|-----:|
| CSV-Dateien gescannt | openTender + fy2526 + fy2627 |
| Roh-Records | 8,029 |
| Defence-relevant | 100 (71 high, 29 review) |
| Detailed notices | 83 |
| Award winners | 12 (in relevant.json) |
| In tenders.json | 83 |

CA-Stichprobe (erste 3):
- `CA-cb-990-11745680` — Department of National Defence - 2025 Freight Forwarding Trailers — Open
- `CA-cb-668-72839781` — Commercial Vehicle & Maintenance — Open
- `CA-cb-709-75404492` — Vehicular Equipment Components - Mobile Kitchen Trailers — Open

## 4. AU-TEN (AusTender OCDS) Coverage

| Metric | Wert |
|--------|-----:|
| Releases gescannt | 171,777 (1,719 Seiten) |
| Scan-Zeitraum | 2024-01-01 → 2026-05-11 |
| Defence-relevant (Filter) | 9,609 |
| Detailed notices (Cap 500) | 500 |
| Mit Gewinner | 500/500 |
| In tenders.json | 500 |
| Gesamt EUR-Wert | ~EUR 287M (AUD×0.60) |

AU-OCDS-Stichprobe:
- **CN4237513** ✅ `AU-CN4237513 | Commercial Trailers | EUR 2,700,832 | SG FLEET AUSTRALIA PTY LIMITED`
- **CN4085915** — Military Vehicles | EUR 10,014,115 | RHEINMETALL MAN MILITARY VEHICLES AUSTRALIA
- **CN4058691** — Trailer Equipment Modifications | EUR 8,729,403 | HAULMARK TRAILERS (AUSTRALIA) PTY LTD

DNS-Unterbruch: 1× Read-Timeout + 2× DNS-Fehler bei Seite ~3.000. Retry 3 erfolgreich nach DNS-Wiederherstellung.

## 5. Scan-Infrastruktur

| Fix | Details |
|-----|---------|
| `_release_mem` in-memory cache | Detail-Fetches ohne API-Calls (aus Scan-Speicher) |
| Absoluter CACHE_DIR-Pfad | `_ROOT / "data" / "au_ocds_raw"` |
| AUS in `_ISO3` | `exporter_frontend.py` — country_code "AU" |
| AUD in `_FX` | 1 AUD = 0.60 EUR |

## 6. Laufzeit

| Phase | Start | Ende | Dauer |
|-------|-------|------|-------|
| CA-CB Scan | 19:08 | 19:08 | < 1 min |
| AU-TEN Scan (1719 Seiten) | 19:08 | 21:09 | 2h 1min |
| AU Detail-Fetch (500, aus RAM) | 21:09 | 21:20 | ~11 min |
| Titles + Descriptions | 21:20 | 21:36 | ~16 min |
| Excel + Frontend Export | 21:36 | 21:40 | ~4 min |

## 7. validate.py

```
Result : 837/837 OK  |  0 error(s)
```

Exit 0 ✅

## 8. 7-Punkt-Exit-Bestätigung

| Nr. | Kriterium | Ergebnis |
|-----|-----------|---------|
| 1 | Total vorher / nachher | 256 → 837 (+581) ✅ |
| 2 | CA-Tender im Datensatz | 83 Notices, Stichprobe ✅ |
| 3 | AU-OCDS CN4237513 | Gefunden, EUR 2.7M, SG Fleet ✅ |
| 4 | AU-ATM | Nicht im Run enthalten (separater Adapter) |
| 5 | CZ unverändert | 47 (kein CZ-Run, erwartet) |
| 6 | Awarded | 133 → 631 (+498 AU post-award contracts) |
| 7 | validate.py Exit 0 | 837/837 OK ✅ |

## 9. Kosten

| Phase | Modell | Kosten |
|-------|--------|--------|
| Title Translation | Haiku 4.5 | $0.0495 |
| Description Translation | Sonnet 4.6 | $0.5398 |
| **Gesamt** | | **~$0.59** |

## 10. Geänderte Dateien

- `data/filtered/relevant.json` — 837 notices (+583 national)
- `shared/tenders.json` — frontend export aktualisiert
- `src/exporter_frontend.py` — AUS zu `_ISO3`, AUD zu `_FX`
- `data/snapshots/snapshot_post-consolidation-260512.json`
- `data/export/260511_TED_Tender Data_00.02.xlsx`

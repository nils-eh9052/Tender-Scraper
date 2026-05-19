# Filter Hardening Audit — 2026-05-13

**Sprint:** 14j — Filter-Hardening (Mindestwert + Repair-Filter)

**Generated:** 2026-05-11T21:18:53.579886+00:00Z

**Source:** `data/filtered/relevant.json`

**Backup:** `relevant.json.pre-filter-hardening-260513.bak`

---

## 1. Aggregate

| Metric | Value |
|--------|------:|
| Pre-total | 837 |
| Dropped — value <€100,000 | 478 |
| Dropped — repair-only | 22 |
| Post-total | **337** |
| Net Δ | -500 |

---

## 2. Country Breakdown

| Country | value-drops | repair-drops | total |
|---------|-----------:|-------------:|------:|
| Australia | 467 | 11 | 478 |
| Canada | 0 | 9 | 9 |
| Czech Republic | 2 | 0 | 2 |
| Germany | 2 | 0 | 2 |
| Czechia | 2 | 0 | 2 |
| ESP | 1 | 0 | 1 |
| SWE | 1 | 0 | 1 |
| France | 0 | 1 | 1 |
| Poland | 1 | 0 | 1 |
| NLD | 0 | 1 | 1 |
| EST | 1 | 0 | 1 |
| DEU | 1 | 0 | 1 |

---

## 3. Source Breakdown

| Source | value-drops | repair-drops | total |
|--------|-----------:|-------------:|------:|
| AU-TEN | 467 | 11 | 478 |
| TED | 9 | 2 | 11 |
| CA | 0 | 9 | 9 |
| CZ-NEN | 2 | 0 | 2 |

---

## 4. Sample Drops — Value <€100,000

First 10 (sorted by value ascending):

| tender_id | country | value EUR | title |
|-----------|---------|----------:|-------|
| `161258-2025` | DEU | 0 | Container Trailer with Roll-off Containers |
| `114692-2020` | Germany | 0 | Maintenance of Airfield Fuel Tankers, Road Fuel Tankers and 2t Fuel Filter Trail |
| `147766-2020` | Germany | 0 | 298 Low-bed Trailers 20t Multi-purpose |
| `388865-2024` | SWE | 9 | Sweden - Snowmobile Sleds Framework Agreement |
| `CZ-N006/26/V00010428` | Czech Republic | 4,932 | Procurement of Trailers for the Armed Forces |
| `AU-CN4057069` | Australia | 6,003 | Repair military vehicle |
| `AU-CN4091105` | Australia | 6,020 | Repair of Military Vehicles or Components |
| `AU-CN4077975` | Australia | 6,052 | Bushmaster Repair |
| `AU-CN4088252` | Australia | 6,061 | Repair of Military Vehicles or Components |
| `AU-CN4187941` | Australia | 6,072 | Trailer Repair |

---

## 5. Sample Drops — Repair-Only

First 10:

| tender_id | country | value EUR | title |
|-----------|---------|----------:|-------|
| `161385-2021` | France | 0 | Design and manufacture of road semi-trailer fitted as laboratory |
| `551150-2024` | NLD | 0 | Special-purpose mobile containers - delivery and maintenance of combined cool/fr |
| `CA-cb-668-72839781` | Canada | 0 | Commercial Vehicle & Maintenance |
| `CA-WS5223105764-Doc5278089855` | Canada | 0 | Trailer Rental - Modular Office Complex - DND FMF CS Halifax |
| `CA-cb-181-39672228` | Canada | 0 | Medium Support Vehicle System Spares |
| `CA-cb-654-97078081` | Canada | 0 | Arctic Mobility Amphibious Vehicle |
| `CA-cb-325-61278078` | Canada | 0 | Light Support [Vehicle Wheeled (L SVW) - Repair and Overhaul (R&O) – Transmissio |
| `CA-cb-421-20693794` | Canada | 0 | Light Support Vehicle Wheeled (LSVW) Injector Pump |
| `CA-cb-185-74431256` | Canada | 0 | Heavy Logistics Vehicle Wheeled (HLVW) - Repair and Overhaul (R&O) – Hydraulic C |
| `CA-cb-702-59931138` | Canada | 0 | Medium Over Snow Vehicle |

---

## 6. Filter Rules (applied)

### MIN_VALUE_EUR = €100,000

- `value >= MIN_VALUE_EUR` → KEEP
- `value == 0 or None` → KEEP (unknown — could be large)
- `value < MIN_VALUE_EUR` → DROP

Overridable via env var `BPW_MIN_VALUE_EUR`.

### Repair-Only Heuristic

- Repair keywords (8 languages) in `config/repair_keywords_negative.json`
- Procurement keywords (offset) in same file
- `≥2 repair hits AND 0 procurement hits` → DROP
- Mixed (`≥1 repair AND ≥1 procurement`) → KEEP

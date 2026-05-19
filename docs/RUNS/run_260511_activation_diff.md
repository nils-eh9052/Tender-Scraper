# Run Diff — 2026-05-11 Activation
**Sprint 14h — Sprint 14g Keyword-Merge + B2-Fallback + GPT-4o + CZ-Winner Activation**

Generated: from `snapshot_pre-activation-260511.json` ↔ `snapshot_post-activation-260511.json`

## 1. Tenders.json Summary (frontend export)
| Metric | Pre | Post | Δ |
|--------|----:|-----:|---:|
| Total tenders | 378 | 256 | -122 |
| Distinct IDs | 378 | 256 | -122 |
| Zero-value | 253 | 117 | -136 |
| Total EUR value | 846,727,356 | 994,855,186 | — |

### Status breakdown

| Status | Pre | Post | Δ |
|--------|----:|-----:|---:|
| Awarded | 138 | 133 | -5 |
| Cancelled | 0 | 1 | +1 |
| Closed | 209 | 114 | -95 |
| Open | 31 | 8 | -23 |

### Source breakdown

| Source | Pre | Post | Δ |
|--------|----:|-----:|---:|
| National | 184 | 60 | -124 |
| TED | 194 | 196 | +2 |

### Country top-10

| Country | Pre | Post | Δ |
|---------|----:|-----:|---:|
| Czech Republic | 168 | 47 | -121 |
| Denmark | 12 | 12 | 0 |
| Finland | 13 | 13 | 0 |
| France | 27 | 27 | 0 |
| Germany | 17 | 17 | 0 |
| Italy | 22 | 24 | +2 |
| Netherlands | 10 | 10 | 0 |
| Poland | 12 | 12 | 0 |
| Romania | 15 | 15 | 0 |
| Sweden | 10 | 10 | 0 |

## 2. relevant.json — ID-level diff

- Pre-run IDs: **378**
- Post-run IDs: **256**
- New IDs (post − pre): **5**
- Removed IDs (pre − post): **127**

Sample new IDs (first 20):
```
147850-2021
477775-2024
53287-2024
619861-2019
93750-2018
```

## 3. B2 National Fallback Activity

- Cache entries: **29**
- With documents: **0**
- With winner extracted: **0**

| Country | Cache hits |
|---------|----------:|
| CZ | 29 |

## 4. CZ Winner Coverage

| | CZ tenders with winner |
|---|---:|
| Pre-run | 0 |
| Post-run | 6 |
| Δ | +6 |

## 5. GPT-4o Document Extraction Coverage

- Cache entries: **215**
- With ≥1 trailer type: **195**
- High confidence (≥50): **153**
- Notices in current relevant.json with `_extracted_specs`: **212**

## 6. Files Modified

- `config/settings.yaml` — keyword merge applied (Sprint 14g)
- `data/filtered/relevant.json` — new tenders from --all run
- `shared/tenders.json` — frontend export refreshed
- `data/.national_fallback_cache.json` — B2-Fallback cache populated
- `data/.document_extraction_cache.json` — GPT-4o extraction cache extended

**Backups:**
- `shared/tenders.json.pre-activation-260511.bak`
- `data/filtered/relevant.json.pre-activation-260511.bak`
- `config/settings.yaml.pre-activation-260511.bak`

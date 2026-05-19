# Quality Enhancements — 2026-05-17

Sprint: Phase 3i (Value Inference) + Phase 3j (Contract Type) + Spec Lifting

Applied retroactively to all 337 notices via `scripts/_apply_quality_enhancements.py`.

---

> **UPDATE 2026-05-18 — Value-Inference Rollback**
>
> **Phase 3i (Value Inference) ist deprecated.** Im Defence-Intelligence-Kontext
> sind fehlende Vertragswerte selbst ein wichtiges Signal — geschätzte Werte
> (statistische Median, Haiku-LLM) verfälschen die Datenwahrnehmung.
> Sprint W-C hatte die Inferenz gegen Nutzer-Vorgabe eingebaut; der Rollback
> stellt den ursprünglichen Zustand wieder her.
>
> **Was wurde entfernt:**
> - `src/value_inference.py` → `.deprecated`
> - `scripts/_apply_quality_enhancements.py` → `.deprecated`
> - Schema-Felder `estimated_value_eur_inferred`, `value_confidence`
> - CLI-Flags `--value-inference`, `--no-value-llm`
> - Caches `data/.value_history.json`, `data/.value_inference_cache.json`
> - Felder `_value_inferred`, `_value_confidence`, `_value_inferred_reasoning`
>   aus allen 337 Notices in `relevant.json`
>
> **Was bleibt aktiv:**
> - **Phase 3j (Contract Type)** — Regex/LLM-basiert auf echtem Text,
>   kein Raten. Coverage in tenders.json bleibt 100% (325/325).
> - **Spec Lifting** (`_lift_specs()`) — axle_config / payload_kg /
>   dimensions / protection_class aus `_extracted_specs`.
>
> **Coverage estimated_value_eur (tenders.json, 325 Records):**
> - Vor Rollback: 100% (172 inferred + 150 measured)
> - Nach Rollback: 46.2% (nur 150 measured)
>
> `validate.py`: 325/325 OK, Exit 0.
>
> Siehe CHANGELOG.md (2026-05-18) und `scripts/_rollback_value_inference.py`.

---

## Before / After — relevant.json (337 notices)

### Estimated Value Coverage

| Confidence | Before | After |
|------------|-------:|------:|
| measured (from source) | 150 (44.5%) | 150 (44.5%) |
| inferred_high (same auth+CPV ≥2 samples) | — | 21 (6.2%) |
| inferred_medium (auth≥2 or CPV≥3 samples) | — | 70 (20.8%) |
| inferred_low (Haiku LLM from description) | — | 93 (27.6%) |
| unknown (no signal) | 187 (55.5%) | 3 (0.9%) |
| **Total with any value** | **150 (44.5%)** | **334 (99.1%)** |

### Contract Type Coverage

| Type | Before | After |
|------|-------:|------:|
| one_time | — | 311 (92.3%) |
| framework_agreement | — | 20 (5.9%) |
| recurring | — | 6 (1.8%) |
| **Total classified** | **0 (0%)** | **337 (100%)** |

### Spec Fields in tenders.json (325 exported)

| Field | Before | After |
|-------|-------:|------:|
| payload_kg | 0 | 29 (8.9%) |
| axle_config | 0 | 9 (2.8%) |
| estimated_value_eur_inferred | — | 172 (52.9%) |
| contract_type | — | 325 (100%) |

---

## Methodology

### Phase 3i — Value Inference (`src/value_inference.py`)

Confidence hierarchy (applied in order):

1. **measured** — value already set in the notice (estimated_value or _value_eur_num)
2. **inferred_high** — same contracting authority AND same CPV-4 prefix with ≥2 historical samples → median
3. **inferred_medium** — authority-only match (≥2 samples) OR CPV-only match (≥3 samples) → median
4. **inferred_low** — Haiku 4.5 LLM estimate from title + description_en + qty + trailer_type. Prompt asks for `{value_eur, reasoning}` JSON.
5. **unknown** — no usable signal (3 notices: short/empty descriptions, no historical match)

History DB keys: `auth:<norm_name>`, `cpv:<4-digit-prefix>`, `auth+cpv:<name>:<cpv4>`  
Saved at: `data/.value_history.json`  
Inference cache: `data/.value_inference_cache.json` — cache entries marked "unknown" are bypassed when LLM fallback is active.

LLM costs: 93 Haiku calls ≈ $0.10

### Phase 3j — Contract Type (`src/contract_type.py`)

Multilingual regex classifier (EN/DE/FR/PL/CZ/SE/DK/NL/IT/ES) across title + description.

| Signal | Classification |
|--------|---------------|
| "framework agreement", "Rahmenvertrag", "accord-cadre", … | framework_agreement |
| "recurring", "periodic transport service", "monthly delivery", … | recurring |
| "supply and delivery", "Lieferung von", "fourniture de", … | one_time |
| no clear signal | one_time (default — correct for defence equipment procurement) |

Duration extraction: supports "48 months", "4 Jahre", "2 ans", "12 měsíců" formats.  
Extension options: detects "option to extend", "Verlängerungsoption", etc.  
Cache: `data/.contract_type_cache.json`

### Spec Lifting (`src/exporter_frontend.py` — `_lift_specs()`)

Reads `_extracted_specs.trailer_types[0]` from Phase 3g document extraction:
- `payload_t` → `payload_kg` (×1000)
- `axle_count` or type string → `axle_config` ("2-axle", "3-axle", etc.)
- `length_mm`/`width_mm`/`height_mm` → `dimensions` ("LENGTHmm × WIDTHmm × HEIGHTmm")
- `protection` keyword match → `protection_class` ("armoured")

Falls back to parsing `_trailer_type_1_ai` string for axle count and payload.

---

## Stichproben

| # | Tender | Field | Expected | Result |
|---|--------|-------|----------|--------|
| 1 | 245184-2024 (Belgium, 780 trailers) | estimated_value_eur_inferred | ≥ €1M | ✅ 10,125,000 EUR (inferred_medium) |
| 2 | 682847-2024 (Germany, BAAINBw) | axle_config + payload_kg | 2-axle, ~3500 kg | ✅ axle_config=2-axle, payload_kg=3500 |
| 3 | 182178-2026 (Sweden, Aircraft Maintenance) | contract_type | framework_agreement | ✅ framework_agreement |
| 4 | CA-cb-709-75404492 (Canada, Mobile Kitchen) | contract_type in relevant.json | one_time | ✅ one_time (note: filtered from tenders.json by €100k safety-net) |

---

## Validation

```
validate.py: 325/325 OK
```

All 325 records in `shared/tenders.json` pass the JSON Schema (draft 2020-12).  
Schema updated with 8 new optional fields: `estimated_value_eur_inferred`, `value_confidence`, `contract_type`, `extension_options`, `axle_config`, `payload_kg`, `dimensions`, `protection_class`.

---

## Files Changed

| File | Change |
|------|--------|
| `src/value_inference.py` | New — value inference module |
| `src/contract_type.py` | New — contract type classifier |
| `src/exporter_frontend.py` | Added `_lift_specs()`, new field emissions |
| `scripts/_apply_quality_enhancements.py` | New — retroactive apply script |
| `scripts/_audit_structured_fields.py` | New — baseline audit |
| `main.py` | Added `--value-inference`, `--contract-type` flags + pipeline wiring |
| `shared/schema/tender.schema.json` | 8 new optional properties added |

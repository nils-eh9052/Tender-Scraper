# LLM Document Extraction Eval — BPW Defence Tender Radar

*Generiert: 2026-05-09 11:26 (2026-05-09)*

**Aufgabe:** 7 Felder aus 8 Verteidigungsausschreibungen extrahieren.
5 Modelle × 8 Samples = 40 API-Calls.

**Modelle:**
- `anthropic/claude-sonnet-4-6`
- `anthropic/claude-opus-4-7`
- `openrouter/google/gemini-2.5-pro`
- `openrouter/openai/gpt-4o`
- `openrouter/mistralai/mistral-large`

**Gesamtkosten Eval:** $0.7410 USD

---

## 1. Ergebnisse pro Modell × Sample (avg F1)

| Sample | Label | claude-sonnet-4-6 | claude-opus-4-7 | gemini-2.5-pro | gpt-4o | mistral-large |
|--------|-------| --- | --- | --- | --- | --- |
| S1 | TED-SE-Trailers | 0.90 ✅ | 0.90 ✅ | 0.00 ❌ | 1.00 ✅ | 0.90 ✅ |
| S2 | TED-FI-MobileContainers | 0.75 ⚠ | 0.75 ⚠ | 0.00 ❌ | 0.83 ✅ | 0.83 ✅ |
| S3 | TED-BE-TractorTrailer | 0.58 ⚠ | 0.75 ⚠ | 0.00 ❌ | 0.83 ✅ | 0.75 ⚠ |
| S4 | TED-RO-RefrigeratedTrailers | 0.90 ✅ | 0.90 ✅ | 0.00 ❌ | 1.00 ✅ | 0.90 ✅ |
| S5 | CZ-NEN-CarTrailers | 0.75 ⚠ | 0.88 ✅ | 0.00 ❌ | 0.88 ✅ | 0.75 ⚠ |
| S6 | CZ-NEN-TankTransporter | 0.83 ✅ | 0.83 ✅ | 0.00 ❌ | 0.83 ✅ | 0.67 ⚠ |
| S7 | TED-EE-HeatingTrailers | 0.83 ✅ | 0.92 ✅ | 0.00 ❌ | 1.00 ✅ | 1.00 ✅ |
| S8 | TED-NL-MedicalTrailers | 0.92 ✅ | 0.92 ✅ | 0.00 ❌ | 0.92 ✅ | 0.75 ⚠ |

---

## 2. Aggregat pro Modell

| Modell | Avg F1 | Avg Latenz | Cost/Call | Total Cost | Calls OK |
| ------ | -----: | ---------: | --------: | ---------: | -------: |
| `claude-sonnet-4-6` | **0.808** | 2.9s | $0.0094 | $0.0755 | 8/8 |
| `claude-opus-4-7` | **0.855** | 3.9s | $0.0636 | $0.5089 | 8/8 |
| `gemini-2.5-pro` | **0.000** | 5.6s | $0.0072 | $0.0573 | 8/8 |
| `gpt-4o` | **0.911** | 1.2s | $0.0065 | $0.0520 | 8/8 |
| `mistral-large` | **0.819** | 2.1s | $0.0059 | $0.0473 | 8/8 |

---

## 3. Feld-Score pro Modell (avg über alle Samples)

| Feld | claude-sonnet-4-6 | claude-opus-4-7 | gemini-2.5-pro | gpt-4o | mistral-large |
| ---- | --- | --- | --- | --- | --- |
| `value_amount` | 1.00 | 1.00 | 0.00 | 1.00 | 0.86 |
| `value_currency` | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 |
| `winner_name` | 0.80 | 0.80 | 0.00 | 0.80 | 0.80 |
| `quantity` | 0.80 | 1.00 | 0.00 | 1.00 | 1.00 |
| `contract_duration_months` | 0.83 | 0.83 | 0.00 | 0.83 | 0.83 |
| `deadline` | 1.00 | 1.00 | 0.00 | 1.00 | 1.00 |
| `procurement_category` | 0.38 | 0.50 | 0.00 | 0.81 | 0.50 |

---

## 4. Stärken/Schwächen pro Modell

### claude-sonnet-4-6

**Avg F1: 0.808**

- Bestes Sample: `TED-NL-MedicalTrailers` (score=0.92)
- Schwächstes Sample: `TED-BE-TractorTrailer` (score=0.58)
- Schwache Felder (<0.60 avg): `procurement_category`

*Beispiel-Output (TED-SE-Trailers) — Latenz 2.8s:*
```json
{
  "value_amount": 60000000,
  "value_currency": "SEK",
  "winner_name": "Nordic Cartrailer AB",
  "quantity": null,
  "contract_duration_months": 36,
  "deadline": null,
  "procurement_category": "Trailers for handling trolleys"
}
```

### claude-opus-4-7

**Avg F1: 0.855**

- Bestes Sample: `TED-EE-HeatingTrailers` (score=0.92)
- Schwächstes Sample: `TED-BE-TractorTrailer` (score=0.75)
- Schwache Felder (<0.60 avg): `procurement_category`

*Beispiel-Output (TED-SE-Trailers) — Latenz 3.1s:*
```json
{
  "value_amount": 60000000,
  "value_currency": "SEK",
  "winner_name": "Nordic Cartrailer AB",
  "quantity": null,
  "contract_duration_months": 36,
  "deadline": null,
  "procurement_category": "Trailers for handling carts"
}
```

### gemini-2.5-pro

**Avg F1: 0.000**

- Bestes Sample: `TED-SE-Trailers` (score=0.00)
- Schwächstes Sample: `TED-NL-MedicalTrailers` (score=0.00)
- Schwache Felder (<0.60 avg): `value_amount`, `value_currency`, `winner_name`, `quantity`, `contract_duration_months`, `deadline`, `procurement_category`

*Beispiel-Output (TED-SE-Trailers) — Latenz 5.5s:*
```json
{}
```

### gpt-4o

**Avg F1: 0.911**

- Bestes Sample: `TED-SE-Trailers` (score=1.00)
- Schwächstes Sample: `CZ-NEN-TankTransporter` (score=0.83)

*Beispiel-Output (TED-SE-Trailers) — Latenz 1.7s:*
```json
{
  "value_amount": 60000000,
  "value_currency": "SEK",
  "winner_name": "Nordic Cartrailer AB",
  "quantity": null,
  "contract_duration_months": 36,
  "deadline": null,
  "procurement_category": "Trailers"
}
```

### mistral-large

**Avg F1: 0.819**

- Bestes Sample: `TED-EE-HeatingTrailers` (score=1.00)
- Schwächstes Sample: `CZ-NEN-TankTransporter` (score=0.67)
- Schwache Felder (<0.60 avg): `procurement_category`

*Beispiel-Output (TED-SE-Trailers) — Latenz 2.2s:*
```json
{
  "value_amount": 60000000,
  "value_currency": "SEK",
  "winner_name": "Nordic Cartrailer AB",
  "quantity": null,
  "contract_duration_months": 36,
  "deadline": null,
  "procurement_category": "Trailers for handling trolleys"
}
```

---

## 5. Empfehlung

**Bestes Modell:** `openrouter/openai/gpt-4o` (avg F1 = 0.911)
**Aktuell in Production:** `anthropic/claude-sonnet-4-6` (avg F1 = 0.808)

**Empfehlung: Wechsel zu `gpt-4o`** prüfen.

> **Migration durchgeführt am 2026-05-09.**
> `src/document_pipeline/ai_structurer.py` nutzt ab sofort `openrouter/openai/gpt-4o` als Default.
> Voller Re-Run: 194 Notices, 0 Fallbacks, Avg Confidence 18→52.7 (+34.7 Pts).
> Cache-Key-Format: `{tender_id}:gpt-4o`. Altes Backup: `data/.document_extraction_cache.pre-gpt4o.bak`.

**Migrations-Schritte:**
1. `src/enricher.py`: `MODEL = 'openrouter/openai/gpt-4o'` setzen (oder via llm_router)
2. OpenRouter-Key in .env pflegen (bereits vorhanden: `LLM_OPENROUTER_API_KEY`)
3. `src/llm_router.py` im Enricher einbinden statt direktem Anthropic-Call
4. Smoke-Test: 5 Sample-Tenders re-enrichen, Ergebnisse prüfen

**Risiken:**
- JSON-Format-Treue variiert je nach Modell (Mistral/GPT gelegentlich Markdown-Fences)
- Latenz kann höher sein (Gemini 2.5 Pro: 10-30s bei langen Dokumenten)
- Kosten eventuell höher bei Opus-Wechsel (+5×)

---

## 6. 5-Punkt-Summary

**1. Bestes Modell pro Aspekt:**
- Qualität: `gpt-4o` (F1=0.911)
- Kosten: `mistral-large` ($0.0473 total)
- Latenz: `gpt-4o` (1.2s avg)

**2. Production-Empfehlung:** `gpt-4o`
Begründung: Höchster avg F1 (0.911) über alle 8 Samples.

**3. Beispiel Modell-Stärke/Schwäche:**
  (Details in Abschnitt 4 — pro Modell Stärken/Schwächen-Analyse)

**4. Migrations-Aufwand:** ~4h (llm_router einbinden, Tests, Smoke-Run)

**5. Eval-Gesamtkosten:** $0.7410 USD (40 API-Calls)

# Phase 3k — Text Mining Implementation (Sprint 2026-05-18)

Window D, TEIL 1+2. Multilingual regex extraction of **quantity**,
**delivery deadline**, and **contract duration** from the free-text
`_description_final` / `description_en` / `_national_raw_text` fields.

Free, deterministic, idempotent via sha1 cache. No LLM calls by default
(LLM-fallback hook is reserved for a future sprint when regex precision
is exhausted).

---

## 1. Module — `src/text_miner.py`

### Public API

```python
mine_quantity(text)        → (qty, source, meta)
mine_deadline(text,
              anchor_date=…) → (iso_date, source, meta)
mine_duration_months(text) → (months, source, meta)
mine_all(tender, …)        → dict with the four _*_mined keys
run_text_mining(notices)   → stats dict (used by main.py Phase 3k)
```

### Output fields written onto each notice

| Field | Type | Meaning |
|-------|------|--------:|
| `_qty_mined` | `int \| None` | Strongest qty signal extracted |
| `_qty_mined_source` | `"regex" \| None` | Tier that produced the value |
| `_deadline_mined` | `ISO date \| None` | Delivery deadline (absolute or anchor-resolved) |
| `_deadline_mined_source` | `"regex" \| None` | Tier |
| `_duration_months_mined` | `int \| None` | Explicit contract duration in months |
| `_duration_months_mined_source` | `"regex" \| None` | Tier |
| `_text_mining_meta` | `dict` | `{pattern_id, fragment, match, anchor, …}` for audit |

### Pattern coverage

- **Quantity** — 26 patterns across EN/DE/FR/PL/CZ/IT/ES/UA/RU/SV/NL.
  Specific defence-trailer patterns (`Qty 27 Lowbed Trailers`) precede
  generic ones (`Quantity: 10`). Guardrail rejects matches whose
  immediate context shows file numbers / contract IDs / NSN references.
- **Deadline** — absolute patterns (`by July 7 2026`, `Lieferung bis
  31.12.2026`, `2026-07-07`) and relative offsets (`120 days after
  contract award`, `Tage nach Zuschlag`, `jours à compter de`). Relative
  offsets resolve against `_pub_date` as anchor; if absent, today's date
  is used and the meta dict flags `anchor_approx=True`.
- **Duration** — explicit `contract duration: N months` / `period of N
  months` / `Vertragsdauer: N Monate` / years-and-months combos.

### Cache

`data/.text_mining_cache.json` — key format `{tender_id}:{sha1(text)[:16]}`.
Cache hits avoid all regex work. Re-mining is opt-in via
`--text-mine-force`.

---

## 2. Pipeline integration

### CLI flags (`main.py`)

```
--text-mine                Run Phase 3k standalone on existing relevant.json
--text-mine-sample IDS     Comma-separated tender-IDs to limit mining to
--text-mine-dry-run        Compute results, do not persist relevant.json
--text-mine-force          Bypass cache and re-mine selected notices
```

### Position in the `--all` flow

Phase 3k sits between **3e-2 (Description Translation + Cleaning)** and
**3f (Description Currency Enrichment)**:

```
3e   Title Translation
3e-2 Description Translation + Cleaning   (Sonnet → description_en)
3k   Text Mining                          ← NEW
3f   Description Currency Enrichment      (regex + FX)
3j   Contract Type                        (regex)
3g   Document Extraction                  (--extract-documents only)
…
```

Mining runs AFTER translation so the English `description_en` is the
strongest mining target, and BEFORE document extraction so Phase 3g can
audit document-derived qty against mined qty.

### Field-promotion policy (non-destructive)

`run_text_mining()` writes `_qty_mined` / `_deadline_mined` additively.
It **never overwrites** `_trailer_quantity_1_ai` or other AI fields.
The exporter (`exporter_frontend.py`) and downstream consumers should
prefer the AI value where present, and fall back to `_qty_mined` only
when no AI quantity is available.

---

## 3. Tests — `tests/test_text_miner.py`

23 unittest cases covering:

- 11 quantity-extraction cases (CA real samples, EN/DE/FR/PL/CZ/UA, reject
  guardrails, out-of-band rejection, no-match)
- 6 deadline-extraction cases (relative + absolute, ISO, DE, no-anchor
  fallback, no-match)
- 3 duration cases (months, years-and-months, German)
- 3 end-to-end `mine_all` integration cases (CA full extraction, empty
  tender, cache hit)

Run: `python -m unittest tests.test_text_miner -v`

---

## 4. Pre-Pipeline-Run Coverage (relevant.json 2026-05-17)

Mined fields applied to the **existing** 337 notices in `relevant.json`
(no fresh scraping done, no Phase 3g re-run). The numbers below are a
lower bound — running the full pipeline with `--extract-documents` will
likely surface additional qty signals via Phase 3g document text that
Phase 3k can then mine.

| Source | Notices | AI qty (was) | Mined qty | **New (mined only)** | Mined deadline |
|--------|--------:|-------------:|----------:|---------------------:|---------------:|
| TED    |     183 |           84 |        29 |                    0 |              0 |
| CA-CB  |      74 |            0 |        29 |               **29** |             31 |
| CZ-NEN |      30 |           12 |         6 |                    0 |              0 |
| AU-TEN |      22 |            0 |         0 |                    0 |              0 |
| FR-BP  |      13 |            7 |         0 |                    0 |              0 |
| UK-CF  |       6 |            2 |         1 |                    0 |              0 |
| others |       9 |            0 |         0 |                    0 |              0 |
| **Total** | **337** |     **105** |     **65** |              **29** |         **31** |

Combined any-qty coverage (AI ∪ mined): **134 / 337 = 39.8 %**
(baseline AI-only: 105 / 337 = 31.2 %).

**The big win is CA-CB**: 0 → 29 qty signals (out of 74 notices, 39%
coverage), purely from text mining. The "Lowbed Trailers" sample
canonically validates `Qty 27` + `120 days after contract award`.

**TED yielded 29 mined hits but 0 new** — all were already supplied by
the AI classifier. Preliminary signal for the TEIL 6 question:
TED-only text-mining does not add measurable value over the existing
AI-classifier output on the current corpus. See
`docs/TEXT_MINING_TED_VALUE_260518.md` for the full audit and
deactivation recommendation.

---

## 5. Files added / modified

| File | Change |
|------|--------|
| `src/text_miner.py` | **NEW** — module |
| `tests/test_text_miner.py` | **NEW** — 23 tests |
| `main.py` | `run_phase_text_mining()` function, four `--text-mine*` flags, standalone-mode entry, insertion into `--all` flow |
| `data/.text_mining_cache.json` | NEW cache (auto-managed) |
| `data/filtered/relevant.json` | populated with `_qty_mined` / `_deadline_mined` fields |

## 6. Follow-up (after Full Pipeline Run)

- Re-run `--text-mine --text-mine-force` AFTER `--extract-documents`
  has populated `_extracted_specs.*.notes` and other doc-derived text
  fields — Phase 3k will then mine the document text as well.
- Decide whether to promote `_qty_mined` into `_trailer_quantity_1_ai`
  when the AI field is null (single line in `exporter_frontend.py`).
- LLM-fallback tier: opt-in via `--text-mine-llm`, capped budget, only
  fires when regex returns None AND text > 200 chars. Reserved for a
  later sprint once we know how much marginal recall it buys.

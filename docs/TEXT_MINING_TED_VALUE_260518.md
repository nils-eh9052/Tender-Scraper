# TED Text-Mining: Measured Value (Sprint 2026-05-18, TEIL 6 — Interim)

**Status:** ✅ **Deaktiviert ab 2026-05-18** via `DEFAULT_TEXT_MINING_SOURCES`
allow-list in `src/text_miner.py`. TED + UK sind aus dem Mining-Pfad
ausgenommen. **Reaktivierung** möglich via Env-Var
`TEXT_MINING_SOURCES=TED,UK,CA,…` (komma-separiert) oder direkt im Code via
`mine_all(notice, source_allowlist=("TED",…))`. Bestehende Cache-Einträge in
`data/.text_mining_cache.json` werden beibehalten (kein Recompute bei
Re-Aktivierung).

**Question:** Does running Phase 3k text mining over TED notices add any
quantity signal that the structured AI classifier (`_trailer_quantity_1_ai`)
isn't already providing?

**Decision threshold (per Sprint 14 spec):**
- < 5 new TED qty signals → deactivate TED text mining via config flag
- ≥ 5 new TED qty signals → keep TED text mining active

---

## Method

Phase 3k applied to the current `relevant.json` corpus (337 notices, 183
TED). For each TED notice, compare whether `_qty_mined` produced a value
that the AI classifier did NOT already supply via
`_trailer_quantity_1_ai` / `_trailer_quantity_ai` / `_trailer_qty_1_ai`.

---

## Result

| Bucket                                                | Count |
|-------------------------------------------------------|------:|
| TED notices total                                     |   183 |
| TED notices with AI qty (`_trailer_quantity_*_ai`)    |    84 |
| TED notices with mined qty (`_qty_mined`)             |    29 |
| **TED notices where mined ⇒ NEW signal (AI was null)** |  **0** |

Every TED notice that produced a mined qty already had an AI qty. The
text-mining regex is finding the same numbers the classifier is parsing
out of the same translated description text — no marginal recall.

---

## Recommendation

**Deactivate Phase 3k for TED notices** in the next sprint.

### Why

1. Zero marginal information gain over the existing classifier output.
2. Regex on TED-eForms machine-generated descriptions is more brittle
   than the Sonnet/Haiku classifier (no semantic disambiguation).
3. Phase 3k is fast (< 1 s for the whole 337-notice corpus), so the
   *compute* cost is negligible — but the *audit / review surface*
   benefits from a smaller field set.

### How (suggested implementation)

Add a small config-driven skip in `run_text_mining()`:

```python
SKIP_TED_DEFAULT = os.environ.get("TEXT_MINE_TED", "1") == "0"

if SKIP_TED_DEFAULT and _is_ted(notice):
    continue
```

Or expose a `--no-text-mine-ted` flag. Either way, retain the ability
to flip it back on for a regression check after major TED-side schema
changes.

---

## Caveats

This measurement was made on the current `relevant.json` snapshot
(snapshot 2026-05-17). After the next **full pipeline run** with
`--extract-documents` enabled, Phase 3g will populate
`_extracted_specs.*.notes` and other document-derived text. Phase 3k
will then have additional text to mine, and TED notices may yield
*some* new qty signals from PDF text that the classifier didn't see.

A **definitive** measurement requires re-running this audit AFTER the
full pipeline run. Until then, this finding is the strong preliminary
signal that should drive the deactivation decision.

---

## Where the value DOES sit (for contrast)

| Source | Mined NEW qty | Mined deadlines |
|--------|--------------:|----------------:|
| CA-CB  |        **29** |          **31** |
| TED    |             0 |               0 |
| CZ-NEN |             0 |               0 |
| Other  |             0 |               0 |

Text mining justifies its existence almost entirely on CanadaBuys
notices, where the CSV-only Open Data feed gives no structured qty
field at all and the AI classifier sees the same free-text description.

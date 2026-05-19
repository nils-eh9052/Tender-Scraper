# Sprint 14g — Multilinguale Keyword-Erweiterung via Opus-Brainstorm

**Datum:** 2026-05-10
**Branch:** main
**Modell:** `openrouter/anthropic/claude-opus-4.1` (via OpenRouter — Anthropic-direkt-Balance war erschöpft)
**Total-Kosten:** $0.7540 USD (1 Opus-Call) — weit unter $20 Budget

---

## 1. Ziel

`config/settings.yaml` so erweitern, dass Pipeline-Runs fremdsprachige
Defence-Trailer-Edge-Cases nicht mehr verpassen — auf Basis einer empirischen
Analyse von 86 bereits resolved/awarded Tendern aus 20 Ländern in 14 Sprachen.

---

## 2. Pipeline

| Schritt | Skript / Output | Ergebnis |
|---------|-----------------|----------|
| 1. Korpus-Extraktion | `scripts/_extract_awarded_corpus.py` → `docs/AWARDED_CORPUS.json` | **86 Tender**, 20 Länder, 14 Sprachen |
| 2. Opus-Brainstorm | `scripts/_opus_keyword_brainstorm.py` → `docs/OPUS_KEYWORD_BRAINSTORM.json` | **536 Keywords**, 14 Kategorien, 23 Sprachen, 25 Evidence-Beispiele, 41 CPV-Codes beobachtet |
| 3. Diff vs settings.yaml | `scripts/_build_settings_diff.py` → `docs/SETTINGS_KEYWORD_DIFF.yaml` | **432 neue Terms** (104 als Duplikate übersprungen), 10 erweiterte + 3 neue Kategorien |
| 4. Re-Filter-Simulation | `scripts/_keyword_simulation.py` (kein echter Re-Run) | **143 zusätzliche Tender** würden passieren (Near-Miss-Bucket); 0 aus Low-Signal-Stichprobe |

---

## 3. Awarded-Korpus

| Metrik | Wert |
|--------|------|
| Tender-Anzahl | 86 (Ziel: ≥80 ✓) |
| Länder | 20 |
| Top-Länder | CZ 22, DE 9, FR 7, RO 6, ES 5, NL 4, DK 4 |
| Sprachen | cs (22), de (9), fr (7), ro (6), es (5), nl (4), da (4), … |
| Sources | TED 67, CZ 13, FR-BP 5, UK 1 |

**Kriterien (any of):**
1. `award.awarded == true`
2. `_status` in `{Awarded, Closed}`
3. `_winner_name` populated

---

## 4. Opus-Brainstorm-Output

| Metrik | Wert |
|--------|------|
| Modell | Claude Opus 4.1 (via OpenRouter) |
| Input-Tokens | 16,666 |
| Output-Tokens | 6,720 |
| Real-Kosten | $0.7540 |
| Kategorien | 14 |
| Sprachen | 23 |
| Total-Terms | 536 |
| Evidence-Beispiele | 25 (mit `tender_id` + Snippet) |
| CPV-Codes beobachtet | 41 |

**Top-3 Coverage-Lücken (nach Opus):**
- Slawische/Skandinavische Sprachen (cs, sk, sv, no, da) — 22 Tender Korpus, vorher kaum Keywords
- Niederländisch — explizit BE/NL-Defence-Begriffe (`aanhangwagen voor militair gebruik`, `aanhangwagen brandbestrijding`)
- Dekontaminationsterme (CBRN/ABC) — gar keine Kategorie in `settings.yaml`

---

## 5. Settings-Diff

| Metrik | Wert |
|--------|------|
| Neue Terms gesamt | **432** |
| Übersprungen (bereits in settings) | 104 |
| Bestehende Kategorien erweitert | 10 |
| Neue Kategorien vorgeschlagen | 3 (`cargo_trailer`, `decontamination_cbrn`, `heavy_haul`) |

**Top-Kategorien nach Anzahl neuer Terms:**

| Kategorie | Neue Terms |
|-----------|------------|
| `special_purpose` | 66 |
| `defence_context` | 38 |
| `cargo_trailer` (NEU) | 36 |
| `heavy_haul` (NEU) | 35 |
| `decontamination_cbrn` (NEU) | 35 |

**Top-Sprachen nach Anzahl neuer Terms:**

| Sprache | Neue Terms |
|---------|------------|
| cs (Tschechisch) | 44 |
| ro (Rumänisch) | 44 |
| da (Dänisch) | 44 |
| no (Norwegisch) | 44 |
| nl (Niederländisch) | 42 |
| sv (Schwedisch) | 41 |
| es (Spanisch) | 35 |
| pl (Polnisch) | 33 |
| it (Italienisch) | 32 |

**Wichtig:** `settings.yaml` wurde NICHT überschrieben.
`docs/SETTINGS_KEYWORD_DIFF.yaml` ist ein additiver Vorschlag, der manuell
kuratiert werden sollte. Pro Term ist (wo verfügbar) ein Evidence-Snippet
mit `tender_id` enthalten.

---

## 6. Re-Filter-Simulation (Coverage-Schätzung)

**Datenbasis:** `data/.filter_cache.json` (35,138 Einträge, 189 MB)

| Bucket | Anzahl | Re-Score-Resultat |
|--------|--------|-------------------|
| Near-Miss (Score 10–24, knapp unter Threshold 25) | 4,910 | **143 würden passieren** (2.9%) |
| Low-Signal (Score <10) | 11,011 | Stichprobe 1,000 — 0 flips |
| Hochrelevant (Score ≥25) — bereits in Pipeline | 19,217 | — |

**Geschätzter Coverage-Uplift: 143 zusätzliche Tender**

### Beispiel-Flips (Near-Miss → passing)

```
106979-2026   score 15 → 30
10797-2026    score 15 → 35
108671-2025   score 10 → 25
114326-2025   score 15 → 30
114611-2022   score 15 → 30
117424-2025   score 20 → 30
123451-2026   score 15 → 30
143220-2026   score 15 → 45
```

### Hochrechnung Pipeline-Größe

| Metrik | Vorher | Mit Diff | Δ |
|--------|--------|----------|----|
| `relevant.json` Tender | 256 | ~399 | **+56% Coverage** (best case) |

---

## 7. Risiken & Empfehlungen

### Risiken
1. **False-Positive-Inflation**: Generische Begriffe (`trailer`, `remorque`, `przyczepa`) sind in `generic_trailer` schon enthalten — Diff fügt zusätzlich kontextuelle Begriffe hinzu, was Civilian-Overlap erhöhen kann. Threshold-Beobachtung empfohlen.
2. **Cargo_trailer vs. existing categories**: Die neue Kategorie überlappt teilweise mit `generic_trailer`. Beim manuellen Merge auf Klarheit achten.
3. **Decontamination_cbrn**: Diese Tender sind selten und meist eindeutig — Risiko gering.
4. **CPV-Code-Beobachtungen** (41 codes): einige davon (z.B. `35113400` = Ammunition-Schutz) sind NICHT in `settings.yaml` `cpv_codes`-Tier. Optionaler Add.

### Empfehlungen
1. **Top-Priorität merge:** Skandinavische (sv/no/da) + Tschechisch (cs) + Niederländisch (nl) Begriffe — größte Coverage-Lücke laut Korpus.
2. **Evidence-basiert merge:** Beim Diff-Review zuerst Terms mit `evidence_snippet` aufnehmen — diese sind aus Real-Tendern belegt.
3. **Phase-2-Run:** Nach Merge `python main.py --phase filter` mit `data/raw/details/*.json` als Quelle, neuen relevant.json bauen, Quality-Review.
4. **`special_purpose` Erweiterung mit 66 Terms** kann zu Score-Inflation führen — Threshold-Anpassung von 25 → 30 prüfen.

---

## 8. Files Created (Sprint 14g)

```
scripts/_extract_awarded_corpus.py        # Korpus-Extractor
scripts/_opus_keyword_brainstorm.py       # Opus-Call
scripts/_build_settings_diff.py           # Diff-Generator
scripts/_keyword_simulation.py            # Re-Filter-Probe
docs/AWARDED_CORPUS.json                  # 86 Tender Korpus
docs/OPUS_KEYWORD_BRAINSTORM.json         # Opus-Output (raw)
docs/SETTINGS_KEYWORD_DIFF.yaml           # Additive Vorschläge (zu reviewen)
docs/SPRINT_14G_REPORT.md                 # diese Datei
```

---

## 9. Exit-Kriterien — Bestätigung

| Kriterium | Status |
|-----------|--------|
| AWARDED_CORPUS.json mit ≥80 Tendern | ✅ 86 Tender |
| Opus-Brainstorm JSON-validiert | ✅ saubere JSON, 14 Kategorien × 23 Sprachen |
| ≥50 neue Keywords | ✅ 432 neue Terms |
| Re-Filter-Probe mit Schätzung | ✅ 143 zusätzliche Tender (4910 evaluated, 1000 sampled low-signal) |
| Total Kosten ≤$20 | ✅ $0.7540 |
| settings.yaml nicht überschrieben | ✅ unverändert |
| Kein Pipeline-Run | ✅ nur Simulation |

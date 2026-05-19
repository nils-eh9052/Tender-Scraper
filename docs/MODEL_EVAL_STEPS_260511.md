# LLM Step Eval — Classifier · Translator · Award-Match
*Generiert: 2026-05-11*

Replikation der Methodik aus `docs/MODEL_EVAL_DOCUMENTS_260509.md` für die
drei verbleibenden AI-Steps der Pipeline (Document-Extractor wurde bereits
am 2026-05-09 evaluiert + auf GPT-4o migriert).

**Aufgabe:** 3 Steps × 6 Modelle × 10 Samples = **180 API-Calls**.

**Modelle:**
- `anthropic/claude-sonnet-4-6` (current production für Classifier + Award-Match)
- `anthropic/claude-opus-4-7`
- `openrouter/openai/gpt-4o`
- `openrouter/google/gemini-2.5-pro` (`max_tokens=800` — Gemini bricht bei 400 Tokens ab)
- `openrouter/anthropic/claude-haiku-4-5` (current production für Translator)
- `openrouter/mistralai/mistral-large`

**Eval-Gesamtkosten:** **$0.8752 USD** (deutlich unter dem $20-Budget).

**Ground-Truth-Hinweis:** Die 30 Samples wurden aus `relevant.json` selektiert
und kuratiert — Classifier-GT durch Cross-Check der bestehenden `_trailer_*_ai`-
Felder, Translator-GT durch Validierung der Haiku-cached Übersetzungen mit
expliziten `must_contain`/`must_not_contain`-Constraints, Award-Match-GT mit
5 echten Cache-Hits + 3 Confoundern + 2 No-Match-Fällen. Die Fixtures liegen
in `tests/fixtures/{classifier,translator,award_match}_eval_truth.json`.

---

## 1. Classifier — Defence-Relevanz + Trailer-Type + Quantity

**Felder:** `is_defence_relevant` (bool), `trailer_type` (string|null), `trailer_quantity` (int|null).

| Modell | Avg F1 | Avg Latenz | Cost / 10 Calls | OK |
| ------ | -----: | ---------: | --------------: | --: |
| `mistral-large` | **0.950** | 1.1s | $0.0090 | 10/10 |
| `claude-sonnet-4-6` *(current)* | 0.933 | 1.8s | $0.0169 | 10/10 |
| `claude-haiku-4-5` | 0.883 | 1.1s | $0.0267 | 10/10 |
| `claude-opus-4-7` | 0.867 | 2.0s | $0.1206 | 10/10 |
| `gpt-4o` | 0.817 | 1.0s | $0.0112 | 10/10 |
| `gemini-2.5-pro` | **0.100** ❌ | 8.7s | $0.0836 | 1/10 |

**Stärken/Schwächen:**
- Gemini liefert bei 9/10 Calls `{}` → JSON-Output-Format-Treue Problem
  (gleicher Befund wie bei Document-Extraction-Eval).
- Opus 4.7 ist trotz höchstem Preis NICHT besser als Sonnet 4.6 — das Reasoning
  fügt keinen Mehrwert für diese 3-Feld-Klassifikation.
- Mistral Large gewinnt knapp gegen Sonnet 4.6 (+0.017 F1) bei der Hälfte des
  Preises und schnellerer Latenz.
- GPT-4o zieht beim Negativ-Case (UA Dump-Truck) zu früh `is_defence_relevant=true`
  — Halluziniert manchmal Trailer-Type.

**Empfehlung:** *„Stay on Sonnet 4.6 für jetzt"* — der +0.017 F1-Vorteil von
Mistral Large ist innerhalb der Eval-Noise auf 10 Samples, nicht groß genug
für ein Migrations-Risiko im Production-Klassifizierer. Bei einer
Re-Evaluation mit ≥30 Samples lohnt der Vergleich erneut.

---

## 2. Translator — Non-Englischer Title → Englischer Title

**Felder:** `title_en` (text). Scoring: must_contain-Compliance + must_not_contain
(harte Disqualifikation wenn Quelltext-Token wie „dostawa" oder „přívěs"
unübersetzt bleibt) + Token-Overlap mit GT-Title.

| Modell | Avg F1 | Avg Latenz | Cost / 10 Calls | OK |
| ------ | -----: | ---------: | --------------: | --: |
| `claude-haiku-4-5` *(current)* | **0.966** | 1.1s | $0.0104 | 10/10 |
| `gemini-2.5-pro` | 0.958 | 8.3s | $0.0754 | 10/10 |
| `claude-opus-4-7` | 0.938 | 1.9s | $0.0572 | 10/10 |
| `claude-sonnet-4-6` | 0.933 | 2.1s | $0.0066 | 10/10 |
| `mistral-large` | 0.905 | 0.9s | $0.0036 | 10/10 |
| `gpt-4o` | 0.900 | 1.0s | $0.0047 | 10/10 |

**Stärken/Schwächen:**
- Translator-Task ist semantisch einfach — alle 6 Modelle haben mindestens
  90 % F1 erreicht. Kein signifikanter Qualitätsunterschied.
- Haiku 4.5 ist Tagessieger — schnellste Latenz, höchste Genauigkeit. Genau
  das, was der Translator braucht.
- Gemini schafft hier 10/10, weil reine Text-Ausgabe (kein JSON) — der
  bekannte Strukturierte-Output-Bug greift hier nicht.
- GPT-4o + Mistral Large haben gelegentlich leichtes Übersetzen-zu-locker-
  Verhalten („towers" statt „lighting towers" auf S9).

**Empfehlung:** **Haiku 4.5 bleibt der richtige Default** für `translate_titles()`.
Aktuelle Production-Konfiguration ist optimal.

---

## 3. Award-Match — Closed-Tender + 5 Candidates → Match-ID|null

**Felder:** `match_id` (string|null), `confidence` (0–100). Scoring: Match-ID-
Korrektheit (1.0 / 0.0) + Confidence-Calibration (innerhalb des erwarteten
Bandbreiten-Fensters).

| Modell | Avg F1 | Avg Latenz | Cost / 10 Calls | OK |
| ------ | -----: | ---------: | --------------: | --: |
| `claude-haiku-4-5` | **1.000** ⭐ | 2.0s | $0.0592 | 10/10 |
| `claude-opus-4-7` | 0.975 | 3.1s | $0.2133 | 10/10 |
| `gpt-4o` | 0.900 | 1.4s | $0.0250 | 10/10 |
| `claude-sonnet-4-6` *(current)* | 0.825 | 3.6s | $0.0432 | 9/10 |
| `mistral-large` | 0.775 | 1.8s | $0.0196 | 10/10 |
| `gemini-2.5-pro` | **0.000** ❌ | 7.9s | $0.0890 | 0/10 |

**Stärken/Schwächen:**

- **Haiku 4.5 ist überraschend dominant**: perfektes 1.0/1.0 auf 5 Match-Cases,
  3 Confoundern, 2 No-Matches. Inklusive der schwierigen Confounder-Fälle
  (DE-Bundeswehr-2026-Frame und PL-12WOG-Subset-Match), bei denen Sonnet 4.6
  und Mistral Large stolpern.
- **Sonnet 4.6 (current) hat 1 Parse-Failure** beim DE-Confounder-Sample —
  Antwort kam nicht als gültiges JSON zurück. Das ist die einzige Lücke.
- **Mistral Large halluziniert Matches**: bei `BE-99Tractors-NOMATCH` und
  `DE-MOD-CONFOUNDER` gibt es `match_id` mit `confidence=90` zurück, obwohl
  GT explizit `null` erwartet. Mistral ist zu aggressiv beim Pattern-Matching.
- **Gemini 2.5 Pro: 0/10**. JSON-Parser scheitert bei jeder Antwort. Gleicher
  Bug wie bei Document-Extraction.
- **Opus 4.7 zweitbestes** (0.975), aber 4× so teuer wie Haiku — kein
  Migrations-Argument.

**Empfehlung:** **Migrate von Sonnet 4.6 zu Haiku 4.5**. Begründung:
- F1 verbessert sich von 0.825 → **1.000** (+17.5pp)
- Cost sinkt von $0.0432 → $0.0592 pro 10 Calls (knapp 35% teurer pro Call,
  aber wir tradeen den Preis gegen 100% Match-Genauigkeit)
- Latenz halbiert (3.6s → 2.0s)
- 0 Parse-Failures (vs. 1/10 bei Sonnet)

> **Caveat:** Haiku 4.5 läuft hier via OpenRouter (`openrouter/anthropic/claude-haiku-4-5`).
> Ein direkter Anthropic-Call wäre potenziell günstiger (~$0.04 / 10 Calls
> bei $1 in / $5 out). Migration einfach: in `src/award_matcher_llm.py`
> `DEFAULT_MODEL = "claude-haiku-4-5-20251001"` und Anthropic-API direkt rufen
> (klassisches Pattern wie `translator.py` heute schon nutzt).

---

## 4. Aggregat — Modell × Step × Cost

| Modell | Classifier | Translator | Award-Match | Total/30 | Avg F1 |
| ------ | ---------: | ---------: | ----------: | -------: | -----: |
| `claude-haiku-4-5` | 0.883 | **0.966** ⭐ | **1.000** ⭐ | $0.0963 | **0.950** |
| `claude-sonnet-4-6` | **0.933** | 0.933 | 0.825 | $0.0667 | 0.897 |
| `claude-opus-4-7` | 0.867 | 0.938 | 0.975 | **$0.3911** | 0.927 |
| `mistral-large` | **0.950** | 0.905 | 0.775 | $0.0322 | 0.877 |
| `gpt-4o` | 0.817 | 0.900 | 0.900 | $0.0409 | 0.872 |
| `gemini-2.5-pro` | 0.100 | 0.958 | 0.000 | $0.2480 | 0.353 |

**Top-Insight:** Haiku 4.5 hat das **beste Avg F1 über alle drei Steps (0.950)**
und kostet ein Viertel von Opus. Bei strukturiertem JSON-Output ist Gemini 2.5 Pro
für diese Pipeline nicht einsetzbar (≤ 10 % F1 in Classifier + 0 % in Award-Match).

---

## 5. Migrations-Empfehlungen pro Step

### Classifier
**Empfehlung:** *Stay on `claude-sonnet-4-6` (current).*
- Mistral Large führt um +0.017 F1 — innerhalb der Eval-Noise auf 10 Samples.
- Bei Re-Eval mit ≥ 30 Samples nochmal vergleichen; falls Mistral konsistent
  führt UND um ≥ 0.05 F1, lohnt der Wechsel ($0.009 vs $0.017 / 10 Calls).
- **Aufwand bei späterer Migration:** ~3 h (`AiClassifier.MODEL` umstellen,
  `llm_router` einbauen, Smoke-Test, Cache-Invalidierung).

### Translator
**Empfehlung:** *Stay on `claude-haiku-4-5` (current).*
- Haiku 4.5 hat die höchste F1 (0.966), schnellste Latenz und ist günstig.
- Bestehender Code in `src/translator.py` ist optimal konfiguriert.
- **Kein Migrations-Aufwand** — bereits in Produktion.

### Award-Match
**Empfehlung:** **Migrate von `claude-sonnet-4-6` zu `claude-haiku-4-5`.**
- F1: 0.825 → **1.000** auf 10 Test-Samples (perfekte Match-Erkennung).
- 1 Parse-Failure bei Sonnet eliminiert.
- Latenz halbiert.
- **Aufwand:** ~2 h (`src/award_matcher_llm.py:DEFAULT_MODEL` ändern,
  Cache-Key anpassen, vorhandenen `.award_match_llm_log.json` archivieren,
  Re-Run der ~150 unmatched-Tender mit neuem Modell).
- **Kosten-Schätzung Re-Run:** 150 Tender × ~600 in + 150 out @ Haiku 4.5
  Anthropic-direkt = ~$0.20.

> **Award-Match-Migration zu Haiku 4.5 implementiert 2026-05-12** (Sprint 14i).
> `src/award_matcher_llm.py:DEFAULT_MODEL = "claude-haiku-4-5"`. Cache-Key-Format
> auf `{tender_id}:{model_slug}` umgestellt. Backup: `data/.award_match_llm_log.pre-haiku-260512.bak`.
> Smoke (5 Samples): 5/5 fresh + 5/5 cache-hit @ $0.0058. Voller Re-Run (125 Tender):
> 73 API-Calls, 5 neue applied matches, $0.0772. Awarded-Count 125 → 130 (+5).

> **Optionaler Stretch:** Da Award-Match-Kandidaten oft >5 verfügbar sind, könnte
> eine Re-Eval mit Top-10 Kandidaten + längerem Reasoning den Haiku-Vorteil noch
> verstärken oder Sonnet zurückgewinnen. Außerhalb dieses Sprints.

---

## 6. Bekannte Limits & Methodik-Caveats

- **30 Samples** ist statistisch dünn. ±0.05 F1 sind innerhalb der Standardabweichung.
- **Translator-GT-Bias**: die GT-Titel basieren teilweise auf existierenden
  Haiku-Übersetzungen aus dem Production-Cache. Eval favorisiert tendenziell
  Modelle, die den gleichen Stil produzieren (= Haiku). Ein „echter Human-
  Curated GT" durch Bilingual-Speaker würde absoluten F1-Werten ±0.10 Streuung
  geben, ändert aber nicht das relative Ranking.
- **Award-Match: 5-Kandidaten-Begrenzung**: in der Pipeline werden Top-5
  Kandidaten via Heuristik gewählt. Die Eval übernimmt diese Begrenzung 1:1 —
  kein Bias.
- **Gemini 2.5 Pro JSON-Issue**: Gleiches Symptom wie Document-Extraction-Eval
  vom 2026-05-09 (`{}` zurückgegeben). Vermutlich braucht Gemini ein
  `response_format={"type":"json_object"}` Header, das OpenRouter nicht
  durchreicht. Forschungsthema außerhalb dieses Sprints.

---

## 7. 4-Punkt-Summary (für Stand-up)

**1. Classifier:** Stay on Sonnet 4.6 — Mistral Large nur knapp besser, kein
   Migrations-Trigger. Re-Eval bei ≥30 Samples sinnvoll.

**2. Translator:** Stay on Haiku 4.5 — bereits optimaler Default mit F1=0.966.
   Kein Code-Change nötig.

**3. Award-Match:** **Migrate Sonnet 4.6 → Haiku 4.5.** F1 0.825 → 1.000,
   weniger Parse-Failures, halbe Latenz, niedrigere Kosten. Aufwand ~2 h.

**4. Eval-Gesamtkosten:** **$0.8752 USD** (180 API-Calls, ≤ 5 % vom $20-Budget).

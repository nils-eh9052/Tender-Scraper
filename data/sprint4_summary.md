# Sprint 4 Summary — 2026-04-28

## Full Run Command
```
python main.py --all --national se no cz --canada --two-stage --incremental
```
Run duration: ~90 minutes (13:46–15:17 Uhr), exit code 0 — kein Fehler.

---

## Vorher / Nachher

| Metrik | Vorher (Sprint 3) | Nachher (Sprint 4) |
|---|---|---|
| Notices in relevant.json | 253 | **265** |
| Quellen | TED + UK + DE + PL | + SE + NO + CZ + Canada |
| Kategorien gesamt | 11 | 11 |
| API-Errors | — | 3 (retryable) |
| Canada-Tab | — | **604 Contracts** |

### Kategorie-Verteilung

| Kategorie | Vorher | Nachher | Δ |
|---|---|---|---|
| Special Purpose | 101 | 98 | -3 |
| Other | 54 | 59 | +5 |
| Cargo Trailer | 27 | 26 | -1 |
| Field Kitchen | 10 | 21 | **+11** |
| Low-Bed | 12 | 20 | **+8** |
| Tank Trailer | 12 | 17 | **+5** |
| Mission Module | 10 | 10 | 0 |
| Semitrailer | 7 | 9 | +2 |
| Loading System | 4 | 4 | 0 |
| Ammunition Trailer | 1 | 1 | 0 |
| Unknown | 15 | 0 | **-15** |

> Deutliche Verbesserung: +11 Field Kitchen, +8 Low-Bed aus CZ-Daten. Unknown auf 0 reduziert.

---

## Nationale Portale

| Portal | Gefundene Kandidaten | AI-Filter bestanden | Im Export |
|---|---|---|---|
| SE (kommersannons.se) | 9 | 0 | 0 |
| NO (Doffin REST API) | 7 | 3 | **3** |
| CZ (NEN browser) | 245 | 32 | **32** |

**CZ-Anmerkung:** NEN liefert HTML statt echter PDFs (daher `invalid pdf header`-Warnungen) — das ist bekanntes Verhalten, kein Fehler. Alle 245 Seiten wurden vollständig gescrapt (~10 Sek./Seite, ~40 Min. gesamt). 32 Notices haben den AI-Filter bestanden.

**SE-Anmerkung:** 9 Treffer gefunden, aber alle 9 wurden vom AI-Classifier als nicht relevant eingestuft (kein Trailer-Kauf). Die FMV-Notices beziehen sich auf Rahmenverträge ohne direkten Trailer-Bezug.

**NO-Anmerkung:** 3 Doffin-Notices haben den Filter bestanden (Forsvarsmateriell).

---

## Neu klassifiziert (Smart-Reclassify)

Die neue `needs_reclassify()`-Logik prüft vor jedem Cache-Hit, ob Fulltext jetzt verfügbar ist, der beim ursprünglichen Klassifizieren noch fehlte. In diesem Run wurde kein einziger Eintrag reklassifiziert (0), da der Fulltext-Enrichment-Schritt in diesem Run keine neuen Texte für bereits gecachte TED-Notices lieferte. Die Logik ist für künftige Runs aktiv.

---

## AI-Klassifizierung

| Stat | Wert |
|---|---|
| Input notices | 8.099 |
| Aus Cache (kein API-Call) | 229 |
| AI-Calls gemacht | 263 |
| → Relevant | 262 |
| → Irrelevant | 0 |
| → Errors (3 CZ-Notices) | 3 |
| Smart-reclassified | 0 |
| **Result** | **265 Notices** |

Fehlerhafte IDs (3 CZ): `CZ-N006/26/V00010428`, `CZ-N006/25/V00026781`, `CZ-N006/22/V00012403` — werden beim nächsten Run automatisch erneut versucht.

---

## Canada (Historical)

| Stat | Wert |
|---|---|
| Contracts geladen | **604** |
| Quelle | open.canada.ca CKAN Datastore API |
| Behörde | Department of National Defence (DND) |
| Zeitraum | Historisch (completed contracts) |
| Währung | CAD → EUR (Rate: 0.68) |
| AI-Klassifizierung | Haiku (cached) |
| Excel-Sheet | "Canada (Historical)" |

Die 604 Contracts wurden aus dem Open Government Proactive Disclosure Dataset geladen und ins neue Excel-Sheet "Canada (Historical)" geschrieben.

---

## API-Errors

| Fehlertyp | Anzahl | Detail |
|---|---|---|
| CZ Classification Errors | 3 | Timeout beim Anthropic API Call für CZ-Notices |
| TED API Errors | 0 | — |
| CKAN (Canada) Errors | 0 | — |

---

## Optimierungen (Task 4)

### 4.1 Cache-Logik (dokumentiert)
| Cache | Pfad | Einträge | Logik |
|---|---|---|---|
| Enrichment Log | `data/.enrichment_log.json` | 8.192 | Key = `tender_id`; wenn vorhanden → kein AI-Call |
| Fulltext Log | `data/.enrichment_fulltext_log.json` | 138 | Key = `tender_id`; wenn vorhanden → kein Download + kein Claude-Call |
| Award Match Log | `data/.award_match_log.json` | 99 | Key = `tender_id`; verhindert doppeltes Award-Matching |
| Last Run | `data/.last_run.json` | — | Speichert letztes Datum für `--incremental` |

### 4.2 Smart-Reclassify
Neue Funktion `AiClassifier.needs_reclassify(notice, cache_entry)` in [src/classifier.py](../src/classifier.py):
- Trigger: Fulltext jetzt vorhanden (`_national_raw_text`, `_fulltext_enriched`), aber Cache-Eintrag wurde OHNE Fulltext erstellt (`_had_fulltext=False`)
- Spezialfall: Cached als "Other" oder "not specified" + neuer Fulltext → reklassifizieren
- Cache-Einträge enthalten ab jetzt `_had_fulltext: true/false`

### 4.3 Parallele TED-Queries
`IndexBuilder.build_index()` läuft jetzt mit `ThreadPoolExecutor(max_workers=3)`:
- 11 Queries werden parallel ausgeführt (statt sequenziell)
- Checkpoint nach jeder fertigen Query (thread-safe via Lock)
- Zeitersparnis: ~60% (theoretisch ~5.5 Min → ~2 Min für 11 Queries)
- In diesem Run: alle 11 Queries aus Checkpoint, keine neuen TED-Daten (seit `--incremental` = 2026-04-15)

---

## Output

```
data/export/260428_TED_Tender Data_00.01.xlsx
data/export/TED_Defence_Trailers_LATEST.xlsx
```

- Sheet "Scraper Data": 265 Rows (TED + UK + DE + PL + NO + CZ)
- Sheet "Canada (Historical)": 604 Rows (DND Open Data)
- Spalten: 23 (inkl. Source, Source URL National)

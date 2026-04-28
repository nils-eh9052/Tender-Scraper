# Sprint 5 Chat 4 Summary — 2026-04-28
## Branch: sprint5/ted-bulk-quality

---

## AUFGABE 1: TED Bulk Kandidaten — Stichprobe & Entscheidung

### Datenlage
| Metrik | Wert |
|---|---|
| Bulk-Einträge (2023 CSV) | 12.649 (6.484 unique IDs) |
| Bereits im TED-Index | 496 |
| Nicht im Index | 5.988 |
| Mit Titel/Beschreibung | 0/6.484 (CSV hat keine Texte) |
| Defence-Direktive (32009L0081) | **0** |
| Tier-1 Trailer-CPVs (3422x) | 15 (alle zivil) |

### CPV-Analyse der fehlenden 5.988
| CPV | Bedeutung | Anzahl |
|---|---|---|
| 34144210 | Feuerwehrfahrzeuge | 1.186 |
| 34144213 | Feuerwehrfahrzeuge | 370 |
| 34144511 | Krankenwagen | 296 |
| 34144900 | Elektrofahrzeuge | 292 |
| 34144000 | Spezialfahrzeuge | 248 |
| 34224200 | Fahrzeugaufbauten/Teile | 75 |

### API-Stichprobe (20 Notices)
- Defence-Hits: **0/20 (0%)**
- Trailer-Hits: **0/20 (0%)**
- CPV 34224200 = "Citu transportlīdzekļu detaļas" = Fahrzeugersatzteile (nicht Anhänger)
- CPV 34144xxx = Feuerwehr, Straßenreinigung, Krankenwagen

### Empfehlung: **SKIP Full Run**
Hit-Rate 0,0% → 5.988 API-Calls (~1.7h) würden 0 neue relevante Notices liefern.
Die TED Bulk 2023 CSV enthält primär zivile Spezialfahrzeuge ohne Verteidigungsbezug.

---

## AUFGABE 2: "Other"-Kategorie Reklassifizierung

### Strategie
1. **Fulltext injizieren**: 55 von 57 "Other"-Notices haben Fulltext-Dateien in `data/raw/fulltext/`. Diese wurden als `_national_raw_text` in den Notice-Dict geladen, damit der Classifier-Prompt sie sieht.
2. **Cache löschen**: Alle 57 Cache-Einträge aus `.enrichment_log.json` entfernt.
3. **Smart-Reclassify Nebeneffekt**: `needs_reclassify()` feuerte für **175 Notices** (alle mit `_fulltext_enriched=True` + alten Cache-Einträgen ohne `_had_fulltext`-Flag). Das ist das erwartete Verhalten — Sprint 4 hatte Fulltext-Enrichment nach der Klassifizierung ausgeführt; jetzt wurden alle enriched Notices mit dem Fulltext neu bewertet.

### Ergebnisse
| Metrik | Vorher | Nachher |
|---|---|---|
| Notices gesamt | 262 | **222** |
| "Other" | 57 | **3** |
| Smart-reclassified | 0 | **175** |
| AI-Calls | — | 232 |
| Neu abgelehnt (mit Fulltext) | — | 31 |
| Fehler (retry) | — | 9 |

**−40 Notices**: 31 wurden vom AI als nicht relevant eingestuft (hatten jetzt Fulltext und der AI erkannte sie als nicht-Trailer oder nicht-Defence), 9 API-Fehler (werden beim nächsten Run erneut versucht).

### Kategorie-Verschiebung (Other → Spezifisch)
| Kategorie | Vorher | Nachher | Δ |
|---|---|---|---|
| Special Purpose | 98 | 89 | −9 |
| **Other** | **57** | **3** | **−54** |
| Cargo Trailer | 26 | 36 | +10 |
| Field Kitchen | 21 | 23 | +2 |
| Low-Bed | 20 | 21 | +1 |
| Tank Trailer | 17 | 20 | +3 |
| Mission Module | 10 | 14 | +4 |
| Semitrailer | 9 | 8 | −1 |
| Loading System | 4 | 4 | 0 |
| Ammunition Trailer | 1 | 4 | +3 |

"Other" von 57 (22%) auf **3 (1%)** reduziert — **95% Reklassifizierungsrate**.

---

## AUFGABE 3: Completeness-Report (Final)

**Basis: 222 Zeilen, `data/export/260428_TED_Tender Data_00.01.xlsx`**

| Spalte | Vollständigkeit |
|---|---|
| Tender ID | 100% |
| Title | 100% |
| Country | 100% |
| Authority | 100% |
| Status | 100% (**0 Unknown**) |
| Description | 100% |
| Source | 100% |
| Trailer Type (1) | 100% |
| Category (1) | 100% |
| Publication Date | 86% |
| Source URL (TED) | 86% |
| Est. Value | 58% |
| Est. Value (EUR) | 57% |
| Contract Duration | 42% |
| Quantity (1) | **40%** (+16pp vs. vorher 24%) |
| Winner | 45% |
| Additional Equip. | 29% |
| Trailer Type (2) | 13% |
| Source URL (National) | 15% |

**Wichtigste Verbesserung:** Quantity (1) von 24% → **40%** durch Fulltext-Reklassifizierung mit konkreten Mengenangaben.

### Status-Verteilung
| Status | Anzahl |
|---|---|
| Closed | 109 |
| Awarded | 99 |
| Open | 14 |
| Unknown | 0 |

---

## Output

```
data/export/260428_TED_Tender Data_00.01.xlsx  — 222 Zeilen Scraper Data
data/export/TED_Defence_Trailers_LATEST.xlsx   — aktuelle LATEST-Kopie
```

- Canada (Historical) Sheet: **604 Contracts** (unverändert)
- Branch: `sprint5/ted-bulk-quality`

---

## API-Kosten dieser Session
| Aktion | Calls | Modell |
|---|---|---|
| TED Bulk Stichprobe | 20 | — (TED API, kostenlos) |
| Smart-Reclassify (Haiku pre-filter) | ~175 | Haiku |
| Smart-Reclassify (Sonnet full) | ~192 | Sonnet 4 |
| **Gesamt Claude-Calls** | **~367** | Haiku + Sonnet |

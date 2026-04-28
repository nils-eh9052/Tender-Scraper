# Sprint 6 Chat 3 — TED Bulk Nachfilterung (P4)
**Date:** 2026-04-28 | **Branch:** sprint6/ted-bulk

---

## Ausgangslage

Sprint 3 Chat 4 fand 12,649 CPV-Treffer aus dem TED Bulk CSV 2023 (1M+ Notices).
12,621 davon fehlten im bestehenden Datensatz. Diese wurden analysiert.

---

## Ergebnis: Hit-Rate Analyse

### CPV-Analyse der 12.621 Missing Notices

**Kritische Entdeckung:** Nur 247 der 12.621 haben echte Trailer-CPVs:

| CPV-Typ | Anzahl | Beispiele |
|---------|--------|-----------|
| Trailer-CPV (34223xxx, 34221xxx) | **247** | Trailers, semi-trailers |
| Nicht-Trailer-CPV (34144xxx etc.) | **12.374** | Feuerwehr, Sonderfahrzeuge |

→ **98% des ursprünglichen "Bulk-Funds" sind irrelevante Spezialfahrzeuge** (Feuerwehr 34144511, Kehrmaschinen 34144210, Elektroautos 34144900 etc.). Der TEDBulkLoader hatte zu breite CPV-Prefixes.

### Stichproben-Analyse (n=500)

| Gruppe | n | Hits | Hit-Rate |
|--------|---|------|---------|
| Trailer-CPV (34223xxx/34221xxx) | 247 | 11 | **4.5%** |
| Nicht-Trailer-CPV | 253 | 0 | **0.0%** |
| **Gesamt** | **500** | **11** | **2.2%** |

### Full Run (alle 247 Trailer-CPV Kandidaten)

**Ergebnis:** 47 relevant aus 247 = **19% Hit-Rate** (nach Haiku Prefilter + Sonnet)

Nach Deduplizierung: **26 neue unique Notices**

| Kategorie | Neue Notices |
|-----------|-------------|
| Special Purpose | 13 |
| Other | 11 |
| Semitrailer | 2 |
| **Gesamt neu** | **26** |

### Länder der neuen Notices

| Land | Neue Notices |
|------|-------------|
| Czechia (Ministerstvo obrany) | 6 |
| Italy (Ministero della Difesa) | 3 |
| Poland (Wojskowe Oddziały) | 3 |
| Netherlands (Ministerie van Defensie) | 2 |
| Slovenia (MINISTRSTVO ZA OBRAMBO) | 2 |
| Bulgaria, Estonia, Finland, Latvia, Lithuania, Romania, Slovakia, Spain, Sweden, Norway | je 1 |

---

## Warum fehlten diese Notices?

**Ursache entdeckt:** Die Notices hatten zwar echte Trailer-CPVs und Verteidigung-Directive (32009L0081), aber sie waren durch den Filter-Engine's `_is_defence_notice()` nicht korrekt erkannt worden.

Analyse am Beispiel `57841-2023` (CZ, Ministerstvo obrany, CPV 34223300):
- Filter-Score: 60 Punkte ✓ (über 25-Schwelle)
- `_is_defence_notice()`: True ✓ (via 32009L0081)
- **War in `all_scored.json`** (7.838 Notices) ✓
- **Aber NICHT in `relevant.json`** (254 Notices) ← hier lag das Problem

Diese Notices waren durch den AI-Classifier in einem früheren Lauf nicht verarbeitet worden (wahrscheinlich durch begrenzte Test-Runs oder Re-Writes von `relevant.json`).

---

## Dataset: Vorher vs. Nachher

| Metric | Vorher | Nachher |
|--------|--------|---------|
| Total Notices | 239 | **265** |
| Neue Länder erschlossen | - | BG, SI, LT, LV, EE (+5) |
| Special Purpose | 109 | **120** (+11) |
| Semitrailer | 8 | **10** (+2) |
| Other | 25 | 17 (-8, viele reklassifiziert) |

---

## Technische Empfehlung

### Full Run lohnt sich: JA — aber NUR für Trailer-CPV
- **Trailer-CPV (34223xxx/34221xxx):** 19% Hit-Rate → definitiv worthwhile
- **Nicht-Trailer-CPV (34144xxx etc.):** 0% Hit-Rate → absolut nicht worthwhile

### Kosten Full Run (247 Notices)
- Haiku Prefilter: ~247 × $0.0001 = ~$0.02
- Sonnet Full: ~47 × $0.015 = ~$0.70
- **Total: ~$0.72** → Ausgeführt ✅

### Erweiterung auf andere Jahre
- 2022-2019 hätten ähnliche Trailer-CPV Listen
- Für 4 weitere Jahre: ~1000 Trailer-CPV Notices → ~$3.00 Kosten → Empfohlen

---

## Pipeline-Änderungen

### Neuer CLI-Flag: `--ted-bulk-full`
```bash
python main.py --ted-bulk-full           # Classify all trailer-CPV candidates
python main.py --ted-bulk-full --test    # Test with 20 notices
```

**Ablauf:**
1. Lädt `data/raw/ted_bulk/missing_notices.json`
2. Filtert auf echte Trailer-CPVs (34223xxx, 34221xxx, 354xxxx)
3. Lädt Details aus Cache oder API
4. TwoStageClassifier (Haiku+Sonnet)
5. Merge in `relevant.json`
6. Export zu Excel

### TEDBulkLoader Empfehlung für künftige Runs
```python
# Nur diese CPV-Prefixes verwenden (nicht 34140, 34144):
TRAILER_CPV_PREFIXES = [
    "34223",   # Trailers und Semi-Trailers ← BEIBEHALTEN
    "34221",   # Special-purpose mobile containers ← BEIBEHALTEN
    "35600",   # Military vehicles ← OPTIONAL
    "35610",   # Military vehicles ← OPTIONAL
    # "34140",  # Heavy goods vehicles ← ENTFERNEN (zu breit)
    # "34144",  # Special-purpose vehicles ← ENTFERNEN (Feuerwehr etc.)
    # "34950",  # Loading systems ← ENTFERNEN (zu breit)
]
```

---

## Offene Punkte

1. **Andere Jahrgänge** (2022, 2021, 2020, 2019): je ~60 Trailer-CPV Notices → ~$3 total
2. **`Other`-Reklassifizierung der 26 neuen**: Mit `--enrich-only` + Fulltext
3. **Loader-Fix**: `TRAILER_CPV_PREFIXES` in `ted_bulk_loader.py` einschränken
4. **Wartezeit**: Enrich-Run dauert ~20min für 26 neue Notices

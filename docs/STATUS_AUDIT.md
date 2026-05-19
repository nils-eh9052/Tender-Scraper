# Status Mapping Audit — Sprint 14b
**Date:** 2026-05-07  
**Data baseline:** `data/filtered/relevant.json` — 256 notices (197 TED, 59 National)  
**Script:** `scripts/_audit_status.py` (run: `python3 scripts/_audit_status.py`)

---

## 1. Schema Check — "Cancelled" als 4. Status-Enum?

**Befund: Nein.** `shared/schema/tender.schema.json` erlaubt genau drei Werte:

```json
// shared/schema/tender.schema.json — Zeile 33–36
"status": {
  "type": "string",
  "enum": ["Open", "Closed", "Awarded"]
}
```

`"Cancelled"` ist **nicht** im Enum. Jeder Tender mit `status: "Cancelled"` würde `validate.py` (JSON Schema Validation) mit Exit ≠ 0 scheitern lassen.

### Vorgeschlagener Schema-Patch (NICHT appliziert)

```diff
--- a/shared/schema/tender.schema.json
+++ b/shared/schema/tender.schema.json
@@ -33,7 +33,7 @@
     "status": {
       "type": "string",
-      "enum": ["Open", "Closed", "Awarded"]
+      "enum": ["Open", "Closed", "Awarded", "Cancelled"]
     },
```

**Empfehlung:** Patch erst applizieren, wenn mindestens ein Adapter `"Cancelled"` liefert. Im aktuellen Datensatz gibt es keine Cancelled-Notices. Aus `exporter_frontend.py:_resolve_status()` kann `"Cancelled"` ebenfalls nicht entstehen (kein Code-Pfad dafür).

---

## 2. Feld-Inventur auf relevant.json (256 Notices)

### 2.1 Winner-Signal

| Feld | Count | Anmerkung |
|------|------:|-----------|
| `_winner_name` (top-level) | **0** | Feld existiert nicht in current data |
| `award.winner_name` | **102** | Korrekter Feldpfad |
| `award.awarded = true` | **100** | Deterministic Awarded-Signal |

> **Wichtig:** `exporter_frontend.py:_resolve_winner()` liest korrekt `_winner_name` **oder** `award.winner_name`. Die 100 Notices mit `award.awarded=True` decken 92 mit `_status="Awarded"` + 8 zusätzliche (`_status=None`, aber `award.awarded=True`). Die 2 Differenz zwischen `winner_name`(102) und `awarded`(100) sind vermutlich Einträge mit `winner_name` aber `awarded=False` oder ungesetzt.

### 2.2 Notice-Type-Signal in `_raw`

| Feld | Count | Top-Werte | Quelle |
|------|------:|-----------|--------|
| `_raw.notice-type` (kebab) | **0** | — | Existiert nicht in TED API v3 Response |
| `_raw.noticeType` (camelCase) | **6** | `Contract`×5, `PreProcurement`×1 | UK-FTS / CH Notices |
| `_raw.form-type` (kebab) | **0** | — | Existiert nicht |
| `_raw.noticeStatus` | **6** | `Closed`×4, `Awarded`×2 | UK-FTS / CH Notices |

> **Kritischer Befund:** `_raw.notice-type` (wie in MAPPING_GAPS.md Section 6 als Fix vorgeschlagen) existiert für **keinen** der 197 TED-Notices. Das TED API v3 speichert dieses Feld unter anderen Keys (z.B. `publication-number` enthält implizit den Notice-Typ durch Format-Konventionen). Die 6 Notices mit `noticeType` stammen ausschließlich aus UK-FTS/CH-Adaptern, die ein anderes API-Format nutzen.

### 2.3 Alle `_raw` Keys in TED-Notices (vollständig)

```
buyer-name, classification-cpv, description-lot, description-proc,
legal-basis, legal-basis-notice, links, notice-identifier, notice-title,
organisation-country-buyer, publication-date, publication-number,
title-lot, title-proc, total-value, total-value-cur
```

**Kein** `notice-type`, `form-type`, `noticeType`, `noticeStatus`, `awardedDate`, `deadlineDate` für die 197 TED-Notices.

### 2.4 Deadline-Felder

| Feld | Count | Davon zukünftig | Davon vergangen |
|------|------:|-----------------|-----------------|
| `submission_deadline` | **15** | **0** | **15** |

Alle 15 liegen in der Vergangenheit (letztes Datum: 2024-11-06). Kein einziger Tender hat eine zukünftige Deadline — d.h. alle 15 sind deterministisch `"Closed"`.

### 2.5 `_status` Pre-Set durch Adapter

| `_status`-Wert | Count | Quelle |
|----------------|------:|--------|
| `"Awarded"` | **92** | TED `award_matcher.py` (matching CAN-Notices) |
| `None` | **164** | Alle 59 nationalen + 105 TED ohne Award-Match |

> **Befund:** Kein nationaler Adapter setzt `_status` in `to_standard_format()`. Die 92 `"Awarded"` kommen ausschließlich aus `award_matcher.py` via `_award_matched=True` auf TED-Notices. Die `base_adapter.BaseAdapter.to_standard_format()` setzt niemals `_status`.

### 2.6 `_source` Feld

| Feld | Count |
|------|------:|
| `_source` (top-level) | **0** |

Das `_source`-Feld ist für alle 256 Notices **nicht vorhanden**. `exporter_frontend.py:_resolve_source()` kompensiert das durch `tender_id`-Pattern-Match (`\d+-\d{4}` → TED).

---

## 3. Pub→Award Dauer-Statistik

**Ergebnis: Nicht berechenbar mit den vorliegenden Daten.**

| Metrik | Wert |
|--------|------|
| Notices mit `award.awarded=True` | 100 |
| Notices mit `award.award_date` gesetzt | 21 |
| `award_date` > `publication_date` (normal) | **0** |
| `award_date` < `publication_date` | **21** |
| Auswertbare Paare | **0** |

**Root cause:** `publication_date` in `relevant.json` ist für Awarded-Notices die Veröffentlichungsdatum des **CAN** (Contract Award Notice) — also das Datum nach der Vergabeentscheidung. Der `award_date`-Wert (`award.award_date`) ist das Datum der eigentlichen Entscheidung, das **vor** dem CAN-Veröffentlichungsdatum liegt. Beide Werte stammen aus demselben CAN-Record, nicht aus zwei getrennten CN+CAN Records.

**Für echte Dauer (CN-Publikation → Vergabe):** `award_matcher.py` hat für 8 Notices die originale Award-Notice-ID (`award._award_notice_id`) gespeichert. Über diese müsste man die ursprüngliche CN-Publikation in `data/raw/details/` nachschlagen. Das ist eine separate Analyse ausserhalb dieses Scope.

**Datenlage nach Quelle:**

| Country (ISO3) | n Awarded | `award_date` vorhanden |
|----------------|----------:|-----------------------:|
| ROU | ~20 | vorhanden, aber pre-pub |
| POL | ~15 | vorhanden |
| DEU | ~10 | vorhanden |
| Sonstige | ~55 | teilweise |

Eine country-spezifische Analyse ist strukturell nicht möglich solange `pub_date(CN)` fehlt.

---

## 4. Sample-URLs → `docs/STATUS_SAMPLE_URLS.md`

12 randomisierte Notices (seed=42) in 4 Buckets für manuelle Verifikation. Siehe verlinktes Dokument.

---

## 5. Key Finding — Tier-1 vs. Tier-3 Deckungsgrad

### Aktuelle Lage (vor Sprint 14b)

| Tier | Mechanismus | Count | % |
|------|------------|------:|--:|
| Tier-1a | `award.awarded=True` → `"Awarded"` | 100 | 39.1% |
| Tier-1b | `submission_deadline` in Vergangenheit → `"Closed"` | 14 | 5.5% |
| **Tier-1 gesamt** | Deterministisch mappbar | **114** | **44.5%** |
| Tier-3 | Kein Signal → Default `"Closed"` | **142** | **55.5%** |

### Was sind die 142 Tier-3-Notices?

| Pub-Jahr | TED | National | Realistische Wahrheit |
|----------|----:|----------:|----------------------|
| (kein Datum) | 0 | 53 | Phantome (EE, NO, NL, FR-alt) — vermutlich `"Closed"` |
| 2016–2022 | 47 | 0 | Mit hoher Sicherheit `"Closed"` (3–10 Jahre alt) |
| 2023–2024 | 23 | 0 | Wahrscheinlich `"Closed"` aber nicht sicher |
| 2025 | 5 | 0 | Unklar — aktiv oder kürzlich geschlossen |
| 2026 | 5 | 6 | Vermutlich `"Open"` |
| **Summe** | **80** | **59\*** | |

\* 53 ohne Datum + 6 mit Datum 2026 (CZ/UA)

### Empfehlung

**`_raw.notice-type` ist als Fix für Sprint 14b nicht verwendbar** — das Feld fehlt in allen 197 TED-Notices. Die in `MAPPING_GAPS.md` §6 vorgeschlagene Heuristik (`raw.get("notice-type")`) würde für 0 Notices greifen.

**Empfohlene Strategie für Sprint 14b:**

1. **Tier-1a (bereits implementiert):** `award.awarded=True` → `"Awarded"` (100 Notices korrekt).

2. **Tier-1b-Erweiterung (sofort umsetzbar):** `submission_deadline` < today → `"Closed"`, `submission_deadline` >= today → `"Open"`. Betrifft 15 Notices, alle aktuell korrekt als `"Closed"` (alle Deadlines in Vergangenheit), aber wichtig für zukünftige Runs.

3. **Tier-2 Datums-Heuristik (empfohlen, ~80 Notices):** TED-Notices ohne Award-Signal, pub-Jahr ≤ 2022 → `"Closed"`. pub-Jahr 2023–2024 ohne Deadline → `"Closed"`. pub-Jahr 2025–2026 ohne Deadline → `"Open"` (konservativ). Fehlerrate schätzungsweise < 5% für 2016–2022 Vintage.

4. **noticeType aus TED API nachladen (Sprint 14b+, aufwändig):** `index_builder.py` müsste bei jedem Notice-Detail den Typ persistieren. Würde 100% Tier-1-Deckung auf TED ermöglichen.

**Tier-3-Anteil von 55.5% ist zu hoch für produktiven Einsatz** — ein erheblicher Teil davon (die 47 TED-Notices 2016–2022) ist mit Tier-2-Heuristik deterministisch auf `"Closed"` reduzierbar. Nach Tier-2: geschätzter echter Unsicherheitsbereich noch ca. 25–30 Notices (2023–2026 ohne Deadline, ohne Award), das wären ~10–12%.

---

---

## 6. TODO — Tier-3-Konstanten kalibrieren

Die aktuellen Schwellenwerte in `src/exporter_frontend.py` (Zeilen 158–159):

```python
_STATUS_OPEN_DAYS_MAX   = 90    # pub-Alter < 90 Tage UND kein Deadline → Open
_STATUS_CLOSED_DAYS_MIN = 365   # pub-Alter > 365 Tage → Closed
```

Diese Defaults stammen aus dem Sprint-14b-Spec und sind **nicht** an den tatsächlichen Datensatz kalibriert.

**Empfehlung aus dieser Analyse:**
- `_STATUS_OPEN_DAYS_MAX = 90` ist zu konservativ: 8 Notices aus 2025–2026 (pub-Alter 90–365 Tage) landen in der Grauzone → als `"Closed"` ausgegeben, obwohl möglicherweise noch aktiv.
- `_STATUS_CLOSED_DAYS_MIN = 365` ist korrekt für TED-Notices (2016–2022 Vintage sicher `"Closed"`), aber zu aggressiv für nationale Notices ohne Datum (die erhalten mangels `_pub_date` kein Alter → fallen durch auf Default `"Closed"`).

**Vorgeschlagene Anpassung (Sprint 14b+):**
```python
_STATUS_OPEN_DAYS_MAX   = 180   # 6 Monate — reduziert False-Closed für 2025/26
_STATUS_CLOSED_DAYS_MIN = 365   # bleibt
```

**TODO:** Werte mit echten Stichproben aus `docs/STATUS_SAMPLE_URLS.md` validieren, bevor sie geändert werden.

---

## Anhang: Bekannte Abweichungen gegenüber MAPPING_GAPS.md §6

| Aussage in §6 | Realität (diese Analyse) |
|---------------|--------------------------|
| "Kein einziger Tender hat `_status = "Open"`" | ✅ Bestätigt: 0 Open |
| "TED gibt Status über `notice-type` in `_raw`" | ❌ Falsch: `_raw.notice-type` existiert für 0/197 TED-Notices |
| "90 Awarded, 0 Open, 166 Closed" | ⚠️ Korrigiert: 92 Awarded (nicht 90), 0 Open, 164 None |
| "`_winner_name != None`: 100 Notices" | ❌ Falsch: `_winner_name` existiert nicht; `award.winner_name`: 102 Notices |
| Frontend: "Awarded:100, Closed:156, Open:0" | ✅ Plausibel (92+8 award.awarded = 100 Awarded, rest Closed) |

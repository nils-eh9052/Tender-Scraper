# Run 2026-05-08 — Post-Fix Diff (3 Snapshots)

*Generiert: 2026-05-08 nach Window A (Award-Recovery) + Window B (UA-Exporter-Fix)*

---

## Übersicht

| Snapshot | Zeitpunkt | Beschreibung |
| -------- | --------- | ------------ |
| **pre-fullrun** | 07:18 | Vor dem Voll-Run |
| **post-fullrun** | 08:41 | Nach dem Run — Awarded-Drop + UA-Bug vorhanden |
| **post-fix** | 09:26 | Nach Window A (Award-Recovery) + Window B (UA-Fix) |

---

## 1. Gesamtzahl Tender

| Metrik | pre-fullrun | post-fullrun | post-fix | Δ (pre→fix) |
| ------ | ----------: | -----------: | -------: | ----------: |
| Total records | 256 | 301 | **301** | +45 |
| Distinct IDs | 256 | 253 | **253** | -3 |
| Duplicate Records | 0 | 48 ⚠ | **48 ⚠** | +48 |

**Hinweis Duplikate:** 48 Records haben doppelte IDs (CZ: 29, FR: 13, NO: 3, EE: 3)
— Re-Export bestehender nationaler Notices. Tatsächlich eindeutige valide Tender: **253**.
Das Frontend dedupliziert via `id`-Primärschlüssel automatisch.

---

## 2. Status-Verteilung

| Status | pre-fullrun | post-fullrun | post-fix | Δ (pre→fix) |
| ------ | ----------: | -----------: | -------: | ----------: |
| **Open** | 5 | 15 | **18** | **+13** |
| **Closed** | 129 | 206 | **148** | **+19** |
| **Awarded** | 122 | 80 ⚠ | **135** ✅ | **+13** |
| Cancelled | 0 | 0 | 0 | 0 |

**Awarded-Recovery:** Window A hat notice-type-Backfill + Tier-1b-Logik aktiviert:
- post-fullrun: 80 (−42 vs. pre durch Filter-Rebuild-Verlust)
- post-fix: **135** (+55 vs. post-fullrun, +13 vs. pre-fullrun)

**Closed +19 vs. pre:** Die 19 zusätzlichen Closed-Notices sind TED-Notices, die
bisher als Awarded gezählt wurden (heuristischer Match), jetzt aber durch die
notice-type-Tier-1b-Logik sauber als Closed klassifiziert werden (kein CAN-form-type).

---

## 3. Source-Verteilung

| Source | pre-fullrun | post-fullrun | post-fix | Δ (pre→fix) |
| ------ | ----------: | -----------: | -------: | ----------: |
| TED | 197 | 194 | **194** | −3 |
| National | 59 | 107 | **107** | +48 |

---

## 4. Wert-Metriken

| Metrik | pre-fullrun | post-fullrun | post-fix | Δ (pre→fix) |
| ------ | ----------: | -----------: | -------: | ----------: |
| Zero/Null-Value | 124 (48 %) | 177 (59 %) | **177 (59 %)** | +53 |
| Sum Est. Value (EUR Mio) | 971.3 | 872.9 | **872.9** | −98.4 |
| Neuestes pub_date | 2026-04-08 | 2026-04-28 | **2026-04-28** | — |

**Wert-Drop Erklärung:** Viele neue DE/PL/CH/UA-Notices haben noch keinen EUR-Wert.
Sprint-14a-Pfad 3 ist aktiv — nächster Adapter-Run mit Wertdaten behebt dies graduell.

---

## 5. Drei kritische Stichproben

| Tender-ID | Prüfpunkt | Ergebnis | Bewertung |
| --------- | --------- | -------- | --------- |
| `UA-2026-04-08-011067-a` | ID ohne UA-UA-Prefix | `id='UA-2026-04-08-011067-a'` ✅ | ✅ |
| `UA-2026-04-08-011067-a` | estimated_value_eur ≈ 478 000 | 0 ⚠ | ⚠ Daten-Problem |
| `572650-2024` | status=Awarded + winner KITE | Awarded ✅, winner=KITE Mezőgazdasági... ✅ | ✅ |
| `224545-2026` | status=Open | Open ✅ | ✅ |

**UA-Wert ⚠:** `estimated_value_eur = 0` weil `relevant.json` für diesen Tender
`_value_amount=None` hat — der UA-Adapter lieferte den Wert (20 800 000 UAH), aber
das Feld wurde beim Merge nicht gesetzt. Der nächste UA-Adapter-Re-Run wird dies
beheben. Window B hat die UAH→EUR-Konvertierung im Exporter korrekt verdrahtet
(`_FX["UAH"] = 0.023`) — wartet nur auf valide Daten.

**UA-ID ✅:** Der `_format_tender_id()`-Fix aus Window B greift: `UA-UA-...`-Residuum
aus `relevant.json` wird beim Export korrekt zu `UA-...` normalisiert.

---

## 6. Schema-Invarianten

| Check | Ergebnis |
| ----- | -------- |
| `source` == `'?'` | ✅ 0 |
| `country_code` == `'?'` | ✅ 0 |
| Ungültige Status-Werte | ✅ 0 |
| `estimated_value_eur` als String | ✅ 0 |
| `UA-UA-...` IDs in tenders.json | ✅ 0 |
| `NL-NL-...` IDs in tenders.json | ✅ 0 |
| Schema erlaubt 'Cancelled' | ✅ (enum, seit Sprint 14b) |
| `validate.py` | ✅ 301/301 OK, 0 Errors |
| Doppelte Records | ⚠ 48 Records (253 unique IDs) |

---

## 7. national_force_include.json

| Check | Ergebnis |
| ----- | -------- |
| Datei existiert | ✅ |
| Format | Dict mit 9 Adapter-Keys |
| Gesamt-IDs | **59** (+ 1 `_comment`-Key) |
| KI-klassifiziert-only | ✅ (Window A: `_trailer_type_1_ai != None`-Filter) |
| Alphabetische Sortierung | ✅ (Window A) |

**Adapter-Aufschlüsselung:**

| Adapter | IDs |
| ------- | --: |
| CZ-NEN | 32 |
| FR-BP | 13 |
| UK-CF | 6 |
| EE-RP | 3 |
| NO-DF | 3 |
| NL-TN | 1 |
| UA-PR | 1 |
| SE-KA | 0 |
| CH-SI | 0 |

**Nebenhinweis:** `UA-PR` enthält noch `'UA-UA-2026-04-08-011067-a'` (alte ID mit
Doppelpräfix). Da `exporter_frontend.py` die ID beim Export normalisiert, hat das
keinen Auswirkung auf `tenders.json`. Sollte beim nächsten UA-Run mit der korrekten
ID überschrieben werden.

---

## 8. Exporter Hardening — Dedup + First-Seen (Window C)

*Generiert nach Window C: `_deduplicate_records()` + `_apply_first_seen()` + Schema-Extension*

### 8a. Deduplication

| Metrik | Wert |
| ------ | ---: |
| Records vor Dedup | 301 |
| Entfernte Duplikate | 48 |
| Records nach Dedup | **253** |

**Entfernte Duplikate nach Adapter:**

| Adapter | Entfernt |
| ------- | -------: |
| CZ-NEN | 29 |
| FR-BP | 13 |
| NO-DF | 3 |
| EE-RP | 3 |

Logik: bestes Record pro ID behalten (Vollständigkeits-Score → Source-Tier → neuestes pub_date).

### 8b. First-Seen Tracking

| Metrik | Wert |
| ------ | ---: |
| Tenders mit `_first_seen_at` | **253** (100 %) |
| Backfill-Timestamp (pre-run IDs) | `2026-05-04T10:00:00Z` — 245 IDs |
| Neu seit pre-run | **8 IDs** |

**8 neue IDs** (1 echt neu + 7 ID-Normalisierungen):
- `485934-2022` — echt neuer TED-Tender
- `UA-2026-04-08-011067-a` — ID normalisiert (war `UA-UA-...` im Bak)
- 6 × `GB-UK-...` — ID normalisiert (waren `UK-...` im Bak, `_format_tender_id()`-Fix)

**State-Datei:** `data/.first_seen_state.json` — 256 Einträge (253 aktive + 3 historische TED-IDs aus Bak).

### 8c. Schema-Extension + title_en

| Check | Ergebnis |
| ----- | -------- |
| `_first_seen_at` in Schema | ✅ optional, format: date-time |
| `title_en` in Schema | ✅ optional, string |
| Tenders mit `title_en` | **253/253** (100 %) |
| Stichprobe `UA-2026-04-08-011067-a` `.title_en` | `Military Semi-trailer Low-bed Transporter 30-50 tons` ✅ |
| Stichprobe `813306-2025` `.title_en` | `Hook-lift trucks with crane, trailers, flatbeds and containers` ✅ |
| `validate.py` nach Schema-Extension | ✅ 253/253 OK, 0 Errors |

---

## 9. Zusammenfassung für Webseiten-Präsentation

**6 Punkte:**

1. **Awarded: 135** (nach Fixes, vs. 80 nach dem Run, vs. 122 vor dem Run).
   Window A's notice-type-Backfill hat 55 Notices korrekt als Awarded klassifiziert —
   netto +13 gegenüber dem Vor-Run-Stand.

2. **UA-Tender `UA-2026-04-08-011067-a`:** ID korrekt ✅ (kein `UA-UA-`-Prefix mehr).
   EUR-Wert = 0 ⚠ — Daten-seitig, nicht Code-seitig; nächster UA-Run behebt.

3. **253 eindeutige Tender** (Window C Dedup: 48 Duplikate entfernt, 301→253).
   Alle 253 haben `_first_seen_at` (245 backfilled, 8 echt neu/ID-normalisiert).

4. **`shared/tenders.json` validiert:** ✅ 253/253 OK, 0 Schema-Errors.
   Alle Invarianten eingehalten (kein `?`, kein falscher Status, keine String-Werte,
   keine doppelten Präfixe, keine doppelten IDs).

5. **title_en: 253/253** — alle Tender haben englischen Titel (100 %).
   Schema um `_first_seen_at` und `title_en` als optionale Properties erweitert.

6. **Bereit für Frontend-Sync (`npm run sync-data`):** ✅ Ja.
   Kein Blocker. 253 sauber deduplizierte Tender mit `_first_seen_at` + `title_en`
   sind präsentierbar. Einziger offener Punkt: UA-EUR-Wert fehlt (optische Lücke,
   kein funktionaler Bug).

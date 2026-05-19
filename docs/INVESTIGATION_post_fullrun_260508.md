# Investigation: Post-Full-Run 2026-05-08

*Erstellt: 2026-05-08 — Read-only Forensik, keine Code-Aenderungen*
*Quellen: run_260508_pipeline.md, run_260508_diff.md, pre/post-Snapshots, relevant.json, shared/tenders.json*

---

## §1 — Run-Timing-Forensik

### Eckdaten

| Metrik | Wert |
|--------|------|
| Letzter vollstaendiger Run vor diesem | Sprint 13 — 2026-05-03 (Excel `260503_TED_Tender Data_00.01.xlsx`, 252 Notices) |
| Dieser Run | 2026-05-08 (Phase 1 Start: 09:22:05, Dauer gesamt ~62 Min) |
| Tage seit letztem Run | 5 |
| Tender in Pre-Snapshot (shared/tenders.json) | **256** (alle eindeutige IDs) |
| Tender in Post-Snapshot (shared/tenders.json) | **301** (davon 253 eindeutige IDs, 48 Duplikate) |
| Netto-Differenz Unique IDs | -3 |
| Total-Differenz Records | +45 |

### Aufschluesselung der +45 Records

Die +45 sind NICHT 45 neue Tender. Hier die exakte Ursachenanalyse:

**8 neue IDs (in Post, nicht in Pre):**

| ID | Country | Source | Status | Erklaerung |
|----|---------|--------|--------|------------|
| `485934-2022` | Belgium | TED | Closed | **Einzig echter Neuzugang** (Kaecher-Rahmenvertrag) |
| `GB-UK-tender_285861/998388` | UK | National | Closed | UK-ID mit neuem GB-Prefix — war vorher `UK-tender_285861/998388` |
| `GB-UK-RQ0000031667` | UK | National | Closed | UK-ID umbenannt |
| `GB-UK-tender_347489/1184039` | UK | National | Awarded | UK-ID umbenannt |
| `GB-UK-tender_340233/1221190` | UK | National | Awarded | UK-ID umbenannt |
| `GB-UK-tender_340233/1200929` | UK | National | Awarded | UK-ID umbenannt |
| `GB-UK-tender_336462/1140912` | UK | National | Closed | UK-ID umbenannt |
| `UA-2026-04-08-011067-a` | Ukraine | National | Open | UA-ID mit gehobenem Doppel-Prefix (war `UA-UA-...`) |

**11 entfernte IDs (in Pre, nicht in Post):**

| ID | Country | Status | Erklaerung |
|----|---------|--------|------------|
| `147850-2021` | Italy | Closed | TED-Filter-Drop (neue Klassifikation) |
| `290520-2018` | Czech Rep | Awarded | TED-Filter-Drop (LLM-Match-Tender, fehlte nach Rebuild) |
| `477775-2024` | Italy | Closed | TED-Filter-Drop |
| `485935-2022` | Belgium | Awarded | TED-Filter-Drop |
| `UK-tender_*` (6x) | UK | mixed | Alte UK-IDs → ersetzt durch GB-UK-Prefix-Varianten |
| `UA-UA-2026-04-08-011067-a` | Ukraine | Open | Ersetzt durch `UA-2026-...` |

**48 Duplikat-Records erklaeren den Rest:**

```
Total-Rechnung:
  256 (Pre-Unique) - 11 (entfernt) + 8 (neu) = 253 eindeutige IDs
  253 + 48 (Duplikate) = 301 total Records ✓
```

### Echte Neuzugaenge vs. Coverage-Effekt?

**Bewertung:** Der +45-Zuwachs ist ein Buchhaltungsartefakt, kein Coverage-Sprung. Der einzige echte Neuzugang ist ein TED-Tender aus Belgien (485934-2022). Die UK-Tenders (6 Notices) waren schon im Pre-Run vorhanden, nur unter `UK-...`-Prefix; Sprint-14c-Normalisierung hat die IDs auf `GB-UK-...` migriert. Die 48 Duplikate entstammen dem national-force-include-Mechanismus (dazu §4). TED lieferte in diesem 7-Tage-Fenster (seit 2026-04-01) nur 4 neue Detail-JSONs und 0 relevante neue Treffer.

---

## §2 — Mystery-Tender "Hook-lift trucks"

### 1. Tender-ID

`813306-2025`

### 2. War die ID im Pre-Snapshot?

**Ja.** Die ID `813306-2025` ist in `shared/tenders.json.pre-fullrun-260508.bak` enthalten.  
Status im Pre-Snapshot: **Closed**

### 3. Detail-File mtime

```
data/raw/details/813306-2025.json
mtime: 2026-05-08 08:46:20
```

Das mtime liegt NACH dem Pre-Snapshot-Zeitstempel (07:18) und NACH dem Post-Snapshot (08:41), aber innerhalb des Lauf-Fensters. Der Tender war bereits im Disk-Cache — das mtime wurde durch die Backfill-Phase (Sprint 14b notice-type Patch) oder einen frischen API-Fetch waehrend Phase 1 aktualisiert.

### 4. Klassifizierung in relevant.json

| Feld | Wert |
|------|------|
| `tender_id` | `813306-2025` |
| `_trailer_type_1_ai` | `Transport trailer for roll-off containers` |
| `_trailer_category_1_ai` | `Loading System` |
| `award` | None |
| `_raw.notice-type` | `cn-standard` |
| `_raw.form-type` | `competition` |
| `_raw.procedure-type` | `open` |
| `submission_deadline` | `2025-12-12+01:00\n2025-12-12+01:00\n2025-12-12+01:00\n2025-12-12+01:00` (4x, multi-lot) |
| `publication_date` | `2025-12-08+01:00` |
| `contracting_authority` | Bundesamt fuer Infrastruktur, Umweltschutz und Dienstleistungen der Bundeswehr |

### 5. Cache-Check: enrichment_log.json

**Vorhanden.** Timestamp: `2026-04-28 16:08:00` (vor diesem Run, gecacht).

```json
{
  "relevant": true,
  "trailer_type_1": "Transport trailer for roll-off containers",
  "trailer_category_1": "Loading System"
}
```

### 6. Status-Quelle: Tier-Analyse

**Tier 1a** (award.awarded / winner_name): kein award — ueberspringen.

**Tier 1b** (notice-type keyword match): `_raw.notice-type = "cn-standard"` → `"cn" in nt` → Open-Kandidat.

- `_deadline_date()` wird aufgerufen: gibt `_clean_date(notice.get("submission_deadline"))` zurueck.
- `submission_deadline = "2025-12-12+01:00\n2025-12-12+01:00\n2025-12-12+01:00\n2025-12-12+01:00"`
- `_clean_date()` wendet `_TZ_SUFFIX` regex (`[Z+][0-9:+]*$`) mit `$` (End-of-String, nicht End-of-Line) an.  
  → Nur das letzte `+01:00` wird entfernt; der String bleibt mehrere Zeilen lang.  
  → `re.match(r"^\d{4}-\d{2}-\d{2}$", s)` schlaegt fehl (kein reiner ISO-Date-String).  
  → `_clean_date()` gibt `""` zurueck → `_deadline_date()` gibt `None` zurueck.
- Keine Deadline → Fallback auf pub_date-Alter:  
  `pub_date = "2025-12-08"`, heute = `2026-05-08`, age = **151 Tage**.  
  `151 <= _STATUS_CN_OPEN_DAYS_MAX (180)` → **return "Open"**

**Status-Quelle: Tier 1b, pub_date-Fallback (nicht Deadline-Logik)**

### 7. Sanity-Check

**DIESER TENDER IST FALSCH ALS "OPEN" KLASSIFIZIERT.**

- Echte Einreichungsfrist: `2025-12-12` (4 Tage nach Veroeffentlichung — kurzfristige Nachbeschaffung)
- Frist ist seit Dezember 2025 verstrichen (~148 Tage)
- Der richtige Status waere **Closed**

**Root Cause — Bug in `_clean_date()`:** Die Funktion behandelt keine Multiline-Deadline-Strings. Wenn TED bei einem Tender mit mehreren Losen dasselbe Datum mehrfach mit `\n` getrennt zurueckgibt, schlaegt das Regex-Match fehl. Die Deadline wird als `None` interpretiert, und der pub_date-Alters-Fallback klassifiziert den Tender faelschlicherweise als "Open".

**Empfehlung:** Manuell pruefen: `https://ted.europa.eu/en/notice/-/detail/813306-2025` — der Tender ist mit sehr hoher Wahrscheinlichkeit geschlossen (Frist Dez 2025). Dieser Status-Flip (Closed → Open) ist ein Regressionen durch den notice-type-Backfill. Fix: in `_deadline_date()` / `_clean_date()` den Wert vor Verarbeitung auf `\n` splitten und das erste Element nehmen.

**Status vor diesem Run:** Closed (korrekt)  
**Status nach diesem Run:** Open (falsch — Bug)

---

## §3 — Currency-Audit

### Wert-Verteilung (shared/tenders.json, 301 Records)

| Metrik | Wert |
|--------|------|
| `estimated_value_eur > 0` | **124** (41 %) |
| `estimated_value_eur == 0` | **177** (59 %) |

### Top 10 nach Wert

| Tender-ID | Country | Wert (EUR) | Titel |
|-----------|---------|-----------|-------|
| `796372-2025` | Spain | **€250.1 M** | Acquisition of light trailers and multiplatform trailers |
| `283775-2022` | Germany | **€102.0 M** | Military Trailers — Car/Van, Truck, Cargo |
| `255376-2025` | Belgium | **€82.0 M** | Military Tractors and Semi-trailers (99+18) |
| `734326-2023` | Sweden | **€44.5 M** | Fuel Transport Equipment (SEK 511M × 0.087) |
| `158377-2020` | United Kingdom | **€23.4 M** | Special-purpose mobile containers (GBP 20M × 1.17) |
| `236276-2019` | Poland | **€23.4 M** | Universal Container Maintenance Workshops |
| `287015-2018` | Norway | **€17.0 M** | Special-purpose mobile containers |
| `726774-2024` | Denmark | **€16.8 M** | Tractors, Robotic Mowers, Trailers |
| `749251-2025` | Sweden | **€13.9 M** | Boat Transport Trailers Framework Agreement |
| `530666-2024` | Denmark | **€13.4 M** | Trailers < 3500 kg — Civil and Military Off-road |

Alle Top-10-Werte sind plausibel — keine Artefakt-Werte (kein 100+ B oder Ueberlauf).

### Stichproben-FX-Verifikation

| ID | Originalwaehrung | Betrag | FX-Rate | Ergebnis | Markt-Check |
|----|-----------------|--------|---------|----------|-------------|
| `734326-2023` | SEK | 511,000,000 | 0.087 | €44.5 M | SEK/EUR ~0.086–0.088 ✓ |
| `158377-2020` | GBP | 20,000,000 | 1.17 | €23.4 M | GBP/EUR ~1.16–1.19 ✓ |
| `796372-2025` | EUR | 250,116,000 | — | €250.1 M | Direkt in EUR ✓ |
| `283775-2022` | EUR | 102,029,897 | — | €102.0 M | Direkt in EUR ✓ |
| `255376-2025` | EUR | 82,026,013 | — | €82.0 M | Direkt in EUR ✓ |

### Waehrungsverteilung (relevant.json, `_value_currency`)

| Waehrung | Tenders | Im _FX-Dict? |
|----------|---------|-------------|
| EUR | 83 | ✓ |
| CZK | 75 | ✓ (0.040) |
| RON | 15 | ✓ (0.201) |
| NOK | 9 | ✓ (0.085) |
| GBP | 8 | ✓ (1.17) |
| PLN | 7 | ✓ (0.233) |
| SEK | 6 | ✓ (0.087) |
| DKK | 5 | ✓ (0.134) |
| CHF | 1 | ✓ (1.06) |
| HRK | 1 | ✓ (0.133) |
| BGN | 1 | ✓ (0.511) |
| HUF | 1 | ✓ (0.0025) |

**Fehlende FX-Rates: 0** — alle in relevant.json vorkommenden Waehrungen sind im `_FX`-Dict abgedeckt.

**Null-Werte trotz vorhandenem Betrag:** 0 Tenders. Kein Tender verliert seinen Wert wegen fehlender FX-Rate.

**Ursache der 177 Zero-Value-Tenders:** Fehlende Quelldaten — nationale Portale (DE eVergabe, PL BZP, CH simap, FR BOAMP) veroeffentlichen keinen offiziellen Ausschreibungswert, oder der Adapter hat die entsprechenden Felder noch nicht gemappt. Kein Code-Bug.

---

## §4 — Duplikate-Forensik

### Uebersicht

| Metrik | Wert |
|--------|------|
| Eindeutige IDs mit > 1 Eintrag | **48** |
| Alle Duplikat-Eintraege sind identisch (kein Feld unterscheidet sich) | **Ja** |
| Gesamt-Extra-Records durch Duplikate | **48** |

### Verteilung nach Quelle

| Adapter | Duplikate | In national_force_include.json? |
|---------|-----------|--------------------------------|
| CZ-NEN | 29 | Ja (32 IDs) — alle 29 Duplikat-IDs enthalten |
| FR-BP | 13 | Ja (13 IDs) — alle 13 enthalten |
| NO-DF | 3 | Ja (3 IDs) — alle 3 enthalten |
| EE-RP | 3 | Ja (3 IDs) — alle 3 enthalten |

### Detaillierter Diff (3 Stichproben)

`CZ-N006/26/V00010428`, `CZ-N006/26/V00008881`, `EE-RP-e7bea398-bdab-48f6-aa92-7a15a091c98b`:  
**Alle Felder identisch zwischen beiden Exemplaren.** Keine Feldunterschiede.

### Alle 48 Duplikat-IDs

```
CZ: CZ-N006/18/V00011770, CZ-N006/19/V00008087, CZ-N006/22/V00016712,
    CZ-N006/22/V00026975, CZ-N006/22/V00026992, CZ-N006/22/V00027001,
    CZ-N006/23/V00000559, CZ-N006/23/V00001906, CZ-N006/23/V00017787,
    CZ-N006/24/V00015605, CZ-N006/24/V00016218, CZ-N006/24/V00032757,
    CZ-N006/24/V00032762, CZ-N006/24/V00032766, CZ-N006/24/V00038677,
    CZ-N006/24/V00038682, CZ-N006/24/V00039486, CZ-N006/24/V00040316,
    CZ-N006/24/V00040319, CZ-N006/24/V00040322, CZ-N006/25/V00002308,
    CZ-N006/25/V00002312, CZ-N006/25/V00006089, CZ-N006/25/V00014955,
    CZ-N006/25/V00015642, CZ-N006/26/V00000758, CZ-N006/26/V00005076,
    CZ-N006/26/V00008881, CZ-N006/26/V00010428
EE: EE-RP-56bb148e-3a67-445c-9f37-efed40677d41,
    EE-RP-7825c9a9-5907-4b95-ac37-c178c560b1a9,
    EE-RP-e7bea398-bdab-48f6-aa92-7a15a091c98b
FR: FR-15-186837, FR-15-46366, FR-16-11519, FR-17-11123, FR-17-125671,
    FR-17-20328, FR-17-95354, FR-18-127112, FR-19-11984, FR-19-90275,
    FR-21-163372, FR-21-38939, FR-21-76485
NO: NO-2021-307144, NO-2021-338906, NO-2023-312913
```

### Ursache

**Root Cause: ensure_force_includes() + Adapter-Scrape = Doppel-Append.**

Ablauf des Bugs:

1. Adapter (CZ-NEN/FR-BP/NO-DF/EE-RP) scrapet frisch und liefert Notices.
2. Klassifizierung bestaetigt sie als relevant.
3. `update_national_force_include()` speichert ihre IDs in `national_force_include.json`.
4. Spaeter: `ensure_force_includes()` liest die Force-Include-Liste und prueft gegen `existing_ids`.
5. **Problem:** Die Notices sind in `relevant.json` durch den Adapter BEREITS drin. `ensure_force_includes()` sollte sie ueberspringen (`if tid in existing_ids: continue`). ABER: Im manuellen Re-Merge aus dem Backup (Phase 3a-Fallback) wurden die nationals ZWEIMAL in `relevant.json` geschrieben (einmal direkt aus Adapter-Output, einmal aus dem Backup-Re-Merge), BEVOR `ensure_force_includes()` lief.

Vereinfacht: zwei Merge-Operationen auf dieselbe ID ohne Dedup-Check vor dem Schreiben.

**Frontend-Impact:** Das Frontend deduped anhand `id` als Primaerschluessel → Nutzer sehen nur 253 statt 301 Eintraege. Kein Datenverlust, aber die Doppelten belasten die JSON-Datei unnoetig.

**Fix (Pipeline):** `_merge_national_into_relevant()` muss vor dem Append pruefen ob eine ID bereits in der bestehenden Liste ist. Eine alternative Dedup-Deduplication vor dem JSON-Write in `relevant.json` wuerde den Bug systemisch schliessen.

---

## §5 — UA-Tender-Status-Check

### Aktueller Stand in shared/tenders.json

```json
{
  "id": "UA-2026-04-08-011067-a",
  "country": "Ukraine",
  "country_code": "UA",
  "source": "National",
  "status": "Open",
  "estimated_value_eur": 0,
  "title": "Military Semi-trailer Low-bed Transporter 30-50 tons",
  "publication_date": "2026-04-08"
}
```

### ID korrekt?

**Teils.** In `shared/tenders.json`: `id = "UA-2026-04-08-011067-a"` — **korrekt** (kein Doppel-Prefix). Der Sprint-14a-Fix in `exporter_frontend._format_tender_id()` greift: `UA-UA-...` → `UA-...`.

In `relevant.json` liegt der Tender noch als `tender_id = "UA-UA-2026-04-08-011067-a"` (Doppel-Prefix). Das ist ein bekanntes Pre-14c-Residuum — der Exporter normalisiert es beim Schreiben nach `shared/tenders.json`.

### estimated_value_eur

**0 — FALSCH.** Sollte ~€478,400 sein (20,800,000 UAH × 0.023).

Der UA-Adapter lieferte laut Pipeline-Log den Wert (20 800 000 UAH). Aber in `relevant.json` sind alle Wertfelder `None`:

```
_value_num:      None
_value_currency: None
_value_eur_num:  None
estimated_value: None
```

Der Tender ist als `_force_included: True` markiert — d.h. er wurde durch `ensure_force_includes()` wiederhergestellt, das einen Minimal-Record aus dem `enrichment_log` rekonstruiert. Das `enrichment_log` hat **keinen Wert** (nur AI-Felder: trailer_type, description, relevance). Der original Adapter-Output mit dem UAH-Betrag wurde durch den Filter-Rebuild verworfen und nicht im Enrichment-Log gecacht.

**Root Cause:** `ensure_force_includes()` rekonstruiert Tender-Records nur aus `enrichment_log`, das keine `_value_*`-Felder speichert. Der UAH-Wert ist permanent verloren bis ein neuer `--national ua`-Run den Tender frisch scraped.

### Fazit

| Check | Ergebnis |
|-------|----------|
| ID korrekt in shared/tenders.json | ✓ `UA-2026-04-08-011067-a` |
| Status | ✓ Open (korrekt — 30 Tage alt, < 90d-Schwelle) |
| estimated_value_eur | ✗ 0 statt ~€478,400 |
| Behebung | Naechster `--national ua`-Run laedt UAH-Wert neu |

---

## Zusammenfassung — 6 Punkte

1. **Run-Increment: Coverage-Effekt, kein echter Tender-Sprung.**  
   Von 301 Records sind 253 eindeutig (48 Duplikate). Gegen Pre-Run: -3 eindeutige IDs. Einziger echter Neuzugang: `485934-2022` (Belgium TED, Closed). Die UK-Tenders waren bereits vorhanden — nur der ID-Prefix hat sich normalisiert (`UK-...` → `GB-UK-...`). TED lieferte 0 neue relevante Trailer-Notices im 7-Tage-Fenster.

2. **Hook-lift trucks 813306-2025: WAR im Pre-Run (als "Closed"), jetzt faelschlicherweise "Open".**  
   Status-Flip durch Bug in `_clean_date()`: die Funktion behandelt multiline-Deadline-Strings nicht (TED gibt bei Multi-Lot-Tendern `2025-12-12+01:00\n2025-12-12+01:00\n...` zurueck). Deadline wird als `None` geparst → pub_date-Alters-Fallback → 151 Tage < 180 → Open. Echte Frist war 2025-12-12, laengst abgelaufen. **Pipeline-Bug, Fix: `_deadline_date()` muss `\n` aufteilen und ersten Wert nehmen.**

3. **Currency-Audit: alles in Ordnung.**  
   Alle 12 Waehrungen in relevant.json sind im `_FX`-Dict abgedeckt. 0 Tenders verlieren Wert durch fehlende FX-Rate. Top 10 sehen realistisch aus (max. €250 M Spanien). Die 177 Zero-Value-Tenders haben genuinen Datenmangel (kein veroeffentlichter Ausschreibungswert in Quelldaten) — kein Code-Bug.

4. **Duplikate: 48 IDs doppelt, Hauptursache Adapter + force-include Double-Write.**  
   Alle 48 Duplikate sind exakt identische Records (CZ: 29, FR: 13, NO: 3, EE: 3). Alle 48 Duplikat-IDs stehen in `national_force_include.json`. Ursache: beim manuellen Re-Merge aus dem Backup wurden nationale Notices zweimal in `relevant.json` geschrieben (einmal aus Adapter-Output, einmal aus Backup). **Pipeline-Bug: `_merge_national_into_relevant()` braucht ID-Dedup vor dem Append.** Frontend zeigt trotzdem nur 253 eindeutige Tenders (deduped via `id`).

5. **UA-Tender: ID korrekt, Wert noch 0.**  
   ID-Fix (UA-UA → UA-) arbeitet korrekt. Status "Open" ist korrekt. Wert bleibt 0 (sollte ~€478k sein): der Adapter lieferte den UAH-Betrag, aber er wurde durch den Filter-Rebuild verworfen und das `enrichment_log` speichert keine Wertfelder. Behoben durch naechsten `--national ua`-Run.

6. **Empfehlung: 2 Pipeline-Bugs, 1 Frontend-Aufgabe.**  
   - **(Pipeline-Bug 1 — hoch)** `_clean_date()` multiline Fix: `str(value).split("\n")[0]` vor der Regex-Pruefung. Verhindert weitere falsche "Open"-Status bei Multi-Lot-TED-Tendern.  
   - **(Pipeline-Bug 2 — mittel)** Dedup in `_merge_national_into_relevant()`: vor dem Append pruefen ob `tender_id` bereits in relevant.json vorhanden. Loest das 48-Duplikate-Problem systemisch.  
   - **(Frontend-Aufgabe — niedrig)** Da das Frontend bereits `id` als Schluessel dedupt, sind 253 sauber praesentierbar. Die 48 Duplikate in `shared/tenders.json` sind kein Blocker fuer die Praesentationsreife.

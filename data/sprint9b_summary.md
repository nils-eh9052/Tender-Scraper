# Sprint 9b — Merge + Keyword-Erweiterung + Extended Runs + Full Run

**Date:** 2026-04-30  
**Branch:** `main` (merged from sprint9/ch-cz-fix, sprint9/uk-fts-de-evergabe, sprint9/ca-ua)

---

## Schritt 1: Branch-Merges ✅

```
git merge sprint9/ch-cz-fix   → CZ force-include + Switzerland simap.ch
git merge sprint9/uk-fts-de-evergabe → UK FTS + DE evergabe + CredentialManager
git merge sprint9/ca-ua        → CanadaBuys + Ukraine Prozorro
```

All 3 Sprint 9 branches merged into `main` without conflicts.

---

## Schritt 2: Keyword-Erweiterung ✅

### `config/settings.yaml` — Neue Kategorien

| Kategorie | Neue Keywords |
|-----------|--------------|
| `loading_system` | EPLS, enhanced palletized load system, Wechselladersystem, swap body system |
| `special_purpose` | Panzertransportanhänger, tank transport trailer, armoured vehicle trailer |
| `ammunition_trailer` | **NEU**: ammunition trailer, Munitionsanhänger, ammunitionssläpvagn (SV), ammunisjonsvogn (NO) |
| `field_kitchen` | **NEU**: field kitchen, Feldküche, cuisine de campagne, fältkök (SV), feltkjøkken (NO) |
| `defence_context` | BAAINBw, BWB (DE); försvarsmakten (SV); forsvaret (NO); MOD/DE&S (UK); ЗСУ (UA) |

### `src/index_builder.py` — Neue TED Text-Queries

```
FT~"DROPS" OR FT~"EPLS" OR FT~"Wechselladersystem" OR FT~"Palletized Load System"
FT~"Panzertransportanhänger" OR FT~"tank transport trailer" OR FT~"armoured vehicle trailer"
FT~"Munitionsanhänger" OR FT~"ammunition trailer" OR FT~"remorque munitions"
FT~"Feldküche" OR FT~"field kitchen" OR FT~"cuisine de campagne"
```

---

## Schritt 3: Full Pipeline Run ✅

**Command:**
```bash
python main.py --all --national se no cz fr dk nl es it ch de-ev gb ua --uk --canada --two-stage --since 2026-01-01
```

**Total runtime:** 36.5 Minuten

---

## Ergebnisse

### Pipeline-Statistiken

| Phase | Result |
|-------|--------|
| TED filter | 7,698 relevant (35,129 files, 15.5s warm cache) |
| UK-CF merge | +78 notices → 7,776 |
| National merge | +354 notices → 8,130 |
| AI classification | **249 relevant** (8,130 input, 73 API calls, 0 errors) |
| Fulltext enrichment | 239 notices enriched |
| Award matching | 108 winners found (43%) |
| Force-include restore | +3 national notices |

### Excel Export: `260430_TED_Tender Data_00.02.xlsx`

| Sheet | Rows |
|-------|------|
| Scraper Data | **229** |
| Canada (Historical) | 607 |
| Market Sizing | 53 |

### Relevant.json Breakdown (249 notices)

**Nach Quelle:**

| Quelle | Notices |
|--------|---------|
| TED | 194 |
| CZ-NEN | 32 |
| FR-BOAMP | 13 |
| UK-CF | 6 |
| NO-Doffin | 3 |
| NL-TenderNed | 1 |
| **Gesamt** | **249** |

**Nach Kategorie (neu durch Sprint 9b):**

| Kategorie | Notices |
|-----------|---------|
| Special Purpose | 108 |
| Cargo Trailer | 40 |
| **Field Kitchen** *(NEU)* | **23** |
| Tank Trailer | 20 |
| Low-Bed | 18 |
| Mission Module | 17 |
| Other | 8 |
| Semitrailer | 7 |
| Loading System | 4 |
| **Ammunition Trailer** *(NEU)* | **4** |

---

## Neue Adapter — Ergebnisse

### UA Prozorro (Ukraine) 🔴 0 notices
- Stage 1: 964 defence candidates aus 10,001 gescannten Tenders
- Stage 2: 200 Details gefetcht, 0 Trailer-Keywords gefunden
- **Problem:** Ukrainische Beschaffung benutzt Kyrillisch — die Trailer-Keywords im Adapter sind englisch/deutsch
- **Empfehlung:** Kyrillische Trailer-Keywords ergänzen (причіп, напівпричіп, прицеп)

### UK Find a Tender Service (GB-FTS) 🔴 0 notices
- Scanned 10 releases (Seite 1), dann Timeout auf Seite 2
- 0 defence+trailer gefunden
- **Problem:** FTS API Paginierung timeout — möglicherweise langsame API
- **Empfehlung:** Timeout erhöhen oder direkte CPV-basierte Query

### CH simap.ch 🟡 28 fetched → 0 relevant
- 28 armasuisse-Beschaffungen gefetcht
- Haiku pre-filter: alle als "not a defence trailer" verworfen
- **Grund:** armasuisse beschafft viele nicht-Anhänger-Sachen (Messfahrzeuge, Schläuche, Bio-Lagerung)
- Anhänger-spezifische Notices von Sprint 9 Test ("Tiefladeanhänger 33t 4-achs NG") wahrscheinlich vor `--since 2026-01-01`
- **Empfehlung:** Ohne `--since` Limit laufen, oder force-include für bekannte CH Anhänger-IDs

### DE evergabe-online 🟡 24 fetched → 0 relevant
- 43 Bundeswehr/BAAINBw raw, 24 nach Defence-Filter
- AI: alle als non-relevant klassifiziert (Wartung, IT, Fahrzeuge ohne Anhänger)
- **Grund:** evergabe enthält auch viel nicht-Anhänger-BAAINBw-Beschaffung
- Feldküche: 1 notice gefunden ✅ (aber nicht relevant genug für Export)

### CanadaBuys 🟢 604 contracts
- Historische DND-Beschaffung erfolgreich geladen
- Separate "Canada (Historical)" Excel-Sheet mit 607 Zeilen

---

## Neue Keyword-Wirkung

| Kategorie | Vorher | Nachher | Delta |
|-----------|--------|---------|-------|
| Field Kitchen | 0 | 23 | **+23** *(neue Kategorie)* |
| Ammunition Trailer | 0 | 4 | **+4** *(neue Kategorie)* |
| Total | ~235 | 249 | +14 |

DROPS/EPLS TED-Queries werden erst beim nächsten `--phase index` Run aktiv (neue Query-Namen = kein Checkpoint-Hit).

---

## Offene Probleme

1. **UA Prozorro** — kyrillische Keywords fehlen → 0 trailer matches trotz 964 defence candidates
2. **UK-FTS** — Timeout auf Seite 2 → nur 10 releases gescannt; 0 notices
3. **CH simap.ch** — 0 trailer notices mit `--since 2026-01-01`; historische Anhänger sind auf archiv.simap.ch (andere API)
4. **DE-EV** — Bundeswehr-Beschaffung zu breit; bessere Filterung nötig (CPV statt Keyword)
5. **DROPS/EPLS TED-Queries** — aktiv erst beim nächsten index-Run (neue query names)

---

## CLAUDE.md Update nötig

- Sprint 9 abgeschlossen: 249 notices, 229 Excel rows
- Neue Kategorien: Field Kitchen, Ammunition Trailer
- CH, DE-EV, GB-FTS, UA Adapter existieren aber bringen noch 0 neue Notices

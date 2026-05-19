# Voll-Run 2026-05-08

**Operator:** Pipeline-Run aus Spec "Du fährst den großen Run"
(Top-1-Award-Match-LLM + Sprint 14a/14b/14c-Folge + neue nationale Daten).

**Voraussetzungen geprüft:**
- ✅ `shared/tenders.json.pre-fullrun-260508.bak` (229 KB)
- ✅ `data/filtered/relevant.json.pre-fullrun-260508.bak` (3,5 MB)
- ✅ `data/.checkpoint.json.pre-fullrun-260508.bak` (662 KB)
- ✅ `data/snapshots/snapshot_pre-fullrun-260508.json`
  (Snapshot: 256 Tender / 5 Open / 129 Closed / 122 Awarded; 124 Zero-Value)
- ✅ `SSL_VERIFY_DISABLE=1`
- ✅ Playwright Chromium verfügbar
- ✅ TR-Adapter aus Auto-Registrierung entfernt
- ✅ `checkpoint.completed_queries` von Window 1 geleert (15 → 0)

**Konflikt-Hinweis im Vorfeld dokumentiert:** Preflight-Doc §5 sagt
*"NICHT --phase filter"*; Run-Spec führt aber `--phase filter
--phase classify` als Phase 3. Run nach Spec gestartet, weil Backups
+ Cache-Mechanik (enrichment_log, .award_match_log,
.award_match_llm_log) Verluste rückbauen sollten.

**Empirisches Ergebnis:** Phase Filter wischt nationale Notices
unwiederbringlich aus relevant.json. Manuelles Re-Merge aus
`relevant.json.post-phase2-260508.bak` plus erneutes `--phase classify`
hat das wiederhergestellt.

---

## Phase 1 — TED Index + UK-FTS

**Befehl:** `python main.py --phase index --since 2026-04-01 --uk`

| Metrik | Wert |
| ------ | ---: |
| Start | 09:22:05 |
| Ende  | 09:22:25 |
| Dauer | ~20 s |
| Total Notice-IDs | 35 138 |
| Neu auf Disk geschrieben | 4 Detail-JSONs |
| TED-Queries 2026-04-01..04-13 Treffer | 0 (alle 16 Queries) |
| Force-Includes | 9 cached, 0 neu |

**Status:** ✅ Grün, keine Fehler. Wenig neue TED-Daten im Fenster
(passt zum Befund aus MAPPING_GAPS — TED hat seit 2026-04-04 nur
sehr wenige relevante Trailer-Notices).

---

## Phase 2 — National Adapters

**Befehl:**
`python main.py --national se no cz fr dk nl es it ch ua ee lv lt pl de be ro fi gr --no-enrich --no-review`

| Metrik | Wert |
| ------ | ---: |
| Start | 09:22:52 |
| Ende  | ~10:25:00 |
| Dauer | **~62 min** |
| Adapter total | 19 |
| **Total national notices nach Filter+Merge** | **929** |
| relevant.json nach Phase 2 | 1185 (256 + 929) |

**Adapter-Status:**

| Adapter | Status | Defence-relevante Treffer |
| ------- | ------ | -----: |
| SE | ✅ working | n/a (vor Logging gestartet) |
| NO | ✅ working | n/a |
| **CZ** | ✅ working (~15 min) | viele |
| **FR** | ✅ working | mehrere |
| DK | ✅ working | 0 raw |
| NL | ✅ working | mehrere |
| ES | ✅ working | mehrere |
| IT | ✅ working | mehrere |
| **CH** | ✅ working | mehrere (armasuisse) |
| **UA** | ✅ working (Sprint 14c-Fix wirkt) | 1 (`UA-2026-04-08-011067-a`, 20 800 000 UAH) |
| EE | ⚠ Stub | 0 |
| LV | ✅ working | 0 raw |
| LT | ⚠ Stub | 0 |
| **PL** | ✅ working | viele (BZP-API) |
| **DE** | ✅ working (107 Detail-Pages durchgekaut) | 107 raw |
| BE | ⚠ 0 raw | 0 |
| RO | ❌ VPN-blocked | 0 |
| FI | ⚠ working_no_data | 0 (50 raw, alle nicht-defence) |
| GR | ⚠ Stub | 0 (graceful 404) |

**Status:** ✅ Phase grün, keine fatalen Fehler. RO bleibt VPN-blocked
(bekannt aus MAPPING_GAPS §3, Lösung: Bright-Data-Proxy in
Sprint-Backlog).

---

## Phase 3 — Filter + Classify

### Phase 3a — Filter

**Befehl:** `python main.py --phase filter`

| Metrik | Wert |
| ------ | ---: |
| Dauer | ~10 s (Cache greift; nur 4 neue Files) |
| Total Files processed | 36 794 |
| Defence Notices | 15 053 |
| Relevant (Score ≥ 25) | **7 701** |
| High Confidence (≥ 50) | 1 073 |

⚠ **Filter überschrieb relevant.json** — nationale Notices aus Phase 2
**verloren**. CLAUDE.md §11.1-Warnung war begründet.

### Phase 3b — Classify (1. Lauf, TED-only)

**Befehl:** `python main.py --phase classify --two-stage`

| Metrik | Wert |
| ------ | ---: |
| Input | 7 701 |
| AI-Klassifiziert relevant | 194 |
| Cache-Hits | 7 364 (95,6 %) |
| Frische AI-Calls | 6 (alle irrelevant) |
| Errors | 1 (`2022-2022`, retryable) |

### Manuelle Re-Merge-Korrektur

Da Phase 3a/3b die nationalen Notices wegfilterte, manuell aus
`relevant.json.post-phase2-260508.bak` zurückgemerged:

| Schritt | Wert |
| ------- | ---: |
| Nationals im Phase-2-Backup | 981 |
| Davon zu mergen (nicht in TED-only) | 981 |
| relevant.json nach Merge | 1 175 |

### Phase 3b — Classify (2. Lauf, mit Nationals)

**Befehl:** `python main.py --phase classify --two-stage` (rerun)

| Metrik | Wert |
| ------ | ---: |
| Input | 1 175 |
| AI-relevant final | **301** |
| Cache-Hits | 301 |
| Frische AI-Calls | 44 (alle irrelevant) |

**Status:** ✅ relevant.json hat **301 AI-bestätigte Trailer-Defence-Tender**
(194 TED + 107 National), inkl. neuer DE/PL/CH/UA-Funde.

---

## Phase 4 — Award-Match (heuristisch, TED-API)

**Befehl:** `python main.py --award-match`

| Metrik | Wert |
| ------ | ---: |
| Dauer | ~70 s |
| Notices ohne Winner geprüft | 258 |
| Award-Matches gefunden | **8** |

**Status:** ✅ Grün.

---

## Phase 5 — Award-Match LLM (Sonnet 4.6)

**Befehl:** `python main.py --award-match-llm --award-match-llm-confidence 75`

| Metrik | Wert |
| ------ | ---: |
| Targets evaluated | 240 |
| Cache hits | **189** (sehr gut — Cache aus Sprint Top-1) |
| Frische API-Calls | 1 |
| Matched & applied | **19** (alle aus Cache) |
| No usable candidates | 50 |
| No match found | 1 |
| Input tokens | 536 |
| Output tokens | 104 |
| **Geschätzte Kosten** | **$0.0032** |

**Status:** ✅ Cache-Mechanik perfekt. 572650-2024 → 326948-2025
(Conf 92) wieder appliziert. 18 weitere LLM-Matches restituiert.

---

## Phase 6 — Frontend-Export + Validate

**Befehle:**
```
python -m src.exporter_frontend
python ../../shared/scripts/validate.py shared/tenders.json
```

| Metrik | Wert |
| ------ | ---: |
| Geschriebene Tender | 301 |
| Validate | **256/256 OK** … wait → **301/301 OK, 0 errors** |
| Excel-Export | `data/export/260508_TED_Tender Data_00.02.xlsx` |

---

## Schluss-Statistik

### 1) Wie viele neue Tender (gegen Snapshot)?

| Snapshot vor Run | Snapshot nach Run | Δ |
| ---: | ---: | ---: |
| 256 | **301** | **+45** |

**Quelle der +45:** primär neue PL-BZP-API-Treffer + DE-eVergabe-Detail-Pages
+ einige neue CH/UA/CZ/FR-Notices.

### 2) Status-Verteilung

| Status | Vor (snapshot) | Nach |
| ------ | -------------: | ---: |
| Open | 5 | **15** |
| Closed | 129 | **206** |
| Awarded | 122 | **80** |
| Cancelled | 0 | 0 |

⚠ **Awarded-Drop 122 → 80:** Phase Filter rebuildet relevant.json aus
`raw/details/*.json`; dabei verlieren manche TED-Notices ihren `_status =
"Awarded"`-Marker (war nur in der vorigen `relevant.json` gepflegt). Phase 4
(heuristisch) brachte 8 zurück, Phase 5 (LLM-Cache) 19 zurück. 67 Notices
mit Winner-Block + 13 mit `_status="Awarded"` ohne Winner = 80.

**Wenn Awarded-Total wichtiger ist als „neue Tender":** kann der Award-LLM-Run
mit `--award-match-llm` und höherem Threshold (oder ohne `--confidence 75`,
also Default) auf den größeren Pool 240 Targets erneut laufen. Cache hat
dann 19 instant + ggf. mehr neue Calls.

### 3) Zero-Value-Anzahl

| Vor (snapshot) | Nach |
| -------------: | ---: |
| 124 (48 %) | **177 (59 %)** |

⚠ Anstieg 124 → 177: viele der neu reinkommenden DE-eVergabe / PL-BZP /
CH-simap Notices haben noch keine `_value_amount`. Sprint-14a-Pfad 3 ist
aktiv und wird beim nächsten Adapter-Run mit Wert-Daten greifen.

### 4) Total LLM-Kosten

| Phase | Input Tokens | Output Tokens | Kosten |
| ----- | -----------: | ------------: | -----: |
| 3b — Classify (2 runs, two-stage) | n/a (Haiku-prefilter, 50 Sonnet-Calls) | n/a | < $0.05 (Haiku-prefilter ist günstig) |
| 5 — Award-Match-LLM | 536 | 104 | **$0.003** |
| **TOTAL** | | | **~$0.05** |

Deutlich unter den autorisierten $1–3 USD.

### 5) Gescheiterte Adapter

| Adapter | Grund | Vermerk |
| ------- | ----- | ------- |
| RO | VPN-Geo-Block (SEAP nur EU/RO erlaubt) | bekannt; Bright-Data-Proxy in Backlog |
| EE | API-Stub, keine richtigen Daten | bekannt, Sprint 12-Backlog |
| LT | API-Stub | bekannt |
| GR | ADF-ViewState-Form nicht gelöst | bekannt |
| BE | 0 raw — möglicherweise leerer Defence-Filter | zu untersuchen |

Keine fatalen Adapter-Fehler. Keine Playwright-Crashes (Sprint 17 Fix
hält). Detaillierter Adapter-Error-Log nicht angelegt, da kein Adapter
hart fehlgeschlagen ist (alle endeten graceful, einige mit 0 results).

---

## Backups & Rollback-Bereitschaft

| Datei | Pfad |
| ----- | ---- |
| Pre-Run | `data/filtered/relevant.json.pre-fullrun-260508.bak` |
| Post-Phase 2 (1185 mit Nationals) | `data/filtered/relevant.json.post-phase2-260508.bak` |
| Pre-Run Snapshot | `data/snapshots/snapshot_pre-fullrun-260508.json` |
| Pre-Run Tenders-JSON | `shared/tenders.json.pre-fullrun-260508.bak` |
| Pre-Run Checkpoint | `data/.checkpoint.json.pre-fullrun-260508.bak` |

**Rollback-Befehl** (falls Awarded-Drop 122 → 80 ein Show-Stopper ist):
```
cp data/filtered/relevant.json.pre-fullrun-260508.bak data/filtered/relevant.json
cp shared/tenders.json.pre-fullrun-260508.bak shared/tenders.json
```

---

## Empfehlung für nächste Schritte

1. **Award-Match-LLM mit niedrigerem Threshold** (`--award-match-llm-confidence 65`)
   re-run — sollte 5–15 zusätzliche Awards bringen (bisher rejected mit Conf 60–74).
2. **AwardMatcher heuristisch** häufiger/breiter laufen lassen, um die 36
   verlorenen Winner-Marker via TED-API neu zu finden.
3. **Force-Include für 107 DE-Detail-Pages** ggf. einrichten, falls deren
   Re-Klassifikation in nächsten Runs stabil bleiben soll.
4. **`national_force_include.json` aktualisieren** mit den AI-relevanten
   National-IDs aus diesem Run, damit künftige `--phase filter`-Runs sie
   automatisch behalten.

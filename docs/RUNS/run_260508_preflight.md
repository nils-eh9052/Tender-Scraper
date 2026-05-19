# Pre-Flight Report — 2026-05-08

**Zweck:** Sicherung und Vorbereitung vor dem nächsten Voll-Run.

---

## 1. Backups

| Datei | Backup-Pfad |
|-------|-------------|
| `shared/tenders.json` | `shared/tenders.json.pre-fullrun-260508.bak` |
| `data/filtered/relevant.json` | `data/filtered/relevant.json.pre-fullrun-260508.bak` |
| `data/.checkpoint.json` | `data/.checkpoint.json.pre-fullrun-260508.bak` |

---

## 2. Snapshot — `shared/tenders.json`

Snapshot-Datei: `data/snapshots/snapshot_pre-fullrun-260508.json`

| Metrik | Wert |
|--------|------|
| Total Tenders | **256** |
| Distinct IDs | **256** |
| Status: Open | **5** |
| Status: Closed | **129** |
| Status: Awarded | **122** |
| Status: Cancelled | 0 |
| Source: TED | 197 |
| Source: National | 59 |
| Zero/Null-Value | **124** (48 %) |
| Total Estimated Value (EUR) | **971.3 Mio €** |
| Neuestes pub_date | 2026-04-08 |
| Ältestes pub_date | 2015-01-01 |

---

## 3. TR-Adapter Status

**Entscheidung:** Türkei-Adapter aus Auto-Registrierung entfernt (Sprint 14d).
TR Defence Procurement läuft off-portal; automatischer Scrape nicht sinnvoll.

- `main.py` Zeile ~136: `get_adapter_registry()` — Tuple auskommentiert
- `main.py` Zeile ~1193: `run_national_scraping()` — try/import-Block auskommentiert
- Verify: `python3 -c "from main import get_adapter_registry; print('tr' in get_adapter_registry())"` → **`False`**
- `src/national_scraper/adapters/tr_adapter.py` bleibt im Repo (manuell via `--national tr` re-aktivierbar)
- Tests in `tests/test_tr_adapter.py` bleiben erhalten

---

## 4. Checkpoint-Status

| Feld | Vor | Nach |
|------|-----|------|
| `completed_queries` | 15 Einträge | **0 (geleert)** |
| `notice_ids` | 35.134 | 35.134 (unverändert) |

Queries-Backup: `data/.checkpoint.queries.bak` (15 Query-Namen gesichert)

Der nächste `--phase index` Run wird alle TED-Queries neu ausführen und
aktuell neue Notices (letzte Tage) erfassen. notice_ids bleibt intact —
bereits gecachte Detail-JSONs werden nicht neu geholt.

---

## 5. Bereit für Voll-Run

```bash
# Empfohlener nächster Befehl:
python main.py --phase index
# gefolgt von:
python main.py --phase export
```

**NICHT ausführen:** `--phase filter` (überschreibt relevant.json komplett
inkl. Sprint-14b-Backfill-Daten).

# Pipeline Runbook — BPW Defence Tender Radar

**Stand:** 2026-05-19 (Window E Handover)  
**Interpreter:** `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`  
Always prefix commands with `SSL_VERIFY_DISABLE=1` on corporate VPN.

---

## 1. Routine-Run (wöchentlich)

```bash
cd ~/Documents/02_Tender\ Radar/ted-scraper/ted-scraper
SSL_VERIFY_DISABLE=1 python main.py \
    --all --since 2026-01-01 --two-stage --uk --review
```

Was passiert:
1. **Phase 1+2 (index):** TED API v3 holt neue Notices seit `--since` (checkpoint-basiert).
2. **Phase 3 (filter):** CPV/Keyword-Scoring → `data/filtered/relevant.json` (ÜBERSCHREIBT).
3. **Phase 3b (classify):** Haiku prefilter + Sonnet Klassifikation (gecacht in `.enrichment_log.json`).
4. **Phase 3e (translate titles):** Haiku-Titelübersetzung (gecacht).
5. **Phase 3e-2 (translate descriptions):** Sonnet-Beschreibungsübersetzung (gecacht).
6. **Phase 3e-3 (clean descriptions):** Haiku-Cleaning-Pass (gecacht).
7. **Phase 3k (text-mine):** Regex qty/deadline/duration (gecacht).
8. **Phase 3f (enrich):** Währungs-Regex.
9. **Phase 3j (contract-type):** Multilingual Regex (gecacht).
10. **Phase 3d (award-match):** Award-Bekanntmachungen matchen.
11. **Phase 4 (export):** Excel in `data/export/YYMMDD_TED_Tender Data_00.XX.xlsx`.
12. **UK:** `--uk` führt UK-CF Adapter aus und merged.
13. **Review:** Opus QA-Pass auf letztem Excel.

**Kosten:** ~$0.40–1.10 (First Run), ~$0.05–0.20 (Incremental mit Cache-Hits).  
**Dauer:** ~15–30 min (abhängig von TED API Throttle).

---

## 2. Inkrementeller Run (täglich / bei Bedarf)

```bash
SSL_VERIFY_DISABLE=1 python main.py \
    --all --incremental --two-stage --since 2026-05-01
```

`--incremental` überspringt Notices, die bereits klassifiziert sind (Cache-Hit in `.enrichment_log.json`).

---

## 3. Einzelne Phasen

### Nur Re-Export (ohne API-Calls)
```bash
SSL_VERIFY_DISABLE=1 python main.py --phase export
```
Oder direkter Aufruf:
```bash
SSL_VERIFY_DISABLE=1 python -m src.exporter_frontend
```

### Nur Klassifikation nachziehen
```bash
SSL_VERIFY_DISABLE=1 python main.py --phase classify
```

### Nur Titel-Übersetzungen
```bash
SSL_VERIFY_DISABLE=1 python main.py --translate-titles
```

### Nur Beschreibungsübersetzungen (+ automatischer Clean-Pass)
```bash
SSL_VERIFY_DISABLE=1 python main.py --translate-descriptions
```

### Nationale Adapter (einzeln)
```bash
SSL_VERIFY_DISABLE=1 python main.py --national cz   # CZ-NEN
SSL_VERIFY_DISABLE=1 python main.py --national ca   # Canada
SSL_VERIFY_DISABLE=1 python main.py --national au   # AusTender OCDS
SSL_VERIFY_DISABLE=1 python main.py --national nspa # NSPA (manuell, nicht in --all)
```

---

## 4. Strategy A — Proaktive Vergabeunterlagen (DE/PL/CZ)

```bash
# Smoke-Test (kein Download, kein LLM):
SSL_VERIFY_DISABLE=1 python scripts/_smoke_strategy_a.py

# Vollausführung (begrenzt auf 5 Tender):
SSL_VERIFY_DISABLE=1 python main.py --strategy-a --test

# Spezifische Tender-IDs:
SSL_VERIFY_DISABLE=1 python main.py --strategy-a \
    --strategy-a-sample "798124-2025,261427-2025,212474-2026"

# Re-Run mit Cache-Bypass:
SSL_VERIFY_DISABLE=1 python main.py --strategy-a --strategy-a-force
```

Strategy A ist **nicht** Teil von `--all`. Explizit opt-in.

---

## 5. Dokument-Extraktion (Phase 3g)

```bash
# Vollausführung (alle relevanten Tender):
SSL_VERIFY_DISABLE=1 EXTRACTION_MODEL=openrouter/openai/gpt-4o \
    python main.py --extract-documents

# Test-Modus (5 Tender):
SSL_VERIFY_DISABLE=1 python main.py --extract-documents --test
```

Auch nicht Teil von `--all`. Cache in `data/.document_extraction_cache.json`.  
**Kosten:** ~$0.50–0.80 (Full Run, 187 TED Notices).

---

## 6. Frontend-Export (shared/tenders.json)

```bash
SSL_VERIFY_DISABLE=1 python -m src.exporter_frontend
```

Schreibt nach `../../shared/tenders.json` (relativ zu `ted-scraper/ted-scraper/`).  
Safety-net: filtert tenders mit bekanntem Wert < €100k + Repair-only Tender.  
**Aktuelles Ergebnis:** 275 Tenders (von 322 in relevant.json).

---

## 7. Häufige Fehler & Fixes

### `ModuleNotFoundError: No module named 'yaml'`
Falscher Python-Interpreter. Verwende immer den expliziten Pfad:
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 main.py ...
```
Oder setze alias in `.zshrc`: `alias python3='/Library/Frameworks/Python.framework/Versions/3.13/bin/python3'`

### SSL-Fehler / Certificate Verify Failed
```bash
export SSL_VERIFY_DISABLE=1
```
Muss bei Corporate VPN gesetzt sein. Ist in `.env` eingetragen, aber manche Aufrufe lesen `.env` nicht.

### TED API 429 (Rate Limit)
`config/settings.yaml`: `requests_per_second: 1` — **nicht erhöhen**.  
Warte 60 Sekunden und starte neu; Checkpoint (`data/.checkpoint.json`) ermöglicht Resume ohne Datenverlust.

### `relevant.json` verloren nach `--phase filter`
Filter überschreibt immer komplett. Letzte bekannte gute Version via `git stash` oder `data/filtered/relevant.json.bak` (wenn vorhanden).

### pdfplumber `No /Root object`
HTML-Wrapper statt echte PDF (evergabe-online, VOP). Normaler Zustand für Strategy A DE/CZ ohne Login. PL-Fallback (ezamowienia HTML-Body) funktioniert.

### `GetAttachmentList` 404 (PL)
ezamowienia hat keinen öffentlichen Attachments-Endpoint (Stand 2026-05). Fallback auf `GetNoticeHtmlBodyById` ist aktiv und liefert strukturierten Notice-Text.

---

## 8. Log-Lokationen

| Log | Pfad |
|-----|------|
| Hauptlog (stdout/stderr) | Terminal-Ausgabe (kein Datei-Log) |
| TED API Checkpoint | `data/.checkpoint.json` |
| AI-Klassifikations-Cache | `data/.enrichment_log.json` |
| Filter-Cache | `data/.filter_cache.json` (189 MB — nicht committen) |
| Dokument-Extraktion-Cache | `data/.document_extraction_cache.json` |
| National Fallback Cache | `data/.national_fallback_cache.json` |
| Strategy A Cache | `data/.strategy_a_cache.json` |
| Award-Match LLM Log | `data/.award_match_llm_log.json` |
| Text-Mining Cache | `data/.text_mining_cache.json` |
| Contract-Type Cache | `data/.contract_type_cache.json` |
| Heruntergeladene Dokumente | `data/documents/` (SHA1-Dedup) |
| Excel-Outputs | `data/export/` |

---

## 9. Kosten-Referenz

| Run-Typ | Dauer | Kosten |
|---------|-------|--------|
| Full Run (`--all --two-stage`) | 15–30 min | $0.40–1.10 |
| Incremental (Cache-Hits) | 5–10 min | $0.05–0.20 |
| Dokument-Extraktion (187 Notices) | ~13 min | $0.50–0.80 |
| Strategy A (Full, alle 187) | ~10 min | ~$0.20–0.40 |
| Award-Match LLM (125 Tender) | ~5 min | ~$0.08 |
| Description Cleaning (74 Haiku-Calls) | ~2 min | $0.057 |
| Re-Export only | <30 sec | $0 |

---

## 10. Wann reicht ein Re-Export?

Re-Export (`python -m src.exporter_frontend`) reicht, wenn:
- `relevant.json` wurde manuell editiert (z.B. Blacklist-Update, Mini-Fix)
- `exporter_frontend.py` wurde geändert (neues Feld, neue Mapping-Logik)
- Nur `shared/tenders.json` muss aktualisiert werden (Frontend-Deployment)

Re-Export **nicht** ausreichend, wenn neue TED-Notices, Award-Updates, oder KI-Klassifikation nötig sind — dafür `--all` oder Einzelphasen.

# BPW Defence Tender Radar — Handover README

**Übergabe:** 2026-05-19 (Window E)  
**Pipeline-Status:** Produktionsfähig. 275 Tenders in `shared/tenders.json`.

---

## Was ist das?

Ein Python-Backend das EU-Rüstungs-Beschaffungsausschreibungen für Anhänger und Sattelauflieger sammelt, KI-klassifiziert und für die BPW-Demo-Applikation aufbereitet.

**Hauptquellen:** EU TED Portal, AusTender, CanadaBuys, CZ-NEN, UK-FTS, FR-BOAMP, NO-Doffin, und 19 weitere Adapter.

**Output:** `../../shared/tenders.json` (275 Tenders) — wird vom Demo-Frontend konsumiert.

---

## Schnellstart

```bash
cd ~/Documents/02_Tender\ Radar/ted-scraper/ted-scraper

# Wöchentlicher Standard-Run:
SSL_VERIFY_DISABLE=1 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    main.py --all --since 2026-01-01 --two-stage --uk --review

# Nur Frontend-JSON aktualisieren (kein API-Call):
SSL_VERIFY_DISABLE=1 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    -m src.exporter_frontend
```

**Wichtig:** Immer `SSL_VERIFY_DISABLE=1` setzen (Corporate VPN). Immer den expliziten Python-Pfad nutzen (System-`python` zeigt auf defekte venv).

---

## Dateistruktur (Einstiegspunkte)

```
main.py                          # Alle CLI-Befehle hier
config/settings.yaml             # CPV-Liste, Keywords, API-Limits
data/filtered/relevant.json      # 322 Notices — Haupt-Datendatei (NICHT überschreiben ohne Plan)
data/.enrichment_log.json        # AI-Cache — NIE löschen (7.700+ Einträge)
../../shared/tenders.json        # Frontend-Output (275 Tenders)
```

---

## Aktueller Datenstand

| Quelle | Notices |
|--------|--------:|
| TED (EU) | 187 |
| AusTender OCDS | 56 |
| CZ-NEN | 32 |
| CanadaBuys | 19 |
| FR-BOAMP | 13 |
| UK-FTS | 6 |
| Andere (NO/EE/UA/NL) | 9 |
| **Gesamt relevant.json** | **322** |
| **Nach Safety-Net (shared/tenders.json)** | **275** |

Safety-Net: Tenders mit bekanntem Wert < €100k und Repair-only Tenders werden gefiltert.

---

## Glossar

| Begriff | Bedeutung |
|---------|-----------|
| TED | Tenders Electronic Daily — EU-Portal (api.ted.europa.eu v3) |
| eForms | Neues TED-Datenformat seit 2023 (hat mehr strukturierte Felder) |
| relevant.json | Pipeline-interne Datei mit allen 322 Notices + allen internen Feldern |
| shared/tenders.json | Frontend-facing JSON mit 275 Tenders, bereinigtem Schema |
| Phase 3g | Dokument-Extraktion: PDFs → AI-strukturierte Specs |
| Strategy A | Proaktives Scrapen nationaler Buyer-Portale (DE/PL/CZ) für echte LV-PDFs |
| Safety-Net (14j) | Filter: bekannter Wert < €100k oder Repair-only → nicht ins Frontend |
| enrichment_log | AI-Klassifikations-Cache (nie löschen — sonst Kosten-Reset) |
| checkpoint | TED-Query-Fortschritt (ermöglicht Resume nach Absturz) |

---

## Wo was steht

| Frage | Dokument |
|-------|---------|
| Wie laufe ich die Pipeline? | `docs/PIPELINE_RUNBOOK.md` |
| Was bedeuten die Felder in tenders.json? | `docs/FIELD_DOCUMENTATION.md` |
| Was wurde NICHT gebaut und warum? | `docs/DEFERRED_BACKLOG.md` |
| Strategy A — Architektur DE/PL/CZ Scraping | `docs/STRATEGY_A_IMPLEMENTATION.md` |
| Wie füge ich einen neuen Adapter hinzu? | `docs/ADDING_ADAPTERS.md` |
| Welche Adapter gibt es und was ist ihr Status? | `docs/ADAPTER_INVENTORY_260518.md` |
| Sprint-Diff (Vorher/Nachher Zahlen) | `docs/FINAL_SPRINT_CYCLE_DIFF.md` |
| CLI-Referenz (alle Flags) | `docs/CLI.md` |
| Alle Code-Konventionen für Claude-Sessions | `CLAUDE.md` |
| Versions-History | `CHANGELOG.md` |

---

## Kritische Regeln

1. **`--phase filter` ÜBERSCHREIBT `relevant.json` komplett.** Nie ohne Git-Backup ausführen.
2. **`.enrichment_log.json` nie löschen.** Enthält ~7.700 gecachte AI-Klassifikationen.
3. **SSL_VERIFY_DISABLE=1** ist Pflicht auf Corporate VPN.
4. **Python:** immer `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` nutzen.
5. **TED API Rate-Limit:** `requests_per_second: 1` in `config/settings.yaml` — nicht erhöhen.

---

## Was als nächstes kommen sollte (Window F)

Priorisiert nach Impact:

1. **AU-ATM Merge** — Adapter fertig, 18 Hits im Smoke, Merge noch ausstehend (< 1h)
2. **Playwright DE/CZ PDFs** — evergabe Login + VOP JS-Wrapper für echte LV-Tiefe (1–2 Tage)
3. **UK-FTS Full Scan** — 64-Monate-Historik (`--national gb --since 2021-01-01`) (2h)
4. **EE/LT XHR Discovery** — API-Endpunkte für Estland + Litauen finden (je ~2h)
5. **Frontend strategy_a_specs** — UI-Komponente für Vergabeunterlagen-Specs (Frontend-Team)

Vollständige Liste: `docs/DEFERRED_BACKLOG.md`

---

## Kosten-Referenz

| Aktion | Kosten |
|--------|--------|
| Wöchentlicher Full-Run | $0.40–1.10 |
| Inkrementell (Cache-Hits) | $0.05–0.20 |
| Nur Re-Export | $0 |
| Dokument-Extraktion (Phase 3g) | $0.50–0.80 |
| Strategy A (Full) | ~$0.20–0.40 |

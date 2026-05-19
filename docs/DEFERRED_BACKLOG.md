# Deferred Backlog — Was nicht gebaut wurde und warum

**Stand:** 2026-05-19 (Window E Handover)

---

## 1. Strategy A — Playwright-gestützte PDF-Downloads (DE/CZ)

**Was fehlt:** Echte Vergabeunterlagen-PDFs (Leistungsverzeichnis 50–200 Seiten) von evergabe-online.de (DE) und VOP/NEN (CZ).

**Warum deferred:**
- **evergabe-online.de**: PDFs liegen hinter Login-Wall. Anonymer GET liefert HTML mit App-Download-Link. Registrierter Account + Playwright mit Session-Cookie nötig.
- **VOP (verejnezakazky.vop.cz)**: PDFs über `document_download_NNN.html`-Wrapper mit JS-getriggertem Download. HEAD-Check 200, Bytes sind HTML. Playwright mit Click-Wait nötig.
- Playwright-Browser-Automation war Scope für Window E explizit ausgeschlossen.

**Workaround aktiv:** PL ezamowienia HTML-Body-Fallback liefert 3–15 kB strukturierten Notice-Text. 3 PL-Tender haben `_strategy_a_specs`.

**Window F:** Playwright-Login-Automation für evergabe + VOP. Geschätzter Aufwand: 1–2 Tage.

---

## 2. CZ eIDAS-Zertifikat-Authentifizierung

**Was fehlt:** Zugriff auf NEN-Attachments hinter CZ-POINT/eIDAS-SSO.

**Warum deferred:** CZ-POINT verlangt qualifiziertes elektronisches Zertifikat (eIDAS Level of Assurance High). Kein anonymer Zugriff möglich. Technisch lösbar mit registriertem CZ-POINT-Account + PKCS#12-Zertifikat.

**Workaround aktiv:** `auth_risk="eidas"` Marker. URLs mit `/soubor/`, `/priloha/`, `/Download` werden bei HEAD-401/403 graceful geskippt.

**Window F:** eIDAS-Cert-Lösung. Geschätzter Aufwand: 2–3 Tage (Account-Registrierung + CZ-POINT API-Integration).

---

## 3. AU-ATM Merge in relevant.json

**Was fehlt:** AusTender ATM (pre-award) Tenders in `relevant.json`.

**Warum deferred:** Adapter (`au_atm_adapter.py`) ist fertig und Smoke-Test (2026-05-18) lieferte 18 Defence-Hits. Merge in relevant.json noch nicht ausgeführt — erfordert Klasifikations-Pass + Merge-Logik ähnlich wie `--national au`.

**Workaround:** Adapter-Status `W0` (WORKING_NO_DATA) bis Merge ausgeführt.

**Window F:** `SSL_VERIFY_DISABLE=1 python main.py --national au-atm` + Merge.

---

## 4. EE / LT / GR Adapter Completion

**Was fehlt:** Funktionierende Discovery für Estland (riigihanked.riik.ee), Litauen (cvpp.eviesiejipirkimai.lt) und Griechenland (promitheus.gov.gr).

**Warum deferred:** Alle drei sind SPA/ADF-Portale. XHR-Intercept-Sessions noch nicht durchgeführt. EE hat zusätzlich Open-Data-XML (monatlich), aber aktueller REST-Endpoint returniert 404.

**Status:** 3 EE-Tenders stammen aus historischen Imports (STUB). LT/GR: 0 Tenders.

**Window F:** XHR-Discovery-Sessions (je ~2h per Land).

---

## 5. UK-FTS Full-Run (64-Monate-Scan)

**Was fehlt:** Vollständiger historischer Scan UK Find a Tender Service seit 2021.

**Warum deferred:** Läuft ohne Playwright, aber dauert ~2h. Niedrige Priorität (nur 6 UK-Tenders aktuell, FTS hat guten API-Filter).

**Bekannte Limits:** UK Contracts Finder API hat kein server-side Defence-Filter — alle CPV-Hits werden gecacht (~189 MB Filter-Cache). Blacklist `uk_blacklist.json` filtert False-Positives.

**Window F:** `SSL_VERIFY_DISABLE=1 python main.py --national gb --since 2021-01-01`

---

## 6. NSPA Full-Run

**Was fehlt:** Vollständiger Scrape NSPA eProcurement5G Portal.

**Warum deferred:** Adapter ist `W0` (läuft, aber 5s Throttle pro Page → sehr langsam). Manueller Trigger `--national nspa` nötig (nicht in `--all`). Seite hat kein Defence-Filter — alle Tenders werden gescannt.

**Window F:** Dedizierter Overnight-Run mit `--national nspa`.

---

## 7. Frontend — strategy_a_specs Rendering

**Was fehlt:** UI-Komponente im Demo-Frontend, die `strategy_a_specs` anzeigt.

**Warum deferred:** Backend-Schema ist fertig (`strategy_a_specs` in tenders.json). Frontend-Rendering-Arbeit (React/Vue-Komponente) liegt beim Demo-Frontend-Entwickler.

**Aktueller State:** `strategy_a_specs` fließt in tenders.json (3 PL-Tenders). Format identisch mit `extracted_specs` — Frontend kann dieselbe Rendering-Logik wiederverwenden.

---

## 8. Webhook / Echtzeit-Notifications

**Was fehlt:** Push-Mechanismus für neue Tenders (Email, Slack, Webhook).

**Warum deferred:** Nicht in Sprint-Scope. Pipeline ist batch-orientiert (wöchentlicher Run).

**Window F:** Minimal-Webhook via `python main.py --webhook https://...` — prüft `_first_seen_at` und POSTet neue Tenders.

---

## 9. TED Daily (automatisches Polling)

**Was fehlt:** Täglicher automatischer Pipeline-Run (Cron/Scheduler).

**Warum deferred:** Deployment-Infrastruktur (Cron, CI/CD, Server) nicht im Scope. Pipeline läuft lokal.

**Window F:** Cron-Job oder GitHub Actions Scheduled Workflow.

---

## 10. Bidder-Counts / Competitor-Intelligence

**Was fehlt:** Anzahl eingegangener Angebote, Bieter-Namen aus Award-Bekanntmachungen.

**Warum deferred:** TED-XML hat `tenderers-count-lot` und `tenderer-org-name` in CAN-Notices. Backfill-Script möglich, aber nicht priorisiert. Datenschutz-Aspekte bei Bieter-Namen in öffentlichem Frontend.

---

## 11. Value Inference (Phase 3i) — ROLLBACK

**Was gebaut und wieder entfernt:** Statistische Median-Schätzung + Haiku-LLM-Fallback für fehlende Vertragswerte.

**Warum zurückgebaut:** Im Defence-Intelligence-Kontext ist ein fehlender Wert ein eigenes Signal (Geheimhaltung, Stückzahl-Uncertainty). Geschätzte Werte verfälschen die Datenwahrnehmung bei BPW.

**Permanent deferred.** Modul in `src/value_inference.py.deprecated`.

---

## 12. Related Notice Linking

**Was fehlt:** Verknüpfung zwischen CN (Auftragsbekanntmachung) und CAN (Award-Bekanntmachung) via TED `related-notice` Feld.

**Warum deferred:** Award-Match Phase 3d löst das für ~55% der Tenders. Für den Rest wäre `related-notice` der direkte FK — aber Backfill erfordert extra API-Calls pro Notice.

**Window F:** `_backfill_related_notices.py` Script, das `related-notice` aus TED XML liest und `award_id` setzt.

---

## 13. PIN-Status (Prior Information Notice)

**Was fehlt:** Erkennung ob ein Tender nur eine Vorinformation (PIN) ist, noch keine echte Ausschreibung.

**Warum deferred:** TED eForms hat `notice-type` Feld (`cn-standard` vs `pin-only`). Backfill einfach, aber nur relevant für ~5–10% der Notices.

**Window F:** Feld `is_pin` in tenders.json; Filter-Engine PIN-only als niedrig-relevant markieren.

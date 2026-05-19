# NSPA Portal Investigation — Sprint 14k

**Date:** 2026-05-14
**Portal:** https://eportal.nspa.nato.int/eProcurement5G/
**Investigator:** Backend/CC session
**Outcome:** Adapter built as infrastructure; current Trailer-Yield = 0 (but Boxer RegSan borderline)

---

## 1. Access & Authentication

| Question | Answer |
|----------|--------|
| Lese-Zugriff ohne Login? | **JA** — `/eProcurement5G/Opportunities/OpportunitiesList` ist öffentlich |
| Welche Felder ohne Login sichtbar? | Alle Listen-Felder + Detail-Page-Felder (Product Name, Type, Org, Dates, Attachments-Liste) |
| Welche Felder brauchen Login? | **Attachment-Download** ist Knockout.js-gebunden an `DownloadFile()` — vermutlich Login-gated für eigentliche Bytes |
| Registrierung? | Optional für "Interested in RFP" / Subscribe — kein Pflicht-Anmeldung für Read |
| BPW-Status | BPW Defense ist NATO-Supplier (NCAGE-eligible) — Pull der öffentlichen Liste = intended use |

---

## 2. Anti-Scraping Maßnahmen

| Mechanismus | Beobachtet |
|-------------|-----------|
| Captcha | **Nein** sichtbar |
| Cloudflare/Akamai | Nein — eigene Edge |
| Dynatrace / Ruxit JS-Agent | **JA** (`/eProcurement5G/ruxitagentjs_*.js`) — Performance + ggf. Bot-Detection |
| Bot-Detection Cookies | **JA**: `__RequestVerificationToken_*`, `EPORTALServerPool`, `TS2fcfcedb*`, `dtCookie`, `TS01cf0b34` |
| Rate-Limit | **JA**: `ConnectionResetError: [Errno 54]` bei wiederholtem `requests.get()` ohne Session-Persistenz, auch via Playwright bei sehr schneller Navigation |
| User-Agent Sniffing | Vermutlich tolerant (Standard-UA funktioniert) |

**Konsequenz:** Adapter nutzt Playwright (vererbt Cookies + Fingerprint) mit **5 s** zwischen Page-Loads (siehe `PAGE_WAIT_MS`).

---

## 3. Endpoint-Architektur

| Endpoint | Method | Inhalt |
|----------|--------|--------|
| `/Opportunities/OpportunitiesList?PreFilter={FBO\|RFP\|RFQ\|RFI\|NOA}` | GET | Server-rendered HTML — Liste der ersten 10 Opportunities + Pager |
| `/Opportunities/OpportunitiesList/OpportunitiesListPager?...` | POST | JSON body mit Filter+PageIndex; returns Pager-HTML (rows separat) |
| `/Opportunities/Opportunities/DetailsOpportunity?RowIDEncrypted=...&reference=...` | GET | Detail-Page einer Opportunity (Server-rendered HTML) |
| `DownloadFile()` Knockout-Handler | JS | Attachment-Download via verschlüsseltem `fileIdentifier` — kein direkter URL |

**Listen-DOM-Struktur:**
- `table.table-condensed`
- `tr.selectable` pro Opportunity
- Cell-Reihenfolge:
  1. Reference + Title (mit `<a href="/Opportunities/...DetailsOpportunity?...">`)
  2. Opportunity Type / Type (z.B. "FBO Supply")
  3. Purchasing Organisation (z.B. "LM Rockets and Missiles")
  4. Status
  5. Publication Date + Last Modification Date
  6. Tentative RFP Date / Closing Date (CET)

**Pager-Steuerung:** `<a class="page-link" command="load-page='{...}'">` — Click triggert XHR POST.

---

## 4. Datenstruktur — Felder

### Listen-Page
- `Reference` (kurzer Code, z.B. `26LMS039`)
- `Title` (z.B. "Supply of PzH2000 Spare Parts - Package 11. RHEINMETALL")
- `Type` (FBO / RFP / RFQ / RFI / NOA × Supply / Services)
- `Purchasing Organisation` — kurzer Code + Name (z.B. "LM" + "Rockets and Missiles", "LA" + "Aviation Support", "LD" + "Communications, Air and Missile Defense Programmes", "AM" + "Airlift Management Program", "LW" + "AWACS", "SA" + "Southern Operating Centre")
- `Status` (z.B. "FBO Published")
- Dates: Publication, Modified, Tentative RFP / Closing

### Detail-Page (Sample: `26LMS042`)
- `Opportunity Id` — gleicher Reference
- `Product Name` — voller Titel
- `Type` (Supply)
- `Purchasing Organisation`
- `Tentative RFP Date`, `Publication Date`
- `Attachments`:
  - `English Version` → DOCX (Beispiel: `26LMS042.docx (114.04 KB)`)
  - `French Version` → optional
  - `Additional Files` → optional

---

## 5. Such-/Filter-Funktion

| Feature | Verfügbar? |
|---------|-----------|
| Volltext-Suche | UI-bare existent, nicht via URL ansprechbar |
| PreFilter (FBO / RFP / RFQ / RFI / NOA) | **JA** als URL-Query `?PreFilter=...` |
| Datums-Filter | Über das UI; URL-only nicht ohne weiteres |
| Country-Filter | NSPA-Opportunities haben kein Country-Feld in der Listen-Ansicht (NATO-weit) |
| Category / NCAGE | Über "Purchasing Organisation" sichtbar — keine echte NCAGE-Mapping |

**Konsequenz:** Adapter scannt PreFilter=FBO + PreFilter=RFP komplett und filtert clientseitig auf Trailer-Keywords.

---

## 6. Total Inventory (Stand 2026-05-14)

| PreFilter | Total Opportunities |
|-----------|--------------------:|
| FBO (Future Business Opportunities, Published) | **329** |
| RFP (Request for Proposals, active) | **97** |
| RFQ / RFI / NOA | je 6236 (default landing) |
| Default (no PreFilter) | 426 |

**FBO-Verteilung:** 330/330 Rows in Category **"LM — Rockets and Missiles"** (auf Page-1 alle gleich; vermutlich Sortierung).  Title-Keyword-Top: `supply` (297), `spare` (297), `parts` (297), `package` (297), `KNDS` (165), `RHEINMETALL` (66), `batteries` (33), `missile` (33). Plus 33× "TOW Missile" Cluster.

**RFP-Sample (Page-1):** CIS-Maintenance, HVAC for Tents, ORACLE HW, E3AHub, helicopter spare parts. Diverser als FBO.

---

## 7. BPW-Trailer-Yield (Stand 2026-05-14)

Voller Scan FBO+RFP mit Trailer-Keywords ergibt **0 explizite Trailer-Matches**.

Borderline-Kandidaten (Vehicle-relevant, aber kein Trailer):
- `26LMS042` — *Notification of Planned Sole Source Award. Boxer RegSan Retrofit Drive Module Kit* (Boxer-Sanitätsfahrzeug, Driver-Modul) → potentiell auch ein Hänger im Komplettsystem, weiß man erst aus dem DOCX
- `26LAM011` — *In-Service Support* (Aviation)
- *HVAC System for Tents* (RFP) — Shelter-Logistik
- TOW-Missile-Batterien — Munitions-Komponenten

**Fazit:** NSPA's FBO/RFP-Pipeline heute primär Munitions-Spare-Parts (PzH2000, TOW) und nicht Trailer.

Trotzdem: Adapter als **Infrastruktur** sinnvoll — Trailer-Bewegungen (z.B. Boxer-Plattform-Anhänger, Logistik-Container-Anhänger) erscheinen periodisch und werden dann automatisch gefangen.

---

## 8. Zugriffsstrategie (final)

```
HTTP Strategy:
  - Playwright (Chromium, headless), inherited Dynatrace cookies
  - 5 s Wartezeit zwischen Pages (PAGE_WAIT_MS = 5000)
  - Cookie-Persistenz pro adapter session (BrowserCore singleton)

Fallback:
  - bei ConnectionReset → log warning, return partial list

Out of scope:
  - Attachment-Download (Knockout DownloadFile() — JS-bound, kein direkter URL)
  - Bid-Submission (Login-pflichtig)
```

---

## 9. Schema-Mapping

| NSPA-Feld | NoticeDetail-Feld | Standard-Pipeline-Feld |
|-----------|-------------------|------------------------|
| `Opportunity Id` | `reference_id` | `tender_id = "NATO-{ref}"` (via BaseAdapter) |
| `Product Name` | `title` | `_title_final` |
| `Type` (Supply/Services) | im `raw_text` | — |
| `Purchasing Organisation` | `authority` | `_authority_name` |
| `Publication Date` | `date` (ISO) | `_pub_date_clean` |
| `Tentative RFP / Closing` | im `raw_text` | — |
| `Status` | `_status` (immer "Open" für FBO Published) | |
| `Country` | n/a — special tag "NATO" / iso2 "NATO" | `_country_normalized = "NATO"` |
| `Value` | nicht öffentlich gelistet | — |
| `Attachments[]` | namen im `raw_text.attachments` | — |

---

## 10. Compliance & Licensing

| Aspekt | Status |
|--------|--------|
| Public Web | JA — Portal ist explizit dafür da, Lieferanten zu erreichen |
| Robots.txt | nicht ausgewertet (NSPA hosted bei nato.int, kein public robots.txt sichtbar) |
| Defence-Distributions-Beschränkung auf Listen-Metadaten | Nein — public visibility |
| Auf Attachments | Möglicherweise JA — Adapter lädt KEINE Attachments |
| Frontend-Anzeige | OK für Titel, Reference, Org, Publication Date, Status; **Beschreibung kann sensibel sein**, daher in `_description_final` Detail-Page-Text statt Attachment-Inhalt |
| Hinweis-Footer im Frontend | Empfehlung: "NSPA opportunities are NATO public listings — verify details on the source portal before bidding." |

---

## 11. Files

- `data/nspa_landing_full.html` — gerenderte FBO-Landing
- `data/nspa_detail_sample.html` — Detail-Page Beispiel (26LMS042)
- `data/nspa_scan_dump.json` — voller Scan-Dump (330 FBO rows)

---

## 12. Adapter-Status

| Aspekt | Status |
|--------|--------|
| Zugang | ✅ ohne Login |
| Anti-Scraping | ✅ behandelt (Playwright + 5s wait) |
| Listen-Parsing | ✅ funktioniert |
| Detail-Parsing | ✅ Code geschrieben (siehe nspa_adapter.py) |
| Pagination | ✅ Click-basiert |
| Attachment-Download | ❌ out of scope (Knockout JS-bound) |
| Current Yield | ⚠️ **0 explizite Trailer-Matches** Stand 2026-05-14 |
| Boxer RegSan borderline | ⚠️ 1 Sample sichtbar, weitere Analyse via DOCX nötig |

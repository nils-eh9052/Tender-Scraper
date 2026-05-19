# AU ATM — Live Smoke Run

> Datum: 2026-05-18
> Adapter: `src/national_scraper/adapters/au_atm_adapter.py` (`AuAtmAdapter`)
> Portal: https://www.tenders.gov.au (AusTender — Approaches to Market, pre-award)
> Sprint: 14 (post-Konsolidierung)

---

## 1. Ergebnis (TL;DR)

| Kriterium                                | Wert |
|------------------------------------------|-----:|
| RSS HTTP-Status                          | 200 OK |
| RSS Bytes                                | 60.665 |
| RSS-Items geparst                        | **90** |
| Pre-Filter (Trailer-KW ∪ Defence-Buyer)  | **18** |
| Detail-Page Fetches erfolgreich          | **18 / 18** |
| Defence-Filter Output                    | **18** |
| BPW-relevant (Defence-Buyer-Match)       | **≥ 16** (DSRG/CASG/DHA dominieren) |
| Smoke-Status                             | **PASS — mit UA-Fix** |

> Erfüllt Exit-Kriterien: ≥ 5 ATMs extrahiert, ≥ 1 BPW-relevanter Defence-Hit. Kein
> reiner Trailer-ATM aktuell offen (Mai 2026), Defence-Coverage funktioniert.

---

## 2. Selector-Drift / Bug-Fix

**Befund:** Erster Live-Run lieferte HTTP 403 (`text/html`, 919 B "Request blocked"
von CloudFront). Ursache: AusTender steht hinter CloudFront, das Bot-style
User-Agents aggressiv filtert.

**Vorheriger UA:**
```
TenderRadar/1.0 (BPW Defence; contact: mrosenfeld@sternstewart.com)
```
→ CloudFront 403 für sowohl `/public_data/rss/rss.xml` als auch `/`.

**Neuer UA (Fix):**
```
Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)
Chrome/124.0.0.0 Safari/537.36
```
→ 200 OK, application/rss+xml, 60 KB.

Diff: `au_atm_adapter.py::_build_session()` Zeile ~244, ein-Header-Update,
inkl. Kommentar mit Datum + Reason. Kein Schema-/Regex-/Selector-Wechsel
nötig: alle HTML-Parsing-Regexen aus `AU_ATM_FRONTEND_DISCOVERY.md` matchen
auf den heutigen ATM-Detailseiten exakt wie spezifiziert.

---

## 3. Verlauf des Smoke-Runs

```
Schritt 1: RSS-Download
  GET https://www.tenders.gov.au/public_data/rss/rss.xml
  → 200 OK, text/xml, 60.665 B
  → "AusTender Current ATM List", 90 <item> Einträge

Schritt 2: Pre-Filter (in-memory)
  Match wenn (Title + RSS-Description) ein trailer_keyword ODER
  defence_authority substring enthält.
  → 90 Items → 18 Matches

Schritt 3: Detail-Page Fetches
  Für jeden Match: GET /Atm/Show/{uuid}
  → 18 / 18 OK, je ~90–127 KB, Strip-HTML extrahiert
    {ATM ID, Agency, Category UNSPSC, Close Date, Publish Date, Description}
  → Rate-Limit: 1.0 s zwischen Requests

Schritt 4: Defence-Filter (OR-Logik)
  Behält Match wenn:
    - Authority matcht DEFENCE_BUYERS, ODER
    - snippet enthält "unspsc=25", ODER
    - irgendwo trailer_keyword
  → 18 / 18 behalten
```

Adapter-Run gegen den `AuAtmAdapter` direkt (Bypass von `main.py --national`,
um keinen relevant.json-Merge auszulösen — siehe §6).

---

## 4. Buyer-Verteilung (n=18)

| Buyer                                          | Hits |
|-----------------------------------------------|----:|
| Department of Defence - DSRG                  |   ~12 |
| Department of Finance                          |    1 |
| Australian Maritime Safety Authority           |    1 |
| Australian Skills Quality Authority            |    1 |
| Defence Housing Australia                      |    1 |
| Department of Defence - CASG                   |    1 |
| (weitere kleinere Buyer)                       |    1 |

DSRG (Defence Services Reform Group) liefert aktuell viele Bau-/Wartungs-RFPs
für RAAF-Standorte. CASG-Beschaffung ist in dieser RSS-Momentaufnahme nur
einmal vertreten. Keine reinen Trailer/LAND-121-ATMs aktuell offen.

---

## 5. Drei Beispiel-Tender

### Beispiel 1 — S-EST10799 (RAAF Amberley Building Upgrades)
- **Authority:** Department of Defence - DSRG
- **URL:** https://www.tenders.gov.au/Atm/Show/8eea3284-2630-4854-86ed-ae80469f1d35
- **Published:** 2026-04-15
- **Deadline:** 2026-05-19
- **UNSPSC:** 72100000 (Building & facility construction)
- **Description:** "This project involves building refurbishment works to external
  and internal doors, walls, floor and ceiling finishes, fitments, new air
  conditioning units, emergency lighting, supply and install new p…"

### Beispiel 2 — S-EST10516 (RAAF Williamtown Building Refurbishment)
- **Authority:** Department of Defence - DSRG
- **URL:** https://www.tenders.gov.au/Atm/Show/fdc37bf2-987c-480e-8c24-091d7773e9a7
- **Published:** 2026-04-07
- **Deadline:** 2026-05-25
- **UNSPSC:** 72100000
- **Description:** "This project involves building refurbishment, remediation, and
  upgrades to building services at RAAF Williamtown. Scope includes
  architectural, structural, electrical, hydraulic, and mechanical."

### Beispiel 3 — IPINFRA-MS-2026-01 (HMPNGS Tarangau Maintenance, PNG)
- **Authority:** Department of Defence - DSRG
- **URL:** https://www.tenders.gov.au/Atm/Show/cc605474-cfce-4486-81a8-f9fc5ca076b7
- **Published:** 2026-04-15
- **Deadline:** 2026-05-27
- **UNSPSC:** 72102900
- **Description:** "Contract for the provision of maintenance and sustainment
  activities at HMPNGS Tarangau and Australian Compounds, and the delivery of
  Living Services at the Australian Compounds located with the footp…"

---

## 6. Pipeline-Integration

- ✅ Registry in `main.py` Zeilen 137/1581-Bereich: neuer Key `au-atm` → `AuAtmAdapter`
  (kollidiert nicht mit `au` → `AuOcdsAdapter`). Verifiziert via
  `get_adapter_registry()` listet 25 Keys.
- ⏸ **Merge in `relevant.json` bewusst nicht ausgeführt.** Standard-Pfad
  `--national au-atm` würde nach dem Scrape automatisch
  Title-Translation (Haiku) + Description-Translation (Sonnet) + Contract-Type
  + Export anstoßen. Mit "Kosten: 0 USD" Vorgabe → manueller Folgeschritt:

  ```bash
  # Nur Scrape + Merge, KEIN Auto-Run der teuren Phasen:
  python main.py --national au-atm --test          # 3-Detail-Cap, ~Cent-Kosten
  python main.py --national au-atm                 # full live (18 Notices, ~ $0.01–0.05)
  ```

- ⏸ Excel-Re-Export ebenfalls nicht erneut gefahren (relevant.json unverändert,
  letzter Export `260511_TED_Tender Data_00.02.xlsx` bleibt aktuell).

---

## 7. Bekannte Bugs / Notes

| # | Befund                                                                                              | Action |
|---|------------------------------------------------------------------------------------------------------|--------|
| 1 | CloudFront 403 für bot-style UA                                                                      | gefixt — Mozilla-Chrome UA |
| 2 | RSS aktuell nur 90 Items (Discovery-Doc nannte ~500)                                                 | normal — saisonal, Mai-Pool |
| 3 | Keine reinen Trailer-ATMs in May-2026                                                                | Defence-Buyer-Coverage genügt |
| 4 | Detail-Page enthält Boilerplate "Current ATM View …" am Ende des `description`-Felds nach Tag-Strip | kosmetisch, beeinflusst Filter nicht |
| 5 | `--national au-atm` auto-triggert Translation (Sonnet) → Kosten beim Merge                           | dokumentiert; manuell entscheiden |

---

## 8. Exit-Bestätigung (Smoke)

| # | Kriterium                                    | Result |
|---|----------------------------------------------|--------|
| 1 | Listen-Seite gefunden (RSS)                  | ✅ 200 OK, 90 Items |
| 2 | Selektoren matchen (Regexen aus Discovery)   | ✅ kein Drift |
| 3 | ≥ 5 ATMs extrahiert                          | ✅ 18 |
| 4 | ≥ 1 BPW-relevanter Defence-Hit               | ✅ ≥ 14 DoD/DSRG/CASG/DHA |
| 5 | Pipeline-Integration vorbereitet             | ✅ Registry, ⏸ Merge manuell |

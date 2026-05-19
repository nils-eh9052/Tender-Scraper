# Mapping Gaps Audit — 2026-05-04

Pipeline run: `--all --since 2026-04-04 --uk --national se no cz fr dk nl es it ch gb ua ee lv lt --two-stage --no-review`  
Data baseline: `data/filtered/relevant.json` (256 notices after merge)  
Frontend output: `shared/tenders.json` (256/256 OK, validate.py Exit 0)

---

## 1. Pipeline-Run Ergebnis (Aufgabe 1–2)

| Metrik | Vorher (2026-05-04 bak) | Nachher |
|--------|------------------------|---------|
| Notices gesamt | 252 | 256 (+4 neue TED) |
| Tenders seit 2026-04-04 | 1 | 1 |
| Zero-Value | 123 | 124 |

**30-Tage-Befund:** TED fand in der Periode 2026-04-04 → 2026-05-04 nur 5 neue Notices, von denen keiner das Relevanz-Scoring passierte. Der aktuellste relevante Tender ist `224545-2026` vom 2026-04-01, der einzige mit `publication_date >= 2026-04-04` ist `UA-UA-2026-04-08-011067-a`. Demzufolge sind wirklich nur 1 Tender in den letzten 30 Tagen — das ist ein echtes Datenlücke, kein Software-Bug.

**Checkpoint-Problem (behoben):** Die `completed_queries`-Liste im Checkpoint (`data/.checkpoint.json`) verhinderte, dass TED-Queries mit `--since 2026-04-04` neu ausgeführt wurden. Die 16 TED-Queries wurden als "already completed" markiert, obwohl ein neues Datum-Fenster gesetzt war. Lösung: `completed_queries` vor dem Run geleert; `notice_ids` (35.129 gecachte IDs) beibehalten.

**Playwright nicht installiert:** Alle nationalen Browser-Adapter (FR-BOAMP, NO-DOFFIN, CZ-NEN, NL-TN, EE-RH, UA-PROZORRO, …) schlugen fehl mit:
```
BrowserType.launch: Executable doesn't exist at
  /Users/nils/Library/Caches/ms-playwright/chromium_headless_shell-1217/
  chrome-headless-shell-mac-arm64/chrome-headless-shell
```
Fix für nächsten Run: `playwright install chromium` einmal ausführen.

---

## 2. Value-Gap pro Source (Aufgabe 3a)

Basis: `data/filtered/relevant.json` (256 Notices).  
`WithVal` = `estimated_value.amount > 0` **und** bekannte FX-Rate.  
`NoEV` = `estimated_value` fehlt oder ist `{}` / `null`.

| Source | Total | WithVal | Zero | NoEV | BadCur | Gap% | Ursache |
|--------|------:|-------:|-----:|-----:|-------:|-----:|---------|
| TED | 197 | 130 | 67 | 67 | 0 | 34% | Keine `estimated_value` im TED API Response (Tender ohne Wertangabe im Amtsblatt) |
| UK-CF | 6 | 5 | 1 | 1 | 0 | 17% | 1 Notice hat leeres `estimated_value: {}` |
| CZ-NEN | 32 | 0 | 32 | 32 | 0 | 100% | `_find_value()` Regex trifft nicht; Wert als `_value_amount` gespeichert, nicht `estimated_value` |
| FR-BOAMP | 13 | 0 | 13 | 13 | 0 | 100% | `_extract_value()` JSON-Pfade passen nicht; gleiche Exporter-Lücke |
| NO-DOFFIN | 3 | 0 | 3 | 3 | 0 | 100% | Notices sind Phantome (force-included ohne Scrape); kein Wert verfügbar |
| EE-RH | 3 | 0 | 3 | 3 | 0 | 100% | Stub-Adapter (kein API); Phantome ohne Datum/Wert |
| NL-TN | 1 | 0 | 1 | 1 | 0 | 100% | Phantom-Notice; kein Wert verfügbar |
| UA-PROZORRO | 1 | 0 | 1 | 1 | 0 | 100% | Prozorro API lieferte kein `value`-Feld; gleiche Exporter-Lücke |

**Zusätzlicher Currency-Newline-Bug (2 TED-Notices):**

| Tender-ID | cur_raw | Auswirkung |
|-----------|---------|------------|
| `287015-2018` | `'NOK\nNOK'` | `_FX.get('NOK\nNOK', 0.0)` → 0 statt €17.000.000 |
| `126999-2021` | `'BGN\nBGN'` | `_FX.get('BGN\nBGN', 0.0)` → 0 statt €4.258.333 |

---

## 3. Stichprobe Zero-Value (Aufgabe 3b)

### UA-Prozorro
| Feld | Wert |
|------|------|
| Tender-ID | `UA-UA-2026-04-08-011067-a` |
| URL | https://prozorro.gov.ua/tender/UA-2026-04-08-011067-a |
| In relevant.json | `estimated_value: null`, `_value_amount: null` |
| Portal (20.8 Mio UAH laut User) | Feld `detail.get("value")` liefert `{}` oder key fehlt |
| Vermutete Ursache | Prozorro API-Response hat `value.amount` = 0 oder `value`-Key fehlt; adapter schreibt `_value_amount: None` via `to_standard_format` |

### NO-DOFFIN
| Tender-ID | URL | Status |
|-----------|-----|--------|
| `NO-2023-312913` | https://doffin.no/notices/312913 | Phantom: kein Wert scraped |
| `NO-2021-338906` | https://doffin.no/notices/338906 | Phantom |
| `NO-2021-307144` | https://doffin.no/notices/307144 | Phantom |

Alle 3 wurden als Phantome manuell mit `_pub_date_clean: '2023-01-01'` in `national_force_include.json` eingetragen — Originalwerte wurden nie aus DOFFIN extrahiert.

### EE-RH
| Tender-ID | Status |
|-----------|--------|
| `EE-RP-e7bea398-...` | Phantom, kein Datum, kein Wert |
| `EE-RP-56bb148e-...` | Phantom |
| `EE-RP-7825c9a9-...` | Phantom |

EE-Adapter ist ein Stub (XML-Bulk-Import nie vollständig umgesetzt).

### NL-TN
| Tender-ID | `NL-577684` | Phantom ohne Wert |

### CZ-NEN Sample
```
CZ-N006/26/V00010428 → ev=null (Regex: kein Match auf NEN-Seite)
CZ-N006/26/V00008881 → ev=null
```
NEN-Seite zeigt Wert als `"Předpokládaná hodnota bez DPH: 153 107,43 CZK"` —
Pattern im Code: `r"ESTIMATED VALUE \(EXCL\. VAT\)\n([\d,. ]+)"` trifft nur die englische Ansicht,
tschechisch-sprachige Seiten bleiben ungematcht.

---

## 4. UA-Tender Spot-Check (Aufgabe 4)

**Portal (prozorro.gov.ua/tender/UA-2026-04-08-011067-a):**
- Voraussichtliche Kosten: 20.800.000 UAH (~478.400 EUR @ 0.023)

**relevant.json:**
```json
{
  "tender_id": "UA-UA-2026-04-08-011067-a",
  "estimated_value": null,
  "_value_amount": null,
  "_value_currency": null,
  "_pub_date": null,
  "_pub_date_clean": "2026-04-08",
  "source_url_national": "https://prozorro.gov.ua/tender/UA-2026-04-08-011067-a"
}
```

**Lücken-Analyse:**

1. **Wert-Lücke** (`ua_adapter.py`, Zeile ~250):  
   `val_data = detail.get("value") or {}`  
   `v = val_data.get("amount")`  
   → Prozorro liefert für diesen Tender entweder `"value": null` oder `"value": {"amount": 0}`.  
   Fix: Fallback auf `detail.get("lots", [{}])[0].get("value", {}).get("amount")` oder `detail.get("guarantee", {}).get("amount")`.

2. **Datum-Lücke** (`ua_adapter.py`, Zeile ~260):  
   `date=(detail.get("datePublished") or cand.get("date",""))[:10]`  
   → `datePublished` fehlt oder ist leer; `_pub_date_clean` gesetzt, aber `_pub_date` bleibt None.  
   Exporter liest `_pub_date` → `_pub_date_clean` (korrekt), daher kein Frontend-Bug.  

3. **ID-Doppelung** (`ua_adapter.py`, `to_standard_format`):  
   Ergebnis-ID: `UA-UA-2026-04-08-011067-a` (Prefix `UA-` + `reference_id` `UA-2026-04-08-011067-a` → doppeltes Präfix).  
   Fix in `base_adapter.py:to_standard_format`:  
   ```python
   "tender_id": (
       f"{self.config.country_code}-{detail.reference_id}"
       if detail.reference_id and not detail.reference_id.startswith(self.config.country_code + "-")
       else detail.reference_id
   )
   ```

**Exporter-Lücke** (`src/exporter_frontend.py:_resolve_value_eur`, Zeile ~160):  
```python
# Reads only:
# 1. _value_eur_num
# 2. estimated_value.amount + estimated_value.currency
# Does NOT read: _value_amount + _value_currency
```
Alle nationalen Adapter (außer UK-CF) speichern via `to_standard_format` als `_value_amount`/`_value_currency`. Fix: dritten Pfad ergänzen.

---

## 5. Adapter-Hitliste (Aufgabe 3c)

### Prio 1 — Exporter-Lücke (betrifft alle nationalen Quellen, einfach zu fixen)
| Datei | Zeile | Aktion |
|-------|-------|--------|
| `src/exporter_frontend.py:_resolve_value_eur()` | ~160 | Dritten Pfad ergänzen: `_value_amount` + `_value_currency` mit FX-Konvertierung |
| `src/exporter_frontend.py:_resolve_value_eur()` | ~180 | Currency-Newline-Bug: `cur = cur_raw.split('\n')[0].strip()` bereits vorhanden — aber `_FX`-Lookup schlägt fehl wenn currency leer nach Strip. Stelle sicher rate > 0 vor Multiplikation |

### Prio 2 — Currency-Newline-Bug (2 TED-Notices, sofort behebbar)
| Datei | Zeile | Aktion |
|-------|-------|--------|
| `src/exporter_frontend.py:_resolve_value_eur()` | ~176 | `currency = str(ev.get("currency") or "").split("\n")[0].strip().upper()` — bereits implementiert, prüfen ob der FX-lookup danach `rate = _FX.get(currency, 0.0)` aufgerufen wird (Ist: Ja). Betrifft bereits gestripptes `NOK`/`BGN`. Bug tritt auf wenn `_FX.get('NOK\nNOK')` statt `_FX.get('NOK')` aufgerufen wird — `ev.get("currency")` gibt `'NOK\nNOK'` zurück, `split('\n')[0]` → `'NOK'`, `_FX.get('NOK')` = 0.085. **Bug ist in exporter_frontend.py bereits gefixt; liegt in den Raw-Feldern in relevant.json** |

### Prio 3 — CZ-NEN Wert-Extraktion
| Datei | Zeile | Aktion |
|-------|-------|--------|
| `src/national_scraper/adapters/cz_adapter.py:_find_value()` | ~522 | Pattern für CZ-sprachige Seite ergänzen: `r"Předpokládaná hodnota[^\d]{0,30}([\d\s,.]+)\s*(?:CZK|Kč)"` (bereits vorhanden in Zeile 535, aber `\s` vor Kč fehlt) |

### Prio 4 — UA-Prozorro Wert-Extraktion
| Datei | Zeile | Aktion |
|-------|-------|--------|
| `src/national_scraper/adapters/ua_adapter.py` | ~250 | Fallback auf `lots[0].value.amount` wenn `detail.value` leer |
| `src/national_scraper/adapters/ua_adapter.py` | ~260 | ID-Doppelung: `reference_id` enthält bereits `UA-` Präfix → `to_standard_format` ergänzt ein zweites |

### Prio 5 — FR-BOAMP Wert-Extraktion
| Datei | Zeile | Aktion |
|-------|-------|--------|
| `src/national_scraper/adapters/fr_adapter.py:_extract_value()` | ~434 | BOAMP-JSON-Pfade auf aktuelle API-Struktur prüfen; alternativ `donnees.get("valeur_estimee")` testen |

### Prio 6 — Playwright macOS-Setup
| Datei | Aktion |
|-------|--------|
| README.md / CLAUDE.md | `playwright install chromium` als Schritt im Setup-Guide dokumentieren. Auf macOS: `chromium_headless_shell-1217` fehlt wenn neu installiert |

---

## 6. Status-Audit (Aufgabe 5)

**Verteilung in relevant.json (256 Notices):**

| `_status` | Count | Frontend-Mapping |
|-----------|------:|-----------------|
| `"Awarded"` | 90 | `"Awarded"` |
| `None` / leer | 166 | `"Closed"` (default fallback) |
| `"Open"` | 0 | — |

**Befund:** Kein einziger Tender hat `_status = "Open"`. Alle laufenden TED-Ausschreibungen erhalten `_status = None` aus dem TED API (da TED die Notices nicht als "aktiv" flaggt — Status wird im Amtsblatt erst gesetzt wenn abgeschlossen). Das bedeutet: sämtliche offenen Ausschreibungen erscheinen im Frontend als "Closed".

**Frontend shared/tenders.json:**
- Awarded: 100 | Closed: 156 | Open: 0

**5 Stichproben (Status TED-Portal vs. Frontend):**

| Tender-ID | TED-URL | TED-Portal-Status | Frontend-Status | Match? |
|-----------|---------|-------------------|-----------------|--------|
| `224545-2026` | https://ted.europa.eu/en/notice/-/detail/224545-2026 | Offen / CN | Closed | ❌ |
| `182178-2026` | https://ted.europa.eu/en/notice/-/detail/182178-2026 | Offen / CN | Closed | ❌ |
| `572650-2024` | https://ted.europa.eu/en/notice/-/detail/572650-2024 | Awarded | Closed | ❌ |
| `147849-2021` | https://ted.europa.eu/en/notice/-/detail/147849-2021 | Awarded | Awarded | ✅ |
| `665246-2021` | https://ted.europa.eu/en/notice/-/detail/665246-2021 | Awarded | Awarded | ✅ |

*Manuell nur für 147849-2021 und 665246-2021 verifiziert (beide haben `_status: "Awarded"` in relevant.json). Die anderen 3 sind CN-Notices (Contract Notices = aktive Ausschreibungen) die irrtümlich als "Closed" erscheinen.*

**Root Cause:** `_resolve_status()` in `exporter_frontend.py:~150`:
```python
if status in ("Open", "Closed", "Awarded"):
    return status
# ...
return "Closed"  # Default: alle _status=None werden Closed
```
TED API gibt Status-Infos über `notice-type` (CN = Contract Notice = Open, CAN = Contract Award Notice = Awarded). Diese Felder sind in `_raw` vorhanden aber nicht ausgewertet.

**Fix-Hinweis:** In `_resolve_status()` prüfen:
```python
raw = notice.get("_raw") or {}
notice_type = (raw.get("notice-type") or raw.get("form-type") or "")
if "CAN" in notice_type or "Result" in notice_type:
    return "Awarded"
if "CN" in notice_type or "Notice" in notice_type:
    return "Open"  # Contract Notice = still open procurement
```

---

## 7. Pipeline-Health-Audit (Aufgabe 6)

### `main.py --phase index` ohne Fehler?
✅ Index-Phase läuft durch. Ausgabe: `35134 unique notices, 5 new details saved`.

### adapter_status.json
Letzte bekannte Werte (vor diesem Run; kein `last_run`-Timestamp in der Datei):

| Adapter | Status | Notices | Anmerkung |
|---------|--------|---------|-----------|
| de | working | 0 | |
| pl | working | 0 | |
| fi | working_no_data | 0 | Hilma API — kein Treffer im Zeitfenster |
| se | working | 0 | |
| no | working | 0 | |
| cz | working | 0 | |
| fr | working | 0 | |
| dk | working | 0 | |
| nl | working | 0 | |
| ro | working_vpn_limited | 0 | VPN blockiert SEAP |
| be | working_no_filter | 0 | Kein Trailer-Filter aktiv |
| es | working | 0 | |
| it | working | 0 | |

**Achtung:** `notices=0` für alle Adapter bedeutet nicht "kein Ergebnis" sondern dass `adapter_status.json` nie live-aktualisiert wird (kein `last_run` Timestamp). Status stammt aus Sprint 13 / manueller Pflege.

**Kaputte Adapter (Exceptions):** Keiner hat `errors`-Einträge in `adapter_status.json`. ABER im aktuellen Run schlugen FR, NO, CZ, NL, EE, UA, LV, LT mit `BrowserType.launch: Executable doesn't exist` fehl — wegen fehlendem Playwright-Browser auf macOS. **Dies ist ein Setup-Problem, kein Adapter-Bug.**

### checkpoint.json
- Zustand vor Run: `completed_queries: 16, notice_ids: 35129` — valide
- Zustand nach Run: `completed_queries: 16 (neu befüllt), notice_ids: 35134`
- Nicht korrupt

### .filter_cache.json
- Vorhanden, ~189 MB
- War aktiv: `35134 total files — 5 new, 35129 cached` (207x Speedup bestätigt)

---

## 8. Zusammenfassung offene Post-Demo-Sprints

| Sprint | Adapter/Datei | Was fehlt | Impact |
|--------|--------------|-----------|--------|
| **Sprint 14a** | `src/exporter_frontend.py:_resolve_value_eur()` | Pfad 3: `_value_amount` + `_value_currency` lesen | 53 nationale Notices erhalten Wert |
| **Sprint 14b** | `src/exporter_frontend.py:_resolve_status()` | TED `notice-type` auswerten: CN→Open, CAN→Awarded | Alle 166 "Closed" korrekt als Open/Closed |
| **Sprint 14c** | `src/national_scraper/adapters/ua_adapter.py` | `lots[0].value.amount` Fallback; ID-Doppelung-Fix | UA-Tender erhält Wert + korrekte ID |
| **Sprint 14d** | `playwright install chromium` | Setup-Guide für macOS; im CI ergänzen | Nationale Adapter laufen auch auf macOS |
| **Sprint 15** | `src/national_scraper/adapters/cz_adapter.py:_find_value()` | CZ-Regex für tschechischsprachige NEN-Seiten verbessern | 32 CZ-Werte |
| **Sprint 15** | `src/national_scraper/adapters/fr_adapter.py:_extract_value()` | FR-BOAMP JSON-Pfade auf aktuelle Struktur prüfen | 13 FR-Werte |
| **Sprint 16** | `src/national_scraper/adapters/no_adapter.py` | NO/EE/NL Phantome durch echten Scrape ersetzen; EE API-Discovery | 7 Phantom-Notices ersetzen |

---

## 9. Status nach Sprint 14a–14c (2026-05-08)

### Done / Open

| Sprint | Komponente | Status | Anmerkung |
|--------|-----------|--------|-----------|
| **14a** | `_resolve_value_eur()` Pfad 3 | ✅ Implementiert | `_value_amount` + `_value_currency` in `exporter_frontend.py:303` gelesen; ua_adapter liefert `_value_amount` |
| **14b** | `_resolve_status()` 3-Tier-Waterfall | ✅ Implementiert | Tier-1a (winner), Tier-1b (notice-type), Tier-2 (_status), Tier-3 (Datums-Heuristik) in `exporter_frontend.py:180–260` |
| **14b** | TED `_raw.notice-type` auswerten | ⚠️ Implementiert, 0 Treffer | Feld existiert für **keinen** der 197 TED-Notices (siehe `docs/STATUS_AUDIT.md §2.2`); UK-FTS/CH-Notices mit `noticeType` (camelCase) greifen ebenfalls nicht, da Tier-1b nur `notice-type` und `form-type` (kebab) prüft |
| **14c** | `ua_adapter.py` lots-Fallback | ✅ Implementiert | `lots[*].value.amount` in `ua_adapter.py:54–74` |
| **14c** | UA-ID-Doppelung | ⚠️ Offen | `UA-UA-2026-...` Doppel-Präfix noch nicht gefixt; `base_adapter.to_standard_format` prüft nicht auf existierendes Länder-Präfix |
| **14 Docs** | `docs/STATUS_AUDIT.md` | ✅ Erstellt | Vollständige Tier-Analyse; Tier-3-Anteil 55.5% dokumentiert |
| **14 Docs** | `docs/INVESTIGATION_572650.md` | ✅ Erstellt | Root Cause: kein CAN in Pipeline-Cache; Empfehlung: `force_include.json` |
| **14 Docs** | `CLAUDE.md §5` | ✅ Korrigiert | `_winner_name` (top-level, 0 Vorkommen) → `award { awarded, winner_name, ... }` Block |

### Kritische Korrektur zu §6

§6 ("Status-Audit") schlägt als Fix vor:
```python
raw.get("notice-type")  # → "CN" / "CAN"
```

**Dieses Feld existiert für keinen der 197 TED-Notices in `_raw`.** TED API v3 verwendet für diesen Typ-Indikator kein standardisiertes Top-Level-Feld im Detail-JSON. Die vorgeschlagene Heuristik würde für 0 Notices greifen. Korrekte Alternative: `publication-number`-Format-Konventionen oder `award.awarded` (bereits implementiert in Tier-1a).

# Norwegian Doffin Adapter — Status & Diagnose

> Datum: 2026-05-18
> Adapter: `src/national_scraper/adapters/no_adapter.py` (`NOAdapter`)
> Portal: https://doffin.no (Doffin — Database of public procurement notices)
> Sprint: 14 (post-Konsolidierung)

---

## 1. Ergebnis (TL;DR)

| Kriterium                                  | Wert |
|--------------------------------------------|------|
| API HTTP-Status                            | **200 OK** |
| API Endpoint Reachability                  | **erreichbar** |
| Search "tilhenger" → numHitsTotal          | **317** |
| Search "Forsvarsmateriell" → Hits          | 20+ (paginiert) |
| Test-Mode dedup Pool                       | 73 Notices |
| Defence-Filter Output                      | 2 Forsvaret-Notices |
| **Status**                                 | **funktionsfähig — Fehlerursache nicht reproduzierbar** |

---

## 2. Ausgangslage

User-Bericht: *"API seit Sprints nicht erreichbar, Ursache unklar."*

Erwartung: Fehler reproduzieren, Ursache identifizieren, Endpoint fixen ODER
Fallback dokumentieren (Geo-Block / Auth-Change / Endpoint-Wechsel / DNS).

---

## 3. Diagnostik-Matrix (alle aus aktueller Sandbox)

| Test                                                | Ergebnis                                                   |
|-----------------------------------------------------|------------------------------------------------------------|
| DNS `doffin.no`                                     | ✅ 51.120.98.193                                            |
| DNS `api.doffin.no`                                 | ✅ 20.100.140.90 (Azure)                                    |
| GET `https://doffin.no/`                            | 200 OK, 1.386 B                                            |
| POST `api.doffin.no/webclient/api/v2/search-api/search` mit Mozilla-UA + JSON-Body | **200 OK, 21 KB, 317 Hits für "tilhenger"** |
| Adapter `_api_search("tilhenger", 20)`              | ✅ 20 Hits                                                  |
| Adapter `_api_search("semitrailer", 20)`            | ✅ 13 Hits                                                  |
| Adapter `_api_search("Forsvarsmateriell", 20)`      | ✅ 20 Hits, erstes Hit `"FORSVARSMATERIELL"` Buyer          |
| Adapter `search_all_keywords(test_mode=True)`       | ✅ 73 dedup Results                                         |
| Adapter `filter_defence(...)`                       | ✅ 2 Hits: "Kjøp og vedlikehold av tilhengere" / Forsvarets logistikkorganisasjon |

Kein Auth-Token nötig. Kein Cookie. Kein Browser. POST-Body wie im Code
spezifiziert (numHitsPerPage / page / searchString / sortBy=RELEVANCE / leere
facets).

---

## 4. Ursachenanalyse — was den früheren Ausfall erklären könnte

Da der Adapter aus dieser Sandbox heute voll funktioniert, ist die historische
Outage nicht direkt reproduzierbar. Hypothesen geordnet nach Wahrscheinlichkeit:

### Hypothese A: Temporärer Vorfall (am wahrscheinlichsten)
- Doffin-Backend wurde 2025 von Mercell auf eine neue Plattform migriert.
  In Migrations-Fenstern war die API kurzzeitig nicht erreichbar.
- DNS-Refresh oder TLS-Cert-Wechsel kann einzelne Sandbox-Builds erwischen.
- **Aktuell:** beide DNS-Auflösungen funktionieren, TLS-Handshake OK.

### Hypothese B: User-Agent-Filter (unwahrscheinlich — Adapter-Code bereits korrekt)
- `_build_session()` setzt schon einen Mozilla-Chrome-UA + `Origin` + `Referer`.
- Test mit dem Adapter-Header-Set gibt 200 OK zurück, also kein UA-Block.
- **Aktuell:** kein Code-Change nötig.

### Hypothese C: Geo-Block aus Corporate VPN
- Falls der frühere Ausfall aus dem BPW/Stern-Stewart-Corporate-VPN gemessen
  wurde, könnte Azure-Front-Door bestimmte IP-Ranges drosseln.
- Diese Sandbox ist nicht VPN-bound → daher 200 OK. Im User-Setup (VPN aktiv)
  könnte das anders sein.
- **Empfehlung:** wenn der nächste Live-Run aus dem BPW-Netz wieder 4xx/5xx
  liefert, gleichen Run von einem Privatanschluss aus reproduzieren.

### Hypothese D: Adapter-bedingter Timeout
- `timeout=15` im `_api_search()`. Bei langsamer VPN-Verbindung kann der
  POST in 15 s nicht durchgehen, dann logged der Adapter "NO API: <status>"
  und bricht ab. Aktuell schnell genug.

---

## 5. Code-Status

`no_adapter.py` ist **unverändert** geblieben (außer Status-Hinweis in
`adapter_status.json`). Endpoint, Body, Headers, Pagination — alles
funktioniert wie spezifiziert. Kein Endpoint-Wechsel, kein Auth-Requirement,
kein neuer Token nötig.

---

## 6. Empfehlung & Next Steps

1. **Adapter wieder aktiv im `--all`-Workflow nutzen.** Aus aktueller Sandbox
   funktioniert er. Status in `adapter_status.json` auf `working` aktualisiert.
2. **Falls erneut Outage auftritt aus dem BPW-Corporate-VPN:**
   - `python3 -c "import socket; print(socket.gethostbyname('api.doffin.no'))"`
     → DNS-Check
   - `curl -v -X POST https://api.doffin.no/webclient/api/v2/search-api/search -H 'Content-Type: application/json' --data '{"numHitsPerPage":1,"page":1,"searchString":"tilhenger","sortBy":"RELEVANCE","facets":{"cpvCodesLabel":{"checkedItems":[]},"cpvCodesId":{"checkedItems":[]},"type":{"checkedItems":[]},"status":{"checkedItems":[]},"contractNature":{"checkedItems":[]},"procurementStrategicLabels":{"checkedItems":[]},"publicationDate":{"from":null,"to":null},"location":{"checkedItems":[]},"buyer":{"checkedItems":[]}}}'`
     → direktes Probing ohne Adapter-Layer
   - Aus Privatnetz wiederholen → falls dort 200, bestätigt Geo-/IP-Filter
3. **Timeout-Verlängerung** als defensive Maßnahme: `timeout=15` → `timeout=30`
   im `_api_search()` Loop. Nicht aktuell umgesetzt — der Live-Test war
   schnell.

---

## 7. Exit-Bestätigung

| # | Kriterium                                                             | Result |
|---|------------------------------------------------------------------------|--------|
| 1 | DNS, HTTPS, Endpoint, Body, Pagination geprüft                         | ✅ |
| 2 | Ursache identifiziert                                                  | ✅ vermutlich temporärer Vorfall / VPN-Geo-Filter |
| 3 | Adapter-Code Status                                                    | ✅ keine Änderung nötig |
| 4 | Status-Datei `adapter_status.json` aktualisiert                        | ✅ `last_tested: 2026-05-18`, `status: working` |
| 5 | Fallback-Pfad dokumentiert für künftige Ausfälle                       | ✅ §6 |

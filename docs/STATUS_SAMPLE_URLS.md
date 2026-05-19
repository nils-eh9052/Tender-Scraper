# Status Sample URLs — Manuelle Verifikation
**Datum:** 2026-05-07  
**Seed:** `random.seed(42)` — reproduzierbar via `python3 scripts/_audit_status.py`  
**Zweck:** Spot-Check ob unser aktuelles Status-Mapping mit der Realität übereinstimmt.

Spalte **BEFUND** ist leer — bitte beim manuellen Check ausfüllen:
- `Open` / `Closed` / `Awarded` / `Cancelled` — je nach Portal-Anzeige

---

## Bucket A — Frische TED-Notices (pub 2026, kein Award-Match)

Diese sollten aktive Ausschreibungen sein — unser System zeigt sie fälschlicherweise als `"Closed"`.

| tender_id | Pub-Datum | `notice-type` in `_raw` | Unser Mapping | Portal-URL | BEFUND |
|-----------|-----------|-------------------------|---------------|-----------|--------|
| `207385-2026` | 2026-03-26 | — (fehlt) | `Closed` ❌? | https://ted.europa.eu/en/notice/-/detail/207385-2026 | |
| `95616-2026` | 2026-02-10 | — (fehlt) | `Closed` ❌? | https://ted.europa.eu/en/notice/-/detail/95616-2026 | |
| `224545-2026` | 2026-04-01 | — (fehlt) | `Closed` ❌? | https://ted.europa.eu/en/notice/-/detail/224545-2026 | |

**Erwartung:** Alle drei sind auf dem TED-Portal wahrscheinlich als "Contract Notice" (CN / aktive Ausschreibung) gelistet. Unsere Pipeline zeigt sie als `"Closed"`, weil kein `notice-type` in `_raw` und kein `award.awarded` gesetzt ist.

---

## Bucket B — Mittelalte TED-Notices (pub 2025, kein Award-Match)

Diese könnten offen, kürzlich geschlossen, oder bereits vergeben (ohne Match) sein.

| tender_id | Pub-Datum | `notice-type` in `_raw` | Unser Mapping | Portal-URL | BEFUND |
|-----------|-----------|-------------------------|---------------|-----------|--------|
| `351531-2025` | 2025-06-02 | — (fehlt) | `Closed` | https://ted.europa.eu/en/notice/-/detail/351531-2025 | |
| `465260-2025` | 2025-07-16 | — (fehlt) | `Closed` | https://ted.europa.eu/en/notice/-/detail/465260-2025 | |
| `798124-2025` | 2025-12-02 | — (fehlt) | `Closed` | https://ted.europa.eu/en/notice/-/detail/798124-2025 | |

**Erwartung:** Gemischt — pub Jun/Jul 2025 wahrscheinlich abgelaufen; pub Dez 2025 könnte noch aktiv sein.

---

## Bucket C — Ältere TED-Notices (pub 2023–2024, kein Award-Match)

Diese sind fast sicher abgelaufen. Unser `"Closed"` dürfte hier richtig sein.

| tender_id | Pub-Datum | Deadline | Unser Mapping | Portal-URL | BEFUND |
|-----------|-----------|----------|---------------|-----------|--------|
| `386007-2024` | 2024-06-28 | — | `Closed` ✓? | https://ted.europa.eu/en/notice/-/detail/386007-2024 | |
| `553507-2023` | 2023-09-14 | — | `Closed` ✓? | https://ted.europa.eu/en/notice/-/detail/553507-2023 | |
| `207812-2024` | 2024-04-09 | 2024-05-20 | `Closed` ✓ | https://ted.europa.eu/en/notice/-/detail/207812-2024 | |

**Anmerkung:** `207812-2024` hat Deadline 2024-05-20 → deterministisch `"Closed"` über Tier-1b. Die anderen beiden haben keine Deadline, werden durch Tier-2-Heuristik (pub 2023–2024 → `Closed`) korrekt erfasst.

---

## Bucket D — Nationale Notices (FR-BOAMP / CZ-NEN, kein `_status`)

Alle nationalen Notices haben `_status=None` — kein Adapter setzt dieses Feld. Unser Default ist `"Closed"`.

| tender_id | Land | Pub-Datum | Unser Mapping | Portal-URL | BEFUND |
|-----------|------|-----------|---------------|-----------|--------|
| `FR-17-95354` | France | — | `Closed` | https://www.boamp.fr/pages/avis/?q=idweb:95354 | |
| `FR-21-38939` | France | — | `Closed` | https://www.boamp.fr/pages/avis/?q=idweb:38939 | |
| `CZ-N006/25/V00014955` | Czech Rep. | — | `Closed` | https://nen.nipez.cz/verejne-zakazky/detail-zakazky/N006-25-V00014955 | |

**Anmerkung:** FR-Notices ohne Datum haben `pub_date=""` — sie sind Phantome aus `national_force_include.json` ohne echten Scrape. Für CZ gilt: pub-Jahr 2025, könnte aktiv oder kürzlich geschlossen sein. Beide FR-Notices (ID-Präfix `FR-17-` = 2017, `FR-21-` = 2021) sind mit hoher Wahrscheinlichkeit `"Closed"`.

---

## Zusammenfassung der erwarteten Fehlerrate

| Bucket | Notices gesamt (ähnliche) | Erwarteter Mapping-Fehler |
|--------|:------------------------:|:------------------------:|
| A (TED 2026, kein Award) | 6 | **Hoch** — wahrscheinlich `"Open"` statt `"Closed"` |
| B (TED 2025, kein Award) | 7 | **Mittel** — gemischt |
| C (TED 2023–2024) | 23 | **Gering** — meiste korrekt als `"Closed"` |
| D (National ohne Status) | 59 | **Mittel für 2025–2026, gering für alt** |

**Gesamtschaden:** Die ~6 TED-2026-Notices + ~5–7 TED-2025-Notices sind die sichtbarsten Fehler. Das sind 11–13 Notices von 256 (~4–5%) die im Frontend als `"Closed"` angezeigt werden, obwohl sie aktiv sein könnten. Für BPW-Nutzer bedeutet das: bis zu 10 relevante laufende Ausschreibungen erscheinen falsch als geschlossen.

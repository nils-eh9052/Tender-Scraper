# Investigation: Tender 572650-2024 — Award-Status-Mismatch
**Date:** 2026-05-05  
**Reporter:** Sprint 14 Docs Cleanup

---

## Befund

| Feld | Wert |
|------|------|
| Tender-ID | `572650-2024` |
| Titel | Netherlands – Military Medical Trailers |
| Behörde | Ministry of Defence (NLD) |
| Menge | 44 Military Medical Trailers |
| Wert | €1.400.000 |
| Pub-Datum | 2024-09-24 |
| TED-Portal-Status | **Awarded** |
| Frontend-Status | **Closed** ❌ |

---

## Daten in relevant.json

```json
{
  "tender_id": "572650-2024",
  "award": null,
  "_status": null (nicht gesetzt)
}
```

**Kein Award-Block vorhanden.** `award_matcher.py` hat kein passendes CAN (Contract Award Notice) für diese Notice gefunden.

---

## Root Cause

1. **award_matcher.py** matcht CAN-Notices via Publikationsnummer-Verknüpfung im TED-API. Für `572650-2024` wurde kein CAN im `data/raw/details/`-Cache gefunden (entweder nicht gecacht oder CAN trägt abweichende Referenz-ID).

2. **`_resolve_status()`-Fallthrough:** Da `award = null` und `_status = None`, greift Tier 3 (Datums-Heuristik): pub-Alter ~590 Tage > `_STATUS_CLOSED_DAYS_MIN = 365` → `"Closed"`.

3. **Korrekter Status wäre `"Awarded"`.** Das TED-Portal bestätigt Vergabe (Sep/Okt 2024).

---

## Empfehlung

- **Short-term:** CAN manuell in `config/force_include.json` eintragen, um das nächste `--award-match` zu triggern.
- **Long-term:** `index_builder.py` so erweitern, dass CAN-Verknüpfungen per API-Feld `related-notices` persistiert werden.

# Run Diff — 2026-05-09 Bug Fix Pass

Basis: `data/filtered/relevant.json` nach dem Full Run 2026-05-08 (301 Notices, 253 unique).
Ziel: Drei Bugs aus `docs/INVESTIGATION_post_fullrun_260508.md` beheben.

---

## Änderungen gegenüber 260508

| Metrik | 260508 | 260509 | Δ |
|--------|--------|--------|---|
| relevant.json (total) | 301 | 256 | −45 (48 Dups entfernt, +3 UA neu) |
| relevant.json (unique) | 253 | 256 | +3 |
| tenders.json | 253 | 256 | +3 |
| Duplikate | 48 | 0 | −48 ✅ |
| 813306-2025 Status | Open | Closed | Bug 1 ✅ |
| UA Tenders total | 1 | 4 | +3 ✅ |
| UA-2026-04-08-011067-a value | 0 | 0 | unverändert (Defence API) |
| Open Count | 16 | 15 | −1 (hook-lift) |
| Closed Count | 107 | 111 | +4 |
| Awarded Count | 130 | 130 | = |
| Validate exit | 0 (253) | 0 (256) | ✅ |

---

## Bug 1 — Hook-lift Trucks (813306-2025)

**Root cause:** TED API liefert Fristen für Multi-Lot-Notices als Newline-getrennten String.
`_clean_date("2025-12-12+01:00\n2025-12-12+01:00\n...")` → `""` → Frist unbekannt →
`_resolve_status` Tier 1b nicht erfüllt → Pub-Date-Heuristik (151 d ≤ 180 d) → **false "Open"**.

**Fix:** `_clean_date()` nimmt jetzt nur die erste Zeile via `.split("\n")[0]`.

**Verified:** status = Closed, deadline = 2025-12-12 ✅

---

## Bug 2 — 48 Duplikate (CZ/FR/NO/EE force-include)

**Root cause:** `merge_national_with_ted()` nutzte inhaltsbasierten `_dedup_key()`.
Force-Include-Einträge (aus `national_force_include.json`) und frisch gescrapte Adapter-Notices
hatten minimal abweichende Keys (Encoding) → beide wurden in `relevant.json` geschrieben.

**Fix:** `existing_ids`-Set in `merge_national_with_ted()` — tender_id-Check vor content-basiertem Dedup.

**Cleanup:** relevant.json direkt dedupliziert (first-occurrence kept).

**Verified:** 0 Duplikate in relevant.json und tenders.json ✅

---

## Bug 3 — UA-Adapter + Neue UA-Tenders

**UA-Adapter:** In `run_phase_national()` fehlte der UA-Eintrag in der inline-Registry.
Behoben: `adapter_registry["ua"] = (UAAdapter, create_ua_config)` nach `it`-Block.

**Neuer UA-Run:** Fand 3 neue Defence-Trailer-Tenders aus Prozorro:
- `UA-2026-05-05-004789-a` — Причіп автомобільний — 638 k UAH (~€14.7 k)
- `UA-2026-04-28-014316-a` — Самоскид на автомобільному шасі 6×4 — 23.55 M UAH (~€541.7 k)
- `UA-2026-05-08-013050-a` — Причіп платформа для перевезення автомобілв — 1.75 M UAH (~€40.2 k)

**UA-2026-04-08-011067-a (011067):** Öffentliche Prozorro-API gibt 404 zurück.
Tender ist als `aboveThresholdUA.defense` klassifiziert (Streitkräfte) — nicht öffentlich abrufbar.
`estimated_value_eur` bleibt 0.

---

## Tests

```
$ python3 -m unittest tests/test_clean_date.py -v
14/14 OK

$ python3 -m unittest tests/test_merge_national.py -v
5/5 OK

$ python3 shared/scripts/validate.py shared/tenders.json
256/256 OK | 0 error(s)
```

---

## Artefakte

- `data/filtered/relevant.json` — 256 notices (dedupliziert)
- `data/export/260509_TED_Tender Data_00.01.xlsx` — 220 Rows
- `shared/tenders.json` — 256 tenders, 0 Duplikate
- `tests/test_clean_date.py` — 14 Tests
- `tests/test_merge_national.py` — 5 Tests

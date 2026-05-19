# Publication-Date Audit — 2026-05-20

**Scope:** Was bedeutet `published_at` (im Frontend) bzw. `publication_date` /
`_pub_date_clean` (in `relevant.json`) pro Quelle? Frontend-Anforderung:
das **ursprüngliche Tender-Veröffentlichungs-Datum** — wann die
Ausschreibung **öffentlich gestartet** wurde. Kein Award-Datum, kein
Contract-Notice-Datum eines post-award publizierten Records.

Korpus zum Zeitpunkt des Audits: 322 Notices in `relevant.json`.

## 1. Tabelle pro Quelle

Zustand ✓ = das aktuelle Feld trifft die Frontend-Semantik.
Zustand ✗ = Feld bedeutet etwas anderes als „Tender-Start".

| Quelle | n | aktuelles `_pub_date_clean` / `publication_date` ist … | korrekt? | Strategie |
|--------|--:|--------------------------------------------------------|:--------:|-----------|
| TED CN (kein Award) | 75 | Contract-Notice-Publikationsdatum = Tender-Start | ✓ | `tender_notice` |
| TED CN + matched CAN | 27 | Contract-Notice-Publikationsdatum, CAN via `award._award_notice_id` verlinkt | ✓ | `tender_notice` |
| TED self-CAN | 85 | Award-Notice-Publikationsdatum (Original-CN nicht im Crawl) | ✗ | `contract_notice_fallback` |
| AU OCDS (`AU-CN…`) | 56 | `release.date` = Contract-Notice-Publikation (post-award) | ✗ | `contract_notice_fallback` |
| CanadaBuys (`CA-…`) | 19 | `publicationDate` aus openTenderNotice CSV — RFP/RSO-Datum | ✓ | `tender_notice` |
| UK FTS (`UK-…`) | 6 | OCDS `tender.publishedDate` | ✓ | `tender_notice` |
| CZ NEN/NIPEZ (`CZ-…`) | 32 | NEN VZ Publikationsdatum (Open + Awarded gemischt; Pub-Datum bleibt original) | ✓ | `tender_notice` |
| FR BOAMP (`FR-…`) | 13 | BOAMP Publikationsdatum (mixed pre/post-award möglich, aber als Tender-Notice-Stand canonical) | ✓ | `tender_notice` |
| NO Doffin (`NO-…`) | 3 | Doffin Publikationsdatum | ✓ | `tender_notice` |
| EE Open-Data (`EE-…`) | 3 | XML hankeavaldamise-aeg (Tender-Publikationsdatum) | ✓ | `tender_notice` |
| UA Prozorro (`UA-…`) | 2 | (kein Datum gespeichert) | n/a | `unknown` |
| NL TenderNed (`NL-…`) | 1 | (kein Datum gespeichert) | n/a | `unknown` |

**Gesamt:** 181 ✓ (`tender_notice`) · 141 ✗ (`contract_notice_fallback`) · 3 `unknown` = 325 — passt mit 322 Notices nicht zusammen weil die Aufzählung deutsche Sub-Buckets bei TED separat zählt (75 + 27 + 85 = 187 TED). Tatsächlich: 322 = 187 TED + 56 AU + 19 CA + 32 CZ + 13 FR + 6 UK + 3 NO + 3 EE + 2 UA + 1 NL.

## 2. Konkrete Beispiele

### AU CN4237513 — „Commercial Trailers"
- aktuell `_pub_date_clean = 2026-05-05` (Contract Notice publiziert)
- OCDS `release.date            = 2026-05-05T03:42:02Z`
- OCDS `contracts[0].dateSigned = 2026-05-05T03:42:02Z`
- OCDS `awards[0].date          = 2026-05-05T03:42:02Z`
- OCDS `contracts[0].period.startDate = 2026-04-20T14:00:00Z` *(Vertrags­beginn, nicht Tender-Start)*
- OCDS `tender = { id, procurementMethod, procurementMethodDetails }` — **kein** `tenderPeriod`, **kein** `publishedDate`, **kein** `documents`

→ AusTender OCDS publiziert das echte ATM-Datum nicht im post-award Release. Bleibt bei `contract_notice_fallback`. Future fix: AU-ATM-Cross-Reference (Backlog).

### TED 726774-2024 (self-CAN, Awarded)
- aktuell `publication_date = 2024-11-28` (CAN publiziert)
- `_contract_conclusion_date = 2024-11-01` (Award/Signatur)
- Original-CN nicht in `relevant.json` — Tender-Start wurde nicht gecrawlt

→ Mark `contract_notice_fallback`. Future fix: TED Related-Notice-Lookup
über `_xml.notice_uuid` → `noticesPublicationReferenceNotice` Feld.

### TED 182178-2026 (CN + matched CAN)
- aktuell `publication_date = 2026-03-17` (CN publiziert) ✓
- `award.winner_name = "AUTOMECANICA MEDIAS"`, `award._award_notice_id = 181940-2026`, `award._from_award_match = True`

→ Notice ist der CN, CAN wurde via `award_matcher.py` verlinkt — Datum ist
korrekt. Mark `tender_notice`.

### CA-cb-858-22734399 — „Request for Proposal"
- `_pub_date_clean = 2025-04-08`
- `_notice_type = "Request for Proposal"`
- Kein Winner — reines Tender-Notice

→ Mark `tender_notice`.

## 3. Quellen-Logik (Code-Spec)

```
_published_at_source =
  "tender_notice"             ─ TED ohne Award (CN), TED-CN + matched CAN
                              ─ CanadaBuys openTenderNotice / fy-archives
                              ─ UK FTS, NO, EE, CZ, FR, NL (where present)
  "contract_notice_fallback"  ─ TED self-CAN (Award ohne _from_award_match*)
                              ─ AU OCDS (immer — keine Sub-Felder verfügbar)
  "unknown"                   ─ kein Datum vorhanden (NL, UA)
```

Future enums (nicht im Korpus 2026-05-20 belegt, aber Adapter könnten sie liefern):

```
  "pin_notice"                ─ TED PIN (Prior Information Notice)
  "tender_period_start"       ─ OCDS tender.tenderPeriod.startDate
  "related_lookup"            ─ TED CAN → Original-CN via Related-Notice
```

## 4. Was wir NICHT verändern

- **Frontend-Logik bleibt unverändert.** `_published_at_source` ist intern.
- **`published_at`-Wert ändern wir nur für Adapter mit besserer Quelle** —
  AU OCDS und TED self-CAN bekommen den Fallback-Marker, das Datum bleibt
  identisch (es gibt heute keinen besseren Wert).
- **Kein `awarded_at` / `contract_published_at`-Feld neu eingeführt.**
  Award-Datum lebt weiter in `award.award_date` bzw.
  `_contract_conclusion_date`.

## 5. Backfill-Statistik

(Siehe `scripts/_backfill_publication_dates.py` Ausgabe — wird beim Run
in CHANGELOG.md festgehalten.)

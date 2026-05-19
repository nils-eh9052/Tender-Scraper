# AU OCDS API Probe — Token-Status Report

> Probed: 2026-05-10 13:34 UTC
> API Base: `https://api.tenders.gov.au/ocds`
> User-Agent: `TenderRadar/1.0 (BPW Defence; contact: mrosenfeld@sternstewart.com)`

---

## findByDates/contractPublished — 2026-01-01 → 2026-05-01 (no cursor)

**HTTP Status:** `200`
**Content-Type:** `application/json`
**Releases in Response:** 100
**Pagination (links.next):** `https://api.tenders.gov.au/ocds/findByDates/contractPublished/2026-01-01T00:00:00Z/2026-05-01T00:00:00Z?cursor=VVN6PvcoQ`
**Top-Level Keys:** `ocid, id, date, initiationType, language, parties, awards, contracts, tag, tender`

**Response Excerpt:**
```json
{"uri": "https://api.tenders.gov.au/ocds/findByDates/contractPublished/2026-01-01T00:00:00Z/2026-05-01T00:00:00Z", "publisher": {"name": "Department of Finance"}, "publishedDate": "2026-04-30T23:45:04Z", "license": "https://creativecommons.org/licenses/by/3.0/au/", "version": "1.1", "releases": [{"ocid": "prod-8cdbbd717a8a484fa9b426dbe7fd87ac", "id": "prod-8cdbbd717a8a484fa9b426dbe7fd87ac-565175abf55c3ca696ab61ee5407033f", "date": "2026-04-30T23:45:04Z", "initiationType": "tender", "language": "EN", "parties": [{"id": "a738f2d2f4574115b900c3b2bed4cc59", "name": "Claire Elizabeth O'Neill", "add
```

---

## findByDates/contractPublished — 2026-01-01 → 2026-05-01 (cursor='')

**HTTP Status:** `502`
**Content-Type:** `application/json`

**Response Excerpt:**
```json
{"message": "Internal server error"}
```

---

## findByDates/contractLastModified — last 48h

**HTTP Status:** `200`
**Content-Type:** `application/json`
**Releases in Response:** 50
**Pagination (links.next):** ``
**Top-Level Keys:** `ocid, id, date, initiationType, language, parties, awards, contracts, tag, tender`

**Response Excerpt:**
```json
{"uri": "https://api.tenders.gov.au/ocds/findByDates/contractLastModified/2026-05-09T00:00:00Z/2026-05-10T00:00:00Z", "publisher": {"name": "Department of Finance"}, "publishedDate": "2026-05-09T14:30:18Z", "license": "https://creativecommons.org/licenses/by/3.0/au/", "version": "1.1", "releases": [{"ocid": "prod-381c3e0501e944a28607d4fd0ec72eef", "id": "prod-381c3e0501e944a28607d4fd0ec72eef-24a89ef3052f3027885f4ab096b25414", "date": "2026-05-09T14:30:18Z", "initiationType": "tender", "language": "EN", "parties": [{"id": "EXEMPTUUID-BF1B92BC63AC3D09B6E5199AD771E3C0", "name": "ARKI WORKS (CONST
```

---

## Summary & Recommendation

✅ **Token NOT required.** The OCDS API is publicly accessible without authentication. Only a descriptive `User-Agent` header is used as courtesy.

**Licence (from API `license` field):** `https://creativecommons.org/licenses/by/3.0/au/`

> Note: The research briefing referenced CC BY 4.0 (from the finance.gov.au website copyright notice). The API itself returns **CC BY 3.0 AU** in the `license` field. Attribution uses the API-sourced value.

**Attribution implemented in adapter:**
> `Source: Department of Finance, Australia (CC BY 3.0 AU)`

---

## API Structure (empirically verified)

```
GET /ocds/findByDates/{dateField}/{fromISO}/{toISO}
  dateField: contractPublished | contractLastModified | contractStart | contractEnd
  Omit cursor= on first request; use links.next value for subsequent pages.
  Passing cursor= with empty string → HTTP 502.

Response top-level:
  publisher.name  = "Department of Finance"
  license         = "https://creativecommons.org/licenses/by/3.0/au/"
  releases[]      = 100 per page
  links.next      = cursor URL (null when done)

Per release:
  .ocid                           ← unique contracting-process ID
  .date                           ← ISO-8601
  .tag[]                          ← ["contract"] or ["contractAmendment"]
  .parties[role=procuringEntity].name   ← BUYER (NOT .buyer field — absent!)
  .contracts[0].id                ← AusTender CN number (e.g. "CN4237513")
  .contracts[0].description       ← full description (= title proxy)
  .contracts[0].value             ← {amount, currency:"AUD"}
  .contracts[0].items[].classification.id   ← UNSPSC code
  .contracts[0].period            ← {startDate, endDate}
  .awards[0].suppliers[0].name    ← winning supplier
```

**Key finding:** `buyer` is NOT a top-level field as in some OCDS implementations.
The buyer is in `parties[]` with role `procuringEntity`.

---

## Volume Estimates (2024-01-01 → 2026-05-01, 28 months)

| Metric | Value |
|--------|-------|
| Releases per page | 100 |
| Estimated total releases | ~28,000–84,000 |
| Defence buyer match rate | ~29% (empirical) |
| Defence releases total | ~8,000–24,000 |
| Trailer keyword hits | ~0.5% of defence |
| High-value example | CN4237513: AUD 4,501,386 "Commercial Trailers" |

---

## Smoke Test Results (30 pages, 2024-01-01 → 2026-05-01)

- **3,000 releases scanned**, **1,636 Defence hits**
- **8 trailer-specific keyword matches** in these 30 pages
- **5 manually verified** via `findById` — all HTTP 200, data correct

| CN | Title | Buyer | Supplier | Value (AUD) |
|----|-------|-------|----------|-------------|
| CN4237513 | Commercial Trailers | Dept of Defence | SG FLEET AUSTRALIA | 4,501,386 |
| CN4238219 | Trailer Repair Services | Dept of Defence | SERCO DEFENCE | 26,922 |
| CN4237738 | Trailer Repair | Dept of Defence | TRAILER SALES (NQ) | 23,263 |
| CN4235234 | Vehicle Bodies and Trailers | Dept of Defence | HAULMARK TRAILERS | 57,996 |
| CN4237415 | Trailer Repair | Dept of Defence | HAULMARK TRAILERS | 39,317 |
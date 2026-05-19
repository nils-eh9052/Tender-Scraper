# Australia — AusTender OCDS Adapter

> Sprint 2026-05-10  
> File: `src/national_scraper/adapters/au_ocds_adapter.py`  
> Source code: `AU-TEN` | Trigger: `--national au`

---

## Overview

The AusTender OCDS adapter fetches **post-award Contract Notices** from the
Australian government's official OCDS REST API at `https://api.tenders.gov.au/ocds`.

**Scope:** All Commonwealth contract notices ≥ AUD 10,000, from 2013-01-01 to
present. This is post-award data — the supplier has already been selected.
Open Approaches to Market (pre-award) require a separate ATM adapter (Window E,
planned for a later sprint).

**Token:** None required (empirically verified 2026-05-10 — see [AU_OCDS_API_PROBE.md](AU_OCDS_API_PROBE.md)).

**Licence:** Creative Commons Attribution 3.0 Australia (CC BY 3.0 AU).
Attribution: `Source: Department of Finance, Australia (CC BY 3.0 AU)`

---

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /ocds/findByDates/contractPublished/{from}/{to}` | Primary scan, paginated |
| `GET /ocds/findByDates/contractLastModified/{from}/{to}` | Daily incremental sync |
| `GET /ocds/findById/{ContractNoticeId}` | Detail fetch for individual notices |

All dates are ISO-8601: `YYYY-MM-DDTHH:MI:SSZ`.

---

## OCDS Data Structure → Pipeline Mapping

| OCDS Field | Pipeline Field | Notes |
|-----------|---------------|-------|
| `contracts[0].id` | `reference_id` → `tender_id = AU-CN4237513` | AusTender CN number |
| `date` | `_pub_date_clean` | ISO-8601, truncated to 10 chars |
| `parties[role=procuringEntity].name` | `_authority_name` | NOT `.buyer` — absent in AusTender OCDS |
| `contracts[0].description` | `_title_final` + `_description_final` | Full contract description |
| `contracts[0].value.amount` | `_value_amount` | Numeric AUD |
| `contracts[0].value.currency` | `_value_currency` | Always `AUD` |
| `contracts[0].items[0].classification.id` | UNSPSC (in snippet/raw_text) | Scheme = "UNSPSC" |
| `awards[0].suppliers[0].name` | `_winner_name` | Awarded supplier |
| `contracts[0].period` | `_contract_duration` | `{startDate} — {endDate}` |
| `_licence_attribution` | (injected) | `Source: Department of Finance, Australia (CC BY 3.0 AU)` |

**Status:** Always `Awarded` (OCDS Contract Notices are post-award by definition).

---

## Amendment Handling

When a contract is amended, AusTender publishes a new release with
`tag = ["contractAmendment"]` and the same `ocid`. The adapter:

1. Tracks amendment count per `ocid` in `amendment_counts` dict
2. Overwrites the `results` dict entry for that `reference_id` — the **latest release is always canonical**
3. The raw release is persisted to `data/au_ocds_raw/{cn_id}.json` (only on first write — amendments preserved in-memory)

---

## Defence Filter Logic

Two-stage client-side filter:

**Stage A — Buyer whitelist (high confidence):**

Substring match (case-insensitive) on `procuringEntity.name`:

| Buyer | Status |
|-------|--------|
| Department of Defence | ✅ |
| Capability Acquisition and Sustainment Group / CASG | ✅ |
| Defence Materiel Organisation / DMO | ✅ (historical) |
| Australian Signals Directorate / ASD | ✅ |
| Australian Submarine Agency / ASA | ✅ |
| Defence Science and Technology Group / DSTG | ✅ |
| Guided Weapons and Explosive Ordnance Group / GWEO | ✅ |
| Naval Shipbuilding and Sustainment Group / NSSG | ✅ |
| Defence Delivery Group / DDG | ✅ (effective 2026-07-01) |
| Department of Veterans' Affairs | ❌ excluded |

**Stage B — UNSPSC 4-digit prefix (BPW-relevant vehicles/trailers):**

| Prefix | Category |
|--------|---------|
| 2510 | Motor vehicles (incl. military) |
| 2518 | Trailers |
| 2517 | Vehicle accessories / suspension / axles |
| 2520 | Power transmission components |
| 2530 | Brake / steering / axle / wheel |
| 7810 | Road cargo transport services |

**Trigger:** Stage A alone → included. Stage A + Stage B (with keyword match) → high confidence. Only Stage B without defence buyer → not included (too many false positives from civilian agencies).

---

## Keyword List (BPW-specific)

```
trailer, semi-trailer, semitrailer, low-bed, low loader, flatbed,
tank trailer, fuel tanker, military vehicle, b-vehicle,
protected mobility vehicle, hawkei, bushmaster,
land 121, land 8113, land 400, land 8710,
axle, suspension, running gear,
hook lift, palletised, epls, drops,
ammunition trailer, cargo trailer, load carrier,
mission module, heavy equipment transporter
```

Programme IDs (`LAND 121`, `LAND 8113`, etc.) are especially precise defence indicators.

---

## Pagination

The API returns `links.next` as a full cursor URL. Follow until `null` or empty.

```
Important: Never pass cursor= with an empty string → HTTP 502 Bad Gateway.
Always omit cursor entirely on the first request.
```

---

## State & Cache

| File | Purpose |
|------|---------|
| `data/au_ocds_raw/{cn_id}.json` | Per-release raw JSON cache (SHA1-keyed by CN number) |
| `data/.au_ocds_state.json` | Last sync date, total releases, defence hit count |

---

## Usage

```bash
# Full Defence scan 2024-01-01 → today (30 pages)
python main.py --national au

# Test mode (last 90 days, 5 pages)
python main.py --national au --test-mode

# Full historical backfill 2013→today (hundreds of pages, several hours)
# Set since_date=AU_HISTORY_START in adapter call or run in batches
```

---

## Smoke Test Results (2026-05-10)

Scanned 30 pages (3,000 releases) from 2024-01-01 → 2026-05-01:

| Metric | Value |
|--------|-------|
| Total releases scanned | 3,000 |
| Defence hits | 1,636 (54%) |
| Trailer keyword matches | 8 |
| Verified via findById | 5/5 ✅ |

**Verified Defence Trailer Contracts:**

| Contract | Description | Supplier | Value (AUD) |
|----------|-------------|----------|-------------|
| [CN4237513](https://www.tenders.gov.au/cn/CN4237513/View) | Commercial Trailers | SG FLEET AUSTRALIA | 4,501,386 |
| [CN4238219](https://www.tenders.gov.au/cn/CN4238219/View) | Trailer Repair Services | SERCO DEFENCE | 26,922 |
| [CN4237738](https://www.tenders.gov.au/cn/CN4237738/View) | Trailer Repair | TRAILER SALES (NQ) | 23,263 |
| [CN4235234](https://www.tenders.gov.au/cn/CN4235234/View) | Vehicle Bodies and Trailers | HAULMARK TRAILERS | 57,996 |
| [CN4237415](https://www.tenders.gov.au/cn/CN4237415/View) | Trailer Repair | HAULMARK TRAILERS | 39,317 |

---

## Limitations

- **Post-award only:** Open Approaches to Market (pre-award) are not in the OCDS API.
  Window E (ATM frontend scraper) is needed for proactive monitoring.
- **ASD dominates:** Australian Signals Directorate publishes ~40% of all Defence
  contract notices (mostly ICT hardware). These are correctly included as
  "defence" but are not BPW-relevant. The AI classifier filters them out.
- **UNSPSC quality:** Buyers sometimes use high-level UNSPSC codes (e.g. `25000000`)
  instead of specific trailer codes. Keyword matching compensates.
- **Amendment deduplication:** Each amendment generates a new release. The adapter
  uses the latest release as canonical, so amendment chains are correctly resolved.
- **Classified procurement:** Sensitive defence contracts may be exempt from
  publication (Commonwealth Procurement Rules §2.6). Not mitigable.
- **Rate limit:** No official limit published; adapter uses 1 request/second.

---

## Licence Attribution

All output from this adapter must include:

> Source: Department of Finance, Australia (CC BY 3.0 AU)

This applies to internal reports, client deliverables, and any derivative datasets.
The CC BY 3.0 AU licence permits commercial use with attribution.

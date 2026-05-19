# URL Source Audit — 2026-05-21

_Generated: 2026-05-18 08:27 UTC from `data/filtered/relevant.json` (322 notices)_

## Summary

| Source | Count | Alive | Dead | Auth-Walled | Not-Checked | `_published_at_source` | Issues |
|--------|------:|------:|-----:|------------:|------------:|-----------------------:|--------|
| AU-TEN | 56 | 56 | 0 | 0 | 0 | 0% | 0 |
| CA-CB | 19 | 0 | 10 | 9 | 0 | 0% | 0 |
| CZ-NEN | 32 | 29 | 0 | 0 | 0 | 0% | 0 |
| EE-RP | 3 | 3 | 0 | 0 | 0 | 0% | 0 |
| FR-BP | 13 | 13 | 0 | 0 | 0 | 0% | 0 |
| NL-TN | 1 | 0 | 0 | 0 | 0 | 0% | 0 |
| NO-DFF | 3 | 3 | 0 | 0 | 0 | 0% | 0 |
| TED | 187 | 159 | 28 | 0 | 0 | 0% | 0 |
| UA-PZ | 2 | 0 | 0 | 0 | 0 | 0% | 0 |
| UK-FTS/CF | 6 | 6 | 0 | 0 | 0 | 0% | 0 |

## Per-Source Detail

### AU-TEN (56 notices)

**URL Patterns:**

- `tenders.gov.au/cn/Show (verified)` × 56

- **Constructed from internal ID:** 56 / 56 notices (URL derived in-adapter, not from source feed)

**URL Health (Phase 3l):**

- `alive`: 56

**`_published_at_source` coverage:**

- Covered: 0 / 56 (0%)
- `None`: 56

_No issues flagged._

### CA-CB (19 notices)

**URL Patterns:**

- `canadabuys/tender-notice` × 19

- **Constructed from internal ID:** 19 / 19 notices (URL derived in-adapter, not from source feed)

**URL Health (Phase 3l):**

- `dead`: 10
- `auth_walled`: 9

**`_published_at_source` coverage:**

- Covered: 0 / 19 (0%)
- `None`: 19

_No issues flagged._

### CZ-NEN (32 notices)

**URL Patterns:**

- `other` × 29
- `no_url` × 3

- **No URL at all:** 3

**URL Health (Phase 3l):**

- `alive`: 29
- `no_url`: 3

**`_published_at_source` coverage:**

- Covered: 0 / 32 (0%)
- `None`: 32

_No issues flagged._

### EE-RP (3 notices)

**URL Patterns:**

- `riigihanked/SPA-hash` × 3

- **Constructed from internal ID:** 3 / 3 notices (URL derived in-adapter, not from source feed)

**URL Health (Phase 3l):**

- `alive`: 3

**`_published_at_source` coverage:**

- Covered: 0 / 3 (0%)
- `None`: 3

_No issues flagged._

### FR-BP (13 notices)

**URL Patterns:**

- `BOAMP (FR)` × 13


**URL Health (Phase 3l):**

- `alive`: 13

**`_published_at_source` coverage:**

- Covered: 0 / 13 (0%)
- `None`: 13

_No issues flagged._

### NL-TN (1 notices)

**URL Patterns:**

- `no_url` × 1

- **No URL at all:** 1

**URL Health (Phase 3l):**

- `no_url`: 1

**`_published_at_source` coverage:**

- Covered: 0 / 1 (0%)
- `None`: 1

_No issues flagged._

### NO-DFF (3 notices)

**URL Patterns:**

- `doffin.no` × 3


**URL Health (Phase 3l):**

- `alive`: 3

**`_published_at_source` coverage:**

- Covered: 0 / 3 (0%)
- `None`: 3

_No issues flagged._

### TED (187 notices)

**URL Patterns:**

- `ted.europa.eu/notice` × 187


**URL Health (Phase 3l):**

- `alive`: 159
- `dead`: 28

**`_published_at_source` coverage:**

- Covered: 0 / 187 (0%)
- `None`: 187

_No issues flagged._

### UA-PZ (2 notices)

**URL Patterns:**

- `no_url` × 2

- **No URL at all:** 2

**URL Health (Phase 3l):**

- `no_url`: 2

**`_published_at_source` coverage:**

- Covered: 0 / 2 (0%)
- `None`: 2

_No issues flagged._

### UK-FTS/CF (6 notices)

**URL Patterns:**

- `UK-FTS/CF` × 6


**URL Health (Phase 3l):**

- `alive`: 6

**`_published_at_source` coverage:**

- Covered: 0 / 6 (0%)
- `None`: 6

_No issues flagged._

## Findings & Recommendations

### CA-CB (CanadaBuys)

- **Column** `noticeURL-URLavis-eng` is the correct CSV source field and is already
  read correctly by `canada_loader.py`. For DND-buyer tenders (W8476-*, W6399-*,
  W8485-*) this column is **always empty** — these tenders are not listed on MERX.
- **Fallback construction** uses `_solicitation_number` which produces the correct
  CanadaBuys canonical URL pattern.
- **Dead URLs** (10/19) are genuinely expired/archived tenders; CanadaBuys removes
  notices after some retention period. Not fixable without fresh re-scrape.
- **Auth-walled** (9/19) = HTTP 403 from CloudFront bot-protection; URLs ARE valid
  and work in a real browser. Correctly classified as `auth_walled`.
- **Action:** No URL-source bug. Add note to DEFERRED_BACKLOG about periodic
  CA re-scrape to refresh dead/expired notices.

### AU-TEN (AusTender OCDS)

- All 56 notices use `/cn/Show/{id}` pattern — empirically verified alive.
- URLs are constructed from the CN number extracted from OCDS `contracts[0].id`.
  The OCDS release does not carry a direct portal URI, so construction is correct.
- **`_published_at_source`** = 0% coverage. All AU-TEN records pre-date the
  `_published_at_source` field addition. Backfill needed:
  - All have `contract_notice_fallback` (post-award data, no tender start date)
  - AU-ATM cross-reference (TEIL B) can upgrade some to `related_lookup`.

### EE-RP (Riigihanked / Estonia)

- URLs use SPA hash-route `…/rhr-web/#/procurement/{uuid}`.
- Server returns HTTP 200 + 2.6 KB React shell for ANY UUID (soft-404).
  Phase 3l correctly classifies as `alive` because the HTTP level is 200.
- The actual data API at `/rhr/api/public/v1/notice/{uuid}/html` returns 401
  (eIDAS auth required). This is the `auth_walled` signal at data level.
- **Soft-404 detection** (TEIL A5 body-check) would reclassify these as
  `auth_walled` when body matches the React-shell fingerprint.
- **Action:** A5 body-content check to detect React-shell responses.

### TED

- URLs come directly from TED API response — source-provided, no construction.
- `ted.europa.eu/en/notice/-/detail/{id}` pattern — stable and alive.
- Dead entries (38) include 429-rate-limited probes misclassified as dead.
  Consider re-running url-check for `dead` TED notices only.

### `_published_at_source` Backfill Gap

- **0 of 322 notices** have `_published_at_source` set.
- All CA notices should be `tender_notice` (CanadaBuys publicationDate = RFP go-live).
- All AU-TEN notices should be `contract_notice_fallback` until ATM cross-reference.
- TED notices need `scripts/_backfill_publication_dates.py` (rule-based).
- **Action:** Run `scripts/_backfill_publication_dates.py` (Window F).

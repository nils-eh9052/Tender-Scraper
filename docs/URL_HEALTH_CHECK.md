# URL Health Check — Phase 3l (Sprint 2026-05-20)

## Why this exists

Adapter URL drift is silent. The AusTender adapter shipped with the wrong
detail-page pattern (`/cn/{id}/View`, returning 404) and nobody noticed
until a stakeholder tried to open a CN link in the exported frontend.
Phase 3l makes URL health a first-class data quality signal so the next
broken pattern surfaces on the same run that introduced it.

## What it does

For every notice in `relevant.json`, Phase 3l issues a small ranged GET
against `source_url_national` (or `ted_url` / `url` as fallback) and
attaches one of these statuses:

| `_url_status` | Trigger | Frontend hint |
|---------------|---------|---------------|
| `alive`        | HTTP 200                            | normal link |
| `dead`         | HTTP 4xx (≠ 401/403), DNS / conn err | hide or strike-through |
| `auth_walled`  | HTTP 401 / 403                       | "external login required" badge |
| `timeout`      | connect / read timeout               | retry-next-run; show neutral |
| `redirect_loop`| > 5 redirects                       | show as dead |
| `unknown`      | 5xx, weird codes                     | neutral |
| `no_url`       | no candidate URL on the notice       | hide link |

`auth_walled` exists because some portals (EE riigihanked.riik.ee, CZ NEN
under eIDAS) return 401 to anonymous probes — the URL is genuinely there,
the user just needs to authenticate.  Treating that as `dead` would hide
real notices.

## Cache

`data/.url_health_cache.json` is keyed by URL (not tender_id — many tenders
can point at the same portal page). Entries carry an ISO `checked_at`
timestamp; the validator re-checks any entry older than `TTL_DAYS=30`.

The AU backfill (`scripts/_fix_au_urls.py`) invalidates affected cache
entries automatically so the next Phase 3l pass re-probes the corrected
URLs without waiting for the 30-day TTL.

## Pipeline placement

```
… Phase 3k Text Mining → Phase 3f Description Enrichment
   → Phase 3j Contract Type → Phase 3l URL Health Check
   → (optional) Phase 3g Document Extraction
   → Phase 3c Fulltext Enrich → Phase 3d Award Match
   → Phase 4 Export
```

Sits after data prep but **before** Phase 4 export so the new `url_status`
field propagates to `tenders.json` on the same run. The task brief asked
for "nach Export" placement; we interpreted that functionally — the field
must reach the exported JSON, which requires running before the exporter.

## Standalone / opt-out

```bash
# Standalone — refresh URL status on existing relevant.json
python main.py --url-check

# Force re-probe (bypass 30-day TTL)
python main.py --url-check --url-check-force

# Limit to one source
python main.py --url-check --url-check-source AU-TEN

# Inside --all (no flag needed — Phase 3l always runs)
python main.py --all --since 2026-01-01 --two-stage --uk --review
```

## Exporter integration

`src/exporter_frontend.py` lifts `_url_status` to the top-level
`url_status` field on each exported tender (schema-validated against
`shared/schema/tender.schema.json`). The field is **omitted** when the
validator hasn't run yet, so legacy exports keep validating without
backfill.

## Frontend integration (handoff note)

The frontend can:
1. Show normal links when `url_status` is missing or `"alive"`.
2. Add a small badge when `url_status` is `"auth_walled"` — these are real
   notices, but the user must log into the source portal.
3. Strike-through / disable links when `url_status` is `"dead"` or
   `"redirect_loop"`.
4. Treat `"timeout"` and `"unknown"` as neutral — they retry on the next
   pipeline run.

## Cost

Free — no LLM calls, just HTTP. A full re-probe of ~340 notices takes
≈ 2–3 min at the default 0.5 s rate-limit (politeness for shared portals).
Cache-hit runs are effectively instant.

## Initial run results (2026-05-20)

See `CHANGELOG.md` and the run output of `python -m src.url_validator`.

## Classifier quirks worth knowing

- **HTTP 206 Partial Content** is success. The probe sends `Range: bytes=0-2047`
  to avoid pulling whole-page HTML; servers that honour Range respond 206,
  not 200. `_classify()` treats `200 ≤ code < 300` as `alive` to handle this.
- **HTTP 403 is ambiguous.** Some portals (CanadaBuys, several CloudFront-
  fronted state portals) return 403 to bot User-Agents even when the page
  is fully accessible in a real browser. We classify 401 *and* 403 as
  `auth_walled` so the frontend can hint "open in browser" rather than
  hiding the link entirely. False positives are visible but harmless; the
  alternative (calling these `dead`) would silently lose real notices.
- **SPA hash routes** (`#/procurement/{uuid}`) always return 200 because
  the fragment is client-side. We accept this as `alive`. If the underlying
  notice no longer exists, the SPA itself renders "not found" — that's a
  UX issue, not a URL-health issue, and is documented at the adapter level
  (e.g. EE riigihanked.riik.ee).

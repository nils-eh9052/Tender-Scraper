# AusTender Source URL Format — Empirical Discovery (Sprint 2026-05-20)

**Status:** Resolved. Adapter fixed. 56/56 existing tenders backfilled.

## TL;DR

| Pattern | Final HTTP | Verdict |
|---------|:---:|---------|
| `https://www.tenders.gov.au/cn/{CN}/View`  | **302 → 404** | broken — was the old adapter output |
| `https://www.tenders.gov.au/Cn/Show/{CN}`  | **302 → 200** | ✓ canonical |
| `https://www.tenders.gov.au/cn/Show/{CN}`  | **302 → 200** | ✓ canonical (path is case-insensitive) |

The adapter now emits `…/cn/Show/{CN}`. The lowercase form was kept because
that's what the OCDS adapter previously used as the path prefix, so any
external bookmark following the same template still resolves.

## Method

Probed all reasonable URL variants for several known CN IDs via Python
`requests` with a Chrome User-Agent, `allow_redirects=True`, `verify=False`
(corporate VPN intercepts). HEAD returned 403 for everything — AusTender's
CloudFront in front of Public/* paths only answers GET, regardless of method.

```
=== AU verification ===
  CN4114917: HTTP 200, 83971b, CN-text-present=True
  CN4048671: HTTP 200, 83971b, CN-text-present=True
  CN4037407: HTTP 200, 83971b, CN-text-present=True
  CN4237513: HTTP 200, 83971b, CN-text-present=True   ← user's reported failing ID
```

All four CN IDs (including the one the user reported failing) returned
HTTP 200 with the corrected `…/Cn/Show/…` pattern and the response body
contained the CN identifier (sanity check that we landed on the right
detail page, not a generic 200 search-shell).

## Why was the old pattern wrong?

`/cn/{ID}/View` looks like a plausible REST-style path but it is not what
AusTender's MVC controller maps. The portal's controller methods are named
`Show`, `Display`, `Search`, etc. — the URL segment matches the *action
name*, not a generic "View" verb. The `/Cn/Show/{id}` form is the route
that survived the 2024 portal redesign.

The original adapter author probably arrived at `/View` from one of the
older `business.gov.au` proxy URLs or from a misremembered Search.* link.
No actual probe was ever done — the adapter shipped with the broken pattern
and nobody noticed because nobody opened a CN link in production until now.

## OCDS API permalink field?

Inspected: the OCDS releases returned by `/findByDates/contractPublished`
do **not** include a `permalink`, `webUrl`, or `htmlUrl` field. The portal
URL has to be constructed from the contract ID. Confirmed against
`release.contracts[0].id` for several samples.

## Adapter changes (committed Sprint 2026-05-20)

1. `src/national_scraper/adapters/au_ocds_adapter.py`
   - `AU_CN_DETAIL` constant changed from `/cn/{id}/View` to `/cn/Show/{id}`.
   - `_cn_portal_url()` rewritten accordingly.
   - Inline comment with the empirical probe summary.
2. `scripts/_fix_au_urls.py` — one-shot backfill that rewrites
   `source_url_national` for every AU-TEN notice in `relevant.json` and
   invalidates the corresponding entries in `data/.url_health_cache.json`.

## Verification after backfill

```
AU-TEN total in relevant.json: 56
URL rewrites performed:        56
Cache entries to invalidate:   56
```

A subsequent `python -m src.url_validator --source AU-TEN` run probes the
new URLs and writes `_url_status="alive"` to each notice (see
`docs/URL_HEALTH_CHECK.md`).

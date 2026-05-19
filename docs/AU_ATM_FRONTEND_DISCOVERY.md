# AU ATM Frontend Discovery

> Probed: 2026-05-10  
> Portal: AusTender — https://www.tenders.gov.au  
> Focus: Pre-award Approaches to Market (ATM), NOT post-award Contract Notices

---

## 1. Portal Architecture

AusTender is a **server-rendered ASP.NET application** (not a SPA). Pages return
complete HTML server-side; no JS execution is needed for scraping.

- Page size: ~90–127 KB per page (includes New Relic agent JS — ignore it)
- No `__NEXT_DATA__` or XHR-heavy search
- Sessions needed for: CSV/Excel export (403 without login), submission forms
- Sessions NOT needed for: RSS feed, ATM detail pages, search result pages

---

## 2. RSS Feed (Primary Source)

**URL:** `https://www.tenders.gov.au/public_data/rss/rss.xml`

| Property | Value |
|----------|-------|
| HTTP Status | 200 OK |
| Content-Type | application/rss+xml |
| Size | ~56 KB (2026-05-10) |
| Feed title | "AusTender Current ATM List" |
| Items | ~500 currently open ATMs |
| Auth required | No |
| Update cadence | Real-time (lastBuildDate in feed) |

### Item structure

```xml
<item>
  <title>GA2026/564: Panel Refresh - Hazard Extent &amp; Information Services Panel</title>
  <link>https://www.tenders.gov.au/Atm/Show/1c0a3c70-363d-4362-944f-22ef307fbb5c</link>
  <description>&lt;p&gt;This Approach to Market (ATM) is an open request for tenders...&lt;/p&gt;</description>
  <guid>https://www.tenders.gov.au/Atm/Show/1c0a3c70-363d-4362-944f-22ef307fbb5c</guid>
  <pubDate>Wed, 01 Apr 2026 00:00:00 GMT</pubDate>
</item>
```

**Field mapping:**
- `title` → `{ATM_ID}: {tender title}` — split on first `: ` to separate ID from title
- `link` / `guid` → detail page URL with UUID
- `description` → HTML-encoded description snippet (decode entities, strip tags)
- `pubDate` → RFC 2822 date → ISO YYYY-MM-DD via `email.utils.parsedate()`

**Limitation:** RSS does NOT include `Agency`, `Category (UNSPSC)`, `Close Date`, or
`ATM Type`. Those require a detail page fetch.

---

## 3. ATM Detail Page

**URL pattern:** `https://www.tenders.gov.au/Atm/Show/{uuid}`

UUID is a standard 32-char hex UUID, e.g. `1c0a3c70-363d-4362-944f-22ef307fbb5c`.

### Confirmed detail fields (from live probe, 2026-05-10)

After HTML tag-stripping, the page text is a single long space-separated string
containing labelled fields in this order:

```
ATM ID : GA2026/564
Agency : Geoscience Australia
Category : 81150000 - Earth science services
Close Date & Time : 11-May-2026 10:00 am (ACT Local Time)
Publish Date : 1-Apr-2026
Location : ACT, NSW, VIC, SA, WA, QLD, NT, TAS ...
ATM Type : Request for Tender
Multi Agency Access : No
Panel Arrangement : Yes
Multi-stage : No
Description : <free text>
Other Instructions : <free text>
Conditions for Participation : <free text>
Timeframe for Delivery : 1 July 2026
Address for Lodgement : tenders@ga.gov.au
Addenda Available : View Addenda
```

### Extraction regexes (applied to stripped single-line text)

| Field | Pattern |
|-------|---------|
| ATM ID | `r'ATM\s+ID\s*:\s*(\S+)'` |
| Agency | `r'Agency\s*:\s*(.*?)\s*(?=Category\s*:)'` |
| UNSPSC code | `r'Category\s*:\s*(\d{8})'` |
| Close date (date only) | `r'Close Date\s*(?:&amp;\|&)?\s*Time\s*:\s*(\d+\-[A-Za-z]+\-\d+)'` |
| Publish date | `r'Publish Date\s*:\s*(\d+\-[A-Za-z]+\-\d+)'` |
| Description | from `Description :` to next section label |

### Date format on detail pages

AusTender uses `DD-Mon-YYYY` format: `11-May-2026`, `1-Apr-2026`.
Conversion: split on `-`, map 3-letter month name → 2-digit month number.

---

## 4. Search Form

**URL:** `https://www.tenders.gov.au/Search/AtmAdvancedSearch`  
**Method:** POST, returns HTML  
**Status:** 200 OK (confirmed)  
**Auth required:** No

Not used in the primary adapter implementation — RSS is sufficient for current ATMs.
Could be used for historical ATMs or agency-specific searches in a future enhancement.

---

## 5. OCDS API (Post-Award Only — NOT Used)

**URL:** `https://api.tenders.gov.au/ocds/findByDates/contractPublished/...`

Covers **Contract Notices only** (post-award). Returns 200 with paginated OCDS 1.1
JSON. ATMs (pre-award) are NOT exposed via this API. See `docs/AU_OCDS_API_PROBE.md`.

---

## 6. CSV / Excel Export

**URL:** `https://www.tenders.gov.au/Search/ExportToCSV` (inferred)  
**Status:** 403 Forbidden without session cookie  
**Decision:** Not implemented — RSS + detail pages are sufficient.

---

## 7. Scraping Strategy

```
┌─────────────────────────────────────────────────────────┐
│ 1. GET https://www.tenders.gov.au/public_data/rss/rss.xml │
│    → Parse ~500 ATM items (title, URL, description, date) │
│    → Pre-filter by TRAILER_KEYWORDS or DEFENCE_BUYERS     │
│    → Typically 10–60 matches                              │
└────────────────────────┬────────────────────────────────┘
                         │ for each match
┌────────────────────────▼────────────────────────────────┐
│ 2. GET https://www.tenders.gov.au/Atm/Show/{uuid}        │
│    → Extract: agency, UNSPSC code, deadline, description  │
│    → Rate-limited to 1.0 s between requests               │
│    → Store full page text as _national_raw_text           │
└─────────────────────────────────────────────────────────┘
```

Expected volumes: 100–500 total ATMs in RSS, ~5–30 defence-relevant after filter.

---

## 8. Key Decisions

| Decision | Reason |
|----------|--------|
| RSS as primary, not search form | RSS is a single request covering all current ATMs; no session required |
| `requests.Session` only, no Playwright | AusTender is server-rendered; Playwright overhead not justified |
| Register as `"au"` in main.py | Consistent with other single-country registrations |
| Source code `AU-AT` | Distinguishes from future `AU-CN` (OCDS Contract Notices) |
| Defence filter: OR logic | Catch trailer tenders from any agency AND defence tenders of any type |
| UNSPSC segment 25 in filter | Covers all ADF vehicle/equipment procurement beyond just trailers |

# TED API Field Discovery — 2026-05-09

**Sprint context:** Cross-Reference-Investigation §4.2 / Strategie B
("erst TED-XML voll auswerten, dann erst nationale Portale scrapen").
This document captures the *empirically validated* TED v3 search-API
field names that our pipeline did not previously request.

**Method:** `scripts/_probe_ted_fields_v2.py` runs a binary-search-style
probe against `https://api.ted.europa.eu/v3/notices/search`. The API
returns HTTP 400 on any unknown field, so the probe halves the candidate
list on each rejection until single-field validity is established. The
final set is then re-fetched to capture sample values.

Probed publication numbers (one per buyer-country): `212474-2026` (DE),
`77247-2026` (FR), `798124-2025` (CZ), `261427-2025` (PL).

---

## 1. Confirmed new fields (8)

All eight names below are accepted by the TED v3 search API. Sample
values are taken from the four probe responses; `—` means the field
was not populated on any of those four notices but the API still
accepted the request.

| Field | Type | Sample value (probe) | Use-case |
| ----- | ---- | -------------------- | -------- |
| `buyer-internet-address` | array | `["http://www.evergabe-online.de/"]` (DE) | **Foreign-Key** to the buyer's procurement portal — best-available equivalent of the XML `buyer-profile-url`. |
| `estimated-value-lot` | array | `["2332000","827000","857000","568000"]` (FR — 4 lots: motorcycles 1, 2, 3, trailers) | **Per-lot value breakdown.** Closes the gap that we currently aggregate to a single `total-value`. |
| `quantity-lot` | array | (empty on the four probes) | Per-lot quantity — **direct mapping target for `_trailer_quantity_*_ai`** that the AI classifier currently has to infer from prose. |
| `procedure-features` | dict (multilingual) | `{"fra": "La présente consultation est une procédure négociée avec publicité préalable…"}` (FR) | Procedure description — useful for status reasoning + AI classifier context. |
| `place-of-performance-city-part` | array | (empty on the four probes) | Performance city — geo enrichment. |
| `place-of-performance-country-part` | array | (empty on the four probes) | Performance country — separates "buyer-country" from "delivery-country". |
| `deadline-receipt-tender-time-lot` | array | (empty on the four probes) | Per-lot deadline time — pairs with the existing `deadline-receipt-tender-date-lot`. |
| `internal-identifier-part` | array | (empty on the four probes) | Internal organisation identifier (auxiliary / rarely populated). |

> **Note on the empty samples:** The four probe-IDs are mostly single-lot
> Defence trailers, so `quantity-lot` and `place-of-performance-*-part`
> often default to empty. Larger / multi-lot frame-agreements tend to
> populate these fields. The empirical probe confirms that the API
> *accepts* the field name; the probe just happened to land on
> notices where the value is null.

---

## 2. Field names that the API does **not** know

Despite Window B's Cross-Reference-Investigation surfacing them in the
TED-**XML** representation, these names are not part of the TED v3
JSON-search API and trigger HTTP 400. The information is only
retrievable by parsing the public XML at
`https://ted.europa.eu/<id>/xml`.

```
tender-documents-access            buyer-profile-url
submit-tenders-address             additional-information-address
internal-reference                 communication-language
contract-folder-id                 contract-duration
framework-agreement                tender-amount
review-procedure-body              review-deadline
classification-additional-cpv      classification-cpv-lot
procurement-procedure-type         procurement-procedure-justification
buyer-internet-address-part        buyer-name-part
organisation-internet-address      lot, lot-id, lot-title
```

A future sprint can introduce a thin **XML fallback fetcher** for the
~10 % of fields where the JSON API is silent (notably the Tender-ID-bearing
`tender-documents-access` which is the direct national-portal-deeplink).
Out of scope for this Sprint.

---

## 3. Recommendation — implement now

Add the 8 confirmed names to `src/api_client.py:ALL_FIELDS`. Map them
in `src/index_builder.py` to top-level structured keys (where they
map cleanly):

```text
buyer-internet-address           → _buyer_profile_url        (string, first array element)
estimated-value-lot              → _lots_array[*].value_eur  (combined with quantity-lot)
quantity-lot                     → _lots_array[*].quantity
procedure-features               → _procedure_features       (string, eng > fra > original)
place-of-performance-city-part   → _performance_city
place-of-performance-country-part → _performance_country
deadline-receipt-tender-time-lot → merged into existing deadline structure
internal-identifier-part         → _internal_reference       (best-effort)
```

The field `buyer-internet-address` is the natural source for the
Document-Pipeline `vergabeunterlagen_url` slot — see
`src/document_pipeline/discovery.py` extension in the same sprint.

---

## 4. Sample raw data

`data/.ted_field_probe.json` contains the full probe-response payload
(four notices × union-of-fields) for reference. Useful as fixture for
unit tests of the new mapping logic.

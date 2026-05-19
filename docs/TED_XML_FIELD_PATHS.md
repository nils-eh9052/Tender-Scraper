# TED XML Field Paths — 2026-05-10

**Sprint context:** Strategy B implemented in the previous sprint
covered the JSON-search-API. The fields documented here live **only in
the TED-XML** representation at
`https://ted.europa.eu/{lang}/notice/{publication-number}/xml` and are
not retrievable through the JSON search API.

The XML follows OASIS UBL 2.3 with the eForms SDK extension (UBLVersionID
`2.3`, ProfileID `eforms-sdk-1.13`). Element names are stable across
notice types (CN = Contract Notice, CAN = Contract Award Notice).

**Probe coverage:** four representative tenders, one per buyer country
(DE / FR / PL / CZ). Path consistency was empirically confirmed.

---

## 1. Foundational fields

### 1.1 `internal_reference` — the buyer's own tender ID

**XPath:** `ContractNotice/ProcurementProject/ID`

```
DE  212474-2026 → "Q/U2BP/RA029/NA103"
FR   77247-2026 → "24R40121"
CZ  798124-2025 → "OVZ/018/3/2025"
PL  261427-2025 → "D/08/12WOG/2025"
```

**Use:** The buyer's internal reference number (Aktenzeichen / référence
contrat / číslo zakázky / numer zamówienia). Required as a search-key
on the national portal when the `tender_documents_access` URL is only a
buyer-portal stem (e.g. FR/PL).

For Contract-Award Notices the root element is `ContractAwardNotice`
instead; the relative path is identical.

### 1.2 `contract_folder_id` — eForms unique folder UUID

**XPath:** `ContractNotice/ContractFolderID`

```
DE → "e911c5fa-bc2a-4b21-ae61-9e360f45da6a"
FR → "697b4024-bc51-4a1b-a4ae-9de3bf9c05ef"
CZ → "59aedf0c-7c52-44a9-b0a4-1ddf9d119631"
PL → "fc9f591b-b13d-43e4-a5c6-281161d9d685"
```

Always populated. Stable across the lifetime of the procurement (CN +
CAN of the same procurement share the same `ContractFolderID`).

### 1.3 `notice_uuid` — eForms notice UUID

**XPath:** `ContractNotice/ID` (first child, **before** the
`ContractFolderID` sibling — by document order)

Always populated. Differs between CN and CAN of the same procurement.

---

## 2. Cross-reference URLs (Foreign-Keys to national portals)

### 2.1 `tender_documents_access` — direct deeplink with tender-id

Primary XPath (most informative — includes tender-ID parameter):

```
ContractNotice/ProcurementProjectLot/TenderingTerms
  /CallForTendersDocumentReference/Attachment/ExternalReference/URI
```

Sample values (where populated):

```
DE 212474-2026 → "https://www.evergabe-online.de/tenderdetails.html?id=771723"
CZ 798124-2025 → "https://verejnezakazky.vop.cz/vz00002751"
```

**Fallback chain** (per-country quirk):

1. `…/CallForTendersDocumentReference/Attachment/ExternalReference/URI`
2. `ContractNotice/ProcurementProjectLot/TenderingProcess/AccessToolsURI`
3. `ContractNotice/ContractingParty/BuyerProfileURI`

For **CAN-Notices** the procurement is already awarded, so step 1 may
be absent. Fall back to step 3 then.

### 2.2 `buyer_profile_url` — full buyer-portal URL

**Primary XPath:** `ContractNotice/ContractingParty/BuyerProfileURI`

```
DE 212474-2026 → "http://www.evergabe-online.de/"  (host-only)
FR  77247-2026 → "www.marches-publics.gouv.fr"      (host-only, scheme missing)
PL 261427-2025 → "https://platformazakupowa.pl/pn/12wog"  ← buyer-code included!
CZ 798124-2025 → "https://verejnezakazky.vop.cz/vz00002751"  ← tender-id included!
```

**Note on schemes:** PL/FR sometimes ship the URL without a scheme
(`www.marches-publics.gouv.fr`). The parser must prepend `https://` for
those.

**Fallback chain:**

1. `ContractingParty/BuyerProfileURI` (preferred — most specific)
2. `Organizations/Organization/Company/WebsiteURI` for the **buyer**
   organisation (look up by `ContractingParty/Party/PartyIdentification/ID`)

Step 2 is what the JSON-API exposes as `buyer-internet-address`. The
XML often has additional path information that the JSON does not.

### 2.3 `submit_tenders_endpoint`

**XPath:**
`ContractNotice/ProcurementProjectLot/TenderingTerms/TenderRecipientParty/EndpointID`

Same value as `tender_documents_access` in DE+CZ samples; absent in
FR+PL CAN-Notices. Useful as a confirmation check.

---

## 3. Field-name renames between JSON-API and XML

| JSON-API name (Sprint 2026-05-09) | XML element | Practical difference |
| --------------------------------- | ----------- | -------------------- |
| `buyer-internet-address`          | `WebsiteURI` (buyer org's `Company/WebsiteURI`) | Identical content |
| (none in API)                     | `BuyerProfileURI` | XML-only, often a fuller URL with buyer-code |
| (none in API)                     | `CallForTendersDocumentReference/.../URI` | XML-only, includes tender-ID parameter |
| (none in API)                     | `ProcurementProject/ID` | XML-only string identifier (`24R40121` etc.) |
| (none in API)                     | `ContractFolderID` | XML-only UUID |
| `internal-identifier-part`        | (no clean equivalent) | API field is sparse / mostly empty |

---

## 4. Implementation notes

* The XML is UTF-8, ~30–80 KB per notice, gzip-compressible (HTTP-level).
* All TED-public URLs work without authentication.
* Rate limit: TED runs nginx with a global rate limiter that fires HTTP
  429 around 4–5 req/s. Stick to **1 req/s** to be safe.
* On `429`, exponential back-off (5 s, 10 s, 15 s) succeeds.
* Use `xml.etree.ElementTree` (stdlib) — strip namespaces with
  `tag.split('}')[-1]`. Avoids `lxml` runtime dependency.
* Cache fetched XML at `data/ted_xml_cache/{publication-number}.xml` so
  re-runs are free.

---

## 5. Out of scope (not implemented in this sprint)

- Multilingual notice-title from XML (already covered by JSON `notice-title`).
- LotsGroup / FrameworkAgreement structure — too deep, separate sprint.
- Award details from CAN-Notices' `TenderResult/AwardedTenderedProject`
  — already mapped via `award.winner_name` from JSON-API.

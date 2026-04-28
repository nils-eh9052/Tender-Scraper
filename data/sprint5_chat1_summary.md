# Sprint 5 Chat 1 — France + Denmark Adapters

**Date:** 2026-04-28  
**Branch:** `sprint5/national-fr-dk`  
**Engineer:** Claude Sonnet 4.6 (Sprint 5, Chat 1)

---

## What Was Implemented

### 1. France Adapter — `src/national_scraper/adapters/fr_adapter.py`

**Portal:** BOAMP (Bulletin Officiel des Annonces des Marchés Publics)  
**Strategy:** Pure REST API (requests-based, no browser needed)

**Key discovery:** BOAMP exposes a full OpenDataSoft REST API at  
`https://www.boamp.fr/api/explore/v2.1/catalog/datasets/boamp/records`  
No authentication required. SQL-like WHERE expressions. Offset pagination.

**Defence filter — `perimetre='DIRECTIVE-81'`:**  
Notices filed under EU defence procurement directive 2009/81/EC carry the field  
`perimetre = 'DIRECTIVE-81'`. This is the most reliable defence filter — more  
reliable than authority name matching (which suffers from "DGA" false positives,  
since DGA is also "Direction Générale Adjointe" in local government).

**Three-phase search strategy:**
1. `perimetre='DIRECTIVE-81' AND objet LIKE '%remorque%' OR ...` — most precise
2. `(MINARM OR MINDEF) AND trailer keywords` — catches non-DIRECTIVE-81 entries
3. Full MINARM sweep — all MINARM notices (for enrichment of TED entries)

**French authority naming in BOAMP:**
- `MINARM/DGA/DO/S2A` — DGA armement
- `MINARM/DMAé/SSAM33503` — Direction de la Maintenance Aéronautique
- `MINDEF/TERRE/SIMMT` — maintien matériel terrestre  
- `Marine/DCSSF/DSSF Toulon` — Marine Nationale
- `ARM/SCA/PFAF-RBT` — Commissariat des Armées

**Key fields extracted:** `idweb`, `objet`, `nomacheteur`, `dateparution`, `url_avis`,  
`titulaire` (winner), `datelimitereponse` (deadline), `donnees` (full JSON for value/quantity/duration)

### 2. Denmark Adapter — `src/national_scraper/adapters/dk_adapter.py`

**Portal:** Udbud.dk  
**Strategy:** Browser-based (Playwright) — Vue.js SPA, client-side search

**Key discoveries:**
- Production URL is `https://udbud.dk` (no www — www redirects to no-www)
- The site is a Vue.js SPA returning a 902-char shell for all paths
- **Search is entirely client-side** — no XHR fires during search, no network requests
- Search form: `input[name="search-query"]` on the homepage, press Enter to trigger
- Notice detail URL: `/detaljevisning?noticeId={UUID}&noticeVersion=N&noticePublicationNumber=N`
- Publication number format: `00253032-2026` (compatible with TED OJEU number)
- Keywords **must use proper Danish characters** (æ, ø, å) — ASCII variants return 0 results

**Search flow:**
1. Navigate to `https://udbud.dk/`
2. Fill `input[name="search-query"]` with keyword  
3. Press Enter, wait 5 seconds for Vue.js re-render
4. Extract `/detaljevisning?noticeId=...` links from DOM via JavaScript

**Authority search:** "FMI Forsvaret" as search keyword returns FMI notices

### 3. main.py Integration

Both adapters registered in `run_national_scraping()`:
```python
adapter_registry["fr"] = (FRAdapter, create_fr_config)
adapter_registry["dk"] = (DKAdapter, create_dk_config)
```

---

## Test Results (`python main.py --national fr dk --test --visible`)

### France (FR-BP) ✅

| Metric | Value |
|---|---|
| Raw search results | 13 |
| Defence-relevant | 13 (100%) |
| Details fetched | 3 (test limit) |
| Notices added to relevant.json | 3 |

**Sample notices:**
- `21-163372` — MINARM/DMAé: Fourniture de groupes de soudure sur remorque, winner=CTF FRANCE SAURON
- `21-38939` — MINARM/DGA/DO/S2A: Conception et réalisation d'une semi-remorque routière aménagée en laboratoire
- `21-47488` — MINARM/DGA/DO/S2A: Acquisition d'un robot terrestre mobile tout terrain télécommandé, de sa remorque

Winner field populated from BOAMP `titulaire` — useful for enrichment of TED entries.

### Denmark (DK-UD) ✅

| Metric | Value |
|---|---|
| Raw search results | 38 |
| Defence-relevant | 2 |
| Details fetched | 2 |
| Notices added to relevant.json | 2 |

**Defence notices found:**
- "Indhentelse af oplysninger i forbindelse med anskaffelse af..." (RFI/market consultation, Forsvaret)
- "Anskaffelse af sigtevinger til forsvarets TMG" (sighting devices for defence TMG)

**Total after merge:** 227 notices in relevant.json (from 222 before)

---

## Open Problems

### FR: BOAMP data is historical (pre-2022 for DIRECTIVE-81 trailers)
The 13 results found are from 2015–2021. Recent DGA trailer procurement may be classified  
(not on BOAMP) or use the more recent eForms format. Full run (no test_mode) will search  
the complete MINARM authority sweep and may find more recent entries.

### DK: Only 2 defence results — Udbud.dk has limited active content
Udbud.dk only covers notices published after March 2022 (per its own note:  
"Find bekendtgørelser udgivet i perioden 01-03-2022 til 12-11-2024" in the archive).  
FMI may publish primarily on TED/OJEU directly. The search for "FMI Forsvaret" returns  
25 results but most are non-trailer FMI notices. This is expected — DK is primarily  
an enrichment source, not a new-notice source.

### DK: Keywords show 0 results for pre-2022 notices (archive)
The main Udbud.dk search only covers notices since March 2022. Earlier DK defence trailer  
notices are in the archive at `https://udbud.dk/arkiv` — not yet implemented. For the  
14 TED DK notices in relevant.json, many may be pre-2022 and not findable on current Udbud.dk.

### DK: filter_defence too strict — misses GEUS Arctic vehicle notice
"De Nationale Geologiske Undersøgelser for Danmark og Grønland" (GEUS) published  
"Profylaksebekendtgørelse om køb af arktiske terrængende og amfibiske køretøjer"  
(prior notice for Arctic terrain and amphibious vehicles). This is semi-relevant  
but GEUS is not a defence authority, so it's correctly filtered out.

### SyntaxWarning fixed
Initial version had `r"\-"` in a Python string containing a JS regex — fixed to `r"-"`.

---

## Recommendations for Next Sprint

1. **Run full FR scan** — remove `test_mode` to run Phase 3 (full MINARM sweep, 500+ notices).  
   Expected 20–50 trailer-relevant notices. Cost: ~0 (requests only).

2. **BOAMP eForms extension** — since 2024, France uses eForms format.  
   Add `famille='JOUE'` filter to catch EU-threshold eForms notices. Search `perimetre='EFORMS'` as alternative.

3. **DK archive scraping** — implement `/arkiv` scraping for pre-2022 notices (14 TED DK entries are mostly pre-2022).

4. **DK enrichment pass** — try matching the 14 DK TED entries to Udbud.dk by publication number  
   (TED pub number `00253032-2026` matches Udbud.dk `noticePublicationNumber=00253032-2026`).

5. **PLACE (marches-publics.gouv.fr)** — secondary FR portal used by some MoD sub-agencies.  
   May duplicate BOAMP but worth a quick check.

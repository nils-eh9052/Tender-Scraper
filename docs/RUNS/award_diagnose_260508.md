# Award Forensic Diagnosis — 2026-05-08

## Summary

| Metric | Count |
|--------|-------|
| Total notices in relevant.json | 301 |
| Computed status = Awarded (exporter_frontend) | 135 |
| award.awarded == True (notice block) | 68 |
| LLM log: applied=True + match!=None | 20 |
| Gap: applied in LLM cache but tender missing from relevant.json | 1 |
| Gap: applied in LLM cache but no award.awarded in relevant.json | 0 |
| Heuristic leak: winner_name set, award.awarded missing | 12 |

## Status distribution (computed)

- **Awarded**: 135
- **Closed**: 148
- **Open**: 18

## Gap D1: Applied in LLM cache but tender not in relevant.json

| Target ID | Matched Award ID |
|-----------|-----------------|
| 290520-2018 | 44748-2019 |

## Gap E: winner_name set but award.awarded missing

| Tender ID | Winner Name |
|-----------|-------------|
| UK-tender_347489/1184039 | Andover Trailers Ltd |
| UK-tender_340233/1221190 | THJ (Machinery) Ltd |
| FR-21-163372 | CTF FRANCE SAURON |
| FR-17-20328 | LOSBERGER RDS |
| FR-17-11123 | delty sas |
| FR-15-186837 | Société GAVAP |
| FR-19-11984 | Entreprise Boraine de Mécanique |
| FR-21-163372 | CTF FRANCE SAURON |
| FR-17-20328 | LOSBERGER RDS |
| FR-17-11123 | delty sas |
| FR-15-186837 | Société GAVAP |
| FR-19-11984 | Entreprise Boraine de Mécanique |

## LLM log — full applied entries

| Target ID | Match ID | Confidence | Reasoning (truncated) |
|-----------|----------|------------|-----------------------|
| 678662-2024 | 30130-2025 | 97 | Identical title, same authority (armasuisse), same CPV codes, and publication da |
| 493986-2024 | 254420-2025 | 97 | Identical subject matter (multifunctional engineer equipment and field lighting  |
| 299270-2019 | 18389-2020 | 97 | Identical title ('Bridge Transport Semi-trailers KB8'), same authority (Försvare |
| 129337-2017 | 510836-2017 | 97 | Identical subject matter (climate-controlled road trailers for pyrotechnic speci |
| 416123-2016 | 98678-2017 | 97 | Identical title, CPV code, buyer (Unitatea Militara 02574 under Ministerul Apara |
| 351531-2025 | 796372-2025 | 97 | Candidate 1 has an identical title ('Acquisition of light trailers and multiplat |
| 538598-2019 | 272850-2020 | 97 | Identical title, CPV code, and contracting authority (MAEE — Direction de la Déf |
| 502486-2022 | 377722-2023 | 97 | Identical title, identical CPV code, identical contracting authority, same count |
| 433505-2022 | 377722-2023 | 97 | Identical title, identical CPV code, identical contracting authority, same count |
| 290520-2018 | 44748-2019 | 97 | Identical title, identical CPV code, identical contracting authority, and public |
| 312763-2020 | 4819-2021 | 97 | Identical title, same CPV code 34221000, same buying unit (Unitatea Militară 018 |
| 529820-2020 | 4819-2021 | 97 | Identical title, CPV code, and contracting authority (same military unit under R |
| 290522-2018 | 44748-2019 | 97 | Identical title, CPV code, and contracting authority (Czech Ministry of Defence) |
| 218375-2020 | 29224-2021 | 95 | Candidate 2 shares the identical title ('Special-purpose mobile containers'), th |
| 572650-2024 | 326948-2025 | 92 | Candidate 1 shares the same subject matter (Military Medical Trailers Role 1 & 2 |
| 385446-2024 | 119311-2025 | 92 | Candidate 1 matches on subject matter (Heavy Platform/Cargo Trailers O4-PN-V for |
| 381122-2019 | 156274-2020 | 92 | Candidate 1 matches on all key dimensions: identical title, same contracting aut |
| 790433-2023 | 53033-2024 | 92 | Candidate 1 shares identical title, exact same authority, same country, and matc |
| UK-tender_340233/1200929 | UK-tender_340233/1221190 | 92 | Candidate 1 shares the identical title 'Box Trailers', the same authority (Minis |
| 431698-2023 | 62507-2024 | 85 | Candidate 1 shares identical title, authority, country, and CPV code (34221000)  |

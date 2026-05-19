# Field-Extraction Audit — 2026-05-09

`relevant.json`: **256** notices total. Goal: surface countries where the AI classifier failed to populate trailer-quantity / contract-duration / trailer-type from non-English source text. Window A produced `description_en` for 256/256 notices, so re-classification on the English copy should close most of these gaps.

| Group | Total | trailer_type_1 | trailer_quantity_1 | contract_duration | description_en |
| ----- | ----: | -------------: | -----------------: | ----------------: | -------------: |
| TED | 194 | 194 (100%) | 73 (38%) | 27 (14%) | 194 (100%) |
| CZ | 32 | 32 (100%) | 12 (38%) | 2 (6%) | 32 (100%) |
| FR | 13 | 13 (100%) | 5 (38%) | 0 (0%) | 13 (100%) |
| UK | 6 | 6 (100%) | 2 (33%) | 1 (17%) | 6 (100%) |
| UA | 4 | 3 (75%) | 2 (50%) | 0 (0%) | 4 (100%) |
| NO | 3 | 3 (100%) | 0 (0%) | 0 (0%) | 3 (100%) |
| EE | 3 | 3 (100%) | 0 (0%) | 0 (0%) | 3 (100%) |
| NL | 1 | 1 (100%) | 0 (0%) | 0 (0%) | 1 (100%) |

## Re-Classification Candidates

**234** notices are missing at least one of `_trailer_type_1_ai`, `_trailer_quantity_1_ai`, `_contract_duration_ai` **AND** have a `description_en` field. These are the targets for the selective Sonnet re-classification run.

```
182178-2026
572650-2024
245184-2024
726774-2024
530666-2024
537199-2024
345761-2025
749251-2025
432811-2024
488694-2022
95616-2026
283775-2022
118630-2024
207812-2024
798124-2025
465260-2025
711549-2022
682847-2024
77247-2026
161258-2025
734326-2023
775798-2024
3730-2025
231675-2021
188150-2024
13179-2023
309470-2022
813306-2025
751810-2024
119311-2025
751287-2024
385446-2024
386007-2024
590889-2025
132540-2025
620674-2024
30130-2025
129915-2025
678662-2024
582377-2025
467088-2025
299270-2019
655783-2024
18389-2020
466852-2018
152406-2025
583390-2025
147849-2021
510836-2017
607291-2021
... and 184 more
```

# Keyword Merge Log — Sprint 14g activation

**Date:** 2026-05-10

**Source:** `docs/SETTINGS_KEYWORD_DIFF.yaml`

**Target:** `config/settings.yaml`

**Rewrite method:** ruamel.yaml (round-trip)

---

## Summary

- **Terms kept:** 384
- **Terms dropped:** 48
- **Categories touched:** 13
- **Stoplist size:** 43

### Curation Rules
1. Drop terms <4 chars
2. Drop stoplist matches (civilian-overlap risk)
3. Drop duplicates already in settings.yaml
4. Keep all multi-word phrases
5. Keep single-word terms ≥6 chars

---

## Per-Category Detail

### `ammunition_trailer`  (kept: 31, dropped: 1)

**cs** (3):
- `muniční přívěs` (multi-word phrase)
- `přívěs na munici` (multi-word phrase)
- `přeprava munice` (multi-word phrase)

**da** (3):
- `ammunitionsvogn` (single word ≥6 chars (15))
- `ammunitionstransport` (single word ≥6 chars (20))
- `våbenvogn` (single word ≥6 chars (9))

**de** (2):
- `munitionstransporter` (single word ≥6 chars (20))
- `munitionsauflieger` (single word ≥6 chars (18))

**en** (2):
- `munitions carrier` (multi-word phrase)
- `ordnance trailer` (multi-word phrase)

**es** (3):
- `remolque munición` (multi-word phrase)
- `transporte munición` (multi-word phrase)
- `plataforma armamento` (multi-word phrase)

**fr** (2):
- `transport munitions` (multi-word phrase)
- `remorque armement` (multi-word phrase)

**it** (3):
- `rimorchio munizioni` (multi-word phrase)
- `trasporto munizioni` (multi-word phrase)
- `rimorchio armamento` (multi-word phrase)

**nl** (3):
- `munitietrailer` (single word ≥6 chars (14))
- `munitietransport` (single word ≥6 chars (16))
- `wapentrailer` (single word ≥6 chars (12))

**no** (3):
- `ammunisjonshenger` (single word ≥6 chars (17))
- `ammunisjonstransport` (single word ≥6 chars (20))
- `våpenhenger` (single word ≥6 chars (11))

**pl** (2):
- `transport amunicji` (multi-word phrase)
- `przyczepa uzbrojenia` (multi-word phrase)

**ro** (3):
- `remorcă muniție` (multi-word phrase)
- `transport muniție` (multi-word phrase)
- `remorcă armament` (multi-word phrase)

**sv** (2):
- `ammunitionssläp` (single word ≥6 chars (15))
- `vapensläp` (single word ≥6 chars (9))

**Dropped** (1):
- 1× already in settings

### `cargo_trailer`  (kept: 36, dropped: 0)

**cs** (3):
- `nákladní přívěs` (multi-word phrase)
- `transportní přívěs` (multi-word phrase)
- `přepravní přívěs` (multi-word phrase)

**da** (3):
- `fragtvogn` (single word ≥6 chars (9))
- `godsvogn` (single word ≥6 chars (8))
- `transportvogn` (single word ≥6 chars (13))

**de** (3):
- `lastenanhänger` (single word ≥6 chars (14))
- `transportanhänger` (single word ≥6 chars (17))
- `güteranhänger` (single word ≥6 chars (13))

**en** (3):
- `cargo trailer` (multi-word phrase)
- `freight trailer` (multi-word phrase)
- `transport trailer` (multi-word phrase)

**es** (3):
- `remolque de carga` (multi-word phrase)
- `remolque transporte` (multi-word phrase)
- `plataforma de carga` (multi-word phrase)

**fr** (3):
- `remorque de fret` (multi-word phrase)
- `remorque cargo` (multi-word phrase)
- `remorque transport` (multi-word phrase)

**it** (3):
- `rimorchio merci` (multi-word phrase)
- `rimorchio cargo` (multi-word phrase)
- `rimorchio trasporto` (multi-word phrase)

**nl** (3):
- `vrachtaanhanger` (single word ≥6 chars (15))
- `goederentrailer` (single word ≥6 chars (15))
- `transportaanhanger` (single word ≥6 chars (18))

**no** (3):
- `frakthenger` (single word ≥6 chars (11))
- `godshenger` (single word ≥6 chars (10))
- `transporthenger` (single word ≥6 chars (15))

**pl** (3):
- `przyczepa transportowa` (multi-word phrase)
- `przyczepa towarowa` (multi-word phrase)
- `przyczepa ładunkowa` (multi-word phrase)

**ro** (3):
- `remorcă marfă` (multi-word phrase)
- `remorcă transport` (multi-word phrase)
- `remorcă cargo` (multi-word phrase)

**sv** (3):
- `fraktsläp` (single word ≥6 chars (9))
- `godssläp` (single word ≥6 chars (8))
- `transportsläp` (single word ≥6 chars (13))

### `decontamination_cbrn`  (kept: 35, dropped: 0)

**cs** (3):
- `dekontaminační přívěs` (multi-word phrase)
- `dekontaminace cbrn` (multi-word phrase)
- `přívěs nbc` (multi-word phrase)

**da** (3):
- `dekontamineringsvogn` (single word ≥6 chars (20))
- `cbrn-vogn` (single word ≥6 chars (9))
- `abc-rensning` (single word ≥6 chars (12))

**de** (3):
- `dekontaminationsanhänger` (single word ≥6 chars (24))
- `abc-dekontamination` (single word ≥6 chars (19))
- `cbrn-anhänger` (single word ≥6 chars (13))

**en** (3):
- `decontamination trailer` (multi-word phrase)
- `cbrn trailer` (multi-word phrase)
- `nbc decontamination` (multi-word phrase)

**es** (3):
- `remolque descontaminación` (multi-word phrase)
- `descontaminación nrbq` (multi-word phrase)
- `remolque nbc` (multi-word phrase)

**fr** (3):
- `remorque décontamination` (multi-word phrase)
- `décontamination nrbc` (multi-word phrase)
- `remorque nbc` (multi-word phrase)

**it** (2):
- `rimorchio decontaminazione` (multi-word phrase)
- `decontaminazione cbrn` (multi-word phrase)

**nl** (3):
- `decontaminatietrailer` (single word ≥6 chars (21))
- `cbrn-trailer` (single word ≥6 chars (12))
- `nbc-decontaminatie` (single word ≥6 chars (18))

**no** (3):
- `dekontamineringshenger` (single word ≥6 chars (22))
- `cbrn-henger` (single word ≥6 chars (11))
- `abc-rensing` (single word ≥6 chars (11))

**pl** (3):
- `przyczepa dekontaminacyjna` (multi-word phrase)
- `dekontaminacja cbrn` (multi-word phrase)
- `przyczepa abc` (multi-word phrase)

**ro** (3):
- `remorcă decontaminare` (multi-word phrase)
- `decontaminare cbrn` (multi-word phrase)
- `remorcă nbc` (multi-word phrase)

**sv** (3):
- `saneringsläp` (single word ≥6 chars (12))
- `cbrn-släp` (single word ≥6 chars (9))
- `abc-sanering` (single word ≥6 chars (12))

### `defence_context`  (kept: 29, dropped: 9)

**cs** (5):
- `vojenský` (single word ≥6 chars (8))
- `obranný` (single word ≥6 chars (7))
- `armáda` (single word ≥6 chars (6))
- `ozbrojené síly` (multi-word phrase)
- `ministerstvo obrany` (multi-word phrase)

**da** (3):
- `forsvar` (single word ≥6 chars (7))
- `værnepligt` (single word ≥6 chars (10))
- `forsvarsministeriet` (single word ≥6 chars (19))

**de** (1):
- `baaainbw` (single word ≥6 chars (8))

**es** (1):
- `minisdef` (single word ≥6 chars (8))

**fi** (5):
- `puolustus` (single word ≥6 chars (9))
- `sotilashanke` (single word ≥6 chars (12))
- `puolustusvoimat` (single word ≥6 chars (15))
- `maavoimat` (single word ≥6 chars (9))
- `logistiikkalaitos` (single word ≥6 chars (17))

**it** (1):
- `ministero difesa` (multi-word phrase)

**nl** (5):
- `militair` (single word ≥6 chars (8))
- `defensie` (single word ≥6 chars (8))
- `krijgsmacht` (single word ≥6 chars (11))
- `landmacht` (single word ≥6 chars (9))
- `ministerie van defensie` (multi-word phrase)

**no** (1):
- `ndma` (borderline single word (4 chars))

**pl** (1):
- `wojsko` (single word ≥6 chars (6))

**ro** (4):
- `apărare` (single word ≥6 chars (7))
- `armată` (single word ≥6 chars (6))
- `forțe armate` (multi-word phrase)
- `mapn` (borderline single word (4 chars))

**sv** (2):
- `försvar` (single word ≥6 chars (7))
- `armé` (borderline single word (4 chars))

**Dropped** (9):
- 5× already in settings
- 4× length <4 (3)

### `dolly`  (kept: 19, dropped: 10)

**cs** (2):
- `přídavná náprava` (multi-word phrase)
- `dolly podvozek` (multi-word phrase)

**da** (2):
- `dollyaksel` (single word ≥6 chars (10))
- `koblingsled` (single word ≥6 chars (11))

**de** (1):
- `dollyachse` (single word ≥6 chars (10))

**es** (2):
- `eje dolly` (multi-word phrase)
- `conversor dolly` (multi-word phrase)

**fr** (1):
- `essieu dolly` (multi-word phrase)

**it** (2):
- `asse dolly` (multi-word phrase)
- `carrello dolly` (multi-word phrase)

**nl** (2):
- `dolly-as` (single word ≥6 chars (8))
- `koppelwagen` (single word ≥6 chars (11))

**no** (1):
- `koblingsledd` (single word ≥6 chars (12))

**pl** (2):
- `wózek dolly` (multi-word phrase)
- `oś dolly` (multi-word phrase)

**ro** (2):
- `axă dolly` (multi-word phrase)
- `cărucior dolly` (multi-word phrase)

**sv** (2):
- `dollyaxel` (single word ≥6 chars (9))
- `kopplingsled` (single word ≥6 chars (12))

**Dropped** (10):
- 10× already in settings

### `field_kitchen`  (kept: 25, dropped: 1)

**cs** (3):
- `polní kuchyně` (multi-word phrase) — _ev_: `775798-2024`
- `kuchyňský přívěs` (multi-word phrase)
- `mobilní kuchyně` (multi-word phrase)

**da** (3):
- `feltkøkken` (single word ≥6 chars (10))
- `køkkenvogn` (single word ≥6 chars (10))
- `mobilt køkken` (multi-word phrase)

**de** (1):
- `verpflegungsanhänger` (single word ≥6 chars (20))

**es** (3):
- `cocina de campaña` (multi-word phrase)
- `remolque cocina` (multi-word phrase)
- `cocina móvil` (multi-word phrase)

**it** (3):
- `cucina campale` (multi-word phrase)
- `rimorchio cucina` (multi-word phrase)
- `cucina mobile` (multi-word phrase)

**nl** (3):
- `veldkeuken` (single word ≥6 chars (10))
- `keukentrailer` (single word ≥6 chars (13))
- `mobiele keuken` (multi-word phrase)

**no** (2):
- `kjøkkenhenger` (single word ≥6 chars (13))
- `mobilt kjøkken` (multi-word phrase)

**pl** (2):
- `przyczepa kuchenna` (multi-word phrase)
- `kontener kuchenny` (multi-word phrase)

**ro** (3):
- `bucătărie de campanie` (multi-word phrase)
- `bucătărie rulantă` (multi-word phrase)
- `remorcă bucătărie` (multi-word phrase)

**sv** (2):
- `köksvagn` (single word ≥6 chars (8))
- `mobilt kök` (multi-word phrase)

**Dropped** (1):
- 1× already in settings

### `generic_trailer`  (kept: 20, dropped: 3)

**cs** (3):
- `přívěs` (single word ≥6 chars (6))
- `přívěsy` (single word ≥6 chars (7))
- `přívěsný vozík` (multi-word phrase)

**da** (3):
- `påhængsvogn` (single word ≥6 chars (11))
- `påhængsvogne` (single word ≥6 chars (12))
- `anhænger` (single word ≥6 chars (8))

**de** (2):
- `containeranhänger` (single word ≥6 chars (17))
- `absetzcontaineranhänger` (single word ≥6 chars (23))

**en** (1):
- `mobile containers` (multi-word phrase)

**es** (1):
- `tráiler` (single word ≥6 chars (7))

**it** (1):
- `carrello` (single word ≥6 chars (8))

**nl** (1):
- `aanhanger` (single word ≥6 chars (9))

**no** (2):
- `henger` (single word ≥6 chars (6))
- `vogn` (borderline single word (4 chars))

**pl** (1):
- `przyczepy transportowe` (multi-word phrase)

**ro** (3):
- `remorcă` (single word ≥6 chars (7))
- `remorci` (single word ≥6 chars (7))
- `remorca` (single word ≥6 chars (7))

**sv** (2):
- `släpvagn` (single word ≥6 chars (8))
- `släpkärra` (single word ≥6 chars (9))

**Dropped** (3):
- 3× stoplist

### `heavy_haul`  (kept: 31, dropped: 4)

**cs** (3):
- `těžký transport` (multi-word phrase)
- `nadměrný náklad` (multi-word phrase)
- `těžkotonážní` (single word ≥6 chars (12))

**da** (3):
- `tungtransport` (single word ≥6 chars (13))
- `specialtransport` (single word ≥6 chars (16))
- `sværlast` (single word ≥6 chars (8))

**de** (2):
- `schwerlast` (single word ≥6 chars (10))
- `schwertransport` (single word ≥6 chars (15))

**en** (3):
- `heavy haul` (multi-word phrase)
- `heavy haulage` (multi-word phrase) — _ev_: `152406-2025`
- `heavy equipment transport` (multi-word phrase)

**es** (3):
- `transporte pesado` (multi-word phrase)
- `transporte especial` (multi-word phrase)
- `carga pesada` (multi-word phrase)

**fr** (3):
- `transport lourd` (multi-word phrase)
- `convoi exceptionnel` (multi-word phrase)
- `poids lourd` (multi-word phrase)

**it** (3):
- `trasporto pesante` (multi-word phrase)
- `trasporto eccezionale` (multi-word phrase)
- `convoglio speciale` (multi-word phrase)

**nl** (3):
- `zwaar transport` (multi-word phrase)
- `exceptioneel transport` (multi-word phrase)
- `zwaarlast` (single word ≥6 chars (9))

**no** (1):
- `spesialtransport` (single word ≥6 chars (16))

**pl** (3):
- `transport ciężki` (multi-word phrase)
- `naczepy ciężkie` (multi-word phrase)
- `transport ponadgabarytowy` (multi-word phrase)

**ro** (3):
- `transport greu` (multi-word phrase)
- `transport agabaritic` (multi-word phrase)
- `transport special` (multi-word phrase)

**sv** (1):
- `tung last` (multi-word phrase)

**Dropped** (4):
- 4× already in settings

### `loading_system`  (kept: 29, dropped: 2)

**cs** (3):
- `hákový nosič` (multi-word phrase)
- `kontejnerový nosič` (multi-word phrase)
- `nakládací systém` (multi-word phrase)

**da** (3):
- `krogløftsystem` (single word ≥6 chars (14))
- `containersystem` (single word ≥6 chars (15))
- `læssesystem` (single word ≥6 chars (11))

**de** (1):
- `absetzcontainer` (single word ≥6 chars (15))

**en** (1):
- `demountable system` (multi-word phrase)

**es** (3):
- `sistema gancho` (multi-word phrase)
- `portacontenedores` (single word ≥6 chars (17))
- `sistema desmontable` (multi-word phrase)

**fr** (3):
- `système ampliroll` (multi-word phrase)
- `bras de levage` (multi-word phrase)
- `système amovible` (multi-word phrase)

**it** (3):
- `sistema scarrabile` (multi-word phrase)
- `gancio carico` (multi-word phrase)
- `sistema amovibile` (multi-word phrase)

**nl** (3):
- `haaksysteem` (single word ≥6 chars (11))
- `containersysteem` (single word ≥6 chars (16))
- `laadsysteem` (single word ≥6 chars (11))

**no** (2):
- `krokløftsystem` (single word ≥6 chars (14))
- `lastesystem` (single word ≥6 chars (11))

**pl** (2):
- `system hakowy` (multi-word phrase)
- `hakowiec` (single word ≥6 chars (8))

**ro** (3):
- `sistem cu cârlig` (multi-word phrase)
- `sistem demontabil` (multi-word phrase)
- `sistem încărcare` (multi-word phrase)

**sv** (2):
- `kroklyftsystem` (single word ≥6 chars (14))
- `lastningssystem` (single word ≥6 chars (15))

**Dropped** (2):
- 2× already in settings

### `low_bed`  (kept: 25, dropped: 0)

**cs** (3):
- `nízkoložný` (single word ≥6 chars (10))
- `podvalník` (single word ≥6 chars (9))
- `nízkoložný přívěs` (multi-word phrase)

**da** (3):
- `lavlad` (single word ≥6 chars (6))
- `sænkevogn` (single word ≥6 chars (9))
- `lavtbygget` (single word ≥6 chars (10))

**de** (1):
- `tiefbettanhänger` (single word ≥6 chars (16))

**en** (1):
- `low loader` (multi-word phrase)

**es** (1):
- `plataforma rebajada` (multi-word phrase)

**fr** (1):
- `plateau surbaissé` (multi-word phrase)

**it** (1):
- `semirimorchio ribassato` (multi-word phrase)

**nl** (3):
- `dieplader` (single word ≥6 chars (9))
- `diepbed` (single word ≥6 chars (7))
- `laagbedoplegger` (single word ≥6 chars (15))

**no** (3):
- `lavlaster` (single word ≥6 chars (9))
- `senkevogn` (single word ≥6 chars (9))
- `lavbygget` (single word ≥6 chars (9))

**pl** (2):
- `platforma niskopodwoziowa` (multi-word phrase)
- `laweta` (single word ≥6 chars (6))

**ro** (3):
- `platformă joasă` (multi-word phrase)
- `trailer surbasat` (multi-word phrase)
- `semiremorcă joasă` (multi-word phrase)

**sv** (3):
- `låglastare` (single word ≥6 chars (10))
- `sänkvagn` (single word ≥6 chars (8))
- `lågbyggd` (single word ≥6 chars (8))

### `mission_module`  (kept: 20, dropped: 11)

**cs** (2):
- `mísní modul` (multi-word phrase)
- `mobilní kontejner` (multi-word phrase)

**da** (1):
- `mobil container` (multi-word phrase)

**en** (1):
- `mobile container` (multi-word phrase)

**es** (2):
- `módulo misión` (multi-word phrase)
- `contenedor móvil` (multi-word phrase)

**fi** (3):
- `johtopaikkakontti` (single word ≥6 chars (17))
- `levitettävä kontti` (multi-word phrase)
- `komentopaikkakontti` (single word ≥6 chars (19))

**fr** (2):
- `module mission` (multi-word phrase)
- `conteneur mobile` (multi-word phrase)

**it** (1):
- `container mobile` (multi-word phrase)

**nl** (2):
- `missiemodule` (single word ≥6 chars (12))
- `mobiele container` (multi-word phrase)

**no** (1):
- `oppdragsmodul` (single word ≥6 chars (13))

**pl** (2):
- `moduł misji` (multi-word phrase)
- `kontener mobilny` (multi-word phrase)

**ro** (2):
- `modul misiune` (multi-word phrase)
- `container mobil` (multi-word phrase)

**sv** (1):
- `uppdragsmodul` (single word ≥6 chars (13))

**Dropped** (11):
- 11× already in settings

### `semitrailer`  (kept: 18, dropped: 7)

**cs** (3):
- `návěs` (borderline single word (5 chars))
- `přívěs návěsový` (multi-word phrase)
- `tahačový přívěs` (multi-word phrase)

**da** (1):
- `sættevogn` (single word ≥6 chars (9))

**es** (2):
- `tráiler articulado` (multi-word phrase)
- `plataforma` (single word ≥6 chars (10))

**fr** (2):
- `remorque articulée` (multi-word phrase)
- `attelage` (single word ≥6 chars (8))

**it** (2):
- `rimorchio articolato` (multi-word phrase)
- `bilico` (single word ≥6 chars (6))

**nl** (1):
- `oplegger` (single word ≥6 chars (8))

**no** (1):
- `påhengsvogn` (single word ≥6 chars (11))

**pl** (2):
- `przyczepa siodłowa` (multi-word phrase)
- `półprzyczepa` (single word ≥6 chars (12))

**ro** (3):
- `semiremorcă` (single word ≥6 chars (11))
- `remorcă articulată` (multi-word phrase)
- `trailer articulat` (multi-word phrase)

**sv** (1):
- `påhängsvagn` (single word ≥6 chars (11))

**Dropped** (7):
- 7× already in settings

### `special_purpose`  (kept: 66, dropped: 0)

**cs** (6):
- `přepravník tanků` (multi-word phrase)
- `tankový přívěs` (multi-word phrase)
- `přívěs pro tanky` (multi-word phrase)
- `speciální přívěs` (multi-word phrase)
- `záchranný přívěs` (multi-word phrase)
- `zvláštní účel` (multi-word phrase)

**da** (6):
- `kampvognstransporter` (single word ≥6 chars (20))
- `panserkøretøjstransporter` (single word ≥6 chars (25))
- `tanktransport` (single word ≥6 chars (13))
- `specialvogn` (single word ≥6 chars (11))
- `bjærgningsvogn` (single word ≥6 chars (14))
- `særligt formål` (multi-word phrase)

**de** (4):
- `panzertransporter` (single word ≥6 chars (17))
- `kampfpanzertransporter` (single word ≥6 chars (22))
- `panzeranhänger` (single word ≥6 chars (14))
- `sonderanhänger` (single word ≥6 chars (14))

**en** (5):
- `tank transporter` (multi-word phrase)
- `tank carrier` (multi-word phrase)
- `armored vehicle transporter` (multi-word phrase)
- `special purpose` (multi-word phrase)
- `specialized trailer` (multi-word phrase)

**es** (6):
- `portacarros` (single word ≥6 chars (11))
- `transporte de blindados` (multi-word phrase)
- `góndola militar` (multi-word phrase)
- `remolque especial` (multi-word phrase)
- `remolque recuperación` (multi-word phrase)
- `propósito especial` (multi-word phrase)

**fr** (4):
- `transport de char` (multi-word phrase)
- `remorque porte-blindés` (multi-word phrase)
- `remorque dépannage` (multi-word phrase)
- `usage spécial` (multi-word phrase)

**it** (6):
- `trasporto carri` (multi-word phrase)
- `rimorchio portacarri` (multi-word phrase)
- `trasporto blindati` (multi-word phrase)
- `rimorchio speciale` (multi-word phrase)
- `rimorchio soccorso` (multi-word phrase)
- `uso speciale` (multi-word phrase)

**nl** (6):
- `tanktransporter` (single word ≥6 chars (15))
- `pantservoertuig transporter` (multi-word phrase)
- `tanktrailer` (single word ≥6 chars (11))
- `speciale trailer` (multi-word phrase)
- `bergingstrailer` (single word ≥6 chars (15))
- `speciaal doel` (multi-word phrase)

**no** (6):
- `stridsvogntransport` (single word ≥6 chars (19))
- `panserkjøretøytransport` (single word ≥6 chars (23))
- `tanktransportør` (single word ≥6 chars (15))
- `spesialhenger` (single word ≥6 chars (13))
- `bergingshenger` (single word ≥6 chars (14))
- `spesielt formål` (multi-word phrase)

**pl** (5):
- `transporter czołgów` (multi-word phrase)
- `laweta czołgowa` (multi-word phrase)
- `przyczepa do transportu czołgów` (multi-word phrase)
- `przyczepa ratownicza` (multi-word phrase)
- `cel specjalny` (multi-word phrase)

**ro** (6):
- `transportor tanc` (multi-word phrase)
- `remorcă pentru tancuri` (multi-word phrase)
- `platformă blindate` (multi-word phrase)
- `remorcă specială` (multi-word phrase)
- `remorcă salvare` (multi-word phrase)
- `scop special` (multi-word phrase)

**sv** (6):
- `stridsvagnstransport` (single word ≥6 chars (20))
- `pansarfordonssläp` (single word ≥6 chars (17))
- `tanktransportör` (single word ≥6 chars (15))
- `specialsläp` (single word ≥6 chars (11))
- `bärgningssläp` (single word ≥6 chars (13))
- `särskilt ändamål` (multi-word phrase)


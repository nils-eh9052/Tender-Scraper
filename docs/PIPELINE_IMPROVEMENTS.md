# Pipeline Improvements — Recherche & Priorisierung

Erstellt: 2026-05-05
Auftraggeber: BPW Defence
Pipeline-Stand: 256 Tender, 8 aktive Quellen, 21 nationale Adapter, 100 Awarded / 156 Closed-Unknown

Dieses Dokument vergleicht acht potenzielle Verbesserungen für die TED-Defence-Pipeline. Ziel ist eine fundierte Priorisierung — pro Thema werden Status quo, Vorschlag, Aufwand, laufende Kosten, Impact und Risiken bewertet. Pricing-Angaben sind, soweit möglich, von offiziellen Provider-Seiten zitiert; bei Unsicherheit als "Schätzung, zu validieren" gekennzeichnet.

---

## 1) OCR-Upgrade für gescannte PDFs

**Status quo:** `src/fulltext_fetcher.py` (Zeilen 187–220) lädt PDFs aus TED und nutzt `pdfplumber.open(...).extract_text()` als Fallback. Bei gescannten PDFs (häufig bei DE-Bund, IT, ES, RO-Behörden) liefert pdfplumber leeren oder fragmentarischen Text. `src/national_scraper/adapters/cz_adapter.py:410` macht dasselbe via pypdf — gleiche Schwäche. Resultat: Awarded-Winner und Stückzahlen aus Award-Notice-PDFs werden im Enrichment-Schritt nicht erfasst.

**Vorschlag:** Bei leerem pdfplumber-Output zweistufiger Fallback. Stufe 1: Mistral OCR API (kommerziell günstigster SOTA-Provider, gute Tabellen-Erkennung, akzeptiert PDF nativ). Stufe 2 (nur bei Mistral-Fehlschlag oder Sprachproblemen): Claude Sonnet 4.6 mit PDF-Document-Block — die Pipeline nutzt Anthropic ohnehin schon (Klassifikation, Enrichment), also keine neue Kreditkarte nötig.

**Empfohlenes Tool/Provider:** **Mistral OCR API** als Primary, **Claude Sonnet PDF Vision** als Backup. Mistral OCR ist mit USD 2/1.000 Seiten (Standard) bzw. USD 1/1.000 Seiten (Batch) konkurrenzlos günstig, unterstützt Tabellen und multilinguale Dokumente (inkl. Kyrillisch, Griechisch, Türkisch). Claude Sonnet als Backup, weil bereits integriert und für komplexere Layout-Reasoning-Cases (z. B. Award-Tabellen mit Mehrfach-Lots) qualitativ überlegen.

**Aufwand:** 8h MVP (Mistral-Wrapper in `enricher.py`, Fallback-Trigger bei `len(text.strip()) < 200`), +1 Tag Polish (Caching wie bei `data/cache/notice_jsons/`, Token-Budget pro Tender, Retry-Logic).

**Laufende Kosten:**
- Mistral OCR: USD 2 / 1.000 Seiten Standard, USD 1 / 1.000 Seiten Batch.
- Claude Sonnet 4.6 für PDF Vision: USD 3 In / USD 15 Out pro 1M Tokens. Eine PDF-Seite = ~1.500–3.000 Tokens (Anthropic-Dokumentation).
- Annahme: 50 PDF-Seiten/Monat fallback-OCR-pflichtig (ca. 20 % der gescannten Tender). Mit Mistral Batch: USD 0,05/Monat. Mit Claude Sonnet Backup für 10 % der OCR-Fälle (5 Seiten × 3.000 Tokens × USD 3/1M): USD 0,05/Monat. **Gesamt ~USD 0,10–0,30/Monat.**

**Impact:** **Mittel.** Bringt geschätzt 10–20 zusätzlich auswertbare Award-PDFs (Winner, Stückzahl, Lot-Werte) ins Quality-Review. Direkter Hebel auf "156 Closed/Unknown → mehr Awarded" gemeinsam mit Thema 5.

**Risiken & Voraussetzungen:**
- Mistral-AI ist französisch (EU/DSGVO-konform) — für Defence unkritisch.
- Mistral-Latenz typ. 2–5 Sek/Seite, bei Batch bis zu mehrere Stunden.
- Anthropic ZDR (Zero Data Retention) ist bereits aktiv für Files-API.
- Edge-Case: handgeschriebene Annotationen oder Stempel — beide Provider mit Schwächen, manuelles Review bleibt nötig.

---

## 2) Premium Tender-Aggregator-Dienste (Coverage-Boost)

**Status quo:** Pipeline scraped TED, UK Contracts Finder + 13 nationale Portale direkt. Coverage-Lücken: nordische Verteidigungs-Subportale (z. B. Försvarets Materielverk SE), polnische Wojsko-Direktbeschaffung, NATO-Direkt-RFPs, NSPA. 256 Tender für 18 Monate Defence-Trailer-Beschaffung in Europa wirken plausibel, aber knapp.

**Vorschlag:** Trial-basiert ausprobieren, dann ggf. eine Quelle ergänzen:

- **Mercell** (Skandinavien-Fokus): "Europas größte Coverage öffentlicher Geschäftsmöglichkeiten". Aggregiert TED + Norwegen + Dänemark + Niederlande + Deutschland + UK. **Pricing nicht öffentlich, Sales-Demo nötig**, Schätzung auf Marktbasis EUR 1.500–4.500/Jahr für Single-User-Suchprofil (zu validieren). Keine offizielle dokumentierte Public-API; Daten via UI-Export oder Enterprise-Feed.
- **dgMarket** (Development-Bank-fokussiert, World-Bank-/EBRD-finanzierte Projekte): kostenfreier Web-Zugang, eingeschränkte API. **Defence-Relevanz gering**, eher Infrastruktur/Logistik in Drittstaaten.
- **GlobalTenders.com**: USD 399/Monat (monatlich) bzw. USD 334/Monat (jährlich) für Premium-Subscription. Coverage global, inkl. US/India Defence. Keine API erkennbar (UI-driven).
- **NATO NCIA / NSPA ePortal**: kostenfrei, aber Login-pflichtig für Bid; öffentliche Liste laufender Opportunities (>EUR 80.000) auf [ncia.nato.int](https://www.ncia.nato.int/business/procurement/current-opportunities) und [eportal.nspa.nato.int](https://eportal.nspa.nato.int). Keine offizielle API — Adapter müsste HTML scrapen. Schätzung 1–2 Tage für Adapter.
- **Janes Defence Procurement Intelligence**: Premium-Preis. UK MoD hat 2026 einen Bridging-Year-Vertrag bis GBP 17,5M gezeichnet — Einzelplatz Janes Defence/Intelligence Review startet ab GBP 666/Jahr. Enterprise-API mit Parquet/RDBMS-Delivery vermutlich im 5-stelligen GBP-Bereich/Jahr (Schätzung, zu validieren mit Janes-Sales).
- **Visible Procurement**: keine etablierte Marktposition gefunden, vermutlich Nischenanbieter — niedrige Priorität.
- **Sourcing-Tribe**: keine eindeutigen Treffer in der Recherche — vermutlich nicht aktiv/relevant.

**Empfohlenes Tool/Provider:** **NSPA ePortal-Scraper-Adapter** (kostenfrei, hoher Defence-Fit) als Quick Win. **Mercell-Trial** parallel als Coverage-Test, falls BPW kommerzielles Budget hat. **Janes nur**, wenn Intelligence-Reports (Markt/Wettbewerber) explizit gewünscht — sonst Overkill.

**Aufwand:**
- NSPA-Adapter: 1–2 Tage (Playwright-basiert, RFP-Liste paginieren, in `national_scraper/adapters/nspa_adapter.py`).
- Mercell-Eval: 4h für Trial-Account + manueller Coverage-Test gegen aktuelle 256.
- Janes-API-Integration: nicht empfohlen ohne Pricing-Klärung.

**Laufende Kosten:**
- NSPA-Adapter: 0 USD.
- Mercell: ~USD 150–400/Monat (Schätzung, zu validieren mit Mercell-Sales).
- GlobalTenders: USD 334/Monat — **nicht empfohlen**, Defence-Coverage zu generisch.
- Janes: vermutlich USD 1.000+/Monat für API-Zugang (Schätzung, zu validieren).

**Impact:** **Mittel** für NSPA (5–15 Defence-Direkt-Tender/Jahr), **groß** für Mercell falls Skandinavien für BPW strategisch ist (DK/NO/SE Defence wachsen).

**Risiken & Voraussetzungen:**
- Mercell hat keine öffentlich dokumentierte API → Daten-Pull via Web-Scraping oder Enterprise-Vertrag.
- NSPA bietet keine offizielle API — HTML-Layout-Änderungen brechen Adapter (typisches Risiko, wie EE/LT bestehende Stubs zeigen).
- Janes-Lizenz ist enterprise-only und erfordert NDA.
- DSGVO/Compliance: alle drei Provider sind EU-konform.

---

## 3) Browser-as-a-Service für blockierte Adapter

**Status quo:** RO-SEAP ist VPN-blockiert (Geo-IP nur EU/RO erlaubt). EE-RH, LT-CVPP, GR-Diavgeia sind Stubs wegen CAPTCHA/Rate-Limiting. Playwright läuft lokal über `chromium_headless_shell` und scheitert ohne Geo-Routing. Aktuell 6 Stub-Adapter ohne nutzbare Daten.

**Vorschlag:** Residential-Proxy-Service mit Geo-Targeting integrieren — entweder als HTTP-Proxy für `requests`/`httpx` oder als Browser-Cloud für Playwright. Für CAPTCHA-Quellen zusätzlich Browser-as-a-Service mit Stealth-Features.

**Empfohlenes Tool/Provider:** **Bright Data Residential Proxies** (USD 4/GB Pay-as-you-go, USD 3/GB ab 332GB) als Primary für RO/EE/LT/GR. Bright Data hat dokumentierte Locations für RO und EE, mit aktuellen 50%-Coupons (RESIGB50, drei Monate). **Browserless.io Scale-Plan (USD 200/Monat, 50 concurrent browsers, ~40k Units)** als Backup für CAPTCHA-Fälle und JavaScript-Heavy-Portale.

Alternativen:
- **ScrapingBee**: Geo-Targeting erst ab Business-Tier USD 249/Monat, Credit-System verwirrend (JS = 5 Credits, Premium-Proxy bis 25 Credits) — nicht empfohlen.
- **ScrapingAnt**: Kleiner Player, weniger Geo-Coverage.
- **Playwright Cloud (Microsoft offiziell)**: Existiert nicht als eigenständiger SaaS — Microsoft pusht stattdessen Playwright auf Azure Container Apps.

**Aufwand:**
- Bright-Data-Integration in vorhandene Adapter: 1–2 Tage (Proxy-URL als Env-Variable, `playwright.chromium.launch(proxy={...})` in `national_scraper/base_adapter.py`).
- Browserless als Fallback: zusätzlich 1 Tag (replace `playwright.chromium.launch` durch `chromium.connect_over_cdp(browserless_url)`).
- Re-Aktivierung der drei Stubs (RO, EE, LT): 2–4 Tage pro Adapter, da CAPTCHA-Lösungen und Selektor-Tuning dazukommen.

**Laufende Kosten:**
- Bright Data: USD 4/GB. Schätzung: 3 Adapter × 30 Runs/Monat × 50 MB Traffic ≈ 4,5 GB/Monat = **USD 18/Monat** (Schätzung, abhängig von Crawl-Tiefe).
- Browserless Scale: USD 200/Monat (nur einsetzen, wenn häufig). MVP-Plan Starter USD 50/Monat reicht für Light-Use.
- Gesamt MVP: **USD 70/Monat** Bright Data + Browserless Starter.

**Impact:** **Groß**, falls RO/EE/LT-Defence relevant ist. Wie viele Tender in 2025/2026 aus diesen drei Ländern stammen, ist im aktuellen Datenstand 0 — Coverage-Gewinn aber strukturell wichtig (Ostflanke-Beschaffung wächst).

**Risiken & Voraussetzungen:**
- Defence-Sensitivität: BPW sollte vorher prüfen, ob residential-Proxy-Verkehr für Government-Sites compliant ist (idR. ja, da öffentliche Daten gescraped werden, aber TOS prüfen).
- Bright Data ist israelisch (Mutter Luminati Networks) — politisch wenig relevant für reine Datenbeschaffung, aber Eskalations-Vermerk wert.
- Browserless ist self-hostable — Self-Host auf BPW-Infra ist Option für Sensitivitäts-Use-Cases (kostet Engineer-Zeit).
- DSGVO: Bright Data Residential-Pool darf nur auf öffentliche Endpoints angewendet werden.

---

## 4) Embedding-basierte Deduplikation + Semantic Search

**Status quo:** `src/filter_engine.py:308` deduplicated heuristisch über base-tender-Reference (authority + Jahr) und bevorzugt Award-Notices über Announcements. Keine semantische Ähnlichkeit — Notices mit anderem Titel aber gleichem CPV+Auftraggeber+Lieferumfang werden nicht erkannt. Cache von 35.129 Notice-IDs in `data/.checkpoint.json` wäre als Embedding-Index nutzbar.

**Vorschlag:** Pro Tender ein Embedding über `title + summary + authority + cpv + winner` erzeugen, in lokaler Vektor-DB speichern. Sekundär-Use-Case: "Find similar tenders to BAAINBw 2024 …"-Frontend-Funktion. Ähnlichkeits-Threshold (Cosine ≥ 0,92) als zusätzliche Dedup-Stufe.

**Empfohlenes Tool/Provider:**
- **Embeddings: Voyage-AI voyage-4-lite** (USD 0,02 / 1M Tokens, 200M Tokens free tier). Voyage gehört zu MongoDB, Daten-Residenz US — alternativ **OpenAI text-embedding-3-small** (USD 0,02 / 1M Tokens, USD 0,01 mit Batch) wenn schon Anthropic-vergleichbar verbreitet. Cohere Embed v4 (USD 0,12 / 1M, multimodal) ist 6x teurer — nicht empfohlen für reinen Text.
- **Vektor-DB: pgvector auf bestehender Postgres-Instanz**, falls vorhanden. Sonst **Qdrant Cloud** (USD 65/Monat ab 10M Vektoren) oder **Qdrant Self-Hosted** (USD 30–50/Monat auf VPS, 8 GB RAM). Pinecone ist 2× teurer und bietet keinen Mehrwert für 256–35.000 Vektoren. Chroma local-only ist für PoC ok, aber kein Multi-User.

**Aufwand:** 2–3 Tage MVP. Phase 1: One-shot-Embedding-Skript für alle 256 Tender (`scripts/embed_tenders.py`). Phase 2: Integration in `filter_engine.py` als zweite Dedup-Stufe. Phase 3: Frontend-Endpoint `GET /api/tenders/{id}/similar`.

**Laufende Kosten:**
- Initial-Embedding 256 Tender × ~500 Tokens ≈ 128k Tokens → kostenfrei (200M Free Tier Voyage).
- Initial-Embedding 35.129 cached notice-jsons × ~800 Tokens ≈ 28M Tokens → kostenfrei in Voyage Free Tier.
- Monthly-Run für ~50 neue Tender × 500 Tokens ≈ 25k Tokens → 0,0005 USD/Monat.
- Vektor-DB: USD 0/Monat (pgvector auf bestehendem Server) oder USD 30–65/Monat (Qdrant managed).

**Impact:** **Mittel** für Dedup (geschätzte 5–15 zusätzliche Duplikat-Treffer aus den 35k cached). **Groß** für Frontend-UX (Similar-Tender-Empfehlungen sind ein Wow-Feature für Sales/BD-User).

**Risiken & Voraussetzungen:**
- Voyage-AI Daten-Residenz US — DSGVO-Bewertung nötig (Tender-Daten sind aber öffentlich).
- Cosine-Threshold-Tuning bringt False-Positives bei Frame Agreements mit ähnlichen Titeln.
- Embedding-Modell-Wechsel later (z. B. Voyage 4 → Voyage 5) erfordert Re-Embedding aller Vektoren.
- pgvector setzt voraus, dass BPW eine Postgres-Instanz hostet — sonst Qdrant Cloud.

---

## 5) Award-Match-LLM-Upgrade

**Status quo:** `src/award_matcher.py` matcht Award-Notices an ihre ursprüngliche Ausschreibung über Heuristiken (authority + CPV + Title-Fragmente + Datum-Window). Resultat: 100/256 als Awarded klassifiziert. Die übrigen 156 sind Status "Closed" oder "Unknown" — teilweise weil Award-Notices fehlen (legitim), teilweise weil das heuristische Match die existierende Award-Notice nicht zuordnen konnte.

**Vorschlag:** Sonnet als Reasoning-Layer für die 156 Edge-Cases. Prompt: "Hier ist die ursprüngliche Tender-Notice und alle Notices vom selben Auftraggeber im 12-Monats-Fenster — gibt es eine Award-Notice dazu? Wenn ja, welche und mit welchem Winner?". Output structured JSON `{matched: bool, award_id: str|null, winner: str|null, confidence: float}`. Heuristik bleibt First-Pass, Sonnet nur Second-Pass für Unmatched.

**Empfohlenes Tool/Provider:** **Claude Sonnet 4.6** (USD 3 In / USD 15 Out pro 1M Tokens). Opus wäre Overkill für diesen Reasoning-Task; Haiku zu schwach für mehrdeutige Title-Vergleiche.

**Schätzung Awarded-Boost:** EU-Defence-Vergabe-Quote liegt typischerweise bei 50–70 % (Quelle: TED Contract Award Notice Rate Studies). Von den 156 Closed-Tendern haben realistisch 30–50 % eine veröffentlichte Award-Notice in der Pipeline-Datenbasis (=47–78 Tender). Davon dürfte LLM-Reasoning 60–80 % korrekt zuordnen — also **+28 bis +62 zusätzliche Awarded**, plausibel ein neuer Total-Awarded zwischen 128–162. Restliche 100+ bleiben legitim Closed-ohne-Award (kleine Werte unter EU-Schwellenwert, abgebrochene Verfahren, oder Award-Notice noch nicht veröffentlicht).

**Aufwand:** 1–2 Tage (Sonnet-Wrapper, JSON-Schema, Integration in `award_matcher.py` als Fallback bei `confidence < 0.6`).

**Laufende Kosten:**
- 156 Tender × 5.000 Input-Tokens × USD 3/1M = **USD 2,34** Eingangs-Run.
- 156 Tender × 500 Output-Tokens × USD 15/1M = **USD 1,17** Eingangs-Run.
- **Initial USD 3,51, anschließend ~USD 1/Monat** für neue Edge-Cases.
- Mit Prompt-Caching auf "alle Notices vom Auftraggeber XY" sinken die Kosten um weitere 30–50 %.

**Impact:** **Groß.** Direkter Hebel auf die wichtigste Frontend-Metrik "Awarded vs Open vs Closed". 28–62 zusätzliche Awarded-Tender heißt 28–62 zusätzliche Winner-Datensätze für BPW-Marktanalyse.

**Risiken & Voraussetzungen:**
- LLM-False-Positives: ein falsch zugeordneter Winner ist schlimmer als unmatched. Confidence-Threshold ≥ 0,75 + manuelles Stichproben-Review (10 % der Matches) als Quality-Gate.
- Daten-Sensitivität: Tender-Inhalte sind öffentlich → Anthropic-Standard-API ohne ZDR ist ok.
- Kein Effekt für Tender ohne existierende Award-Notice — diese bleiben legitim Closed.

---

## 6) Defence-Keyword/CPV-Erweiterung via LLM-Brainstorm

**Status quo:** `config/settings.yaml` enthält ~30 Defence-Keywords (DE/EN) und 40+ CPV-Codes für Defence-Trailer. Liste wurde manuell kuratiert; Sprachen außerhalb DE/EN sind unterabgedeckt (nur Übersetzungen via DeepL ohne Domain-Tuning). Folge: Tender aus PL/CZ/RO/UA mit lokalem Vokabular werden vom Filter-Engine ggf. übersehen.

**Vorschlag:** One-shot Opus-Run über die 100 bekannten Awarded Defence-Tender. Prompt: "Hier ist Title + Summary + Winner. Extrahiere defence-spezifische Begriffe in DE, EN, PL, FR, IT, ES, CZ, RO/UA. Schlage Erweiterungen für die bestehende Keyword-Liste vor (Diff-Format)." Output: strukturiertes YAML-Patch, manuell von Auftraggeber reviewt, dann in `settings.yaml` gemergt.

**Schritt-für-Schritt:**
1. Skript `scripts/keyword_brainstorm.py` lädt 100 Awarded Tender aus `data/filtered/relevant.json` (gefiltert auf `is_awarded=True`).
2. Prompt-Template: System "Du bist Defence-Procurement-Linguist", User "Hier sind 100 Tender mit DE/EN/PL/CZ/etc Volltext. Extrahiere Top-50 Keywords und Top-20 CPV-Empfehlungen, gruppiert nach Sprache."
3. Opus generiert YAML-Diff-Vorschlag.
4. Manuelles Review (1h) durch Auftraggeber: ja/nein pro Eintrag, ggf. Aliasing.
5. Merge in `settings.yaml`, Testlauf `python main.py --phase filter` über Cache (kein neuer API-Run nötig), Diff der Tender-IDs.

**Empfohlenes Tool/Provider:** **Claude Opus 4.7** für die einmalige Brainstorm-Run. Opus ist bei multilingualer Domain-Expansion qualitativ deutlich überlegen, und der Run läuft nur einmal.

**Aufwand:** 1–2 h Implementierung Skript + Prompt + Run + 1–2 h Review = ~4 h gesamt.

**Laufende Kosten (One-Shot):**
- 100 Tender × 8.000 Input-Tokens × USD 15/1M (Opus 4.7) = **USD 12.**
- 100 Tender × 4.000 Output-Tokens × USD 75/1M (Opus 4.7) = **USD 30.**
- **Total ~USD 42 einmalig.** Wiederholung halbjährlich = USD 84/Jahr.

(Pricing-Hinweis: Opus 4.7 Pricing nach Anthropic Pricing-Page — Schätzung USD 15/USD 75 In/Out, zu validieren mit aktueller [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing).)

**Impact:** **Mittel-bis-groß** für Sprint 14g (Ziel 256 → 350+). Erweiterte Keywords betreffen direkt die Recall-Quote in `filter_engine.py`. Realistische Schätzung +30–80 zusätzliche Tender allein durch erweiterte Sprach-Coverage in PL/CZ/RO.

**Risiken & Voraussetzungen:**
- LLM-False-Positives bei Keywords: "armée" matcht zu generisch. Manueller Review-Step ist Pflicht.
- CPV-Vorschläge müssen gegen offizielle EU-CPV-Tabelle validiert werden (Opus halluziniert ggf. Codes).
- Nach Keyword-Erweiterung: vollständiger Re-Run nötig (`python main.py --phase index --since 2024-01-01`) — Token-Kosten dafür separat (Sonnet-Klassifikation).
- Für UA-Sprache: Opus hat im Pre-Training Lücken, manuelles Review besonders wichtig.

---

## 7) Winner → Company-Intelligence-Cross-Reference

**Status quo:** Awarded-Winner werden als String-Name aus Award-Notice extrahiert (z. B. "BAE Systems Hägglunds AB", "Rheinmetall MAN Military Vehicles GmbH"). Keine Anreicherung mit Mutterkonzern, Defence-Umsatzanteil, Hauptsitz, Beschäftigte. Frontend zeigt Plain-Name ohne Kontext.

**Vorschlag:** Pro Awarded Winner ein Lookup gegen externe Company-DB. Anreicherung um: parent_company, ultimate_owner, defence_revenue_segment, country_hq, employee_count.

**Empfohlenes Tool/Provider:** Stufenweise Empfehlung:

- **OpenCorporates** als Primary für Konzern-Struktur. **Pricing: ab GBP 2.250/Jahr (Essentials), GBP 6.600/Jahr (Starter), GBP 12.000/Jahr (Basic)**, Enterprise on request. Coverage Europa exzellent (200M+ Companies, ISO-Jurisdictions). Kein Defence-Spezifikum, aber Owner-Tracking.
- **D&B Direct+** für Mutterkonzern + Umsatzdaten. **Pricing nicht öffentlich**, typische Enterprise-Verträge laut Markt EUR 5.000–25.000/Jahr für API mit ~10.000 Lookups (Schätzung, zu validieren mit D&B Sales). Defence-Umsatz nicht direkt segmentiert, aber Industry-Codes und Revenue.
- **Sayari Graph**: defence-supply-chain-spezifisch ($7,8M CBP-Vertrag 2024 als Referenz), 250+ Jurisdictions, MCP-API verfügbar. **Pricing nicht öffentlich**, vermutlich USD 30k+/Jahr für Enterprise (Schätzung, zu validieren). Stärke: Sub-Tier-Networks und Sanktions-Risiko — für BPW-Hauptaufgabe (Trailer-OEM-Wettbewerber-Analyse) Overkill.
- **Crunchbase**: zu Startup-fokussiert, schlechte Coverage europäische Defence-Mittelständler — **nicht empfohlen.**

**Pragmatischer Stack:** OpenCorporates Essentials (~EUR 2.300/Jahr) + manuelle Anreicherung der 20 Top-Winner mit BPW-internem Wissen. Sayari/D&B nur, falls BPW-Procurement-Compliance-Use-Case (Sanktionen, UFLPA) relevant wird.

**Frontend-Nutzwert:** User sieht statt "Patria Land Oy" zusätzlich:
- Mutterkonzern: Patria Plc (FI, Mehrheit Staat)
- HQ: Helsinki, Finnland
- Mitarbeiter: ~3.300
- Defence-Anteil Umsatz: >70 %
- Sanktions-Status: clean
- Vergangene BPW-Awards (sofern in Pipeline-DB): X Tender, Y Mio EUR

**Aufwand:** 2–4 Tage (OpenCorporates-Wrapper + Caching in `data/cache/companies/` + Mapping-Script Winner→OC-Company-ID + Frontend-Felder).

**Laufende Kosten:**
- OpenCorporates Essentials: **GBP 2.250/Jahr ≈ USD 220/Monat** (Schätzung Wechselkurs).
- Caching reduziert API-Calls drastisch; 100 Awarded × 1–2 Lookups = 200 Calls einmalig, dann Cache-Hits.
- D&B / Sayari: nicht empfohlen für MVP.

**Impact:** **Mittel.** Frontend-UX-Boost spürbar, aber kein direkter Coverage-Gewinn. Hilft beim Sales-Pitch und bei Konzern-Struktur-Übersicht (Rheinmetall AG ↔ KMW+Nexter Defense Systems ↔ KNDS).

**Risiken & Voraussetzungen:**
- OpenCorporates zählt jeden API-Call — auch erfolglose. Aggressives Caching nötig.
- Name-Matching ist nicht trivial: "Rheinmetall" matcht 47 Entities, korrekte Auswahl braucht Country + Type-Filter.
- D&B und Sayari sind ohne Sales-Engagement kaum testbar — Trial-Anfrage langwierig.
- DSGVO unkritisch (Company-Data, keine Personen-Daten).

---

## 8) Webhook / Alert-System

**Status quo:** Pipeline läuft per `python main.py --all`, Output ist Excel-File in `data/export/`. Kein aktiver Push — Auftraggeber muss Excel manuell öffnen. Keine "Hot-Tender"-Benachrichtigung.

**Vorschlag:** Am Ende der Pipeline (`main.py` nach `--phase export`) Filter-Logic auf neue Tender mit `(status=Open AND quantity≥X AND value≥Y_EUR)` und Push via Webhook an Microsoft Teams oder Slack. Konfiguration der Schwellen in `config/settings.yaml`.

**Empfohlenes Tool/Provider:** **Microsoft Teams Workflows Webhook** (Power Automate Incoming Webhooks). BPW als M365-Tenant-Kunde nutzt vermutlich Teams als Default-Collaboration-Tool. **Wichtig:** Microsoft hat klassische Teams Connector Webhooks deprecated (Migration bis 31. März 2026 abgeschlossen) — neue Integrationen müssen via **Power Automate Workflow** mit "When a Teams webhook request is received"-Trigger laufen.

Falls BPW Slack nutzt, Slack Incoming Webhooks sind ähnlich einfach (eine URL, JSON-POST). Beide kostenfrei für interne Nutzung.

**Aufwand:** 4–6 h MVP. `src/notifier.py` mit `requests.post(WEBHOOK_URL, json=card_payload)`. Adaptive-Card-Format für Teams (Title, Tender-ID, Authority, Value, CPV, Link). Einbindung als Post-Export-Hook in `main.py`. Plus 1–2 h für BPW-Setup des Teams-Workflows.

**Laufende Kosten:** **0 USD.** Webhooks sind Bestandteil der bestehenden M365-Lizenzen.

**Impact:** **Mittel-bis-groß** für die User-Adoption. Ein wöchentlicher Pipeline-Run mit 0–3 neuen Hot-Tendern per Teams-Push ist wesentlich relevanter im Tagesgeschäft als ein 256-Zeilen-Excel.

**Risiken & Voraussetzungen:**
- BPW muss Teams Workflow-Webhook-URL bereitstellen (5 Min Setup durch BPW-IT).
- Rate-Limit Teams: max 4 Requests/Sek, Message-Size max 28 KB — bei normalen Run-Volumes irrelevant.
- Schwellen-Tuning iterativ: zu niedrig → Spam, zu hoch → keine Pushes.
- Falls Slack vorgezogen wird: Slack-App-Setup ist 10 Min, JSON-Schema leicht anders.

---

## Vergleichstabelle

| # | Thema | Aufwand | Laufende Kosten/Monat | Impact | Score Impact/Aufwand |
|---|---|---|---|---|---|
| 1 | OCR-Upgrade (Mistral + Sonnet PDF) | 1–1,5 Tage | ~USD 0,30 | Mittel | **Hoch** |
| 2 | Premium-Aggregator (NSPA-Adapter) | 1–2 Tage | USD 0 | Mittel | **Hoch** |
| 2b | Premium-Aggregator (Mercell Trial) | 4 h Eval | ~USD 150–400 (Schätzung) | Mittel-Groß | Mittel |
| 3 | Browser-as-a-Service (Bright Data + Browserless) | 3–5 Tage | ~USD 70 | Groß | Mittel |
| 4 | Embedding-Dedup + Semantic Search (Voyage + pgvector) | 2–3 Tage | USD 0–65 | Mittel-Groß | Mittel |
| 5 | Award-Match-LLM-Upgrade (Sonnet) | 1–2 Tage | ~USD 1–5 | **Groß** | **Sehr hoch** |
| 6 | Keyword-Brainstorm (Opus One-Shot) | ~4 h | USD 0 (USD 42 einmalig) | Mittel-Groß | **Sehr hoch** |
| 7 | Winner Company-Intelligence (OpenCorporates) | 2–4 Tage | ~USD 220 | Mittel | Niedrig-Mittel |
| 8 | Webhook/Alert-System (Teams Workflow) | 4–6 h | USD 0 | Mittel-Groß | **Sehr hoch** |

Score-Lesehilfe: **Sehr hoch** = großer Hebel bei minimalem Aufwand und Kosten — Quick Wins. **Hoch** = lohnt sich klar. **Mittel** = strategisch wertvoll, aber teurer/aufwändiger. **Niedrig-Mittel** = nice-to-have.

---

## TOP-3-Empfehlung

1. **Award-Match-LLM-Upgrade (Thema 5).** 1–2 Tage Aufwand, ~USD 3,50 einmalig + USD 1/Monat, schätzungsweise +28 bis +62 zusätzlich identifizierte Awarded-Tender — direkter Hebel auf die wichtigste Frontend-Metrik. Quick Win mit messbarer Daten-Qualitäts-Verbesserung.
2. **Webhook/Alert-System für Teams (Thema 8).** 4–6 h Aufwand, 0 USD/Monat, sofort spürbar in der täglichen Nutzung beim Auftraggeber. Wandelt das Excel-Artefakt in einen aktiven Daten-Service um — unverzichtbar für User-Adoption.
3. **Keyword-Brainstorm via Opus One-Shot (Thema 6).** ~4 h Aufwand, USD 42 einmalig, geschätzt +30–80 zusätzliche Tender durch verbesserte multilinguale Recall-Quote — zahlt direkt auf das Sprint-14g-Ziel "256 → 350+ Tender" ein und kostet praktisch nichts.

Diese drei Maßnahmen lassen sich in <1 Woche umsetzen, kosten zusammen ~USD 50 einmalig + ~USD 1–6/Monat laufend, und adressieren die drei wichtigsten Schwachstellen: Daten-Qualität (Awarded-Quote), User-Adoption (Push statt Pull), Coverage (Recall in Nicht-DE/EN-Sprachen).

Themen 1 (OCR), 4 (Embeddings) und 3 (Browser-as-a-Service) sind die nächsten logischen Schritte für Sprint 15+. Thema 7 (Company-Intelligence) und 2b (Mercell) sind Premium-Add-Ons, die erst nach Klärung des kommerziellen Budgets sinnvoll werden.

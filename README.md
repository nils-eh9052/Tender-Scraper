# TED Defence Trailer Scraper

Automated pipeline for discovering and analyzing defence procurement notices
related to military trailers across Europe, NATO, and allied nations.

## Overview

- **219 confirmed defence trailer procurements** across **24 countries**
- **23 data sources**: TED (EU), UK Contracts Finder, and 21 national portals
- **AI-powered classification** using Claude Sonnet with Haiku pre-filter
- **23-column Excel output** with EUR-normalized values

## Quick Start

### Prerequisites
- Python 3.10+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Playwright browsers (`playwright install chromium`)

### Installation
```bash
git clone https://github.com/nils-eh9052/Tender-Scraper.git
cd Tender-Scraper
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Edit .env: add your ANTHROPIC_API_KEY
```

### Usage
```bash
# Full run — all sources, AI classification, enrichment, export
python main.py --all --national se no cz fr dk nl es it ch gb ua ee lv lt --uk --canada --two-stage

# Test run (limited AI calls, ~$0.10)
python main.py --all --test

# Only re-export existing data (no API calls)
python main.py --phase export

# Incremental update (only new notices since last run)
python main.py --all --incremental --two-stage

# Specific national portals only
python main.py --national cz fr se

# Skip enrichment (faster, less complete)
python main.py --all --no-enrich

# Skip Opus quality review
python main.py --all --no-review
```

### Output
Excel file in `data/export/` with 23 columns:

| Column | Description |
|--------|-------------|
| Tender ID | Unique identifier (TED number or national ID) |
| Title | English title |
| Country | Full country name |
| Authority | Procuring organization |
| Publication Date | YYYY-MM-DD |
| Status | Open / Awarded / Closed / Unknown |
| Est. Value / Currency / Est. Value (EUR) | Original + EUR-converted value |
| Trailer Type (1) / Category (1) / Quantity (1) | Primary trailer |
| Trailer Type (2) / Category (2) / Quantity (2) | Second trailer (multi-lot) |
| Additional Equip. / Additional Qty | Non-trailer items |
| Contract Duration | e.g., "48 months" |
| Winner | Awarded company |
| Source URL (TED) | Link to TED notice |
| Description | English summary |
| Source | Data source (TED, UK-CF, CZ-NEN, FR-BP, etc.) |
| Source URL (National) | Link to national portal |

## Architecture

```
TED API (16+ queries)  ──┐
UK Contracts Finder     ──┤
National Portals (21)   ──┤──→ Filter + Score ──→ AI Classify ──→ Enrich ──→ Export
CanadaBuys Open Data    ──┘    (~36k notices)     (Claude Sonnet)   (Fulltext)   (Excel)
```

### Pipeline Phases
1. **Index** — Fetch notices from TED API + national portals (parallel)
2. **Filter** — Defence filter + relevance scoring (cached, <20 sec warm)
3. **Classify** — AI classification with Haiku pre-filter + Sonnet (cached)
4. **Enrich** — Fulltext download + PDF extraction + Award matching
5. **Export** — Excel with blacklist, manual overrides, force-includes
6. **Review** — Automated Opus QA (finds duplicates, FPs, category errors)

## Data Sources

| Source | Country / Region | Method | Auth Required |
|--------|-----------------|--------|---------------|
| TED API | All EU + EEA | REST API | No |
| UK Contracts Finder | UK | REST API | No |
| UK Find a Tender (FTS) | UK | REST API (OCDS) | No |
| Czech NEN (NIPEZ) | CZ | Playwright | No |
| French BOAMP | FR | REST API | No |
| Swedish Kommersannons | SE | Requests | No |
| Norwegian Doffin | NO | REST API | No |
| Danish Udbud.dk | DK | Playwright | No |
| Dutch TenderNed | NL | REST API | No |
| Spanish PLACE | ES | Playwright | No |
| Italian ANAC | IT | REST + Playwright | No |
| Swiss simap.ch | CH | REST API | No |
| Ukrainian Prozorro | UA | REST API | No |
| Estonian riigihanked | EE | XML Bulk | No |
| Latvian IUB | LV | REST API | No |
| Lithuanian CVPP | LT | Playwright | No |
| German evergabe-online | DE | Playwright | Optional |
| German service.bund.de | DE | Playwright | No |
| Belgian e-Procurement | BE | Playwright | No |
| Polish BZP | PL | Playwright | No |
| Romanian SEAP | RO | Playwright | No |
| Finnish Hilma | FI | REST API | No |
| CanadaBuys Open Data | CA | CSV Download | No |

## Trailer Categories

Low-Bed, Semitrailer, Dolly, Tank Trailer, Mission Module, Loading System,
Special Purpose, Ammunition Trailer, Field Kitchen, Cargo Trailer, Other

## Cost Structure

| Mode | AI Cost | Speed |
|------|---------|-------|
| Full run (cold cache) | ~$5–8 | ~45 min |
| Full run (warm cache) | ~$1–3 | ~25 min |
| Incremental (weekly) | ~$0.10 | ~5 min |
| Opus review | ~$0.50 | +2 min |
| `--batch` mode | 50% off | async |

## Configuration

| File | Purpose |
|------|---------|
| `config/settings.yaml` | CPV codes, keywords, scoring, API settings |
| `config/blacklist.json` | Permanently excluded tender IDs |
| `config/manual_overrides.json` | Manual category corrections |
| `config/force_include.json` | TED IDs that must always be fetched |
| `config/national_force_include.json` | National IDs preserved across runs |
| `Vorlage.xlsx` | Excel template (Sheet: "Scraper Data") |

## Adding a New Country Adapter

See [docs/ADDING_ADAPTERS.md](docs/ADDING_ADAPTERS.md) for a step-by-step guide.

## License

Proprietary — Stern Stewart & Co. / BPW Defence

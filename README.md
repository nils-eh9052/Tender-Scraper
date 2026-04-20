# TED Defence Trailer Scraper

## Download Latest Data

**[-> Download current Excel](data/export/TED_Defence_Trailers_LATEST.xlsx)** (updated weekly, every Sunday)

The scraper runs automatically via GitHub Actions. Check the [Actions tab](../../actions) for run status.

---

Automated pipeline for discovering and analyzing EU defence procurement notices related to military trailers and trailer-based systems.

Built for defence market intelligence — identifies trailer procurements across 21+ European countries, classifies them by type and category using AI, and exports structured Excel reports.

## What it does

1. **Searches** the EU's TED (Tenders Electronic Daily) database via 11 targeted queries
2. **Filters** ~17,500 notices down to ~7,000 defence-relevant candidates
3. **Classifies** each notice using Claude AI — extracts trailer type, category, quantity, winner, contract duration
4. **Exports** a structured Excel workbook (21 columns, all in English, EUR-normalized values)

## Pipeline Architecture

```
TED API (11 queries) -> 17,500 notices
    |
    v
Defence Filter + Scoring -> 7,000 candidates
    |
    v
AI Classification (Claude Sonnet) -> ~137 confirmed trailer procurements
    |
    v
Excel Export -> Structured workbook with 21 columns
```

## Quick Start

### Prerequisites
- Python 3.10+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

### Installation
```bash
git clone https://github.com/YOUR_ORG/ted-defence-trailer-scraper.git
cd ted-defence-trailer-scraper
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Usage
```bash
# Test run (10 AI calls, ~$0.10)
python main.py --all --test

# Full run (~$3-4 with cache, ~45 min)
python main.py --all

# With 50% cost reduction (async, ~1h processing)
python main.py --all --batch

# Only re-export existing data (no API calls)
python main.py --phase export

# Incremental update (only new notices since last run)
python main.py --all --incremental
```

### Output
Excel file in `data/export/` with these columns:

| Column | Description |
|--------|-------------|
| Tender ID | TED notice number |
| Title | English title |
| Country | Full country name |
| Authority | Procuring organization |
| Publication Date | YYYY-MM-DD |
| Status | Open / Awarded / Closed / Unknown |
| Est. Value + Currency | Original value |
| Est. Value (EUR) | EUR-converted (fixed FX rates) |
| Trailer Type (1) + Category (1) + Quantity (1) | Primary trailer |
| Trailer Type (2) + Category (2) + Quantity (2) | Second trailer type (if multi-lot) |
| Additional Equipment + Qty | Non-trailer items in same procurement |
| Contract Duration | e.g., "48 months" |
| Winner | Awarded company |
| TED URL | Direct link to notice |
| Description | English summary (max 500 chars) |

## Trailer Categories

Low-Bed, Semitrailer, Dolly, Tank Trailer, Mission Module, Loading System, Special Purpose, Ammunition Trailer, Field Kitchen, Cargo Trailer, Other

## Configuration

- `config/settings.yaml` — CPV codes, keywords, scoring weights, API settings
- `config/force_include.json` — Manually curated tender IDs that must always be fetched
- `Vorlage.xlsx` — Excel template

## Cost Structure

| Mode | Cost | Speed |
|------|------|-------|
| Full run (first time) | ~$3-4 | ~45 min |
| Full run (cached) | ~$0 | ~5 min |
| `--batch` mode | 50% off | ~1h async |
| `--two-stage` (Haiku pre-filter) | ~$1-2 | ~30 min |
| Incremental (weekly) | ~$0.10 | ~2 min |

## License

Proprietary — Stern Stewart & Co. / BPW Defence

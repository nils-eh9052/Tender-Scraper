# Adding a New Country Adapter

This guide explains how to add a new national procurement portal to the scraper.

## Prerequisites

- Identify the portal URL and search mechanism (REST API, HTML form, SPA)
- Know the defence authority names in the local language
- Have trailer-related keywords in the local language
- Verify the portal is publicly accessible (or credentials available)

## Step 1: Create the Adapter File

Create `src/national_scraper/adapters/{cc}_adapter.py` where `{cc}` is the
ISO-2 country code (lowercase).

```python
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

def create_{cc}_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Country Name",
        country_code="CC",
        source_code="CC-XX",        # Unique source identifier
        base_url="https://...",
        search_url="https://.../search",
        language="xx",
        trailer_keywords=[
            "local_word_for_trailer",
            "local_word_for_semitrailer",
            # ...
        ],
        defence_authorities=[
            "Ministry of Defence in local language",
            # ...
        ],
    )

class CCAdapter(BaseAdapter):
    def search(self, keyword, max_results=50):
        # Implement search logic
        # Return list of SearchResult
        pass

    def get_detail(self, result):
        # Implement detail fetching
        # Return NoticeDetail or None
        pass
```

## Step 2: Register the Adapter

In `src/national_scraper/adapters/__init__.py`, add:
```python
from .{cc}_adapter import CCAdapter, create_{cc}_config
```

In `main.py`, add to the adapter registry and to the `--national` choices in argparse.

## Step 3: Add Keywords to settings.yaml

Under `keywords:`, add trailer terms in the new language.

## Step 4: Test

```bash
# Discovery (visible browser)
python main.py --national cc --test --visible

# Full run
python main.py --national cc
```

## Step 5: Credentials (if needed)

Add to `.env`:
```
CC_PORTAL_USERNAME=...
CC_PORTAL_PASSWORD=...
```

Use `CredentialManager.get("CC_PORTAL")` in the adapter.

## Tips

- **REST API > Playwright** — always prefer API if available (faster, more reliable)
- **XHR interception** — for SPAs, use browser DevTools Network tab to find hidden APIs
- **Rate limiting** — minimum 1–2 seconds between requests to government portals
- **Resilience** — use `RetrySession` from `src/national_scraper/resilience.py`
- **Dedup with TED** — national notices already on TED get merged automatically via `tender_id`
- **filter_defence()** — implement AND logic: both trailer keyword AND defence authority must match

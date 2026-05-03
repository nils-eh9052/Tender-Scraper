# Security Notes

## SSL Verification

The environment variable `SSL_VERIFY_DISABLE=1` disables TLS certificate
verification for all HTTP requests. This is required when running behind
a corporate VPN/proxy that performs SSL interception.

**Remove this setting** when running outside the corporate network:
```bash
# In .env — comment out or delete:
# SSL_VERIFY_DISABLE=1
```

## API Keys

All API keys are loaded from environment variables (`.env` file).
Never commit `.env` to version control — it is listed in `.gitignore`.

## Portal Credentials

UK DSP and DE evergabe credentials are stored in `.env` as:
```
UK_DSP_USERNAME=...
UK_DSP_PASSWORD=...
DE_EVERGABE_USERNAME=...
DE_EVERGABE_PASSWORD=...
```

These are only used when the respective adapters run. No credentials
are transmitted to any third party except the target portal.

## Data Storage

- `data/filtered/relevant.json` — structured tender data, no credentials
- `data/.enrichment_log.json` — AI response cache, no credentials
- `data/raw/details/*.json` — raw TED API responses, public data

None of these files contain credentials and all are gitignored (except `.gitkeep` markers).

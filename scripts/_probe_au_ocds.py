"""
AusTender OCDS API — Token-Probe

Versucht, die API ohne Authentication-Header abzufragen.
Schreibt Ergebnis nach docs/AU_OCDS_API_PROBE.md.

Run: python scripts/_probe_au_ocds.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API_BASE = "https://api.tenders.gov.au/ocds"
UA = "TenderRadar/1.0 (BPW Defence; contact: mrosenfeld@sternstewart.com)"

PROBE_ENDPOINTS = [
    {
        "label": "findByDates/contractPublished — 2026-01-01 → 2026-05-01 (no cursor)",
        "url": (
            f"{API_BASE}/findByDates/contractPublished"
            "/2026-01-01T00:00:00Z/2026-05-01T00:00:00Z"
        ),
        "params": {},
    },
    {
        "label": "findByDates/contractPublished — 2026-01-01 → 2026-05-01 (cursor='')",
        "url": (
            f"{API_BASE}/findByDates/contractPublished"
            "/2026-01-01T00:00:00Z/2026-05-01T00:00:00Z"
        ),
        "params": {"cursor": ""},
    },
    {
        "label": "findByDates/contractLastModified — last 48h",
        "url": (
            f"{API_BASE}/findByDates/contractLastModified"
            "/2026-05-09T00:00:00Z/2026-05-10T00:00:00Z"
        ),
        "params": {},
    },
]

SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in (
    "1", "true", "yes"
)


def _probe(ep: dict) -> dict:
    url = ep["url"]
    params = ep["params"]
    label = ep["label"]

    headers = {"User-Agent": UA, "Accept": "application/json"}

    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=30,
            verify=SSL_VERIFY,
        )
    except requests.RequestException as exc:
        return {
            "label": label,
            "status": "EXCEPTION",
            "detail": str(exc),
            "body_excerpt": "",
            "releases_count": None,
            "has_pagination": False,
        }

    status = resp.status_code
    body_raw = resp.text or ""

    releases_count = None
    has_pagination = False
    schema_fields: list[str] = []
    sample_release: dict = {}
    next_link = ""

    try:
        data = resp.json()
        if isinstance(data, dict):
            releases = data.get("releases") or data.get("data") or []
            if isinstance(releases, list):
                releases_count = len(releases)
                if releases:
                    sample_release = releases[0]
                    schema_fields = list(sample_release.keys())

            links = data.get("links") or {}
            next_link = links.get("next", "")
            has_pagination = bool(next_link)
    except Exception:
        pass

    return {
        "label": label,
        "status": status,
        "detail": resp.headers.get("Content-Type", ""),
        "body_excerpt": body_raw[:600],
        "releases_count": releases_count,
        "has_pagination": has_pagination,
        "next_link": next_link[:120],
        "schema_fields": schema_fields,
        "sample_release": sample_release,
    }


def _write_probe_doc(results: list[dict]) -> Path:
    lines: list[str] = [
        "# AU OCDS API Probe — Token-Status Report",
        "",
        f"> Probed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"> API Base: `{API_BASE}`",
        f"> User-Agent: `{UA}`",
        "",
        "---",
        "",
    ]

    auth_required = False
    auth_ok = False

    for r in results:
        lines.append(f"## {r['label']}")
        lines.append("")
        s = r["status"]
        if s == "EXCEPTION":
            lines.append(f"**Status:** EXCEPTION — `{r['detail']}`")
        else:
            lines.append(f"**HTTP Status:** `{s}`")
            lines.append(f"**Content-Type:** `{r['detail']}`")

        if s in (401, 403):
            auth_required = True
            lines.append("")
            lines.append(
                "**⚠️ AUTHENTICATION REQUIRED** — API verlangt einen Token."
            )
        elif s == 200:
            auth_ok = True
            lines.append(f"**Releases in Response:** {r['releases_count']}")
            lines.append(f"**Pagination (links.next):** `{r.get('next_link', '')}`")
            if r.get("schema_fields"):
                lines.append(f"**Top-Level Keys:** `{', '.join(r['schema_fields'])}`")

        if r.get("body_excerpt"):
            lines.append("")
            lines.append("**Response Excerpt:**")
            lines.append("```json")
            lines.append(r["body_excerpt"])
            lines.append("```")

        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Summary ──────────────────────────────────────────────────────────────
    lines.append("## Summary & Recommendation")
    lines.append("")
    if auth_ok and not auth_required:
        lines.append(
            "✅ **Token NOT required.** The OCDS API is publicly accessible without "
            "authentication. Proceed with adapter implementation using only the "
            f"`User-Agent: {UA}` header."
        )
        lines.append("")
        lines.append(
            "Attribution: `Source: Department of Finance, Australia (CC BY 4.0)`"
        )
    elif auth_required:
        lines.append(
            "❌ **Token IS required.** All probed endpoints returned 401/403."
        )
        lines.append("")
        lines.append("**Action required:**")
        lines.append(
            "1. E-Mail an `tenders@finance.gov.au` — Subject: "
            "\"OCDS API access for market observation (non-bidding)\""
        )
        lines.append("2. Telefon: +61 2 6215 1558 (Mo–Fr 09:00–17:00 AEST)")
        lines.append(
            "3. Fallback: Apify Actor `fortuitous_pirate/austender-scraper` "
            "(kein eigener Token benötigt)"
        )
    else:
        lines.append(
            "⚠️ **Unclear** — some endpoints succeeded, some failed. "
            "Check per-endpoint status above."
        )

    out_path = ROOT / "docs" / "AU_OCDS_API_PROBE.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main():
    print(f"Probing AusTender OCDS API: {API_BASE}")
    results = []
    for ep in PROBE_ENDPOINTS:
        print(f"  → {ep['label'][:60]}...", end=" ", flush=True)
        r = _probe(ep)
        status = r["status"]
        count = r.get("releases_count")
        print(
            f"HTTP {status}"
            + (f", {count} releases" if count is not None else "")
        )
        results.append(r)

    out = _write_probe_doc(results)
    print(f"\nReport written to: {out}")

    # Also print compact summary to stdout
    all_200 = all(r["status"] == 200 for r in results)
    any_auth = any(r["status"] in (401, 403) for r in results)
    if all_200:
        print("✅ Token NOT required — API is publicly accessible.")
    elif any_auth:
        print("❌ Token required — contact tenders@finance.gov.au")
    else:
        statuses = [r["status"] for r in results]
        print(f"⚠️  Mixed results: {statuses}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

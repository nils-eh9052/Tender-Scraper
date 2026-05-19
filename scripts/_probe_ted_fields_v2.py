"""Probe the TED v3 search API to discover field names available beyond
our current ``ALL_FIELDS`` list.

Strategy: pick a known-rich CN-Notice (e.g. 245184-2024 or 212474-2026)
and request a comprehensive candidate-field list. The API silently
ignores unknown fields, so we can request optimistically. We then dump
the keys actually returned for the notice.

Output: stdout summary + ``data/.ted_field_probe.json`` (raw response).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env so SSL_VERIFY_DISABLE works on corporate VPN
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import urllib3
_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.api_client import ALL_FIELDS  # noqa: E402

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)",
}

# Optimistic candidate-list: standard names from the TED-XML schema and the
# Cross-Reference Investigation. The API silently drops names it does not
# know — so we can shovel a generous set without harm.
CANDIDATE_FIELDS = sorted(set(ALL_FIELDS) | {
    # Buyer / portal
    "buyer-profile-url",
    "buyer-name",
    "buyer-name-part",
    "buyer-internet-address-part",
    "buyer-internet-address",
    "organisation-internet-address",
    # Tender access / submission URLs
    "tender-documents-access",
    "submit-tenders-address",
    "additional-information-address",
    "communication-language",
    # Identifiers / references
    "internal-reference",
    "internal-identifier-part",
    "notice-identifier",
    "publication-number",
    # Lot-level (per-lot value, quantity, title)
    "lot",
    "lot-id",
    "lot-title",
    "title-lot",
    "estimated-value-lot",
    "total-value-lot",
    "total-value-cur-lot",
    "quantity-lot",
    # Classification + procedure
    "classification-additional-cpv",
    "classification-cpv-lot",
    "procurement-procedure-type",
    "procurement-procedure-justification",
    "procedure-features",
    # Contract / framework specifics
    "contract-folder-id",
    "contract-duration",
    "framework-agreement",
    # Award / financial
    "tender-amount",
    "tender-amount-currency",
    "estimated-value",
    "estimated-value-currency",
    # Geography
    "place-of-performance-country-part",
    "place-of-performance-city-part",
    "place-of-performance-region-part",
    # Review / appeals
    "review-procedure-body",
    "review-deadline",
    # Time / dates
    "date-publication-direct",
    "submission-deadline-date",
    "submission-deadline-time",
    "deadline-receipt-tender-time-lot",
})


import time as _time


def probe(publication_number: str, fields: list[str], retries: int = 3) -> tuple[dict, dict]:
    """Run one probe and return ``(notice, error_info)`` with 429 handling.

    The TED API returns 400 on any unknown field, so callers must filter
    the candidate list first via ``probe_field_names``.
    """
    payload = {
        "query": f'publication-number="{publication_number}"',
        "fields": fields,
        "page": 1,
        "limit": 1,
        "paginationMode": "PAGE_NUMBER",
    }
    for attempt in range(retries):
        try:
            resp = requests.post(SEARCH_URL, json=payload, headers=HEADERS,
                                 timeout=30, verify=_SSL_VERIFY)
        except Exception as exc:
            return {}, {"error": f"network: {exc}"}
        if resp.status_code == 200:
            body = resp.json()
            if not body.get("notices"):
                return {}, {"empty": True}
            return body["notices"][0], {}
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            _time.sleep(wait)
            continue
        return {}, {"status": resp.status_code, "body": resp.text[:300]}
    return {}, {"status": 429, "body": "rate-limited after retries"}


def probe_field_names(pub_num: str, candidates: list[str]) -> tuple[set[str], set[str]]:
    """Return ``(valid, invalid)`` field names by binary-search-style culling.

    Strategy: try the whole list. On 400, halve the list and retry, keeping
    track of what works. Cheap because we only care about coarse validity,
    not actual data.
    """
    valid: set[str] = set()
    invalid: set[str] = set()

    def recurse(batch: list[str]) -> None:
        if not batch:
            return
        notice, err = probe(pub_num, batch)
        if not err:
            valid.update(batch)
            return
        if len(batch) == 1:
            invalid.add(batch[0])
            return
        mid = len(batch) // 2
        recurse(batch[:mid])
        recurse(batch[mid:])

    recurse(list(candidates))
    return valid, invalid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="212474-2026,77247-2026,798124-2025,261427-2025",
                    help="Comma-separated publication numbers to probe.")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / ".ted_field_probe.json")
    args = ap.parse_args()

    ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    candidates_only_new = sorted(set(CANDIDATE_FIELDS) - set(ALL_FIELDS))
    print(
        f"  Probing {len(ids)} notices to discover field validity. "
        f"{len(candidates_only_new)} new candidates (existing ALL_FIELDS: {len(ALL_FIELDS)})."
    )

    # ── Phase 1: per ID find which of CANDIDATE_FIELDS the API accepts.
    valid_any: set[str] = set()
    for tid in ids:
        print(f"  [probe-validity] {tid} …", flush=True)
        valid, invalid = probe_field_names(tid, candidates_only_new)
        valid_any.update(valid)

    new_valid = sorted(valid_any - set(ALL_FIELDS))
    print()
    print(f"  ── {len(new_valid)} NEW VALID FIELD NAMES (accepted by API) ──")
    for f in new_valid:
        print(f"    + {f}")

    # ── Phase 2: for the validated fields, fetch real data per ID.
    results: dict[str, dict] = {}
    fetch_set = sorted(set(ALL_FIELDS) | valid_any)
    for tid in ids:
        _time.sleep(2)  # be gentle with TED rate-limit between fetches
        notice, err = probe(tid, fetch_set)
        if err:
            print(f"  [probe-data] {tid} [error] {err}")
            continue
        results[tid] = notice

    print()
    print("  ── Sample values for new fields ──")
    for f in new_valid:
        sample = None
        sample_id = None
        for tid in ids:
            v = results.get(tid, {}).get(f)
            if v not in (None, "", [], {}):
                sample = v
                sample_id = tid
                break
        sample_repr = json.dumps(sample, ensure_ascii=False)[:200] if sample is not None else "—"
        print(f"    {f} (from {sample_id or '—'}): {sample_repr}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"new_valid_fields": new_valid, "data": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  [OK] Wrote raw probe data → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

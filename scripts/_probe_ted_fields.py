"""
TED API v3 Field Discovery Probe — Sprint 14b
Hit the live API for 1-2 known notices and print ALL returned fields.

Targets:
  - 224545-2026  (fresh Contract Notice, pub 2026-04-01, Belgium)
  - 207385-2026  (fresh Contract Notice, pub 2026-03-26, Belgium)

Strategy:
  1. Request with candidate notice-type/form-type field names added
  2. Print ALL keys in the raw response so we can identify the right one
  3. Also try fields=["*"] wildcard to see if API supports it

Run from ted-scraper/ted-scraper/:
    python3 scripts/_probe_ted_fields.py
"""
from __future__ import annotations
import json
import sys
import time
import requests

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"

PROBE_TARGETS = ["224545-2026", "207385-2026"]

# Baseline fields (what we already fetch)
BASELINE_FIELDS = [
    "notice-identifier",
    "publication-number",
    "notice-title",
    "publication-date",
    "buyer-name",
    "organisation-country-buyer",
    "classification-cpv",
    "legal-basis",
    "total-value",
    "total-value-cur",
    "description-lot",
    "description-proc",
    "description-part",
    "title-lot",
    "title-proc",
    "contract-title",
    "winner-name",
    "winner-country",
    "winner-identifier",
    "winner-decision-date",
    "winner-size",
    "deadline-receipt-tender-date-lot",
    "legal-basis-proc",
    "legal-basis-notice",
    "place-of-performance-post-code-part",
    "identifier-part",
    "announcement-title",
]

# Candidate notice-type field names to probe
CANDIDATE_FIELDS = [
    "notice-type",
    "form-type",
    "notice-subtype",
    "publication-type",
    "form-type-code",
    "notice-type-code",
    "procedure-type",
    "notice-kind",
    "document-type",
    "contract-notice-type",
    "procurement-type",
    "award-notice",
    "contract-type",
    "notice-form-type",
    "stage",
    "stage-type",
]

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)",
}


def probe_with_fields(pub_number: str, fields: list[str]) -> dict | None:
    payload = {
        "query": f'publication-number="{pub_number}"',
        "fields": fields,
        "page": 1,
        "limit": 1,
        "paginationMode": "PAGE_NUMBER",
    }
    resp = requests.post(SEARCH_URL, json=payload, headers=HEADERS, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        notices = data.get("notices", [])
        return notices[0] if notices else None
    else:
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return None


def main():
    target = PROBE_TARGETS[0]

    # ── Step 1: Probe with baseline + all candidate fields ──────────────────────
    print(f"\n{'='*60}")
    print(f"STEP 1: Extended field probe for {target}")
    print(f"Fields: baseline ({len(BASELINE_FIELDS)}) + {len(CANDIDATE_FIELDS)} candidates")
    print(f"{'='*60}")

    all_fields = BASELINE_FIELDS + CANDIDATE_FIELDS
    result = probe_with_fields(target, all_fields)
    time.sleep(1)

    if result:
        present = [f for f in CANDIDATE_FIELDS if f in result and result[f] not in (None, [], "")]
        absent  = [f for f in CANDIDATE_FIELDS if f not in result or result[f] in (None, [], "")]
        print(f"\nCandidate fields PRESENT (non-empty): {present}")
        print(f"Candidate fields absent/null:          {absent}")
        print(f"\nAll keys in response (sorted):")
        for k in sorted(result.keys()):
            v = result[k]
            preview = str(v)[:80].replace("\n", "\\n") if v not in (None, [], {}) else "(null/empty)"
            print(f"  {k:45s}  {preview}")
    else:
        print("No result returned for STEP 1")

    # ── Step 2: Wildcard fields=["*"] ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"STEP 2: Wildcard fields=[\"*\"] for {target}")
    print(f"{'='*60}")

    wildcard_result = probe_with_fields(target, ["*"])
    time.sleep(1)

    if wildcard_result:
        print(f"\nAll keys in wildcard response (sorted):")
        for k in sorted(wildcard_result.keys()):
            v = wildcard_result[k]
            preview = str(v)[:80].replace("\n", "\\n") if v not in (None, [], {}) else "(null/empty)"
            print(f"  {k:45s}  {preview}")
    else:
        print("Wildcard returned no results (API may not support '*')")

    # ── Step 3: Probe a known CAN (award notice) to compare ─────────────────────
    # Use an awarded notice to see if the type changes
    can_target = "95616-2026"
    print(f"\n{'='*60}")
    print(f"STEP 3: Same extended probe for {can_target} (compare notice type)")
    print(f"{'='*60}")

    can_result = probe_with_fields(can_target, all_fields)
    time.sleep(1)

    if can_result:
        print(f"\nAll keys in response (sorted):")
        for k in sorted(can_result.keys()):
            v = can_result[k]
            preview = str(v)[:80].replace("\n", "\\n") if v not in (None, [], {}) else "(null/empty)"
            print(f"  {k:45s}  {preview}")

        # Diff against first result
        if result:
            diff_fields = []
            for k in set(list(result.keys()) + list(can_result.keys())):
                v1 = result.get(k)
                v2 = can_result.get(k)
                if str(v1) != str(v2) and k not in ("publication-number", "notice-identifier",
                                                      "notice-title", "buyer-name",
                                                      "description-lot", "description-proc",
                                                      "title-lot", "title-proc",
                                                      "organisation-country-buyer",
                                                      "classification-cpv", "legal-basis",
                                                      "legal-basis-notice", "links"):
                    diff_fields.append((k, str(v1)[:60], str(v2)[:60]))
            if diff_fields:
                print(f"\nFields that DIFFER between {target} and {can_target}:")
                for fname, v1, v2 in sorted(diff_fields):
                    print(f"  {fname:40s}  [{v1}]  vs  [{v2}]")
            else:
                print("\nNo structural differences found beyond expected content fields.")
    else:
        print("No result for STEP 3")

    print("\nDone.")


if __name__ == "__main__":
    main()

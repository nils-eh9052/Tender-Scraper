"""
Sprint 14b — Backfill notice-type / form-type / procedure-type
into existing relevant.json and data/raw/details/*.json files.

Only patches TED notices that are missing _raw.notice-type.
Reads/writes relevant.json in-place; also updates the detail JSONs.

Run from ted-scraper/ted-scraper/:
    python3 scripts/_backfill_notice_type.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"
DETAILS_DIR = ROOT / "data" / "raw" / "details"
SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)",
}
FETCH_FIELDS = ["publication-number", "notice-type", "form-type", "procedure-type"]
_TED_PAT = re.compile(r"^\d+-\d{4}$")


def is_ted(notice: dict) -> bool:
    return bool(_TED_PAT.match(str(notice.get("tender_id", ""))))


def fetch_notice_type(pub_num: str) -> dict | None:
    payload = {
        "query": f'publication-number="{pub_num}"',
        "fields": FETCH_FIELDS,
        "page": 1,
        "limit": 1,
        "paginationMode": "PAGE_NUMBER",
    }
    try:
        resp = requests.post(SEARCH_URL, json=payload, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            notices = resp.json().get("notices", [])
            return notices[0] if notices else None
        print(f"  HTTP {resp.status_code} for {pub_num}: {resp.text[:100]}", file=sys.stderr)
    except Exception as e:
        print(f"  Error fetching {pub_num}: {e}", file=sys.stderr)
    return None


def main(dry_run: bool = False) -> None:
    print(f"Loading {RELEVANT_JSON} …")
    with open(RELEVANT_JSON, encoding="utf-8") as f:
        notices = json.load(f)

    # Identify TED notices missing notice-type in _raw
    to_patch = []
    for n in notices:
        if not is_ted(n):
            continue
        raw = n.get("_raw") or {}
        if not isinstance(raw, dict) or not raw.get("notice-type"):
            to_patch.append(n)

    print(f"TED notices missing notice-type: {len(to_patch)} of {len(notices)}")
    if not to_patch:
        print("Nothing to backfill.")
        return

    if dry_run:
        print("[dry-run] Would patch these tender_ids:")
        for n in to_patch:
            print(f"  {n.get('tender_id')}")
        return

    patched = 0
    failed = 0

    for i, notice in enumerate(to_patch):
        tid = notice.get("tender_id", "")
        sys.stdout.write(f"\r[{i+1}/{len(to_patch)}] {tid:<20s}")
        sys.stdout.flush()

        api_data = fetch_notice_type(tid)
        time.sleep(1.0)  # respect rate limit

        if not api_data:
            failed += 1
            continue

        nt = api_data.get("notice-type")
        ft = api_data.get("form-type")
        pt = api_data.get("procedure-type")

        if not nt and not ft:
            print(f"\n  {tid}: API returned no notice-type or form-type — skipping")
            failed += 1
            continue

        # --- patch relevant.json entry in-place ---
        raw = notice.get("_raw")
        if not isinstance(raw, dict):
            notice["_raw"] = {}
            raw = notice["_raw"]
        if nt:
            raw["notice-type"] = nt
        if ft:
            raw["form-type"] = ft
        if pt:
            raw["procedure-type"] = pt

        # --- patch data/raw/details/{id}.json ---
        safe_id = tid.replace("/", "_").replace("\\", "_")
        detail_path = DETAILS_DIR / f"{safe_id}.json"
        if detail_path.exists():
            try:
                with open(detail_path, encoding="utf-8") as f:
                    detail = json.load(f)
                detail_raw = detail.get("_raw")
                if isinstance(detail_raw, dict):
                    if nt:
                        detail_raw["notice-type"] = nt
                    if ft:
                        detail_raw["form-type"] = ft
                    if pt:
                        detail_raw["procedure-type"] = pt
                    with open(detail_path, "w", encoding="utf-8") as f:
                        json.dump(detail, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"\n  Warning: could not update detail JSON for {tid}: {e}")

        patched += 1

    print(f"\n\nDone: {patched} patched, {failed} failed.")

    if patched > 0:
        print(f"Writing updated relevant.json …")
        with open(RELEVANT_JSON, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)
        print("Done.")

    # Summary
    print("\nSample results:")
    for n in notices:
        if not is_ted(n):
            continue
        raw = n.get("_raw") or {}
        nt = raw.get("notice-type", "—")
        if nt != "—":
            print(f"  {n.get('tender_id'):<20s}  notice-type={nt}")
            if patched <= 10:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill notice-type into relevant.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be patched without making changes")
    args = parser.parse_args()
    main(dry_run=args.dry_run)

"""
Pre-Run Snapshot — shared/tenders.json
Collects key metrics and writes them to data/snapshots/snapshot_<label>.json.

Run from ted-scraper/ted-scraper/:
    python3 scripts/_snapshot_tenders.py [--label pre-fullrun-260508]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
TENDERS_JSON = ROOT.parent.parent / "shared" / "tenders.json"
SNAPSHOTS_DIR = ROOT / "data" / "snapshots"


def build_snapshot(label: str) -> dict:
    with open(TENDERS_JSON, encoding="utf-8") as f:
        tenders = json.load(f)

    total = len(tenders)
    status_count: Counter = Counter()
    source_count: Counter = Counter()
    country_count: Counter = Counter()
    zero_value = 0
    total_value = 0.0
    pub_dates: list[str] = []
    seen_ids: set[str] = set()

    for t in tenders:
        status_count[t.get("status") or "unknown"] += 1
        source_count[t.get("source") or "unknown"] += 1
        country_count[t.get("country") or "unknown"] += 1

        val = t.get("estimated_value_eur")
        if val is None or val == 0:
            zero_value += 1
        else:
            try:
                total_value += float(val)
            except (TypeError, ValueError):
                zero_value += 1

        pd = t.get("pub_date") or t.get("publication_date") or ""
        if pd and len(pd) >= 10:
            pub_dates.append(pd[:10])

        tid = t.get("tender_id") or t.get("id") or ""
        if tid:
            seen_ids.add(tid)

    pub_dates_clean = sorted(d for d in pub_dates if d)
    newest_pub = pub_dates_clean[-1] if pub_dates_clean else None
    oldest_pub = pub_dates_clean[0] if pub_dates_clean else None

    snapshot = {
        "label": label,
        "generated_at": datetime.utcnow().isoformat(),
        "source_file": str(TENDERS_JSON),
        "total_tenders": total,
        "distinct_tender_ids": len(seen_ids),
        "count_by_status": dict(status_count.most_common()),
        "count_by_source": dict(source_count.most_common()),
        "count_by_country_top10": dict(country_count.most_common(10)),
        "zero_or_null_value": zero_value,
        "total_estimated_value_eur": round(total_value, 2),
        "newest_pub_date": newest_pub,
        "oldest_pub_date": oldest_pub,
    }
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Snapshot shared/tenders.json metrics")
    parser.add_argument("--label", default="pre-fullrun-260508",
                        help="Label used in output filename")
    args = parser.parse_args()

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOTS_DIR / f"snapshot_{args.label}.json"

    snapshot = build_snapshot(args.label)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"Snapshot written: {out_path}")
    print(f"  total_tenders        : {snapshot['total_tenders']}")
    print(f"  distinct_ids         : {snapshot['distinct_tender_ids']}")
    print(f"  count_by_status      : {snapshot['count_by_status']}")
    print(f"  count_by_source      : {snapshot['count_by_source']}")
    print(f"  zero_or_null_value   : {snapshot['zero_or_null_value']}")
    print(f"  total_value_eur      : {snapshot['total_estimated_value_eur']:,.0f}")
    print(f"  newest_pub_date      : {snapshot['newest_pub_date']}")
    print(f"  oldest_pub_date      : {snapshot['oldest_pub_date']}")


if __name__ == "__main__":
    main()

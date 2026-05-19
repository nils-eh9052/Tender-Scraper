"""
Strategy-A smoke-test — discover only (no AI, no live LLM cost).

For each of the 9 hand-picked DE/PL/CZ candidates, run
``_discover_strategy_a`` against the active relevant.json snapshot and report
how many DocumentRefs each tender produced + a sample URL.

Yield is reported but no documents are downloaded — that proves the
discovery pipeline works against live portals without burning $.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLE = {
    "DE": ["212474-2026", "719142-2025", "682847-2024"],
    "PL": ["261427-2025", "432811-2024", "736943-2024"],
    "CZ": ["798124-2025", "465260-2025", "467088-2025"],
}


def main(check_alive: bool = False) -> None:
    from src.document_pipeline.discovery import _discover_strategy_a, _strategy_a_inputs, url_is_healthy

    with open(ROOT / "data" / "filtered" / "relevant.json", encoding="utf-8") as f:
        notices = json.load(f)
    by_id = {str(n.get("tender_id", "")): n for n in notices}

    overall = {"DE": 0, "PL": 0, "CZ": 0}
    alive_overall = {"DE": 0, "PL": 0, "CZ": 0}
    rows = []

    for cc, ids in SAMPLE.items():
        for tid in ids:
            notice = by_id.get(tid)
            if not notice:
                rows.append((cc, tid, "MISSING from relevant.json", 0, 0, ""))
                continue

            inputs = _strategy_a_inputs(notice)
            refs = _discover_strategy_a(notice)
            n_alive = 0
            sample_url = ""
            if refs:
                sample_url = refs[0].url[:90]
                if check_alive:
                    for r in refs[:3]:
                        if r.url.startswith(("http://", "https://")):
                            if url_is_healthy(r.url, timeout=8):
                                n_alive += 1

            yielded = len(refs) > 0
            if yielded:
                overall[cc] += 1
                if n_alive > 0:
                    alive_overall[cc] += 1

            buyer = inputs.get("buyer_profile_url", "")
            docs = inputs.get("tender_documents_access", "")
            ref = inputs.get("internal_reference", "")
            url_in = docs or buyer or "(no URL)"

            rows.append((cc, tid, url_in, len(refs), n_alive, sample_url))

    print(f"{'CC':<3} {'TID':<14} {'URL-IN':<50} {'#REFS':>6} {'#ALIVE':>6}  SAMPLE-OUT")
    for cc, tid, url_in, n_refs, n_alive, sample in rows:
        print(f"{cc:<3} {tid:<14} {url_in[:48]:<50} {n_refs:>6} {n_alive:>6}  {sample}")

    print()
    print(f"Yield by country (≥1 ref found): "
          f"DE={overall['DE']}/3, PL={overall['PL']}/3, CZ={overall['CZ']}/3, "
          f"total={sum(overall.values())}/9")
    if check_alive:
        print(f"Yield with ≥1 alive URL:        "
              f"DE={alive_overall['DE']}/3, PL={alive_overall['PL']}/3, "
              f"CZ={alive_overall['CZ']}/3, total={sum(alive_overall.values())}/9")


if __name__ == "__main__":
    main(check_alive="--alive" in sys.argv)

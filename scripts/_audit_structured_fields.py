"""
Structured Fields Audit — Sprint 14k+

Classifies every notice in relevant.json on four dimensions:
  estimated_value_eur  — known / null
  contract_duration    — known / null
  trailer_type         — specific (has specs) / generic / null
  trailer_qty          — known / null

Writes docs/STRUCTURED_FIELD_AUDIT_260514.md with coverage per field × country.

Usage:
    python scripts/_audit_structured_fields.py
    python scripts/_audit_structured_fields.py --json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEVANT_PATH = ROOT / "data" / "filtered" / "relevant.json"
OUT_PATH = ROOT / "docs" / "STRUCTURED_FIELD_AUDIT_260514.md"

# Trailer-type strings that are generic (not specific)
_GENERIC_TRAILER_PATTERNS = re.compile(
    r"type not specified|unspecified|unknown|generic|tbd|n/a",
    re.IGNORECASE,
)


def _get_value_eur(notice: dict) -> float | None:
    v = notice.get("_value_eur_num")
    if v is not None:
        try:
            f = float(v)
            if f > 0.01:
                return f
        except (ValueError, TypeError):
            pass
    ev = notice.get("estimated_value")
    if isinstance(ev, dict):
        try:
            amt = float(ev.get("amount") or 0)
            if amt > 0.01:
                return amt  # raw amount (currency conversion not needed for audit)
        except (ValueError, TypeError):
            pass
    raw_amt = notice.get("_value_amount")
    if raw_amt is not None:
        try:
            amt = float(raw_amt)
            if amt > 0.01:
                return amt
        except (ValueError, TypeError):
            pass
    return None


def _trailer_type_class(notice: dict) -> str:
    """'specific', 'generic', or 'null'"""
    t1 = notice.get("_trailer_type_1_ai")
    if not t1:
        # Also check extracted_specs
        specs = notice.get("_extracted_specs") or {}
        tt = specs.get("trailer_types") or []
        if tt and tt[0].get("type"):
            return "specific"
        return "null"
    if _GENERIC_TRAILER_PATTERNS.search(str(t1)):
        return "generic"
    return "specific"


def _has_extracted_specs(notice: dict) -> bool:
    specs = notice.get("_extracted_specs") or {}
    tt = specs.get("trailer_types") or []
    return bool(specs and any(
        t.get("payload_t") or t.get("axle_load_t") or t.get("mass_t")
        for t in tt
    ))


def classify(notice: dict) -> dict:
    country = notice.get("_country_normalized") or "Unknown"
    source = notice.get("_source") or (
        "TED" if re.match(r"^\d+-\d{4}$", str(notice.get("tender_id", ""))) else "National"
    )
    return {
        "country": country,
        "source": source,
        "value_known": _get_value_eur(notice) is not None,
        "duration_known": bool(notice.get("_contract_duration_ai")),
        "trailer_type": _trailer_type_class(notice),
        "qty_known": notice.get("_trailer_quantity_1_ai") is not None,
        "specs_with_payload": _has_extracted_specs(notice),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--relevant", default=str(RELEVANT_PATH))
    args = parser.parse_args()

    path = Path(args.relevant)
    if not path.exists():
        import sys
        sys.exit(f"Not found: {path}")

    with open(path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    total = len(notices)
    rows = [classify(n) for n in notices]

    # Overall counts
    value_known = sum(1 for r in rows if r["value_known"])
    dur_known = sum(1 for r in rows if r["duration_known"])
    type_specific = sum(1 for r in rows if r["trailer_type"] == "specific")
    type_generic = sum(1 for r in rows if r["trailer_type"] == "generic")
    type_null = sum(1 for r in rows if r["trailer_type"] == "null")
    qty_known = sum(1 for r in rows if r["qty_known"])
    specs_payload = sum(1 for r in rows if r["specs_with_payload"])

    # By country
    by_country: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_country[r["country"]].append(r)

    # By source
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_source[r["source"]].append(r)

    lines: list[str] = [
        f"# Structured Field Audit — {date.today().isoformat()}",
        "",
        f"**relevant.json:** `{path}` ({total} notices)",
        "",
        "## 1. Overall Coverage",
        "",
        "| Field | Known | Null | Coverage |",
        "|-------|------:|-----:|---------:|",
    ]

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%"

    lines += [
        f"| estimated_value_eur | {value_known} | {total - value_known} | {pct(value_known)} |",
        f"| contract_duration | {dur_known} | {total - dur_known} | {pct(dur_known)} |",
        f"| trailer_qty | {qty_known} | {total - qty_known} | {pct(qty_known)} |",
        f"| extracted_specs (payload/axle) | {specs_payload} | {total - specs_payload} | {pct(specs_payload)} |",
        "",
        "### Trailer Type Breakdown",
        "",
        "| Class | Count | % |",
        "|-------|------:|--:|",
        f"| specific | {type_specific} | {pct(type_specific)} |",
        f"| generic | {type_generic} | {pct(type_generic)} |",
        f"| null | {type_null} | {pct(type_null)} |",
        "",
        "## 2. By Country",
        "",
        "| Country | N | Value% | Duration% | Qty% | Type-Specific% |",
        "|---------|--:|-------:|----------:|-----:|---------------:|",
    ]

    for country in sorted(by_country, key=lambda c: -len(by_country[c])):
        cr = by_country[country]
        n = len(cr)
        v_pct = sum(1 for r in cr if r["value_known"]) / n * 100
        d_pct = sum(1 for r in cr if r["duration_known"]) / n * 100
        q_pct = sum(1 for r in cr if r["qty_known"]) / n * 100
        t_pct = sum(1 for r in cr if r["trailer_type"] == "specific") / n * 100
        lines.append(
            f"| {country} | {n} | {v_pct:.0f}% | {d_pct:.0f}% | {q_pct:.0f}% | {t_pct:.0f}% |"
        )

    lines += [
        "",
        "## 3. By Source",
        "",
        "| Source | N | Value% | Duration% | Qty% | Type-Specific% |",
        "|--------|--:|-------:|----------:|-----:|---------------:|",
    ]

    for src in sorted(by_source, key=lambda s: -len(by_source[s])):
        sr = by_source[src]
        n = len(sr)
        v_pct = sum(1 for r in sr if r["value_known"]) / n * 100
        d_pct = sum(1 for r in sr if r["duration_known"]) / n * 100
        q_pct = sum(1 for r in sr if r["qty_known"]) / n * 100
        t_pct = sum(1 for r in sr if r["trailer_type"] == "specific") / n * 100
        lines.append(
            f"| {src} | {n} | {v_pct:.0f}% | {d_pct:.0f}% | {q_pct:.0f}% | {t_pct:.0f}% |"
        )

    lines += [
        "",
        "## 4. Gaps — Value-Unknown Sample (up to 5)",
        "",
    ]
    no_val = [notices[i] for i, r in enumerate(rows) if not r["value_known"]][:5]
    for n in no_val:
        lines += [
            f"**{n.get('tender_id')}** ({rows[notices.index(n)]['country']}) "
            f"— {(n.get('title_en') or n.get('_title_final') or '')[:80]}",
            "",
        ]

    lines += [
        "## 5. Gaps — Null Trailer Type Sample (up to 5)",
        "",
    ]
    no_type = [notices[i] for i, r in enumerate(rows) if r["trailer_type"] == "null"][:5]
    for n in no_type:
        lines += [
            f"**{n.get('tender_id')}** ({rows[notices.index(n)]['country']}) "
            f"— {(n.get('title_en') or n.get('_title_final') or '')[:80]}",
            "",
        ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Audit written → {OUT_PATH}")

    print(f"\nTotal: {total}")
    print(f"  estimated_value_eur: {value_known} ({pct(value_known)})")
    print(f"  contract_duration:   {dur_known} ({pct(dur_known)})")
    print(f"  trailer_qty:         {qty_known} ({pct(qty_known)})")
    print(f"  trailer_type specific: {type_specific} ({pct(type_specific)})")
    print(f"  extracted_specs (payload): {specs_payload} ({pct(specs_payload)})")

    if args.json:
        jp = OUT_PATH.with_suffix(".json")
        jp.write_text(json.dumps({
            "total": total,
            "coverage": {
                "value_known": value_known, "duration_known": dur_known,
                "qty_known": qty_known, "specs_payload": specs_payload,
                "trailer_specific": type_specific, "trailer_generic": type_generic,
                "trailer_null": type_null,
            },
            "by_country": {
                k: {
                    "n": len(v),
                    "value_pct": round(sum(1 for r in v if r["value_known"]) / len(v) * 100, 1),
                    "duration_pct": round(sum(1 for r in v if r["duration_known"]) / len(v) * 100, 1),
                }
                for k, v in by_country.items()
            },
        }, indent=2), encoding="utf-8")
        print(f"[OK] JSON written → {jp}")


if __name__ == "__main__":
    main()

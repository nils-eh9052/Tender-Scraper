#!/usr/bin/env python3
"""
_audit_ca_quality.py — Diagnose-Audit für CA-CB-Tender Quality im Frontend.

User-Report: CA Lowbed Trailers fehlen Quantity + Trailer-Type-Clustering
im Frontend. Dieses Script analysiert die ganze Mapping-Kette:

  relevant.json ──→ AI-Classifier ──→ Text-Miner ──→ Exporter ──→ tenders.json

Output: docs/CA_QUALITY_AUDIT_260520.md mit Befund pro Tender.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
REL = ROOT / "data" / "filtered" / "relevant.json"
SHARED = ROOT.parent.parent / "shared" / "tenders.json"
OUT = ROOT / "docs" / "CA_QUALITY_AUDIT_260520.md"


def _source_of(notice: dict) -> str:
    tid = str(notice.get("tender_id", ""))
    src = notice.get("_source") or notice.get("source", "")
    if src:
        return src
    if tid.startswith("AU-TEN"):
        return "AU-TEN"
    if "-" in tid and tid.split("-")[0].isalpha():
        return tid.split("-")[0]
    return "TED"


def main() -> None:
    rel = json.loads(REL.read_text(encoding="utf-8"))
    tenders_by_id = {t["id"]: t for t in json.loads(SHARED.read_text(encoding="utf-8"))}

    ca = [n for n in rel if str(n.get("tender_id", "")).startswith("CA-")]

    lines: list[str] = []
    lines.append("# CA Quality Audit — 2026-05-20")
    lines.append("")
    lines.append("> Auto-generiert von `scripts/_audit_ca_quality.py`.")
    lines.append("")
    lines.append("## Root-Cause Analyse")
    lines.append("")
    lines.append("**User-Report:** CA Lowbed Trailers — `Qty 27` im Text, aber Frontend zeigt weder Quantity noch Trailer-Type-Clustering.")
    lines.append("")
    lines.append("**Befund:** Daten sind in `relevant.json` korrekt klassifiziert.")
    lines.append("Das Problem liegt **im Exporter-Mapping**:")
    lines.append("")
    lines.append("| Lücke | Auswirkung |")
    lines.append("|-------|-----------|")
    lines.append("| `vehicle_types[i].category` hartcodiert auf `\"trailer\"` | `_trailer_category_{i}_ai` (Low-Bed/Cargo/Ammunition/...) verloren — kein Clustering möglich |")
    lines.append("| Quantity liest nur `_trailer_quantity_{i}_ai` | `_qty_mined` Fallback nie genutzt — bricht bei AI-Misses |")
    lines.append("| Deadline liest nur `submission_deadline` | CA setzt `_closing_date`, text_miner setzt `_deadline_mined` — Frontend hat **0/322** Tenders mit deadline |")
    lines.append("")
    lines.append("## Field Coverage in relevant.json (CA-CB, 19 Tender)")
    lines.append("")
    fields = [
        ("_trailer_type_1_ai", "AI Trailer-Type-Beschreibung"),
        ("_trailer_category_1_ai", "AI Trailer-Cluster"),
        ("_trailer_quantity_1_ai", "AI Quantity"),
        ("_qty_mined", "Text-Miner Quantity"),
        ("_closing_date", "CA-Adapter Closing Date"),
        ("_deadline_mined", "Text-Miner Deadline"),
        ("submission_deadline", "Generisches Deadline-Feld (TED/UK)"),
    ]
    lines.append("| Feld | Coverage | Bedeutung |")
    lines.append("|------|---------:|-----------|")
    for f, desc in fields:
        c = sum(1 for n in ca if n.get(f))
        lines.append(f"| `{f}` | {c}/19 | {desc} |")
    lines.append("")

    lines.append("## Per-Tender Detail")
    lines.append("")
    lines.append("Status-Spalten:")
    lines.append("- **RJ_qty**: Quantity in `relevant.json` (AI / mined)")
    lines.append("- **RJ_cat**: Category in `relevant.json` (`_trailer_category_1_ai`)")
    lines.append("- **RJ_dl**: Deadline-Quellen in `relevant.json`")
    lines.append("- **FE_qty**: Quantity im Frontend (`vehicle_types[0].quantity`)")
    lines.append("- **FE_cat**: Category im Frontend (`vehicle_types[0].category` — aktuell hartcodiert)")
    lines.append("- **FE_dl**: Deadline im Frontend")
    lines.append("")
    lines.append("| ID | Title | RJ_qty | RJ_cat | RJ_dl | FE_qty | FE_cat | FE_dl |")
    lines.append("|----|-------|-------:|--------|-------|-------:|--------|-------|")
    for n in ca:
        tid = n.get("tender_id", "")
        title = (n.get("_title_final") or n.get("title") or "")[:40]
        q_ai = n.get("_trailer_quantity_1_ai")
        q_mined = n.get("_qty_mined")
        rj_qty = f"{q_ai or '–'}/{q_mined or '–'}"
        cat = n.get("_trailer_category_1_ai") or "–"
        rj_dl = []
        if n.get("submission_deadline"): rj_dl.append("sub")
        if n.get("_closing_date"): rj_dl.append("clo")
        if n.get("_deadline_mined"): rj_dl.append("min")
        rj_dl_s = ",".join(rj_dl) or "–"

        t = tenders_by_id.get(tid)
        if t:
            fe_qty = "–"
            fe_cat = "–"
            if t.get("vehicle_types"):
                v = t["vehicle_types"][0]
                fe_qty = str(v.get("quantity", "–"))
                fe_cat = v.get("category", "–")
            fe_dl = t.get("deadline") or "–"
        else:
            fe_qty = fe_cat = fe_dl = "NOT_IN_TENDERS"

        lines.append(f"| `{tid}` | {title} | {rj_qty} | {cat} | {rj_dl_s} | {fe_qty} | {fe_cat} | {fe_dl} |")
    lines.append("")

    lines.append("## Aggregate: Deadline-Coverage über ALLE Sources (322 Tender)")
    lines.append("")
    src_stats = defaultdict(lambda: {"total": 0, "sub": 0, "clo": 0, "mined": 0})
    for n in rel:
        s = src_stats[_source_of(n)]
        s["total"] += 1
        if n.get("submission_deadline"): s["sub"] += 1
        if n.get("_closing_date"): s["clo"] += 1
        if n.get("_deadline_mined"): s["mined"] += 1

    lines.append("| Source | Tenders | submission_deadline | _closing_date | _deadline_mined |")
    lines.append("|--------|--------:|--------------------:|--------------:|----------------:|")
    for src, s in sorted(src_stats.items()):
        lines.append(f"| {src} | {s['total']} | {s['sub']} | {s['clo']} | {s['mined']} |")
    lines.append("")
    fe_dl_count = sum(1 for t in tenders_by_id.values() if t.get("deadline"))
    lines.append(f"**Frontend `deadline` gesetzt:** {fe_dl_count}/{len(tenders_by_id)} (sollte mit Fix ≥ ~55 sein)")
    lines.append("")

    lines.append("## Empfohlene Fixes (in `src/exporter_frontend.py`)")
    lines.append("")
    lines.append("### Fix 1 — `_build_vehicle_types()`")
    lines.append("```python")
    lines.append("# ALT:")
    lines.append('entry = {"name": name, "category": "trailer"}')
    lines.append("# NEU:")
    lines.append('cat_ai = notice.get(f"_trailer_category_{i}_ai")')
    lines.append('entry = {"name": name, "category": cat_ai or "trailer"}')
    lines.append("# Quantity-Fallback:")
    lines.append('qty = (notice.get(f"_trailer_quantity_{i}_ai")')
    lines.append('       or (notice.get("_qty_mined") if i == 1 else None))')
    lines.append("```")
    lines.append("")
    lines.append("### Fix 2 — Deadline-Resolution")
    lines.append("```python")
    lines.append("def _deadline_date(notice):")
    lines.append("    for f in ('submission_deadline', '_closing_date', '_deadline_mined'):")
    lines.append("        v = _clean_date(notice.get(f))")
    lines.append("        if v: return v")
    lines.append("    return None")
    lines.append("```")
    lines.append("")
    lines.append("## Was NICHT zu fixen ist (Hypothesen widerlegt)")
    lines.append("")
    lines.append("- **Classifier-Bypass für CA:** 19/19 CA-Tender haben `_trailer_type_1_ai` gesetzt. Classifier läuft korrekt.")
    lines.append("- **Classifier-Prompt-Schwäche bei \"Low-Bed\":** CA-cb-259-10824239 hat `_trailer_category_1_ai: \"Low-Bed\"`. Klassifikation funktioniert.")
    lines.append("- **Text-Mining-Bug:** `_qty_mined: 27` in Lowbed-Tender korrekt extrahiert.")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Wrote {OUT}")


if __name__ == "__main__":
    main()

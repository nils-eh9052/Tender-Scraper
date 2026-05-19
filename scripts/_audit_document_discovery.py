"""
Document Discovery Audit — per-source coverage of:
  (1) which discovery handler is invoked for each notice
  (2) how many DocumentRef objects the handler returns
  (3) what fraction of notices in that source-bucket already have
      _extracted_specs (i.e. the doc-pipeline successfully extracted text)

Run:  python scripts/_audit_document_discovery.py

Output:
  - stdout summary
  - docs/DOCUMENT_DISCOVERY_AUDIT_260518.md  (overwritten)

Intent (Sprint 2026-05-18, Window D):
  Identify which adapters still need list_documents() / discovery-handler
  implementation. Used to prioritise the Phase 3g coverage rollout.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.document_pipeline.discovery import discover_for_notice  # noqa: E402

RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"
OUTPUT_MD = ROOT / "docs" / "DOCUMENT_DISCOVERY_AUDIT_260518.md"


def _classify_source(notice: dict) -> str:
    """Return the canonical source label used for grouping in the audit."""
    tid = (notice.get("tender_id") or "").strip()
    explicit = notice.get("_source") or notice.get("source")
    if explicit:
        return str(explicit)

    if tid.startswith("UA-"):
        return "UA-PR"
    if tid.startswith("AU-CN"):
        return "AU-TEN"
    if tid.startswith("AU-"):
        return "AU-AT"
    if tid.startswith("CA-"):
        return "CA-CB"
    if tid.startswith("UK-"):
        return "UK-CF"
    if tid.startswith("CZ-"):
        return "CZ-NEN"
    if tid and tid[0].isdigit():
        return "TED"
    return "?"


def _classify_handler(notice: dict) -> str:
    """Mirror the dispatch logic of discover_for_notice() for diagnostics."""
    tid = (notice.get("tender_id") or "").strip()

    if tid.startswith("UA-"):
        return "_discover_ua"
    if tid.startswith("AU-CN"):
        return "_discover_au_ocds"
    if tid.startswith("AU-"):
        return "_discover_au_atm"
    if tid.startswith("CA-"):
        return "_discover_ca"
    if tid.startswith("UK-") or tid.startswith("CZ-"):
        return "<stub: empty>"
    if notice.get("links", {}) or (notice.get("_raw") or {}).get("links"):
        return "_discover_ted"
    if notice.get("_national_raw_text") or notice.get("_description_final"):
        return "_discover_national_text"
    return "<no handler>"


def main() -> int:
    if not RELEVANT_JSON.exists():
        print(f"ERROR: {RELEVANT_JSON} not found", file=sys.stderr)
        return 1

    data = json.loads(RELEVANT_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(data)} notices from {RELEVANT_JSON.name}\n")

    # Per source: counts + extracted_specs coverage + handler routing
    by_source = defaultdict(lambda: {
        "count": 0,
        "with_extracted_specs": 0,
        "with_national_raw_text": 0,
        "handlers": defaultdict(int),
        "doc_counts": [],
        "real_url_docs": 0,
        "synthetic_text_docs": 0,
    })

    for notice in data:
        src = _classify_source(notice)
        bucket = by_source[src]
        bucket["count"] += 1

        if notice.get("_extracted_specs"):
            bucket["with_extracted_specs"] += 1
        if notice.get("_national_raw_text"):
            bucket["with_national_raw_text"] += 1

        handler = _classify_handler(notice)
        bucket["handlers"][handler] += 1

        # Run actual discovery (no network calls for synthetic refs)
        try:
            refs = discover_for_notice(notice)
        except Exception as exc:
            refs = []
            bucket["handlers"][f"<error: {exc.__class__.__name__}>"] += 1

        bucket["doc_counts"].append(len(refs))
        for r in refs:
            if r.url.startswith("internal://"):
                bucket["synthetic_text_docs"] += 1
            else:
                bucket["real_url_docs"] += 1

    # ── stdout summary ────────────────────────────────────────────────────────
    print(f"{'Source':<10}  {'N':>5}  {'specs':>5}  {'natxt':>5}  "
          f"{'realdocs':>8}  {'syntxt':>6}  {'avg_refs':>8}")
    print("-" * 78)
    rows_sorted = sorted(by_source.items(), key=lambda x: -x[1]["count"])
    for src, b in rows_sorted:
        n = b["count"]
        avg = sum(b["doc_counts"]) / n if n else 0
        print(f"{src:<10}  {n:>5}  {b['with_extracted_specs']:>5}  "
              f"{b['with_national_raw_text']:>5}  {b['real_url_docs']:>8}  "
              f"{b['synthetic_text_docs']:>6}  {avg:>8.2f}")

    print("\nPer-source handler routing:")
    for src, b in rows_sorted:
        print(f"\n  {src} (n={b['count']}):")
        for h, c in sorted(b["handlers"].items(), key=lambda x: -x[1]):
            print(f"    {h:<45s} {c:>4}")

    # ── Markdown report ──────────────────────────────────────────────────────
    md_lines = [
        "# Document Discovery Audit — 2026-05-18",
        "",
        "Phase 3g coverage analysis: which adapters route to which discovery",
        "handler, and what fraction of their notices already have",
        "`_extracted_specs` populated.",
        "",
        f"**Corpus**: `data/filtered/relevant.json` — {len(data)} notices",
        "",
        "## Coverage Matrix",
        "",
        "| Source | Notices | _extracted_specs | _national_raw_text | "
        "real-URL docs | synth-text docs | avg refs/notice |",
        "|--------|---------|-----------------:|-------------------:|"
        "--------------:|----------------:|----------------:|",
    ]
    for src, b in rows_sorted:
        n = b["count"]
        avg = sum(b["doc_counts"]) / n if n else 0
        md_lines.append(
            f"| {src} | {n} | {b['with_extracted_specs']} | "
            f"{b['with_national_raw_text']} | "
            f"{b['real_url_docs']} | {b['synthetic_text_docs']} | {avg:.2f} |"
        )

    md_lines.extend([
        "",
        "## Handler Routing",
        "",
        "How `discover_for_notice()` dispatches each source. `<no handler>`",
        "and `<stub: empty>` rows are coverage gaps.",
        "",
    ])
    for src, b in rows_sorted:
        md_lines.append(f"### {src} (n={b['count']})")
        md_lines.append("")
        md_lines.append("| Handler | Count |")
        md_lines.append("|---------|------:|")
        for h, c in sorted(b["handlers"].items(), key=lambda x: -x[1]):
            md_lines.append(f"| `{h}` | {c} |")
        md_lines.append("")

    md_lines.extend([
        "## Gap Analysis",
        "",
        "Sources where discovery returns **synthetic text** instead of",
        "real document URLs lose out on the Phase 3g full PDF/docx",
        "extraction path. The AI structurer can still operate on text, but",
        "it never sees buyer-side tender documents (Leistungsverzeichnis,",
        "technical specifications), which carry the highest-value structured",
        "fields (qty, dimensions, delivery dates).",
        "",
        "### Priority for rollout (by notice volume × current gap)",
        "",
    ])
    priorities = []
    for src, b in rows_sorted:
        if b["count"] < 1:
            continue
        if b["real_url_docs"] == 0 and b["count"] >= 5:
            # No real document URLs and meaningful volume → priority
            priorities.append((src, b["count"], b))
    for src, n, b in priorities:
        md_lines.append(
            f"- **{src}** ({n} notices, 0 real-URL docs) — currently routed "
            f"to `{next(iter(b['handlers']))}`. Synthetic text only."
        )
    if not priorities:
        md_lines.append("_All sources with meaningful volume already yield real document URLs._")

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\nWrote {OUTPUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

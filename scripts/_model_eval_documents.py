"""
LLM Document Extraction Eval — BPW Defence Tender Radar.

Tests 5 models × 8 sample documents for extraction quality on 7 fields:
  value_amount, value_currency, winner_name, quantity,
  contract_duration_months, deadline, procurement_category

Run from ted-scraper/ted-scraper/:
    python3 scripts/_model_eval_documents.py
    python3 scripts/_model_eval_documents.py --dry-run   # skip API calls
    python3 scripts/_model_eval_documents.py --models anthropic/claude-sonnet-4-6

Outputs:
  docs/MODEL_EVAL_DOCUMENTS_260509.md
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.llm_router import call_with_usage, estimate_cost_usd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if val and not os.environ.get(key):
            os.environ[key] = val
    # Map project-specific key aliases
    if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("LLM_ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["LLM_ANTHROPIC_API_KEY"]
    if not os.environ.get("OPENROUTER_API_KEY") and os.environ.get("LLM_OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = os.environ["LLM_OPENROUTER_API_KEY"]


_load_env()

# ── Config ──────────────────────────────────────────────────────────────────

MODELS: list[str] = [
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-opus-4-7",       # spec says 4-6 but correct ID is 4-7
    "openrouter/google/gemini-2.5-pro",
    "openrouter/openai/gpt-4o",
    "openrouter/mistralai/mistral-large",
]

MAX_TEXT_CHARS = 12000   # truncate to ~3000 tokens to keep cost reasonable
EXTRACTION_MAX_TOKENS = 400

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "document_eval_truth.json"
RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"
OUT_MD = ROOT / "docs" / "MODEL_EVAL_DOCUMENTS_260509.md"

SYSTEM_PROMPT = """You are a defence procurement data extraction specialist. Extract structured information from procurement notice texts with high precision.

Return ONLY a JSON object with exactly these keys (use null for missing or unclear fields):
{
  "value_amount": <number — contract/award value in original currency, raw (e.g. 60000000 not "60M")>,
  "value_currency": <"EUR"/"SEK"/"RON"/"CZK"/"GBP"/"PLN"/"UAH"/"NOK"/"DKK" or null>,
  "winner_name": <"company name" — primary awarded supplier, null if not yet awarded>,
  "quantity": <integer — number of physical units ordered (firm, not options), null if not stated>,
  "contract_duration_months": <integer — total contract duration in months (1 year=12, 1 day≈0.033)>,
  "deadline": <"YYYY-MM-DD" — tender submission deadline, null if absent>,
  "procurement_category": <short English phrase describing what is procured>
}

Rules:
- value_amount: prefer awarded/actual over estimated; never convert currency; raw number only
- quantity: firm order count only; skip framework min/max ranges → null
- winner_name: first winner only if multiple; null for open/competition notices
- Return ONLY the JSON object, no markdown fences, no explanation"""

USER_TEMPLATE = """Extract the procurement fields from this notice:

---
{text}
---"""

# ── Text loader ──────────────────────────────────────────────────────────────

def _load_relevant() -> dict[str, dict]:
    if not RELEVANT_JSON.exists():
        return {}
    data = json.loads(RELEVANT_JSON.read_text(encoding="utf-8"))
    return {n.get("tender_id", ""): n for n in data}


def load_sample_text(sample: dict, relevant: dict[str, dict]) -> str:
    source_type = sample.get("source_type", "")

    if source_type == "ted_fulltext":
        txt_path = ROOT / sample["text_file"]
        if txt_path.exists():
            text = txt_path.read_text(encoding="utf-8", errors="replace")
            return text[:MAX_TEXT_CHARS]

    if source_type == "national_raw_text":
        notice = relevant.get(sample["tender_id"])
        if notice:
            raw = notice.get("_national_raw_text") or ""
            return raw[:MAX_TEXT_CHARS]

    logger.warning("No text found for sample %s", sample["id"])
    return ""

# ── Parsing & scoring ────────────────────────────────────────────────────────

def _parse_json_from_text(text: str) -> Optional[dict]:
    text = text.strip()
    # Strip markdown fences if model added them
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract first {...} block
        m2 = re.search(r"\{[\s\S]+\}", text)
        if m2:
            try:
                return json.loads(m2.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _norm_name(s: Any) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).lower().strip())


def score_field(field: str, predicted: Any, truth: Any) -> float:
    """Returns 0.0–1.0 field score. Null truth → always 1.0 (correct abstention or FP doesn't penalize)."""
    if truth is None:
        return 1.0  # don't penalize false positives, just note them

    if predicted is None:
        return 0.0  # missing

    if field in ("value_amount",):
        try:
            p, t = float(predicted), float(truth)
            if t == 0:
                return 1.0 if p == 0 else 0.0
            ratio = p / t
            if 0.9 <= ratio <= 1.1:
                return 1.0   # within 10%
            if 0.5 <= ratio <= 2.0:
                return 0.5   # within 2×
            return 0.0
        except (ValueError, TypeError):
            return 0.0

    if field in ("quantity", "contract_duration_months"):
        try:
            p, t = int(float(predicted)), int(float(truth))
            if p == t:
                return 1.0
            ratio = p / t if t else 0
            if 0.8 <= ratio <= 1.2:
                return 1.0
            if 0.5 <= ratio <= 2.0:
                return 0.5
            return 0.0
        except (ValueError, TypeError):
            return 0.0

    if field == "value_currency":
        return 1.0 if str(predicted).upper().strip() == str(truth).upper().strip() else 0.0

    if field == "deadline":
        # Normalise YYYY-MM-DD
        def _date(v: Any) -> str:
            s = re.sub(r"[^\d-]", "", str(v or ""))
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
            return m.group(0) if m else ""
        return 1.0 if _date(predicted) == _date(truth) else 0.0

    if field == "winner_name":
        p, t = _norm_name(predicted), _norm_name(truth)
        if p == t:
            return 1.0
        # Partial: core name words present
        t_words = set(w for w in t.split() if len(w) > 3)
        p_words = set(p.split())
        overlap = t_words & p_words
        if overlap and len(overlap) / len(t_words) >= 0.5:
            return 0.5
        return 0.0

    if field == "procurement_category":
        p, t = _norm_name(predicted), _norm_name(truth)
        if p == t:
            return 1.0
        t_words = set(w for w in t.split() if len(w) > 3)
        p_words = set(p.split())
        overlap = t_words & p_words
        if overlap and len(overlap) / max(len(t_words), 1) >= 0.4:
            return 0.5
        return 0.0

    return 0.0


SCORED_FIELDS = ["value_amount", "value_currency", "winner_name",
                 "quantity", "contract_duration_months", "deadline",
                 "procurement_category"]


def evaluate_extraction(predicted: dict, ground_truth: dict) -> dict[str, float]:
    scores: dict[str, float] = {}
    for field in SCORED_FIELDS:
        truth = ground_truth.get(field)
        pred = predicted.get(field)
        scores[field] = score_field(field, pred, truth)
    return scores


def avg_score(scores: dict[str, float], ground_truth: dict) -> float:
    """Average only over fields where ground truth is non-null (those are the real challenges)."""
    relevant = [f for f in SCORED_FIELDS if ground_truth.get(f) is not None]
    if not relevant:
        return 0.0
    return sum(scores[f] for f in relevant) / len(relevant)

# ── Main eval ────────────────────────────────────────────────────────────────

def run_eval(models: list[str], dry_run: bool = False) -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    samples = fixture["samples"]
    relevant = _load_relevant()

    # Load texts upfront
    texts: dict[str, str] = {}
    for s in samples:
        texts[s["id"]] = load_sample_text(s, relevant)
        logger.info("Sample %-6s %-30s text=%d chars", s["id"], s["label"], len(texts[s["id"]]))

    results: dict[str, list[dict]] = {m: [] for m in models}
    total_cost = 0.0

    for model_id in models:
        logger.info("\n=== Model: %s ===", model_id)
        model_results = []

        for sample in samples:
            sid = sample["id"]
            text = texts.get(sid, "")
            if not text:
                logger.warning("Skipping %s — no text", sid)
                model_results.append({"sample_id": sid, "error": "no text"})
                continue

            user_msg = USER_TEMPLATE.format(text=text)

            if dry_run:
                logger.info("  [DRY RUN] %s × %s — skipped", model_id, sid)
                model_results.append({
                    "sample_id": sid, "label": sample["label"],
                    "predicted": {f: None for f in SCORED_FIELDS},
                    "scores": {f: 0.0 for f in SCORED_FIELDS},
                    "avg_score": 0.0,
                    "latency_s": 0.0,
                    "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                    "raw_response": "[DRY RUN]",
                })
                continue

            t0 = time.time()
            error = None
            predicted = {}
            raw = ""
            usage = {}

            try:
                raw, usage = call_with_usage(model_id, SYSTEM_PROMPT, user_msg, EXTRACTION_MAX_TOKENS)
                parsed = _parse_json_from_text(raw)
                if parsed is None:
                    error = f"parse_failed: {raw[:200]}"
                    predicted = {}
                else:
                    predicted = parsed
            except Exception as exc:
                error = str(exc)
                logger.error("  %s × %s ERROR: %s", model_id, sid, exc)

            latency = time.time() - t0
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            cost = estimate_cost_usd(model_id, in_tok, out_tok)
            total_cost += cost

            gt = sample["ground_truth"]
            scores = evaluate_extraction(predicted, gt) if predicted else {f: 0.0 for f in SCORED_FIELDS}
            a_score = avg_score(scores, gt)

            logger.info(
                "  %s × %s: score=%.2f lat=%.1fs in=%d out=%d cost=$%.4f%s",
                model_id[-20:], sid, a_score, latency, in_tok, out_tok, cost,
                f" ERR={error[:60]}" if error else "",
            )

            model_results.append({
                "sample_id": sid,
                "label": sample["label"],
                "predicted": predicted,
                "ground_truth": gt,
                "scores": scores,
                "avg_score": a_score,
                "latency_s": round(latency, 2),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": round(cost, 5),
                "error": error,
                "raw_response": raw[:500],
            })

        results[model_id] = model_results
        time.sleep(1)  # brief pause between models

    logger.info("\nTotal cost: $%.4f", total_cost)
    return {"results": results, "total_cost": total_cost, "dry_run": dry_run}

# ── Report generation ────────────────────────────────────────────────────────

def _model_label(model_id: str) -> str:
    parts = model_id.split("/")
    return parts[-1] if len(parts) > 1 else model_id


def generate_report(eval_data: dict, fixture: dict) -> str:
    results = eval_data["results"]
    samples = fixture["samples"]
    models = list(results.keys())
    total_cost = eval_data.get("total_cost", 0.0)

    lines = [
        "# LLM Document Extraction Eval — BPW Defence Tender Radar",
        "",
        f"*Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')} (2026-05-09)*",
        "",
        "**Aufgabe:** 7 Felder aus 8 Verteidigungsausschreibungen extrahieren.",
        "5 Modelle × 8 Samples = 40 API-Calls.",
        "",
        "**Modelle:**",
    ]
    for m in models:
        lines.append(f"- `{m}`")
    lines += [
        "",
        f"**Gesamtkosten Eval:** ${total_cost:.4f} USD",
        "",
        "---",
        "",
        "## 1. Ergebnisse pro Modell × Sample (avg F1)",
        "",
    ]

    # Header row
    header = "| Sample | Label |" + "".join(f" {_model_label(m)[:22]} |" for m in models)
    sep = "|--------|-------|" + "".join(" --- |" for _ in models)
    lines += [header, sep]

    for s in samples:
        sid = s["id"]
        row = f"| {sid} | {s['label'][:28]} |"
        for m in models:
            m_res = results[m]
            sr = next((r for r in m_res if r.get("sample_id") == sid), None)
            if sr and sr.get("error") and "parse_failed" not in (sr.get("error") or ""):
                row += " ERR |"
            elif sr:
                sc = sr.get("avg_score", 0)
                emoji = "✅" if sc >= 0.8 else ("⚠" if sc >= 0.5 else "❌")
                row += f" {sc:.2f} {emoji} |"
            else:
                row += " — |"
        lines.append(row)

    # Aggregate per model
    lines += ["", "---", "", "## 2. Aggregat pro Modell", ""]
    lines.append("| Modell | Avg F1 | Avg Latenz | Cost/Call | Total Cost | Calls OK |")
    lines.append("| ------ | -----: | ---------: | --------: | ---------: | -------: |")
    for m in models:
        m_res = results[m]
        ok = [r for r in m_res if not r.get("error") or "parse_failed" in (r.get("error") or "")]
        scores = [r["avg_score"] for r in ok if "avg_score" in r]
        lats = [r["latency_s"] for r in ok if "latency_s" in r]
        costs = [r["cost_usd"] for r in ok if "cost_usd" in r]
        avg_f1 = sum(scores) / len(scores) if scores else 0
        avg_lat = sum(lats) / len(lats) if lats else 0
        avg_cost = sum(costs) / len(costs) if costs else 0
        tot_cost = sum(costs)
        lines.append(
            f"| `{_model_label(m)}` | **{avg_f1:.3f}** | {avg_lat:.1f}s"
            f" | ${avg_cost:.4f} | ${tot_cost:.4f} | {len(ok)}/{len(m_res)} |"
        )

    # Per-field breakdown
    lines += ["", "---", "", "## 3. Feld-Score pro Modell (avg über alle Samples)", ""]
    field_header = "| Feld |" + "".join(f" {_model_label(m)[:18]} |" for m in models)
    field_sep = "| ---- |" + "".join(" --- |" for _ in models)
    lines += [field_header, field_sep]

    for field in SCORED_FIELDS:
        row = f"| `{field}` |"
        for m in models:
            m_res = results[m]
            field_scores = [
                r["scores"][field] for r in m_res
                if "scores" in r and field in r["scores"]
                and r.get("ground_truth", {}).get(field) is not None  # only scored when GT non-null
            ]
            avg = sum(field_scores) / len(field_scores) if field_scores else None
            if avg is None:
                row += " — |"
            else:
                row += f" {avg:.2f} |"
        lines.append(row)

    # Qualitative observations per model (based on scores)
    lines += ["", "---", "", "## 4. Stärken/Schwächen pro Modell", ""]
    for m in models:
        m_res = results[m]
        ok = [r for r in m_res if "scores" in r and r.get("ground_truth")]
        all_scores = [r["avg_score"] for r in ok]
        avg_f1 = sum(all_scores) / len(all_scores) if all_scores else 0

        # Best and worst samples
        ok_sorted = sorted(ok, key=lambda r: r.get("avg_score", 0), reverse=True)
        best = ok_sorted[0] if ok_sorted else None
        worst = ok_sorted[-1] if ok_sorted else None

        # Field weaknesses
        weak_fields = []
        for field in SCORED_FIELDS:
            fs = [r["scores"][field] for r in ok
                  if field in r["scores"]
                  and r.get("ground_truth", {}).get(field) is not None]
            if fs and sum(fs) / len(fs) < 0.6:
                weak_fields.append(field)

        lines += [
            f"### {_model_label(m)}",
            "",
            f"**Avg F1: {avg_f1:.3f}**",
            "",
        ]
        if best:
            lines.append(f"- Bestes Sample: `{best['label']}` (score={best['avg_score']:.2f})")
        if worst and worst != best:
            lines.append(f"- Schwächstes Sample: `{worst['label']}` (score={worst['avg_score']:.2f})")
        if weak_fields:
            lines.append(f"- Schwache Felder (<0.60 avg): {', '.join(f'`{f}`' for f in weak_fields)}")
        lines.append("")

        # Show a sample prediction for context
        if ok:
            r0 = ok[0]
            lines += [
                f"*Beispiel-Output ({r0['label']}) — Latenz {r0.get('latency_s', 0):.1f}s:*",
                "```json",
                json.dumps(r0.get("predicted", {}), ensure_ascii=False, indent=2),
                "```",
                "",
            ]

    # Recommendation
    model_avgs = {}
    for m in models:
        m_res = results[m]
        ok = [r for r in m_res if "avg_score" in r]
        if ok:
            model_avgs[m] = sum(r["avg_score"] for r in ok) / len(ok)

    if model_avgs:
        best_model = max(model_avgs, key=model_avgs.get)
        current = "anthropic/claude-sonnet-4-6"
        current_score = model_avgs.get(current, 0)
        best_score = model_avgs[best_model]

        lines += [
            "---",
            "",
            "## 5. Empfehlung",
            "",
            f"**Bestes Modell:** `{best_model}` (avg F1 = {best_score:.3f})",
            f"**Aktuell in Production:** `{current}` (avg F1 = {current_score:.3f})",
            "",
        ]
        if best_model == current or best_score - current_score < 0.05:
            lines += [
                "**Empfehlung: Kein Wechsel.** Sonnet 4.6 liefert wettbewerbsfähige Qualität",
                "bei niedrigeren Kosten und direkter Anthropic-Integration.",
                "Migrations-Aufwand (0h) — kein Benefit.",
                "",
            ]
        else:
            lines += [
                f"**Empfehlung: Wechsel zu `{_model_label(best_model)}`** prüfen.",
                "",
                "**Migrations-Schritte:**",
                f"1. `src/enricher.py`: `MODEL = '{best_model}'` setzen (oder via llm_router)",
                "2. OpenRouter-Key in .env pflegen (bereits vorhanden: `LLM_OPENROUTER_API_KEY`)",
                "3. `src/llm_router.py` im Enricher einbinden statt direktem Anthropic-Call",
                "4. Smoke-Test: 5 Sample-Tenders re-enrichen, Ergebnisse prüfen",
                "",
                "**Risiken:**",
                "- JSON-Format-Treue variiert je nach Modell (Mistral/GPT gelegentlich Markdown-Fences)",
                "- Latenz kann höher sein (Gemini 2.5 Pro: 10-30s bei langen Dokumenten)",
                "- Kosten eventuell höher bei Opus-Wechsel (+5×)",
                "",
            ]

    # Summary
    sorted_models = sorted(model_avgs.items(), key=lambda x: x[1], reverse=True)
    lines += [
        "---",
        "",
        "## 6. 5-Punkt-Summary",
        "",
        "**1. Bestes Modell pro Aspekt:**",
    ]
    if sorted_models:
        lines.append(f"- Qualität: `{_model_label(sorted_models[0][0])}` (F1={sorted_models[0][1]:.3f})")
        # Cost: find cheapest with decent score
        min_cost_model = min(
            [(m, sum(r["cost_usd"] for r in results[m] if "cost_usd" in r)) for m in models],
            key=lambda x: x[1]
        )
        lines.append(f"- Kosten: `{_model_label(min_cost_model[0])}` (${min_cost_model[1]:.4f} total)")
        # Latency
        min_lat_model = min(
            [(m, sum(r.get("latency_s", 99) for r in results[m] if "latency_s" in r) /
              max(1, len([r for r in results[m] if "latency_s" in r]))) for m in models],
            key=lambda x: x[1]
        )
        lines.append(f"- Latenz: `{_model_label(min_lat_model[0])}` ({min_lat_model[1]:.1f}s avg)")

    if model_avgs:
        best_model = max(model_avgs, key=model_avgs.get)
        lines += [
            "",
            f"**2. Production-Empfehlung:** `{_model_label(best_model)}`",
            f"Begründung: Höchster avg F1 ({model_avgs[best_model]:.3f}) über alle 8 Samples.",
            "",
            "**3. Beispiel Modell-Stärke/Schwäche:**",
            "  (Details in Abschnitt 4 — pro Modell Stärken/Schwächen-Analyse)",
            "",
            f"**4. Migrations-Aufwand:** {'0h (kein Wechsel empfohlen)' if best_model == current else '~4h (llm_router einbinden, Tests, Smoke-Run)'}",
            "",
            f"**5. Eval-Gesamtkosten:** ${total_cost:.4f} USD ({len(models) * len(samples)} API-Calls)",
        ]

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip API calls, generate report skeleton")
    parser.add_argument("--models", nargs="+", default=MODELS,
                        help="Model IDs to test")
    parser.add_argument("--out", default=str(OUT_MD),
                        help="Output markdown path")
    args = parser.parse_args()

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    print(f"\n[Eval] {len(args.models)} models × {len(fixture['samples'])} samples = "
          f"{len(args.models) * len(fixture['samples'])} API calls")
    if args.dry_run:
        print("[Eval] DRY RUN — no actual API calls")

    eval_data = run_eval(args.models, dry_run=args.dry_run)
    report = generate_report(eval_data, fixture)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\n[OK] Report written: {out}")
    print(f"[OK] Total cost: ${eval_data['total_cost']:.4f} USD")


if __name__ == "__main__":
    main()

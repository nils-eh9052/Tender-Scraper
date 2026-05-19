"""Multi-model eval for the three remaining AI steps (Sprint 2026-05-11).

Replicates ``scripts/_model_eval_documents.py`` methodology for:
1. **Classifier**     — binary defence-relevance + trailer-type + qty
2. **Translator**     — non-English title → English title
3. **Award-Match**    — closed-tender + 5 candidates → match-id|null

Models tested per step:
  anthropic/claude-sonnet-4-6
  anthropic/claude-opus-4-7
  openrouter/openai/gpt-4o
  openrouter/google/gemini-2.5-pro      (max_tokens=800 — Gemini hangs at 400)
  openrouter/anthropic/claude-haiku-4-5
  openrouter/mistralai/mistral-large

Total calls: 3 steps × 6 models × 10 samples = 180. Budget ≤ $20.

Run from ``ted-scraper/ted-scraper/``::

    python3 scripts/_model_eval_steps.py
    python3 scripts/_model_eval_steps.py --dry-run
    python3 scripts/_model_eval_steps.py --steps classifier
    python3 scripts/_model_eval_steps.py --models anthropic/claude-sonnet-4-6
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


# Workspace-aware .env loading (workspace-root .env.local + repo-local .env).
from src.env_loader import load_env_chain  # noqa: E402
load_env_chain(repo_root=ROOT)

# llm_router reads OPENROUTER_API_KEY or LLM_OPENROUTER_API_KEY — alias here
# for compatibility with callers that only set the legacy name.
if not os.environ.get("OPENROUTER_API_KEY") and os.environ.get("LLM_OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = os.environ["LLM_OPENROUTER_API_KEY"]

from src.llm_router import call_with_usage, estimate_cost_usd  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODELS_DEFAULT: list[str] = [
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-opus-4-7",
    "openrouter/openai/gpt-4o",
    "openrouter/google/gemini-2.5-pro",
    "openrouter/anthropic/claude-haiku-4-5",
    "openrouter/mistralai/mistral-large",
]

# Per-step max-tokens: Gemini fails at < 800 for structured output, others fine at 400.
def _max_tokens_for(model_id: str, step: str) -> int:
    if "gemini" in model_id:
        return 800
    return {
        "classifier": 500,
        "translator": 200,
        "award_match": 400,
    }[step]


# ── Prompt templates ────────────────────────────────────────────────────

CLASSIFIER_SYSTEM = """You are a strict defence-procurement analyst. Given a tender notice, decide whether it concerns a TRAILER (not truck-mounted bed, not tank, not generic vehicle) being procured by a DEFENCE/MILITARY authority.

Return ONLY a JSON object:
{
  "is_defence_relevant": true|false,
  "trailer_type": "<short specific type or null>",
  "trailer_quantity": <integer or null>
}

Rules:
- A truck or APC with a body mounted on it is NOT a trailer (return false).
- A trailer pulled by a vehicle, including semi-trailers and low-bed transporters, IS a trailer.
- trailer_type: short specific phrase (e.g. "Low-bed semi-trailer", "Field kitchen trailer"). null if not a trailer.
- trailer_quantity: firm quantity in primary slot only; null if unstated.
- Output ONLY the JSON, no markdown fences."""

CLASSIFIER_USER = """NOTICE:
Country: {country}
Title: {title}
Description: {description}

Decide is_defence_relevant + extract trailer_type + trailer_quantity."""

TRANSLATOR_SYSTEM = """You translate procurement-tender titles into concise, accurate English. Keep technical terminology (CPV codes, vehicle types, lot numbers). Output ONLY the English title, no quotes, no prefix, no explanatory commentary."""

TRANSLATOR_USER = """Country: {country}
Original title: {title}
Description excerpt: {description}

Translate the title to English."""

AWARD_MATCH_SYSTEM = """You are a defence-procurement analyst tasked with award-notice matching.

A "Closed" tender has no winner data on file. Below are the closed tender and up to five award-bearing notices from the same country and time window. Decide whether ONE of the candidates is the award notice for the closed tender (i.e. the same procurement, just the result publication).

Two notices are the SAME procurement when they refer to identical subject matter, the same buyer (or a clearly subordinate organ of the same ministry), and the candidate's publication date is plausible (typically 0–18 months AFTER the closed tender's publication date).

If no candidate is the matching award notice, answer with match_id: null.

Return STRICT JSON only, no markdown:
{
  "match_id": "<candidate_tender_id>" | null,
  "confidence": 0-100,
  "reasoning": "one or two short sentences"
}"""

AWARD_MATCH_USER = """CLOSED TENDER:
{target_block}

CANDIDATES:
{candidates_block}

Pick the matching candidate (or null) and rate confidence."""


def _format_award_block(notice: dict, label: str) -> str:
    return (
        f"{label}:\n"
        f"  id: {notice.get('tender_id')}\n"
        f"  title: {notice.get('title')}\n"
        f"  authority: {notice.get('authority')}\n"
        f"  country: {notice.get('country')}\n"
        f"  pub_date: {notice.get('pub_date')}\n"
        f"  cpv: {', '.join(notice.get('cpv_codes', []))}\n"
        f"  winner: {notice.get('winner_name') or '—'}\n"
    )


# ── JSON parser ──

def _parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m2 = re.search(r"\{[\s\S]+\}", text)
        if m2:
            try:
                return json.loads(m2.group(0))
            except json.JSONDecodeError:
                pass
    return None


# ── Scoring ──

def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").lower().strip())


def score_classifier(predicted: dict, gt: dict) -> dict[str, float]:
    scores: dict[str, float] = {}
    # is_defence_relevant — strict bool
    p_rel = bool(predicted.get("is_defence_relevant"))
    t_rel = bool(gt.get("is_defence_relevant"))
    scores["is_defence_relevant"] = 1.0 if p_rel == t_rel else 0.0
    # trailer_type — semantic overlap
    p_type, t_type = _norm(predicted.get("trailer_type")), _norm(gt.get("trailer_type"))
    if t_type == "":
        # GT null — predicted should also be null/empty
        scores["trailer_type"] = 1.0 if p_type == "" else 0.5
    elif p_type == "":
        scores["trailer_type"] = 0.0
    else:
        # Token overlap (3+ char meaningful words)
        t_words = {w for w in t_type.split() if len(w) > 3}
        p_words = set(p_type.split())
        overlap = t_words & p_words
        if t_words and len(overlap) / len(t_words) >= 0.5:
            scores["trailer_type"] = 1.0
        elif overlap:
            scores["trailer_type"] = 0.5
        else:
            scores["trailer_type"] = 0.0
    # trailer_quantity — exact int OR within 20%
    p_qty, t_qty = predicted.get("trailer_quantity"), gt.get("trailer_quantity")
    if t_qty is None:
        scores["trailer_quantity"] = 1.0 if p_qty is None else 0.5
    elif p_qty is None:
        scores["trailer_quantity"] = 0.0
    else:
        try:
            pi, ti = int(float(p_qty)), int(float(t_qty))
            if pi == ti:
                scores["trailer_quantity"] = 1.0
            else:
                ratio = pi / ti if ti else 0
                if 0.8 <= ratio <= 1.2:
                    scores["trailer_quantity"] = 1.0
                elif 0.5 <= ratio <= 2.0:
                    scores["trailer_quantity"] = 0.5
                else:
                    scores["trailer_quantity"] = 0.0
        except (ValueError, TypeError):
            scores["trailer_quantity"] = 0.0
    return scores


def score_translator(predicted: str, sample: dict) -> dict[str, float]:
    pred = _norm(predicted or "")
    gt = _norm(sample["ground_truth_title_en"])
    must_contain = [_norm(s) for s in sample.get("must_contain", [])]
    must_not_contain = [_norm(s) for s in sample.get("must_not_contain", [])]

    # Hard-fail: any "must_not_contain" present (untranslated source token)
    if any(forbid in pred for forbid in must_not_contain if forbid):
        return {"contains_forbidden": 0.0, "contains_required": 0.0, "token_overlap": 0.0}

    contains_required = 1.0 if all(req in pred for req in must_contain) else 0.0
    # Token overlap (≥4-char content words)
    gt_words = {w for w in re.findall(r"\b\w{4,}\b", gt)}
    pred_words = set(re.findall(r"\b\w{4,}\b", pred))
    if gt_words:
        overlap = len(gt_words & pred_words) / len(gt_words)
    else:
        overlap = 1.0 if pred else 0.0
    return {
        "contains_forbidden": 1.0,        # passed the must_not_contain check
        "contains_required":  contains_required,
        "token_overlap":      round(overlap, 2),
    }


def score_award_match(predicted: dict, gt: dict) -> dict[str, float]:
    p_id = predicted.get("match_id")
    t_id = gt.get("match_id")
    p_conf = predicted.get("confidence")
    try:
        p_conf = int(p_conf or 0)
    except (TypeError, ValueError):
        p_conf = 0

    # match-id correctness
    match_score = 1.0 if str(p_id or "") == str(t_id or "") else 0.0

    # confidence calibration
    cal_score = 1.0
    if t_id is None:
        # no_match expected — confidence_max
        max_allowed = gt.get("expected_confidence_max", 60)
        if p_id is None:
            cal_score = 1.0 if p_conf <= max_allowed else 0.5
        else:
            cal_score = 0.0
    else:
        # match expected — confidence_min
        min_required = gt.get("expected_confidence_min", 60)
        if p_id == t_id:
            cal_score = 1.0 if p_conf >= min_required else 0.5
        else:
            cal_score = 0.0

    return {"match_id": match_score, "confidence_calibration": cal_score}


# ── Per-step orchestration ───────────────────────────────────────────────

def _run_classifier(model_id: str, samples: list[dict]) -> list[dict]:
    out = []
    for sample in samples:
        # In the real pipeline the classifier sees JSON + many fields; for the
        # eval we rebuild a minimal-but-realistic prompt context.
        notice_id = sample["tender_id"]
        # Read context from relevant.json to give the model real description text
        rel = json.loads((ROOT / "data" / "filtered" / "relevant.json").read_text())
        n = next((x for x in rel if x.get("tender_id") == notice_id), {})
        title = n.get("_title_final") or n.get("_title_english") or n.get("title") or ""
        if isinstance(title, dict):
            title = title.get("eng") or next(iter(title.values()), "") or ""
        description = (n.get("description_en") or n.get("_description_english")
                       or n.get("description") or "")[:1500]
        if isinstance(description, dict):
            description = description.get("eng") or next(iter(description.values()), "") or ""
        country = sample.get("country", "")

        user = CLASSIFIER_USER.format(country=country, title=title, description=description)
        result = _exec_call(model_id, "classifier", CLASSIFIER_SYSTEM, user)
        result["sample_id"] = sample["id"]
        result["label"] = sample["label"]
        result["scores"] = score_classifier(result["parsed"] or {}, sample["ground_truth"]) if result["parsed"] else {
            "is_defence_relevant": 0.0, "trailer_type": 0.0, "trailer_quantity": 0.0,
        }
        result["avg_score"] = sum(result["scores"].values()) / len(result["scores"])
        out.append(result)
    return out


def _run_translator(model_id: str, samples: list[dict]) -> list[dict]:
    out = []
    for sample in samples:
        inp = sample["input"]
        user = TRANSLATOR_USER.format(country=inp.get("country", ""),
                                      title=inp["title"],
                                      description=inp.get("description", "")[:300])
        result = _exec_call(model_id, "translator", TRANSLATOR_SYSTEM, user, parse_json=False)
        result["sample_id"] = sample["id"]
        result["label"] = sample["label"]
        # Translator output is plain text, not JSON
        translated = (result.get("raw") or "").strip().strip('"\'').strip()
        # Drop trailing period
        if translated.endswith(".") and not translated.endswith(".."):
            translated = translated[:-1]
        result["translated"] = translated
        result["scores"] = score_translator(translated, sample)
        result["avg_score"] = sum(result["scores"].values()) / len(result["scores"])
        out.append(result)
    return out


def _run_award_match(model_id: str, samples: list[dict]) -> list[dict]:
    out = []
    for sample in samples:
        target_block = _format_award_block(sample["target"], "TARGET")
        cand_blocks = "\n".join(
            _format_award_block(c, f"CANDIDATE {i+1}") for i, c in enumerate(sample["candidates"])
        )
        user = AWARD_MATCH_USER.format(target_block=target_block, candidates_block=cand_blocks)
        result = _exec_call(model_id, "award_match", AWARD_MATCH_SYSTEM, user)
        result["sample_id"] = sample["id"]
        result["label"] = sample["label"]
        if result.get("parsed"):
            result["scores"] = score_award_match(result["parsed"], sample["ground_truth"])
        else:
            result["scores"] = {"match_id": 0.0, "confidence_calibration": 0.0}
        result["avg_score"] = sum(result["scores"].values()) / len(result["scores"])
        out.append(result)
    return out


def _exec_call(model_id: str, step: str, system: str, user: str,
               parse_json: bool = True) -> dict:
    """One LLM call with timing + token tracking + cost. Returns standard dict."""
    t0 = time.time()
    raw, usage, error = "", {}, None
    parsed: Optional[dict] = None
    try:
        raw, usage = call_with_usage(model_id, system, user, _max_tokens_for(model_id, step))
        if parse_json:
            parsed = _parse_json(raw)
            if parsed is None:
                error = "parse_failed"
    except Exception as exc:
        error = str(exc)
        logger.error("%s × %s ERROR: %s", model_id, step, exc)
    latency = time.time() - t0
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cost = estimate_cost_usd(model_id, in_tok, out_tok)
    return {
        "model_id": model_id, "step": step,
        "raw": raw, "parsed": parsed, "error": error,
        "latency_s": round(latency, 2),
        "input_tokens": in_tok, "output_tokens": out_tok,
        "cost_usd": round(cost, 4),
    }


# ── Main ─────────────────────────────────────────────────────────────────

STEP_RUNNERS = {
    "classifier":  _run_classifier,
    "translator":  _run_translator,
    "award_match": _run_award_match,
}

FIXTURE_PATHS = {
    "classifier":  ROOT / "tests" / "fixtures" / "classifier_eval_truth.json",
    "translator":  ROOT / "tests" / "fixtures" / "translator_eval_truth.json",
    "award_match": ROOT / "tests" / "fixtures" / "award_match_eval_truth.json",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", nargs="+",
                    default=list(STEP_RUNNERS.keys()),
                    choices=list(STEP_RUNNERS.keys()))
    ap.add_argument("--models", nargs="+", default=MODELS_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data" / "model_eval_steps_results.json")
    args = ap.parse_args()

    print(f"  Steps:  {args.steps}")
    print(f"  Models: {args.models}")
    print(f"  Total:  {len(args.steps) * len(args.models)} step×model combos × 10 samples")

    # Load fixtures
    fixtures: dict[str, dict] = {}
    for step, path in FIXTURE_PATHS.items():
        if step not in args.steps:
            continue
        if not path.exists():
            print(f"  [!] Missing fixture: {path}")
            return 1
        fixtures[step] = json.loads(path.read_text(encoding="utf-8"))

    if args.dry_run:
        print("  [dry-run] no API calls")
        return 0

    all_results: dict[str, dict[str, list[dict]]] = {step: {} for step in args.steps}
    grand_total_cost = 0.0

    for step in args.steps:
        samples = fixtures[step]["samples"]
        runner = STEP_RUNNERS[step]
        for model_id in args.models:
            print(f"\n=== {step} × {model_id} ===")
            results = runner(model_id, samples)
            all_results[step][model_id] = results
            step_cost = sum(r["cost_usd"] for r in results)
            avg_score = sum(r["avg_score"] for r in results) / len(results) if results else 0
            n_ok = sum(1 for r in results if not r.get("error"))
            grand_total_cost += step_cost
            print(f"  → avg_score={avg_score:.3f}  ok={n_ok}/{len(results)}  cost=${step_cost:.4f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "models": args.models,
        "total_cost_usd": round(grand_total_cost, 4),
        "results": all_results,
    }, ensure_ascii=False, indent=2))
    print(f"\n  Total cost: ${grand_total_cost:.4f}")
    print(f"  Wrote raw results → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
AI-powered structured extraction from document text.

Default model : openrouter/openai/gpt-4o  (F1=0.911 in eval 2026-05-09)
Override env  : EXTRACTION_MODEL=<model_id>   e.g. anthropic/claude-sonnet-4-6
Fallback      : anthropic/claude-sonnet-4-6  (on OpenRouter error or JSON failure)

Output schema:
{
  "trailer_types": [
    {
      "type": str,          # e.g. "4-Axle Cargo Trailer"
      "qty": int|None,
      "mass_t": float|None, # GVW / payload in metric tons
      "length_mm": int|None,
      "width_mm": int|None,
      "height_mm": int|None,
      "axle_load_t": float|None,
      "payload_t": float|None,
    }
  ],
  "fuel_type": str|None,        # "diesel", "electric", etc.
  "drive_type": str|None,       # "4x4", "AWD", "trailer" etc.
  "coupling_type": str|None,    # "NATO", "king-pin", etc.
  "additional_equipment": [],   # list of strings
  "standards": [],              # e.g. ["STANAG 2021", "MIL-STD-1366"]
  "confidence": int,            # 0-100
  "source_doc_title": str,
  "notes": str,
}
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Model configuration ───────────────────────────────────────────────────────
_DEFAULT_MODEL = "openrouter/openai/gpt-4o"
_FALLBACK_MODEL = "anthropic/claude-sonnet-4-6"
MAX_TEXT_CHARS = 15_000
_MAX_TOKENS = 1200  # increased headroom for GPT-4o verbose outputs


def active_model() -> str:
    """Return the configured extraction model ID (env override or default)."""
    raw = os.environ.get("EXTRACTION_MODEL", "").strip()
    return raw if raw else _DEFAULT_MODEL


def cache_slug(model_id: str | None = None) -> str:
    """Short slug for use in cache keys, derived from model ID.

    Examples:
      "openrouter/openai/gpt-4o"      → "gpt-4o"
      "anthropic/claude-sonnet-4-6"   → "claude-sonnet-4-6"
      "openrouter/google/gemini-2.5-pro" → "gemini-2.5-pro"
    """
    mid = model_id or active_model()
    return mid.rstrip("/").split("/")[-1]


# ── Prompt ────────────────────────────────────────────────────────────────────
_SYSTEM = """You are a defence procurement analyst. Extract structured trailer/vehicle specifications from the document text below.

Return ONLY a valid JSON object (no markdown, no commentary) with this exact schema:
{
  "trailer_types": [
    {
      "type": "<short English description>",
      "qty": <integer or null>,
      "mass_t": <GVW in metric tons or null>,
      "length_mm": <integer mm or null>,
      "width_mm": <integer mm or null>,
      "height_mm": <integer mm or null>,
      "axle_load_t": <float tons or null>,
      "payload_t": <float tons or null>
    }
  ],
  "fuel_type": "<diesel|electric|hybrid|petrol|null>",
  "drive_type": "<description or null>",
  "coupling_type": "<NATO|king-pin|fifth-wheel|pintle|other|null>",
  "additional_equipment": ["<item>", ...],
  "standards": ["<standard>", ...],
  "confidence": <0-100 how confident you are the specs are correct>,
  "source_doc_title": "<document title if visible>",
  "notes": "<any important caveats>"
}

Rules:
- Prefer metric units. Convert if needed.
- If a field is truly unknown/absent, use null (not 0 or "").
- If multiple trailer types are listed, include each as a separate object in trailer_types.
- "mass_t" = Gross Vehicle Weight (total laden weight), NOT curb weight.
- "confidence" reflects how clearly the document states specs (not your general confidence).
"""


# ── Core call ─────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> Optional[dict]:
    """Strip code fences and parse JSON. Returns None on failure."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _call_model(model_id: str, user_msg: str) -> tuple[Optional[str], dict]:
    """Call model via llm_router; returns (raw_text, usage_dict)."""
    from src import llm_router
    try:
        text, usage = llm_router.call_with_usage(
            model_id, _SYSTEM, user_msg, max_tokens=_MAX_TOKENS
        )
        return text, usage
    except Exception as e:
        logger.warning(f"AI structurer: {model_id} call failed: {e}")
        return None, {}


# ── Public API ────────────────────────────────────────────────────────────────

def structure_with_ai(
    text: str,
    notice: dict,
    source_doc_title: str = "",
    anthropic_client=None,  # kept for backward compat (ignored — llm_router used)
) -> Optional[dict]:
    """Send text to the extraction model and return structured extracted_specs dict.

    Strategy:
      1. Call active_model() (default: gpt-4o via OpenRouter)
      2. On API error or JSON parse failure → retry once with same model
      3. If still failing → fall back to Sonnet 4.6 (Anthropic)
      4. Returns None only if all three attempts fail.

    Usage tracking is handled internally; cost is reflected in orchestrator stats.
    """
    if not text or not text.strip():
        return None

    trimmed = text[:MAX_TEXT_CHARS]
    title_hint = (notice.get("_title_final") or notice.get("title") or "")[:120]
    user_msg = f"Tender title (context): {title_hint}\n\nDocument text:\n{trimmed}"

    model = active_model()
    last_usage: dict = {}

    # Attempts: primary → primary retry → fallback
    attempts = [model, model, _FALLBACK_MODEL]
    for i, m in enumerate(attempts):
        is_fallback = m == _FALLBACK_MODEL and i == 2

        raw, usage = _call_model(m, user_msg)
        if usage:
            last_usage = usage

        if raw is None:
            if is_fallback:
                logger.error(f"AI structurer: all models failed for notice")
                return None
            logger.info(f"AI structurer: retry/fallback after failure on attempt {i+1}")
            continue

        result = _parse_json(raw)
        if result is not None:
            if is_fallback:
                logger.info(f"AI structurer: used Sonnet fallback (GPT-4o failed)")
                result["_extraction_model"] = _FALLBACK_MODEL
            else:
                result["_extraction_model"] = m
            if source_doc_title and not result.get("source_doc_title"):
                result["source_doc_title"] = source_doc_title
            return result

        logger.warning(f"AI structurer: JSON parse failed on attempt {i+1} — raw[:100]: {raw[:100]}")
        if is_fallback:
            return None

    return None


def get_usage_cost(usage: dict, model_id: str | None = None) -> float:
    """Estimate USD cost from a usage dict returned by llm_router."""
    from src import llm_router
    mid = model_id or active_model()
    return llm_router.estimate_cost_usd(
        mid,
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
    )

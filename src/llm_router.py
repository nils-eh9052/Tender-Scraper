"""
Minimal LLM router for BPW Defence Tender Radar — all calls via OpenRouter.

All model IDs are passed directly to OpenRouter (OpenAI-compatible endpoint).
The legacy "anthropic/<model>" prefix is supported and routed to OpenRouter,
which then forwards the call to the Anthropic model.

Usage:
    from src.llm_router import call, call_with_usage

    text = call("anthropic/claude-sonnet-4.6", system="...", user="...", max_tokens=500)
    text, usage = call_with_usage("google/gemini-2.5-pro", system="...", user="...")

Env vars:
  LLM_OPENROUTER_API_KEY or OPENROUTER_API_KEY — required
  SSL_VERIFY_DISABLE=1                          — bypass SSL (corporate VPN)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
import urllib3

logger = logging.getLogger(__name__)

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MAX_RETRIES = 3

# USD per 1M tokens (input, output) — approximate 2026-05 pricing
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6":          (3.0,   15.0),
    "claude-opus-4-7":            (15.0,  75.0),
    "anthropic/claude-opus-4.1":  (15.0,  75.0),  # via OpenRouter
    "anthropic/claude-opus-4":    (15.0,  75.0),  # via OpenRouter
    "anthropic/claude-sonnet-4-6":(3.0,   15.0),  # via OpenRouter
    "google/gemini-2.5-pro":      (1.25,  10.0),
    "openai/gpt-4o":              (2.5,   10.0),
    "mistralai/mistral-large":    (2.0,    6.0),
}


def _openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_OPENROUTER_API_KEY") or ""
    if not key:
        raise EnvironmentError("Set OPENROUTER_API_KEY or LLM_OPENROUTER_API_KEY")
    return key


def _call_openrouter(model: str, system: str, user: str, max_tokens: int) -> tuple[str, dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_openrouter_key()}",
        "HTTP-Referer": "https://bpw-tender-radar.internal",
        "X-Title": "BPW Defence Tender Radar",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.post(_OPENROUTER_URL, json=payload, headers=headers,
                              verify=_SSL_VERIFY, timeout=180)
            if r.status_code == 429:
                wait = 8 * (attempt + 1)
                logger.warning("OpenRouter 429 — retry in %.0fs", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"OpenRouter error: {data['error']}")
            text = data["choices"][0]["message"]["content"]
            usage_raw = data.get("usage", {})
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
            }
            return text, usage
        except Exception as exc:
            if attempt == _MAX_RETRIES - 1:
                raise RuntimeError(f"OpenRouter [{model}] failed: {exc}") from exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def call(model_id: str, system: str, user: str, max_tokens: int = 2000) -> str:
    """Call OpenRouter and return completion text.

    model_id: any OpenRouter-compatible model ID, e.g. "anthropic/claude-sonnet-4.6"
    The legacy "openrouter/" prefix is stripped for backward compatibility.
    """
    text, _ = call_with_usage(model_id, system, user, max_tokens)
    return text


def call_with_usage(model_id: str, system: str, user: str,
                    max_tokens: int = 2000) -> tuple[str, dict[str, Any]]:
    """Like call() but returns (text, usage_dict) where usage has input/output token counts."""
    # Strip legacy "openrouter/" prefix if present
    if model_id.startswith("openrouter/"):
        model_id = model_id[len("openrouter/"):]
    return _call_openrouter(model_id, system, user, max_tokens)


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost in USD given token usage."""
    bare = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    price_in, price_out = PRICE_TABLE.get(bare, (5.0, 20.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

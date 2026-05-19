"""
LLM-based award matcher (Sprint Top-1 recommendation, 2026-05-08).

Additive layer on top of ``src/award_matcher.py``. The heuristic matcher
runs first and matches Award-Notices via TED-API search by CPV + buyer +
date. Whatever the heuristic could not match is the input for this layer:
a Claude Haiku 4.5 reasoner (default since Sprint 14i, 2026-05-12) that
compares the unmatched tender against the top-N existing award-bearing
notices already in ``relevant.json`` and decides whether one of them is
the missing award.

**Model migration (2026-05-12):** Default switched from `claude-sonnet-4-6`
to `claude-haiku-4-5` based on ``docs/MODEL_EVAL_STEPS_260511.md`` (F1
0.825 → 1.000, +17.5pp; latency halved). Override via env var
``AWARD_MATCH_MODEL`` if needed. Cache keys now include the model id, so
old Sonnet entries do not poison new Haiku results.

Why a separate module
---------------------
* The heuristic matcher uses *external* TED-API queries, costs no API
  tokens, and writes ``data/.award_match_log.json``.
* The LLM matcher uses *internal* candidates from ``relevant.json``,
  costs Anthropic tokens, and writes ``data/.award_match_llm_log.json``.
* Both write to ``notice["award"]`` — but with different provenance flags
  (``_from_award_match`` vs. ``_from_award_match_llm``) so the source of
  every match remains auditable.

Cache structure
---------------
``data/.award_match_llm_log.json``::

    {
      "<tender_id>:<model_slug>": {        # <- key includes model since 14i
        "match":            "<award_notice_id>" | null,
        "confidence":       0..100,
        "reasoning":        "<one or two sentences>",
        "candidate_ids":    [...],
        "applied":          true|false,
        "model":            "claude-haiku-4-5",
        "ts":               "2026-05-12 09:21:55"
      },
      ...
    }

Re-runs hit the cache for every cached tender (matching tender_id AND
model) and make zero API calls unless ``LLMAwardMatcher.clear_log()`` is
called or specific tender IDs are passed via ``force_ids=``. Switching
model (`AWARD_MATCH_MODEL=...`) automatically forces fresh calls because
the cache key changes.

Backwards compatibility: legacy entries keyed by plain ``tender_id``
(pre-14i) are still **read** as a fallback when no model-keyed entry
exists. They are NOT promoted into model-keyed entries — re-running with
Haiku writes new entries side-by-side under ``"<tender_id>:claude-haiku-4-5"``.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import re
import time
import urllib3
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ── SSL handling mirrors classifier.py (corporate VPN with self-signed cert)
_SSL_VERIFY = (
    os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
    not in ("1", "true", "yes")
)
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration
LLM_LOG_PATH = Path(__file__).parent.parent / "data" / ".award_match_llm_log.json"

# Default model — Haiku 4.5 since Sprint 14i (2026-05-12) per MODEL_EVAL_STEPS_260511.md
# Override via env var AWARD_MATCH_MODEL.
DEFAULT_MODEL = os.environ.get("AWARD_MATCH_MODEL", "anthropic/claude-haiku-4.5").strip() or "anthropic/claude-haiku-4.5"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Pricing per 1M tokens (USD). Lookup by model id (bare slug after last "/").
_PRICING = {
    "claude-haiku-4.5":  (1.0,  5.0),
    "claude-sonnet-4.6": (3.0, 15.0),
    "claude-opus-4.6":   (15.0, 75.0),
    # Legacy bare names kept for backward compat with old cache entries
    "claude-haiku-4-5":  (1.0,  5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}


def _model_pricing(model: str) -> tuple[float, float]:
    return _PRICING.get(model, (3.0, 15.0))


def cache_slug(model: str) -> str:
    """Stable cache-key suffix derived from a model id."""
    # Strip any vendor prefix (e.g. "anthropic/claude-haiku-4-5" → "claude-haiku-4-5")
    return model.rsplit("/", 1)[-1].strip()


def _cache_key(tender_id: str, model: str) -> str:
    return f"{tender_id}:{cache_slug(model)}"

# Match acceptance threshold (per Sprint spec).
DEFAULT_CONFIDENCE_MIN = 75

# Pre-filter for candidate selection.
DATE_WINDOW_DAYS = 365
TOP_CANDIDATES = 5


# ────────────────────────────────────────────────────────────────────
# Pure helpers (testable without API key)
# ────────────────────────────────────────────────────────────────────

def _norm_str(value: Any) -> str:
    """Flatten dict/list multilingual fields to a single string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        # Prefer English, then German, then any value
        for k in ("eng", "en", "deu", "de"):
            if value.get(k):
                v = value[k]
                if isinstance(v, list):
                    return " ".join(str(x) for x in v if x)
                return str(v)
        return " ".join(str(v) for v in value.values() if v)
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return str(value)


def _title(notice: dict) -> str:
    return _norm_str(
        notice.get("_title_english")
        or notice.get("_title_final")
        or notice.get("title")
    )


def _authority(notice: dict) -> str:
    ca = notice.get("contracting_authority") or {}
    if isinstance(ca, dict):
        return _norm_str(ca.get("name") or ca.get("name_short") or "")
    return _norm_str(ca) or _norm_str(notice.get("_authority_name"))


def _country(notice: dict) -> str:
    ca = notice.get("contracting_authority") or {}
    if isinstance(ca, dict):
        c = _norm_str(ca.get("country"))
        if c:
            return c.split("\n")[0].strip()
    return _norm_str(notice.get("_country_normalized"))


def _pub_date_iso(notice: dict) -> Optional[str]:
    s = notice.get("_pub_date") or notice.get("_pub_date_clean")
    if not s:
        raw = notice.get("_raw") or {}
        if isinstance(raw, dict):
            s = raw.get("publication-date")
    if not s:
        return None
    s = str(s).strip()
    if "T" in s:
        s = s.split("T")[0]
    s = s.split("+")[0].split("Z")[0][:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


def _has_award(notice: dict) -> bool:
    award = notice.get("award") or {}
    if isinstance(award, dict) and (award.get("awarded") or award.get("winner_name")):
        return True
    if notice.get("_winner_name"):
        return True
    if notice.get("_status") == "Awarded":
        return True
    return False


def _has_winner(notice: dict) -> bool:
    award = notice.get("award") or {}
    if isinstance(award, dict) and award.get("winner_name"):
        return True
    return bool(notice.get("_winner_name"))


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b\w{3,}\b", text.lower()))


def _cpv_set(notice: dict, prefix_len: int = 5) -> set[str]:
    return {c[:prefix_len] for c in (notice.get("cpv_codes") or []) if c}


def _score_candidate(target: dict, candidate: dict) -> float:
    """Heuristic score combining authority, title, and CPV similarity."""
    score = 0.0
    auth_target = _tokenize(_authority(target))
    auth_cand = _tokenize(_authority(candidate))
    score += len(auth_target & auth_cand) * 1.0

    title_target = _tokenize(_title(target))
    title_cand = _tokenize(_title(candidate))
    # Strip noise tokens (country-name prefix, defence) — they match too often
    noise = {"defence", "ministry", "trailers", "trailer", "semi", "and"}
    title_overlap = len((title_target & title_cand) - noise)
    score += title_overlap * 0.6

    cpv_target = _cpv_set(target)
    cpv_cand = _cpv_set(candidate)
    score += len(cpv_target & cpv_cand) * 0.7

    return score


def select_candidates(
    target: dict,
    pool: list[dict],
    *,
    top_n: int = TOP_CANDIDATES,
    date_window_days: int = DATE_WINDOW_DAYS,
) -> list[dict]:
    """Select up to ``top_n`` award-bearing candidates from ``pool``.

    Filters by same country (when both sides have a country) and by
    publication-date window (±``date_window_days`` days when both sides
    have a date). Ranks by ``_score_candidate``.
    """
    target_country = _country(target)
    target_pub_iso = _pub_date_iso(target)
    target_pub_d: Optional[_dt.date] = None
    if target_pub_iso:
        try:
            target_pub_d = _dt.date.fromisoformat(target_pub_iso)
        except ValueError:
            pass

    target_id = target.get("tender_id")
    scored: list[tuple[float, dict]] = []

    for cand in pool:
        if cand.get("tender_id") == target_id:
            continue
        if not _has_award(cand):
            continue

        cand_country = _country(cand)
        if target_country and cand_country and cand_country != target_country:
            continue

        cand_pub_iso = _pub_date_iso(cand)
        if target_pub_d and cand_pub_iso:
            try:
                cd = _dt.date.fromisoformat(cand_pub_iso)
                if abs((cd - target_pub_d).days) > date_window_days:
                    continue
            except ValueError:
                pass

        score = _score_candidate(target, cand)
        if score <= 0:
            continue
        scored.append((score, cand))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_n]]


# ────────────────────────────────────────────────────────────────────
# Prompt construction
# ────────────────────────────────────────────────────────────────────

def _format_notice_block(notice: dict, label: str) -> str:
    """Compact one-block summary used in both target and candidates."""
    award = notice.get("award") or {}
    winner = award.get("winner_name") or notice.get("_winner_name") or ""
    return (
        f"{label}:\n"
        f"  id: {notice.get('tender_id')}\n"
        f"  title: {_title(notice)[:240]}\n"
        f"  authority: {_authority(notice)[:120]}\n"
        f"  country: {_country(notice)}\n"
        f"  pub_date: {_pub_date_iso(notice) or 'unknown'}\n"
        f"  cpv: {', '.join((notice.get('cpv_codes') or [])[:6])}\n"
        f"  winner: {winner or '—'}\n"
    )


def build_prompt(target: dict, candidates: list[dict]) -> str:
    cand_blocks = "\n".join(
        _format_notice_block(c, f"CANDIDATE {i+1}")
        for i, c in enumerate(candidates)
    ) or "  (no candidates available)"

    return f"""You are a defence-procurement analyst tasked with award-notice matching.

A "Closed" tender has no winner data on file. Below are the closed tender
and up to five award-bearing notices from the same country and time
window. Decide whether ONE of the candidates is the award notice for
the closed tender (i.e. the same procurement, just the result publication).

Two notices are the SAME procurement when they refer to identical
subject matter (same vehicles / lot composition), the same buyer (or a
clearly subordinate organ of the same ministry), and the candidate's
publication date is plausible (typically 0–18 months AFTER the closed
tender's publication date).

If no candidate is the matching award notice, answer with match: null.

Return STRICT JSON only, no markdown, no commentary:

{{
  "match": "<candidate_id>" | null,
  "confidence": 0-100,
  "reasoning": "one or two short sentences"
}}

Confidence guidance:
- 90-100: clear match (same lot description, same buyer, dates plausible)
- 75-89:  strong match (same buyer, very similar subject, dates fit)
- 50-74:  weak — likely related but unsure
- < 50:   not enough evidence

{_format_notice_block(target, "CLOSED TENDER")}
{cand_blocks}
"""


# ────────────────────────────────────────────────────────────────────
# The matcher
# ────────────────────────────────────────────────────────────────────

class LLMAwardMatcher:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        confidence_min: int = DEFAULT_CONFIDENCE_MIN,
    ):
        self.api_key = api_key or (
            os.environ.get("LLM_OPENROUTER_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or None
        )
        self.model = model
        self.cache_slug = cache_slug(model)
        self.price_in, self.price_out = _model_pricing(model)
        self.confidence_min = confidence_min
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or ''}",
            "HTTP-Referer": "https://bpw-tender-radar.internal",
            "X-Title": "BPW Defence Tender Radar",
        })
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.api_calls = 0

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    # ── Cache ────────────────────────────────────────────────────────

    @staticmethod
    def _load_log() -> dict:
        if LLM_LOG_PATH.exists():
            with open(LLM_LOG_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_log(log: dict) -> None:
        LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LLM_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

    @staticmethod
    def clear_log() -> None:
        if LLM_LOG_PATH.exists():
            LLM_LOG_PATH.unlink()

    # ── API call ─────────────────────────────────────────────────────

    def call_llm(
        self,
        target: dict,
        candidates: list[dict],
        max_retries: int = 3,
    ) -> dict:
        prompt = build_prompt(target, candidates)
        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    _OPENROUTER_URL,
                    json={
                        "model": self.model,
                        "max_tokens": 400,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                logger.warning("OpenRouter call failed (attempt %d): %s", attempt + 1, exc)
                if attempt + 1 < max_retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                return {"match": None, "confidence": 0, "reasoning": f"network: {exc}"}

            if resp.status_code == 200:
                body = resp.json()
                self.api_calls += 1
                usage = body.get("usage") or {}
                in_tok = int(usage.get("prompt_tokens") or 0)
                out_tok = int(usage.get("completion_tokens") or 0)
                self.input_tokens += in_tok
                self.output_tokens += out_tok
                self.cost_usd += in_tok * self.price_in / 1_000_000
                self.cost_usd += out_tok * self.price_out / 1_000_000

                text = body["choices"][0]["message"]["content"].strip()
                text = text.replace("```json", "").replace("```", "").strip()
                # Strip trailing commas before close-brace
                text = re.sub(r",\s*}", "}", text)
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    logger.warning("LLM returned non-JSON for %s: %s",
                                   target.get("tender_id"), exc)
                    return {"match": None, "confidence": 0,
                            "reasoning": f"json parse: {exc}",
                            "_raw_text": text[:400]}
                # Normalise
                conf = parsed.get("confidence")
                try:
                    conf = int(conf)
                except (TypeError, ValueError):
                    conf = 0
                return {
                    "match": parsed.get("match"),
                    "confidence": conf,
                    "reasoning": str(parsed.get("reasoning") or ""),
                }
            elif resp.status_code in (429, 529):
                wait = 5 * (attempt + 1)
                logger.warning("Rate-limit/overloaded (%s), waiting %ds", resp.status_code, wait)
                time.sleep(wait)
                continue
            else:
                logger.error("OpenRouter API error %s: %s", resp.status_code, resp.text[:200])
                return {"match": None, "confidence": 0,
                        "reasoning": f"HTTP {resp.status_code}"}

        return {"match": None, "confidence": 0, "reasoning": "all retries exhausted"}

    # ── Match application ────────────────────────────────────────────

    @staticmethod
    def _apply_award(target: dict, award_notice: dict, confidence: int) -> dict:
        """Insert award block into target notice (additive, non-destructive)."""
        a = award_notice.get("award") or {}
        winner = a.get("winner_name") or award_notice.get("_winner_name") or ""
        if isinstance(winner, list):
            winner = winner[0] if winner else ""
        if isinstance(winner, dict):
            winner = next(iter(winner.values()), "") or ""

        existing = target.get("award") or {}
        if existing.get("winner_name"):
            return target  # never overwrite an already-set winner

        target = dict(target)
        target["award"] = {
            **existing,
            "winner_name": winner or None,
            "awarded": True,
            "_from_award_match_llm": True,
            "_award_notice_id": award_notice.get("tender_id"),
            "_match_confidence": confidence,
        }
        target["_award_matched_llm"] = True
        return target

    # ── Top-level batch ──────────────────────────────────────────────

    def match_batch(
        self,
        notices: list[dict],
        target_ids: Optional[list[str]] = None,
        force_refresh: bool = False,
        dry_run: bool = False,
    ) -> tuple[list[dict], dict]:
        """Run the matcher and return ``(updated_notices, summary)``.

        ``target_ids`` — restrict to these tender ids (else all unmatched).
        ``force_refresh`` — bypass cache for the targeted IDs.
        ``dry_run`` — go through candidate selection but skip API calls
        (useful for cost preview).
        """
        log = self._load_log()
        idx = {n.get("tender_id"): n for n in notices}

        # ── pick candidates ──
        if target_ids is not None:
            todo = [idx[t] for t in target_ids if t in idx]
        else:
            todo = [n for n in notices if not _has_winner(n)]

        summary = {
            "total_targets": len(todo),
            "cache_hits": 0,
            "api_calls": 0,
            "matched": 0,
            "rejected_low_confidence": 0,
            "no_candidates": 0,
            "no_match": 0,
            "applied": [],     # list of dict {target, match, confidence, reasoning}
            "skipped_no_api_key": False,
            "cost_usd": 0.0,
        }

        if not self.is_available and not dry_run:
            summary["skipped_no_api_key"] = True
            logger.warning("LLM matcher: LLM_OPENROUTER_API_KEY not set — skipping")
            return notices, summary

        updates: dict[str, dict] = {}

        for i, target in enumerate(todo):
            tid = target.get("tender_id")
            cache_key = _cache_key(tid, self.model)
            logger.info("LLM-match [%d/%d]: %s [%s]", i + 1, len(todo), tid, self.cache_slug)

            # Cache hit? Prefer model-keyed entry; legacy plain-tid entry is a
            # fallback for the slug currently set as DEFAULT_MODEL only — not
            # used when the active model differs from the legacy entry's model.
            cached = None
            if not force_refresh:
                if cache_key in log:
                    cached = log[cache_key]
                elif tid in log:
                    legacy = log[tid]
                    if isinstance(legacy, dict) and legacy.get("model") == self.model:
                        cached = legacy

            if cached is not None:
                summary["cache_hits"] += 1
                if cached.get("applied") and cached.get("match"):
                    award_notice = idx.get(cached["match"])
                    if award_notice:
                        updates[tid] = self._apply_award(
                            target, award_notice, cached.get("confidence", 0)
                        )
                        summary["matched"] += 1
                        summary["applied"].append({
                            "target": tid,
                            "match": cached["match"],
                            "confidence": cached.get("confidence", 0),
                            "reasoning": cached.get("reasoning", ""),
                            "from_cache": True,
                        })
                continue

            candidates = select_candidates(target, notices)
            if not candidates:
                summary["no_candidates"] += 1
                log[cache_key] = {
                    "match": None, "confidence": 0,
                    "reasoning": "no candidates after filtering",
                    "candidate_ids": [],
                    "applied": False,
                    "model": self.model,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                continue

            if dry_run:
                # No API call; just log who would be evaluated
                log[cache_key] = {
                    "match": None, "confidence": 0,
                    "reasoning": "dry_run",
                    "candidate_ids": [c.get("tender_id") for c in candidates],
                    "applied": False,
                    "model": self.model,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                continue

            decision = self.call_llm(target, candidates)
            summary["api_calls"] += 1

            entry = {
                "match": decision.get("match"),
                "confidence": int(decision.get("confidence") or 0),
                "reasoning": decision.get("reasoning", ""),
                "candidate_ids": [c.get("tender_id") for c in candidates],
                "applied": False,
                "model": self.model,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

            match_id = entry["match"]
            if match_id and match_id in idx and entry["confidence"] >= self.confidence_min:
                award_notice = idx[match_id]
                updates[tid] = self._apply_award(
                    target, award_notice, entry["confidence"]
                )
                entry["applied"] = True
                summary["matched"] += 1
                summary["applied"].append({
                    "target": tid,
                    "match": match_id,
                    "confidence": entry["confidence"],
                    "reasoning": entry["reasoning"],
                    "from_cache": False,
                })
            elif match_id and entry["confidence"] < self.confidence_min:
                summary["rejected_low_confidence"] += 1
            else:
                summary["no_match"] += 1

            log[cache_key] = entry

            # persist log every 5 calls so a crash doesn't wipe progress
            if (i + 1) % 5 == 0:
                self._save_log(log)

        self._save_log(log)
        summary["cost_usd"] = round(self.cost_usd, 4)
        summary["input_tokens"] = self.input_tokens
        summary["output_tokens"] = self.output_tokens

        # Stitch updated notices back into the original list (preserve order)
        result = []
        for n in notices:
            tid = n.get("tender_id")
            result.append(updates.get(tid, n))

        return result, summary


# ────────────────────────────────────────────────────────────────────
# Standalone cache-merge utility (no API calls)
# ────────────────────────────────────────────────────────────────────

def merge_cached_awards(relevant_path: str, confidence_min: int = 65) -> int:
    """Re-apply LLM award-cache entries to relevant.json without API calls.

    Reads ``.award_match_llm_log.json``, finds every entry where
    ``applied=True AND match!=None AND confidence>=confidence_min``, and
    writes the ``award`` block back into the matching tender in
    *relevant_path* if ``award.awarded`` is not already set.

    Safe to call after ``--phase filter`` to prevent LLM matches from
    silently disappearing in the rebuilt ``relevant.json``.

    Returns the count of notices that were newly updated.
    """
    relevant = Path(relevant_path)
    if not relevant.exists():
        logger.warning("merge_cached_awards: %s not found, skipping", relevant_path)
        return 0

    with open(relevant, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    log = LLMAwardMatcher._load_log()
    if not log:
        return 0

    idx: dict[str, dict] = {n.get("tender_id"): n for n in notices}
    merged = 0

    # Cache keys are either "<tid>:<model_slug>" (since 14i) or legacy plain "<tid>".
    # When multiple model-keyed entries exist for the same tender, prefer the
    # one with the higher confidence (keeps best result regardless of model).
    by_tid: dict[str, dict] = {}
    for raw_key, entry in log.items():
        if not (entry.get("applied") and entry.get("match")):
            continue
        # Extract bare tender_id from key
        bare_tid = raw_key.split(":", 1)[0]
        existing = by_tid.get(bare_tid)
        if existing is None or int(entry.get("confidence") or 0) > int(existing.get("confidence") or 0):
            by_tid[bare_tid] = entry

    for tid, entry in by_tid.items():
        conf = int(entry.get("confidence") or 0)
        if conf < confidence_min:
            continue
        match_id = entry["match"]

        target = idx.get(tid)
        if target is None:
            logger.debug("merge_cached_awards: target %s not in relevant.json", tid)
            continue

        # Skip if already awarded — never overwrite.
        existing_award = target.get("award") or {}
        if isinstance(existing_award, dict) and existing_award.get("awarded"):
            continue
        if target.get("_winner_name"):
            continue

        # Apply award block. Winner name comes from the match notice if present.
        award_notice = idx.get(match_id) or {}
        a = award_notice.get("award") or {}
        winner = a.get("winner_name") or award_notice.get("_winner_name") or None
        if isinstance(winner, list):
            winner = winner[0] if winner else None
        if isinstance(winner, dict):
            winner = next(iter(winner.values()), None) or None
        if winner:
            winner = str(winner)

        target["award"] = {
            **existing_award,
            "awarded": True,
            "winner_name": winner,
            "_from_award_match_llm": True,
            "_award_notice_id": match_id,
            "_match_confidence": conf,
        }
        target["_award_matched_llm"] = True
        merged += 1
        logger.info("merge_cached_awards: applied %s → %s (conf=%d)", tid, match_id, conf)

    if merged:
        with open(relevant, "w", encoding="utf-8") as f:
            json.dump(notices, f, ensure_ascii=False, indent=2)
        logger.info("merge_cached_awards: merged %d awards into %s", merged, relevant_path)
    else:
        logger.debug("merge_cached_awards: nothing to merge")

    return merged

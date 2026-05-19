"""
Title & Description translation pass — Sprint Translate, 2026-05-08/09.

Goal
----
Every notice in ``relevant.json`` should have a ``title_en`` field with a
concise, accurate English title. The frontend exporter (``exporter_frontend``)
prefers ``title_en`` over ``_title_final`` so the UI is always English.

Strategy
--------
1. Heuristic language check on the source title:
   * mostly ASCII letters (> 90 %)
   * AND at least one common English stop-word (the/of/for/and/…)
   → pass-through, set ``title_en = source``, no API call.
2. Otherwise: Claude Haiku 4.5 translates the title (cheap: ~$0.0003/title).

Cache
-----
``data/.translation_cache.json``::

    {
      "<tender_id>": {
        "original":         "<source title>",
        "title_en":         "<English title>",
        "is_english":       true|false,
        "translated_at":    "2026-05-08 12:00:00",
        "model":            "anthropic/claude-haiku-4.5",
        "input_tokens":     int,
        "output_tokens":    int
      }
    }

Cache key is ``tender_id`` because titles cannot change for a fixed ID.
Re-runs hit the cache for every entry → 0 API calls when stable.
"""
from __future__ import annotations

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

# ── SSL handling mirrors classifier.py
_SSL_VERIFY = (
    os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
    not in ("1", "true", "yes")
)
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration
TRANSLATION_CACHE_PATH = (
    Path(__file__).parent.parent / "data" / ".translation_cache.json"
)
DESCRIPTION_TRANSLATION_CACHE_PATH = (
    Path(__file__).parent.parent / "data" / ".description_translation_cache.json"
)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

# Haiku 4.5 list pricing as of 2026-05 (USD per 1M tokens)
PRICE_INPUT_PER_M = 1.0
PRICE_OUTPUT_PER_M = 5.0

# Heuristic ASCII threshold for "this is probably English"
_ASCII_THRESHOLD = 0.90

# Common English stop-words; presence of >=1 strongly suggests English text.
_ENGLISH_STOPWORDS = {
    "the", "of", "for", "and", "with", "to", "in", "on", "by",
    "from", "at", "or", "is", "are", "as", "an", "be",
}

# Title fields tried in order — same chain as exporter_frontend, plus the
# raw multilingual ``title`` dict TED API returns when nothing else is set.
_TITLE_FIELDS = ("_title_final", "_title_english", "title")


def is_likely_english(text: str) -> bool:
    """Cheap language check for procurement tender titles.

    Returns True iff the text is mostly ASCII *and* contains a recognisable
    English stop-word. The combined check screens out pure-ASCII non-English
    titles (e.g. Polish ``Zakup pojazdow ciezarowych``) while accepting
    English titles that contain a few accented author names.
    """
    if not text:
        return False

    ascii_chars = sum(1 for c in text if ord(c) < 128)
    if len(text) == 0 or ascii_chars / len(text) < _ASCII_THRESHOLD:
        return False

    tokens = set(re.findall(r"\b[a-zA-Z]{2,}\b", text.lower()))
    return bool(tokens & _ENGLISH_STOPWORDS)


def _source_title(notice: dict) -> str:
    """Pick the best non-empty source title from a notice."""
    for f in _TITLE_FIELDS:
        v = notice.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            # TED multilingual title: prefer English entries first
            for lang in ("eng", "en"):
                if v.get(lang):
                    val = v[lang]
                    if isinstance(val, list):
                        val = next((x for x in val if x), "")
                    if val:
                        return str(val).strip()
            # otherwise take any non-empty value
            for val in v.values():
                if isinstance(val, list):
                    val = next((x for x in val if x), "")
                if val:
                    return str(val).strip()
    return ""


def _country_name(notice: dict) -> str:
    """Best-effort country string for the prompt context."""
    cn = notice.get("_country_normalized")
    if cn:
        return str(cn)
    ca = notice.get("contracting_authority") or {}
    if isinstance(ca, dict):
        return str(ca.get("country") or "").split("\n")[0].strip()
    return ""


def _description_excerpt(notice: dict, max_chars: int = 300) -> str:
    """Short, English-preferred description used as translation context."""
    for f in ("_description_final", "_description_english", "description"):
        v = notice.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()[:max_chars]
        if isinstance(v, dict):
            for lang in ("eng", "en"):
                if v.get(lang):
                    val = v[lang]
                    if isinstance(val, list):
                        val = next((x for x in val if x), "")
                    if val:
                        return str(val).strip()[:max_chars]
    return ""


def _build_prompt(country: str, title: str, description: str) -> str:
    bits = []
    if country:
        bits.append(f"Country: {country}")
    bits.append(f"Original title: {title}")
    if description:
        bits.append(f"Description excerpt: {description}")
    bits.append(
        "Translate the title to concise, accurate English. Keep technical "
        "procurement terminology (CPV codes, vehicle types, lot numbers). "
        "Output ONLY the English title — no quotes, no prefix, no commentary."
    )
    return "\n".join(bits)


# ────────────────────────────────────────────────────────────────────
# Cache
# ────────────────────────────────────────────────────────────────────

def _load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ────────────────────────────────────────────────────────────────────
# Translator
# ────────────────────────────────────────────────────────────────────

class TitleTranslator:
    """Calls Claude Haiku to translate a single tender title."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        self.api_key = api_key or (
            os.environ.get("LLM_OPENROUTER_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or None
        )
        self.model = model
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

    def translate_one(
        self,
        country: str,
        title: str,
        description: str,
        max_retries: int = 3,
    ) -> Optional[str]:
        prompt = _build_prompt(country, title, description)

        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    OPENROUTER_API_URL,
                    json={
                        "model": self.model,
                        "max_tokens": 200,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=30,
                )
            except requests.RequestException as exc:
                logger.warning("Translator call failed (attempt %d): %s",
                               attempt + 1, exc)
                if attempt + 1 < max_retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                return None

            if resp.status_code == 200:
                body = resp.json()
                self.api_calls += 1
                usage = body.get("usage") or {}
                in_tok = int(usage.get("prompt_tokens") or 0)
                out_tok = int(usage.get("completion_tokens") or 0)
                self.input_tokens += in_tok
                self.output_tokens += out_tok
                self.cost_usd += in_tok * PRICE_INPUT_PER_M / 1_000_000
                self.cost_usd += out_tok * PRICE_OUTPUT_PER_M / 1_000_000

                text = body["choices"][0]["message"]["content"].strip()
                # Strip enclosing quotes the model sometimes adds despite the
                # explicit instruction.
                text = text.strip('"\'').strip()
                # Drop a trailing period if the model adds one
                if text.endswith(".") and not text.endswith(".."):
                    text = text[:-1]
                return text or None
            elif resp.status_code in (429, 529):
                wait = 3 * (attempt + 1)
                logger.warning("Rate-limit/overloaded (%s), waiting %ds",
                               resp.status_code, wait)
                time.sleep(wait)
                continue
            else:
                logger.error("Anthropic API error %s: %s",
                             resp.status_code, resp.text[:200])
                return None

        return None


# ────────────────────────────────────────────────────────────────────
# Top-level entry
# ────────────────────────────────────────────────────────────────────

def translate_titles(
    relevant_path: str | Path,
    *,
    cache_path: str | Path = TRANSLATION_CACHE_PATH,
    model: str = DEFAULT_MODEL,
    target_ids: Optional[list[str]] = None,
    force_refresh: bool = False,
    max_calls: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Translate every non-English ``_title_final`` in ``relevant.json``.

    Args:
        relevant_path: Path to ``data/filtered/relevant.json``.
        cache_path: Path to translation cache (created if missing).
        model: Anthropic model id (defaults to Haiku 4.5).
        target_ids: If set, restrict to these tender ids (smoke testing).
        force_refresh: Bypass cache for the targeted ids.
        max_calls: Hard ceiling on API calls per run (cost guardrail).
        dry_run: Decide who would be translated, but make no API calls.

    Returns:
        Summary dict with counts + cost.
    """
    relevant_path = Path(relevant_path)
    cache_path = Path(cache_path)

    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    cache = _load_cache(cache_path)
    translator = TitleTranslator(model=model)

    summary: dict[str, Any] = {
        "total":               len(notices),
        "evaluated":           0,
        "skipped_no_title":    0,
        "already_english":     0,   # heuristic detected English
        "translated_now":      0,   # API call made
        "from_cache":          0,
        "errors":              0,
        "cost_usd":            0.0,
        "input_tokens":        0,
        "output_tokens":       0,
        "samples":             [],  # 5 examples (target, original, title_en)
    }

    if not dry_run and not translator.is_available:
        logger.warning(
            "Translator: LLM_OPENROUTER_API_KEY not set — skipping. "
            "title_en will be filled only from cache or pass-through."
        )

    target_set: Optional[set[str]] = (
        set(target_ids) if target_ids is not None else None
    )

    for i, notice in enumerate(notices):
        tid = notice.get("tender_id")
        if not tid:
            continue

        if target_set is not None and tid not in target_set:
            continue

        summary["evaluated"] += 1
        original = _source_title(notice)
        if not original:
            summary["skipped_no_title"] += 1
            continue

        # ── 1. Cache check
        if not force_refresh and tid in cache:
            entry = cache[tid]
            notice["title_en"] = entry.get("title_en") or original
            summary["from_cache"] += 1
            continue

        # ── 2. Heuristic English check
        if is_likely_english(original):
            cache[tid] = {
                "original":     original,
                "title_en":     original,
                "is_english":   True,
                "translated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "model":        None,
                "input_tokens":  0,
                "output_tokens": 0,
            }
            notice["title_en"] = original
            summary["already_english"] += 1
            continue

        # ── 3. Translate (Haiku) — unless dry-run / no API
        if dry_run or not translator.is_available:
            cache[tid] = {
                "original":     original,
                "title_en":     None,
                "is_english":   False,
                "translated_at": None,
                "model":        None,
                "_dry_run":     dry_run,
                "input_tokens":  0,
                "output_tokens": 0,
            }
            continue

        if max_calls is not None and translator.api_calls >= max_calls:
            logger.info("max_calls cap reached (%d) — stopping translation",
                        max_calls)
            break

        country = _country_name(notice)
        description = _description_excerpt(notice)
        translated = translator.translate_one(country, original, description)

        if translated:
            cache[tid] = {
                "original":      original,
                "title_en":      translated,
                "is_english":    False,
                "translated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "model":         model,
                "input_tokens":  translator.input_tokens,  # cumulative;
                "output_tokens": translator.output_tokens,  # see summary instead
            }
            notice["title_en"] = translated
            summary["translated_now"] += 1
            if len(summary["samples"]) < 5:
                summary["samples"].append({
                    "id":        tid,
                    "country":   country,
                    "original":  original,
                    "title_en":  translated,
                })
        else:
            summary["errors"] += 1

        # persist cache periodically
        if (i + 1) % 25 == 0:
            _save_cache(cache_path, cache)

    _save_cache(cache_path, cache)

    # Backfill notices whose title_en didn't get touched (target_ids subset
    # or English heuristic in earlier runs) so the field is always populated
    # downstream — guarantees: every notice with a non-empty title has
    # title_en set.
    for notice in notices:
        if "title_en" in notice and notice["title_en"]:
            continue
        tid = notice.get("tender_id")
        cached = cache.get(tid) if tid else None
        if cached and cached.get("title_en"):
            notice["title_en"] = cached["title_en"]
            continue
        # As a last resort, fall back to the source title so exporter has a
        # non-null value (better the foreign title than a missing one).
        src = _source_title(notice)
        if src:
            notice["title_en"] = src

    # Always write back relevant.json — even when dry_run, we still set
    # title_en for English-detected entries (no harm: the field is additive).
    with open(relevant_path, "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)

    summary["cost_usd"]      = round(translator.cost_usd, 4)
    summary["input_tokens"]  = translator.input_tokens
    summary["output_tokens"] = translator.output_tokens
    summary["api_calls"]     = translator.api_calls
    summary["model"]         = model
    return summary


# ────────────────────────────────────────────────────────────────────
# Description translation
# ────────────────────────────────────────────────────────────────────

# Sonnet — richer context, better summarisation for procurement text.
DESC_DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"

# Sonnet 4.6 pricing per 1M tokens (USD)
DESC_PRICE_INPUT_PER_M = 3.0
DESC_PRICE_OUTPUT_PER_M = 15.0

# Haiku 4.5 — used for the cleaning pass (cheaper, fast, sufficient for EN→EN)
CLEAN_DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
CLEAN_PRICE_INPUT_PER_M = 1.0
CLEAN_PRICE_OUTPUT_PER_M = 5.0

_DESC_SOURCE_FIELDS = ("_description_final", "description", "_description_english")
_DESC_RAW_SUBKEYS   = ("description",)

# Bad description-en prefixes that signal an unprocessed English dump
_BAD_DESC_PREFIXES: tuple[str, ...] = (
    "file number",
    "notice of proposed procurement",
    "avis de projet",
    "solicitation number",
    "reissue of request",
    "this solicitation",
    "nso number",
    "abn:",
    "procurement identification",
    "solicitation cancels",
    "this request for",
    "note:",
    "the contracting authority hereby",
    "amendment",
)


def _sentence_count(text: str) -> int:
    # Collapse decimal points (e.g. "3.5", "12.5") so they don't split as sentences
    normalized = re.sub(r"(\d)\.(\d)", r"\1,\2", text)
    return len([s for s in re.split(r"[.!?]+", normalized) if len(s.strip()) > 10])


def _needs_cleaning(desc_en: str, source_text: str) -> bool:
    """Return True if description_en looks like an unprocessed dump."""
    if not desc_en:
        return True
    low = desc_en.lower().strip()
    if any(low.startswith(p) for p in _BAD_DESC_PREFIXES):
        return True
    n_sent = _sentence_count(desc_en)
    if n_sent > 4:
        return True
    # Pass-through of a verbose source
    if source_text and desc_en.strip() == source_text.strip():
        src_sents = _sentence_count(source_text)
        if src_sents > 4:
            return True
    return False


def _build_clean_prompt(title_en: str, raw_text: str, country: str) -> str:
    """Haiku-optimised prompt for English→English description cleaning."""
    bits = []
    if country:
        bits.append(f"Country: {country}")
    if title_en:
        bits.append(f"Tender title: {title_en}")
    bits.append(f"Raw tender text:\n{raw_text[:4000]}")
    bits.append(
        "You are a defence-procurement analyst. Write a clean 2–4 sentence "
        "summary capturing: WHAT is being procured (vehicle/trailer type, "
        "quantity), WHO is the buyer, WHERE (delivery location if given), and "
        "KEY specs (dimensions, payload, capabilities).\n"
        "Remove: file numbers, solicitation headers, legal disclaimers, NSN/GSIN "
        "codes, procedural boilerplate, references to previous solicitations.\n"
        "Output ONLY the clean summary — no preamble, no commentary."
    )
    return "\n\n".join(bits)


def _source_description(notice: dict) -> tuple[str, str]:
    """Return (source_text, field_name) for the best available description."""
    for f in _DESC_SOURCE_FIELDS:
        v = notice.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip(), f
        if isinstance(v, dict):
            for lang in ("eng", "en"):
                if v.get(lang):
                    val = v[lang]
                    if isinstance(val, list):
                        val = next((x for x in val if x), "")
                    if val:
                        return str(val).strip(), f
    # Try _raw sub-dict
    raw = notice.get("_raw") or {}
    for k in _DESC_RAW_SUBKEYS:
        v = raw.get(k, "")
        if isinstance(v, str) and v.strip():
            return v.strip()[:2000], f"_raw.{k}"
    return "", ""


def _build_desc_prompt(title_en: str, source_text: str, country: str) -> str:
    bits = []
    if country:
        bits.append(f"Country: {country}")
    if title_en:
        bits.append(f"Tender title: {title_en}")
    bits.append(f"Original description:\n{source_text[:1500]}")
    bits.append(
        "You are a defence-procurement analyst. Translate and summarize the "
        "tender description into clear English. Keep all technical specifications "
        "(vehicle types, quantities, capacities, dimensions). Remove procedural "
        "boilerplate (legal disclaimers, country-of-origin restrictions, generic "
        "regulations). Maximum 4 sentences. Output: ONLY the English summary."
    )
    return "\n\n".join(bits)


def translate_descriptions(
    relevant_path: str | Path,
    *,
    cache_path: str | Path = DESCRIPTION_TRANSLATION_CACHE_PATH,
    model: str = DESC_DEFAULT_MODEL,
    target_ids: Optional[list[str]] = None,
    force_refresh: bool = False,
    max_calls: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Translate/summarise every non-English description in ``relevant.json``.

    For each notice the function picks the best available description source
    (``_description_final`` → ``description`` → ``_raw.description``).
    If that source is already likely English it is promoted to
    ``description_en`` without an API call.  If not, Claude Sonnet translates
    and summarises it into ≤4-sentence English prose.

    Cache key: ``<tender_id>:<sha1(source_text)>`` — invalidated automatically
    when the source text changes.

    Result field: ``description_en`` in each notice (additive, never overwrites
    an existing non-empty value unless ``force_refresh=True``).
    """
    relevant_path = Path(relevant_path)
    cache_path = Path(cache_path)

    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    cache = _load_cache(cache_path)
    translator = TitleTranslator(model=model)
    # Override pricing to Sonnet rates
    translator.cost_usd = 0.0

    summary: dict[str, Any] = {
        "total":              len(notices),
        "evaluated":          0,
        "skipped_no_source":  0,
        "already_english":    0,
        "translated_now":     0,
        "from_cache":         0,
        "errors":             0,
        "cost_usd":           0.0,
        "input_tokens":       0,
        "output_tokens":      0,
        "samples":            [],
    }

    if not dry_run and not translator.is_available:
        logger.warning(
            "translate_descriptions: LLM_OPENROUTER_API_KEY not set — "
            "only pass-through for already-English descriptions."
        )

    target_set: Optional[set[str]] = (
        set(target_ids) if target_ids is not None else None
    )

    in_tok_total = 0
    out_tok_total = 0
    cost_total = 0.0
    api_calls = 0

    for i, notice in enumerate(notices):
        tid = notice.get("tender_id")
        if not tid:
            continue
        if target_set is not None and tid not in target_set:
            continue
        if not force_refresh and notice.get("description_en"):
            continue

        summary["evaluated"] += 1
        source_text, source_field = _source_description(notice)
        if not source_text:
            summary["skipped_no_source"] += 1
            continue

        cache_key = f"{tid}:{hashlib.sha1(source_text.encode()).hexdigest()[:12]}"

        # ── 1. Cache check
        if not force_refresh and cache_key in cache:
            entry = cache[cache_key]
            desc_en = entry.get("description_en")
            if desc_en:
                notice["description_en"] = desc_en
                summary["from_cache"] += 1
                continue

        # ── 2. Heuristic: already English?
        if is_likely_english(source_text):
            notice["description_en"] = source_text
            cache[cache_key] = {
                "tender_id":     tid,
                "source_field":  source_field,
                "description_en": source_text,
                "is_english":    True,
                "translated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "model":         None,
            }
            summary["already_english"] += 1
            continue

        # ── 3. Translate via Sonnet
        if dry_run or not translator.is_available:
            continue

        if max_calls is not None and api_calls >= max_calls:
            logger.info("max_calls cap reached (%d) — stopping", max_calls)
            break

        title_en = notice.get("title_en") or _source_title(notice)
        country = _country_name(notice)
        prompt = _build_desc_prompt(title_en, source_text, country)

        for attempt in range(3):
            try:
                resp = translator.session.post(
                    OPENROUTER_API_URL,
                    json={
                        "model": model,
                        "max_tokens": 400,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60,
                )
            except requests.RequestException as exc:
                logger.warning("desc translate attempt %d failed: %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                summary["errors"] += 1
                break

            if resp.status_code == 200:
                body = resp.json()
                api_calls += 1
                usage = body.get("usage") or {}
                in_tok = int(usage.get("prompt_tokens") or 0)
                out_tok = int(usage.get("completion_tokens") or 0)
                in_tok_total += in_tok
                out_tok_total += out_tok
                cost_total += (
                    in_tok * DESC_PRICE_INPUT_PER_M / 1_000_000
                    + out_tok * DESC_PRICE_OUTPUT_PER_M / 1_000_000
                )
                desc_en = body["choices"][0]["message"]["content"].strip().strip('"\'').strip()
                notice["description_en"] = desc_en
                cache[cache_key] = {
                    "tender_id":      tid,
                    "source_field":   source_field,
                    "description_en": desc_en,
                    "is_english":     False,
                    "translated_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
                    "model":          model,
                    "input_tokens":   in_tok,
                    "output_tokens":  out_tok,
                }
                summary["translated_now"] += 1
                if len(summary["samples"]) < 5:
                    summary["samples"].append({
                        "id":       tid,
                        "country":  country,
                        "original": source_text[:120],
                        "desc_en":  desc_en[:120],
                    })
                break
            elif resp.status_code in (429, 529):
                wait = 5 * (attempt + 1)
                logger.warning("Rate-limit %s — waiting %ds", resp.status_code, wait)
                time.sleep(wait)
            else:
                logger.error("API error %s: %s", resp.status_code, resp.text[:200])
                summary["errors"] += 1
                break

        if (i + 1) % 25 == 0:
            _save_cache(cache_path, cache)

    _save_cache(cache_path, cache)

    with open(relevant_path, "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)

    summary["cost_usd"]      = round(cost_total, 4)
    summary["input_tokens"]  = in_tok_total
    summary["output_tokens"] = out_tok_total
    summary["api_calls"]     = api_calls
    summary["model"]         = model
    return summary


# ────────────────────────────────────────────────────────────────────
# Haiku cleaning pass (EN → EN summarisation)
# ────────────────────────────────────────────────────────────────────

def _make_clean_api_call(
    session: requests.Session,
    prompt: str,
    model: str,
    max_retries: int = 3,
) -> tuple[Optional[str], int, int]:
    """Single Haiku cleaning call. Returns (cleaned_text | None, in_tok, out_tok)."""
    for attempt in range(max_retries):
        try:
            resp = session.post(
                OPENROUTER_API_URL,
                json={
                    "model": model,
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.warning("Clean API call attempt %d failed: %s", attempt + 1, exc)
            if attempt + 1 < max_retries:
                time.sleep(3 * (attempt + 1))
                continue
            return None, 0, 0

        if resp.status_code == 200:
            body = resp.json()
            usage = body.get("usage") or {}
            in_tok = int(usage.get("prompt_tokens") or 0)
            out_tok = int(usage.get("completion_tokens") or 0)
            text = body["choices"][0]["message"]["content"].strip().strip('"\'').strip()
            return text or None, in_tok, out_tok
        elif resp.status_code in (429, 529):
            wait = 5 * (attempt + 1)
            logger.warning("Rate-limit %s — waiting %ds", resp.status_code, wait)
            time.sleep(wait)
        else:
            logger.error("Clean API error %s: %s", resp.status_code, resp.text[:200])
            return None, 0, 0

    return None, 0, 0


def process_descriptions(
    relevant_path: str | Path,
    *,
    cache_path: str | Path = DESCRIPTION_TRANSLATION_CACHE_PATH,
    model: str = CLEAN_DEFAULT_MODEL,
    target_ids: Optional[list[str]] = None,
    force_clean: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Universal Haiku cleaning pass — EN→EN summarisation.

    For every notice where ``description_en`` is missing or looks like an
    unprocessed English dump (``_needs_cleaning`` returns True), call Haiku 4.5
    to produce a clean 2–4 sentence summary.

    Cache key: ``{tid}:{sha1(source_text[:2000])[:12]}:haiku-clean`` — the
    model-tagged suffix prevents collision with Sonnet translation entries.

    Args:
        relevant_path: Path to data/filtered/relevant.json.
        cache_path: Shared description translation cache.
        model: Anthropic model id (defaults to Haiku 4.5).
        target_ids: Restrict to these tender ids (smoke testing).
        force_clean: Bypass the clean-cache and re-run Haiku for every
            notice that ``_needs_cleaning`` flags.
        dry_run: Log what would be cleaned but make no API calls.
    """
    relevant_path = Path(relevant_path)
    cache_path = Path(cache_path)

    with open(relevant_path, encoding="utf-8") as f:
        notices: list[dict] = json.load(f)

    cache = _load_cache(cache_path)

    api_key = (
        os.environ.get("LLM_OPENROUTER_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or None
    )
    session = requests.Session()
    session.verify = _SSL_VERIFY
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key or ''}",
        "HTTP-Referer": "https://bpw-tender-radar.internal",
        "X-Title": "BPW Defence Tender Radar",
    })

    summary: dict[str, Any] = {
        "total":             len(notices),
        "evaluated":         0,
        "skipped_no_source": 0,
        "already_clean":     0,
        "cleaned_now":       0,
        "from_cache":        0,
        "errors":            0,
        "cost_usd":          0.0,
        "input_tokens":      0,
        "output_tokens":     0,
        "samples":           [],
    }

    if not dry_run and not api_key:
        logger.warning(
            "process_descriptions: LLM_OPENROUTER_API_KEY not set — dry-run mode."
        )
        dry_run = True

    target_set: Optional[set[str]] = (
        set(target_ids) if target_ids is not None else None
    )

    in_tok_total = 0
    out_tok_total = 0
    cost_total = 0.0
    api_calls = 0

    for i, notice in enumerate(notices):
        tid = notice.get("tender_id")
        if not tid:
            continue
        if target_set is not None and tid not in target_set:
            continue

        desc_en = (notice.get("description_en") or "").strip()
        source_text, source_field = _source_description(notice)

        if not _needs_cleaning(desc_en, source_text):
            summary["already_clean"] += 1
            continue

        summary["evaluated"] += 1

        if not source_text:
            summary["skipped_no_source"] += 1
            continue

        # Model-tagged cache key — no collision with Sonnet translation entries
        raw_key_text = source_text[:2000]
        cache_key = (
            f"{tid}:{hashlib.sha1(raw_key_text.encode()).hexdigest()[:12]}:haiku-clean"
        )

        # ── Cache check
        if not force_clean and cache_key in cache:
            entry = cache[cache_key]
            cleaned = entry.get("description_en")
            if cleaned:
                notice["description_en"] = cleaned
                summary["from_cache"] += 1
                continue

        # ── Dry run
        if dry_run:
            logger.info("[dry-run] Would clean: %s (%s)", tid, source_field)
            continue

        # ── Haiku cleaning API call
        title_en = notice.get("title_en") or _source_title(notice)
        country = _country_name(notice)
        prompt = _build_clean_prompt(title_en, source_text, country)

        cleaned, in_tok, out_tok = _make_clean_api_call(session, prompt, model)

        if cleaned:
            api_calls += 1
            in_tok_total += in_tok
            out_tok_total += out_tok
            cost_total += (
                in_tok * CLEAN_PRICE_INPUT_PER_M / 1_000_000
                + out_tok * CLEAN_PRICE_OUTPUT_PER_M / 1_000_000
            )
            notice["description_en"] = cleaned
            cache[cache_key] = {
                "tender_id":      tid,
                "source_field":   source_field,
                "description_en": cleaned,
                "is_english":     True,
                "cleaned":        True,
                "translated_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
                "model":          model,
                "input_tokens":   in_tok,
                "output_tokens":  out_tok,
            }
            summary["cleaned_now"] += 1
            if len(summary["samples"]) < 5:
                summary["samples"].append({
                    "id":      tid,
                    "country": country,
                    "before":  desc_en[:120] or source_text[:120],
                    "after":   cleaned[:120],
                })
            logger.info("[clean] %s → %d chars", tid, len(cleaned))
        else:
            summary["errors"] += 1
            logger.warning("[clean] Failed for %s", tid)

        if (i + 1) % 25 == 0:
            _save_cache(cache_path, cache)

    _save_cache(cache_path, cache)

    with open(relevant_path, "w", encoding="utf-8") as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)

    summary["cost_usd"]      = round(cost_total, 4)
    summary["input_tokens"]  = in_tok_total
    summary["output_tokens"] = out_tok_total
    summary["api_calls"]     = api_calls
    summary["model"]         = model
    return summary

"""
Strategy A — proactive Vergabeunterlagen scraping for DE/PL/CZ tenders.

Unlike Phase 3g+ (which fires the national fallback only when TED docs are
dead), Strategy A proactively pulls the deep Leistungsverzeichnis / SWZ /
Zadávací dokumentace PDFs from the buyer's portal whenever the TED notice
exposes a ``buyer_profile_url`` but no direct ``tender_documents_access``
deeplink. These PDFs are 50–200 pages of axle configuration, dimensions,
material requirements — the genuine spec depth that no API surfaces.

Trigger: only via ``--strategy-a`` CLI flag (not active in ``--all``).

Cache : data/.strategy_a_cache.json (separate from .document_extraction_cache.json
        so a Strategy-A run cannot evict the regular 3g extraction cache).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .discovery import _discover_strategy_a, url_is_healthy
from .downloader import download_document
from .extractor import extract_text
from .ai_structurer import active_model, cache_slug, structure_with_ai

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
RELEVANT_JSON = PROJECT_ROOT / "data" / "filtered" / "relevant.json"
CACHE_PATH = PROJECT_ROOT / "data" / ".strategy_a_cache.json"


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict, path: Path) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def run_strategy_a(
    notices: list[dict],
    *,
    sample_ids: Optional[list[str]] = None,
    test_mode: bool = False,
    dry_run: bool = False,
    force: bool = False,
    max_docs_per_tender: int = 4,
) -> dict:
    """Discover, download, and (unless dry_run) AI-structure Strategy-A docs.

    Returns a summary dict. Notices are mutated in place: ``_strategy_a_specs``
    is set when AI extraction succeeded.
    """
    model = active_model()
    slug = cache_slug(model)
    cache = _load_cache(CACHE_PATH)

    candidates = notices
    if sample_ids:
        ids = {s.strip() for s in sample_ids if s and s.strip()}
        candidates = [n for n in notices if str(n.get("tender_id", "")) in ids]
    if test_mode:
        candidates = candidates[:5]

    # Vision is handled internally by extractor.py via OpenRouter — no client object needed.
    vision_client = None

    stats = {
        "candidates":           len(candidates),
        "triggered":            0,
        "no_inputs":            0,
        "docs_discovered":      0,
        "docs_alive":           0,
        "docs_downloaded":      0,
        "docs_text_extracted":  0,
        "auth_blocked":         0,
        "ai_calls":             0,
        "cache_hits":           0,
        "by_country":           {"DE": 0, "PL": 0, "CZ": 0},
        "yield_by_country":     {"DE": 0, "PL": 0, "CZ": 0},
        "extracted_tenders":    [],
    }

    for notice in candidates:
        tid = str(notice.get("tender_id", "?"))
        key = f"{tid}:{slug}"

        if not force and key in cache:
            notice["_strategy_a_specs"] = cache[key].get("specs")
            stats["cache_hits"] += 1
            continue

        refs = _discover_strategy_a(notice)
        if not refs:
            stats["no_inputs"] += 1
            continue

        # Country tag from first ref (all refs in a call share a country)
        cc = ""
        if refs[0].source.startswith("DE"):
            cc = "DE"
        elif refs[0].source.startswith("PL"):
            cc = "PL"
        elif refs[0].source.startswith("CZ"):
            cc = "CZ"
        if cc:
            stats["by_country"][cc] = stats["by_country"].get(cc, 0) + 1

        stats["triggered"] += 1
        stats["docs_discovered"] += len(refs)
        logger.info(f"Strategy-A {tid} ({cc}): {len(refs)} doc ref(s)")

        # Health check, cap and download
        alive = []
        for ref in refs[:max_docs_per_tender]:
            if not ref.url.startswith(("http://", "https://")):
                alive.append(ref)
                continue
            if (ref.extra or {}).get("auth_risk") == "eidas":
                # cheap skip — these usually require CZ-POINT SSO
                if not url_is_healthy(ref.url, timeout=8):
                    stats["auth_blocked"] += 1
                    continue
            if url_is_healthy(ref.url, timeout=10):
                alive.append(ref)
        stats["docs_alive"] += len(alive)
        if not alive:
            continue

        # Download + extract first ref that yields >200 chars of text
        extracted_text = ""
        used_ref = None
        for ref in alive:
            # Inline-text refs (e.g. PL notice HTML body wrapped as txt) —
            # no download needed.
            inline = (ref.extra or {}).get("text", "")
            if inline and len(inline) > 200:
                extracted_text = inline
                used_ref = ref
                stats["docs_text_extracted"] += 1
                break
            if not ref.is_extractable and ref.format != "zip":
                continue
            local_path = download_document(ref, force=force)
            if local_path is None:
                continue
            stats["docs_downloaded"] += 1
            try:
                text = extract_text(local_path, ref.format, anthropic_client=vision_client)
            except Exception as exc:
                logger.debug(f"Strategy-A {tid}: extract error: {exc}")
                continue
            if text and len(text) > 200:
                extracted_text = text
                used_ref = ref
                stats["docs_text_extracted"] += 1
                break

        if not extracted_text:
            continue

        if cc:
            stats["yield_by_country"][cc] = stats["yield_by_country"].get(cc, 0) + 1
        stats["extracted_tenders"].append(tid)

        if dry_run:
            continue

        specs = structure_with_ai(
            extracted_text,
            notice,
            source_doc_title=used_ref.title if used_ref else "",
        )
        stats["ai_calls"] += 1
        if specs:
            specs.pop("_extraction_model", None)
            notice["_strategy_a_specs"] = specs
            cache[key] = {"specs": specs, "source_url": used_ref.url if used_ref else ""}
            logger.info(
                f"Strategy-A {tid} ({cc}): extracted "
                f"{len(specs.get('trailer_types', []))} trailer type(s), "
                f"confidence={specs.get('confidence', '?')}"
            )

    if not dry_run:
        _save_cache(cache, CACHE_PATH)

    return stats

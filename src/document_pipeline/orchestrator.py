"""
Document extraction orchestrator — Phase 3g.

For each notice in relevant.json:
  1. Discover downloadable documents
  2. URL health-check: mark dead URLs, trigger national fallback for DE/PL/CZ
  3. Download with dedup caching
  4. Extract text (PDF/docx/xlsx/html + Vision fallback)
  5. AI-structure specs via active_model() (default: gpt-4o via OpenRouter)
  6. Write _extracted_specs into the notice

National Fallback (new, 2026-05-10):
  Triggered when no alive document URLs are found AND country is DE, PL, or CZ.
  Falls back to the national portal search modules in
  src/national_scraper/fallback/{de,pl,cz}_search.py.
  Results are cached in data/.national_fallback_cache.json.
  Pass --no-fallback-cache to bypass the fallback cache.

Cache: data/.document_extraction_cache.json
  Key format: "{tender_id}:{model_slug}"
  — model slug included so changing EXTRACTION_MODEL forces fresh calls.
  — Example: "245184-2024:gpt-4o"

Stats: notices checked, docs downloaded, AI calls, real cost (via llm_router).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from .discovery import discover_for_notice, url_is_healthy
from .downloader import download_document
from .extractor import extract_text
from .ai_structurer import active_model, cache_slug, structure_with_ai

logger = logging.getLogger(__name__)

RELEVANT_JSON      = Path(__file__).parent.parent.parent / "data" / "filtered" / "relevant.json"
CACHE_PATH         = Path(__file__).parent.parent.parent / "data" / ".document_extraction_cache.json"
FALLBACK_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / ".national_fallback_cache.json"

# Countries that have national fallback modules
_FALLBACK_COUNTRIES = {"DE", "PL", "CZ"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict, path: Path) -> None:
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_key(tid: str, slug: str) -> str:
    return f"{tid}:{slug}"


def _fallback_cache_key(tid: str, country: str) -> str:
    return f"{tid}:{country}"


def _infer_country_code(notice: dict) -> str:
    """Infer ISO-2 country code for national fallback routing."""
    raw = notice.get("_raw", {}) or {}
    xml = raw.get("_xml", {}) or {}

    # From buyer portal URL
    for url_field in (xml.get("tender_documents_access", ""),
                      xml.get("buyer_profile_url_full", "")):
        if not url_field:
            continue
        if "evergabe-online.de" in url_field or ".bund.de" in url_field:
            return "DE"
        if "ezamowienia.gov.pl" in url_field or "platformazakupowa.pl" in url_field:
            return "PL"
        if "nipez.cz" in url_field or "vop.cz" in url_field or ".gov.cz" in url_field:
            return "CZ"

    # From buyer-internet-address
    bint = raw.get("buyer-internet-address", [])
    if isinstance(bint, list):
        bint = bint[0] if bint else ""
    bint = str(bint)
    if ".de/" in bint or bint.endswith(".de"):
        return "DE"
    if ".pl/" in bint or bint.endswith(".pl"):
        return "PL"
    if ".cz/" in bint or bint.endswith(".cz"):
        return "CZ"

    # From _country_normalized
    country_name = (notice.get("_country_normalized") or "").lower()
    if "german" in country_name:
        return "DE"
    if "poland" in country_name or "polish" in country_name:
        return "PL"
    if "czech" in country_name:
        return "CZ"

    return ""


def _extract_fallback_inputs(notice: dict) -> dict:
    """Extract the search inputs needed by the fallback modules."""
    raw = notice.get("_raw", {}) or {}
    xml = raw.get("_xml", {}) or {}

    internal_ref = xml.get("internal_reference", "")
    tender_docs_url = xml.get("tender_documents_access", "") or xml.get("buyer_profile_url_full", "")
    buyer_profile_url = xml.get("buyer_profile_url_full", "")

    # Buyer name — try several fields
    buyer = ""
    for field in ("contracting_authority", "_authority_name"):
        raw_val = notice.get(field)
        if isinstance(raw_val, str) and raw_val:
            buyer = raw_val
            break
        if isinstance(raw_val, dict):
            buyer = raw_val.get("name", "") or raw_val.get("officialName", "")
            if buyer:
                break

    # Title keywords (3-5 significant words from tender title)
    title = notice.get("title") or notice.get("_title_final") or ""
    if isinstance(title, dict):
        title = title.get("eng", "") or title.get("fra", "") or next(iter(title.values()), "")
    keywords = _title_keywords(str(title))

    return {
        "internal_ref":       internal_ref,
        "buyer":              buyer[:100] if buyer else "",
        "title_keywords":     keywords,
        "tender_documents_url": tender_docs_url,
        "buyer_profile_url":  buyer_profile_url,
    }


def _title_keywords(title: str) -> list[str]:
    """Extract 3-5 meaningful words from a tender title for search."""
    stop = {
        "and", "or", "the", "for", "of", "in", "with", "a", "an",
        "to", "by", "at", "on", "is", "are", "-", "–", "&",
        "und", "oder", "für", "mit", "der", "die", "das",
        "i", "oraz", "dla", "do", "na", "z",
        "a", "pro", "za", "ze", "na",
    }
    words = re.findall(r"\b[a-zA-ZÀ-žА-яёА-Я]{4,}\b", title)
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        wl = w.lower()
        if wl not in stop and wl not in seen:
            seen.add(wl)
            out.append(w)
        if len(out) >= 5:
            break
    return out


def _run_national_fallback(notice: dict, country: str) -> Optional[list]:
    """
    Run the appropriate national fallback search and return DocumentRef list
    or None if nothing found.
    """
    inputs = _extract_fallback_inputs(notice)
    tid = notice.get("tender_id", "?")

    logger.info(
        f"National fallback: {tid} ({country}) "
        f"ref='{inputs['internal_ref']}' buyer='{inputs['buyer'][:40]}'"
    )

    try:
        if country == "DE":
            from src.national_scraper.fallback.de_search import search_de
            result = search_de(
                internal_ref=inputs["internal_ref"],
                buyer=inputs["buyer"],
                title_keywords=inputs["title_keywords"],
                tender_documents_url=inputs["tender_documents_url"],
            )
        elif country == "PL":
            from src.national_scraper.fallback.pl_search import search_pl
            result = search_pl(
                internal_ref=inputs["internal_ref"],
                buyer=inputs["buyer"],
                title_keywords=inputs["title_keywords"],
                buyer_profile_url=inputs["buyer_profile_url"],
            )
        elif country == "CZ":
            from src.national_scraper.fallback.cz_search import search_cz
            result = search_cz(
                internal_ref=inputs["internal_ref"],
                buyer=inputs["buyer"],
                title_keywords=inputs["title_keywords"],
                tender_documents_url=inputs["tender_documents_url"],
            )
        else:
            return None
    except Exception as exc:
        logger.error(f"National fallback error for {tid} ({country}): {exc}")
        return None

    if result is None:
        return None

    # Backfill tender_id into each DocumentRef
    docs = result.get("documents", [])
    for doc in docs:
        if not doc.tender_id:
            doc.tender_id = tid

    # Merge additional_fields into notice (non-destructive)
    extra = result.get("additional_fields", {}) or {}
    if extra.get("winner") and not (notice.get("award") or {}).get("winner_name"):
        notice.setdefault("_fallback_winner", extra["winner"])
    if extra.get("quantity") and not notice.get("_trailer_qty_1_ai"):
        notice.setdefault("_fallback_quantity", extra["quantity"])
    if extra.get("contract_duration") and not notice.get("_contract_duration_ai"):
        notice.setdefault("_fallback_contract_duration", extra["contract_duration"])
    if extra.get("value"):
        notice.setdefault("_fallback_value", extra["value"])

    # Record which portal was used
    portal_url = result.get("portal_url", "")
    if portal_url:
        notice.setdefault("_source_url_national", portal_url)

    return docs if docs else None


# ── Main entry point ──────────────────────────────────────────────────────────

def run_extraction(
    notices: list[dict],
    *,
    force: bool = False,
    test_mode: bool = False,
    sample_ids: Optional[list[str]] = None,
    dry_run: bool = False,
    no_fallback_cache: bool = False,
) -> list[dict]:
    """Run document extraction on all notices; return updated notices list.

    Args:
        notices:          List of notice dicts (from relevant.json)
        force:            Re-process even if cache hit
        test_mode:        Limit to first 5 notices
        sample_ids:       Only process these tender_ids
        dry_run:          Discover + download, but skip AI structuring (0 API cost)
        no_fallback_cache: Bypass national fallback cache (re-run portal searches)
    """
    model = active_model()
    slug = cache_slug(model)

    cache = _load_cache(CACHE_PATH)
    fallback_cache = _load_cache(FALLBACK_CACHE_PATH) if not no_fallback_cache else {}
    vision_client = None  # Vision handled internally by extractor.py via OpenRouter

    candidates = notices
    if sample_ids:
        candidates = [n for n in notices if n.get("tender_id") in set(sample_ids)]
    if test_mode:
        candidates = candidates[:5]

    print(f"  Extraction model  : {model}")

    stats = {
        "notices_checked":    len(candidates),
        "docs_discovered":    0,
        "docs_downloaded":    0,
        "docs_text_extracted": 0,
        "ai_calls":           0,
        "ai_fallbacks":       0,
        "cache_hits":         0,
        "skipped_no_docs":    0,
        "fallback_triggered": 0,
        "fallback_found":     0,
        "fallback_cache_hits": 0,
        "cost_usd":           0.0,
    }

    for notice in candidates:
        tid = notice.get("tender_id", "?")
        key = _cache_key(tid, slug)

        # Extraction cache hit (model-aware)
        if not force and key in cache:
            notice["_extracted_specs"] = cache[key]
            stats["cache_hits"] += 1
            continue

        # ── Step 1: Discover documents ────────────────────────────────────────
        refs = discover_for_notice(notice)
        stats["docs_discovered"] += len(refs)

        # ── Step 2: URL health-check ──────────────────────────────────────────
        alive_refs = []
        for ref in refs:
            # Synthetic refs (internal://) and non-URL docs are always "alive"
            if not ref.url.startswith(("http://", "https://")):
                alive_refs.append(ref)
                continue
            if url_is_healthy(ref.url):
                alive_refs.append(ref)
            else:
                stats["dead_urls"] = stats.get("dead_urls", 0) + 1
                logger.debug(f"Dead URL for {tid}: {ref.url[:80]}")

        # ── Step 3: National fallback ──────────────────────────────────────────
        if not alive_refs:
            country = _infer_country_code(notice)
            if country in _FALLBACK_COUNTRIES:
                stats["fallback_triggered"] += 1
                fb_key = _fallback_cache_key(tid, country)

                if not no_fallback_cache and fb_key in fallback_cache:
                    # Cache hit: reconstruct DocumentRef from cached data
                    cached_fb = fallback_cache[fb_key]
                    stats["fallback_cache_hits"] += 1
                    if cached_fb.get("docs"):
                        from .discovery import DocumentRef
                        for doc_dict in cached_fb["docs"]:
                            alive_refs.append(DocumentRef(**doc_dict))
                        logger.debug(f"Fallback cache hit for {tid} ({country})")
                else:
                    fb_docs = _run_national_fallback(notice, country)
                    # Cache the fallback result (even if empty — to avoid re-running)
                    fb_entry = {"docs": [], "portal_url": notice.get("_source_url_national", "")}
                    if fb_docs:
                        stats["fallback_found"] += 1
                        alive_refs.extend(fb_docs)
                        fb_entry["docs"] = [
                            {
                                "url": d.url,
                                "format": d.format,
                                "language": d.language,
                                "title": d.title,
                                "source": d.source,
                                "tender_id": d.tender_id,
                                "doc_type": d.doc_type,
                                "extra": d.extra,
                            }
                            for d in fb_docs
                        ]
                    fallback_cache[fb_key] = fb_entry
                    if not dry_run:
                        _save_cache(fallback_cache, FALLBACK_CACHE_PATH)

        if not alive_refs:
            stats["skipped_no_docs"] += 1
            continue

        # ── Step 4: Download + extract ────────────────────────────────────────
        extracted_text = ""
        used_ref = None

        for ref in alive_refs:
            # national_page_text refs carry text inline — no download needed.
            # When the inline text is long enough we accept it; otherwise we
            # fall through to the next ref (typically a portal-URL HTML page
            # added by _discover_au_ocds / _discover_ca).
            if ref.doc_type == "national_page_text":
                inline = (ref.extra or {}).get("text", "")
                if inline and len(inline) > 200:
                    extracted_text = inline
                    used_ref = ref
                    stats["docs_text_extracted"] += 1
                    break
                continue

            if not ref.is_extractable:
                continue

            local_path = download_document(ref, force=force)
            if local_path is None:
                continue
            stats["docs_downloaded"] += 1

            text = extract_text(
                local_path,
                ref.format,
                anthropic_client=vision_client,
            )
            if text and len(text) > 200:
                extracted_text = text
                used_ref = ref
                stats["docs_text_extracted"] += 1
                break

        if not extracted_text:
            logger.debug(f"No text extracted for {tid}")
            continue

        if dry_run:
            logger.info(f"[dry-run] Would AI-structure {tid} ({len(extracted_text)} chars)")
            continue

        # ── Step 5: AI structuring ────────────────────────────────────────────
        specs = structure_with_ai(
            extracted_text,
            notice,
            source_doc_title=used_ref.title if used_ref else "",
        )
        stats["ai_calls"] += 1

        if specs:
            used_model = specs.pop("_extraction_model", model)
            if used_model == "anthropic/claude-sonnet-4-6" and used_model != model:
                stats["ai_fallbacks"] += 1

            try:
                from src import llm_router
                stats["cost_usd"] += llm_router.estimate_cost_usd(used_model, 4000, 400)
            except Exception:
                pass

            notice["_extracted_specs"] = specs
            cache[key] = specs
            logger.info(
                f"Extracted specs for {tid} [{cache_slug(used_model)}]: "
                f"{len(specs.get('trailer_types', []))} type(s), "
                f"confidence={specs.get('confidence', '?')}"
            )

    # Persist extraction cache
    if not dry_run:
        _save_cache(cache, CACHE_PATH)

    print(
        f"\nDocument Extraction — Phase 3g complete:\n"
        f"  Model used           : {model}\n"
        f"  Notices checked      : {stats['notices_checked']}\n"
        f"  Cache hits           : {stats['cache_hits']}\n"
        f"  Docs discovered      : {stats['docs_discovered']}\n"
        f"  Dead URLs skipped    : {stats.get('dead_urls', 0)}\n"
        f"  Fallback triggered   : {stats['fallback_triggered']}\n"
        f"  Fallback found docs  : {stats['fallback_found']}\n"
        f"  Fallback cache hits  : {stats['fallback_cache_hits']}\n"
        f"  Docs downloaded      : {stats['docs_downloaded']}\n"
        f"  Text extracted       : {stats['docs_text_extracted']}\n"
        f"  AI calls made        : {stats['ai_calls']}\n"
        f"  Sonnet fallbacks     : {stats['ai_fallbacks']}\n"
        f"  Skipped (no docs)    : {stats['skipped_no_docs']}\n"
        f"  Estimated cost       : ${stats['cost_usd']:.4f}\n"
    )

    return notices

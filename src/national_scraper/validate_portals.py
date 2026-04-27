"""
Portal Validation — Check if national portals actually carry defence trailer tenders.

Strategy: Take known TED tenders (military authority + trailer title) and search
for the same authority on the national portal. If we find trailer notices from that
authority → portal is a valid supplementary source.

Run via:
    python main.py --validate-portals de pl --visible
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# TED country code → full name (as stored in contracting_authority.country)
TED_COUNTRY_CODES = {
    "de": "DEU",
    "pl": "POL",
    "fi": "FIN",
}

# Trailer keywords in each language — used to check if national results are relevant
TRAILER_KEYWORDS_BY_LANG = {
    "de": ["Anhänger", "Sattelanhänger", "Tieflader", "Tankanhänger", "Shelter",
           "Feldküche", "Hakenladegerät", "Abrollcontainer", "Container"],
    "pl": ["przyczepa", "naczepa", "laweta", "cysterna", "niskopodwoziow",
           "hakowo", "hakowa"],
    "fi": ["perävaunu", "puoliperävaunu", "lavetti", "säiliöperävaunu"],
}


def _get_title_str(notice: dict) -> str:
    """Extract plain-text title from TED notice (title can be str or dict)."""
    title = notice.get("title", "")
    if isinstance(title, dict):
        title = title.get("eng") or title.get("deu") or next(iter(title.values()), "")
    return str(title or "")


def get_known_tenders_by_country(country_code: str) -> list[dict]:
    """Load known TED tenders for a country from our dataset."""
    ted_code = TED_COUNTRY_CODES.get(country_code.lower())
    if not ted_code:
        return []

    relevant_path = Path("data/filtered/relevant.json")
    if not relevant_path.exists():
        return []

    with open(relevant_path, encoding="utf-8") as f:
        notices = json.load(f)

    country_notices = [
        n for n in notices
        if (n.get("contracting_authority") or {}).get("country") == ted_code
    ]

    # Sort by recency
    country_notices.sort(
        key=lambda n: str(n.get("publication_date") or ""), reverse=True
    )

    return country_notices[:5]  # Top 5 most recent


def _authority_name(notice: dict) -> str:
    auth = notice.get("contracting_authority") or {}
    return auth.get("name_short") or auth.get("name", "")


def _title_words(title: str, min_len: int = 5) -> list[str]:
    """Extract meaningful words from a title."""
    return [w for w in title.split() if len(w) >= min_len][:4]


def _title_overlap(t1: str, t2: str) -> int:
    """Count word overlap between two titles (case-insensitive)."""
    s1 = set(t1.lower().split())
    s2 = set(t2.lower().split())
    return len(s1 & s2)


def _is_trailer_related(title: str, lang: str) -> bool:
    keywords = TRAILER_KEYWORDS_BY_LANG.get(lang, [])
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


# ─────────────────────────────────────────────────────────────────────────────
# DE-specific validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_de(adapter, known_tenders: list[dict]) -> dict:
    """
    Validate service.bund.de against known BAAINBw/BAIUDBw tenders.

    Approach:
    1. Run the VSVgV (defence) filter — gives all current defence tenders on portal
    2. Run the KFZ (vehicle) filter
    3. Check if any results contain authority names from our known tenders
    4. Check if any results are trailer-related
    """
    result = {
        "portal": "DE-SB (service.bund.de)",
        "country": "Germany",
        "tenders_checked": len(known_tenders),
        "known_authorities": [],
        "portal_results_vsv": 0,
        "portal_results_kfz": 0,
        "authority_matches": [],
        "trailer_hits": [],
        "search_attempts": [],
        "found": 0,
        "not_found": 0,
        "conclusion": "",
    }

    # Collect authority names from known TED tenders
    known_auths = list({_authority_name(n) for n in known_tenders if _authority_name(n)})
    result["known_authorities"] = known_auths
    logger.info(f"DE: known authorities from TED: {known_auths}")

    # --- Run VSVgV filter ---
    logger.info("DE: running VSVgV (Verteidigung & Sicherheit) filter...")
    try:
        vsv_results = adapter._collect_with_filter("f-ausschreibungsart-vsvgv", max_results=100)
        result["portal_results_vsv"] = len(vsv_results)
        logger.info(f"DE: VSVgV → {len(vsv_results)} results")

        result["search_attempts"].append({
            "query": "VSVgV filter (Verteidigung & Sicherheit)",
            "results_count": len(vsv_results),
            "sample_titles": [r.title[:60] for r in vsv_results[:5]],
        })

        for r in vsv_results:
            combined = (r.title + " " + r.authority + " " + r.snippet).lower()
            # Authority match
            for auth in known_auths:
                if any(word.lower() in combined for word in auth.split() if len(word) > 4):
                    result["authority_matches"].append({
                        "known_authority": auth,
                        "national_title": r.title[:80],
                        "national_url": r.url,
                    })
                    break
            # Trailer match
            if _is_trailer_related(r.title, "de"):
                result["trailer_hits"].append({
                    "title": r.title[:80],
                    "authority": r.authority[:40],
                    "url": r.url,
                })
    except Exception as e:
        logger.error(f"DE: VSVgV filter failed: {e}")
        result["search_attempts"].append({"query": "VSVgV filter", "error": str(e)})

    # --- Run KFZ filter (vehicle category) ---
    logger.info("DE: running KFZ (Kraftfahrwesen) filter...")
    try:
        kfz_results = adapter._collect_with_filter("f-leistung-kraftfahrwesen", max_results=100)
        result["portal_results_kfz"] = len(kfz_results)
        logger.info(f"DE: KFZ → {len(kfz_results)} results")

        result["search_attempts"].append({
            "query": "KFZ filter (Kraftfahrwesen)",
            "results_count": len(kfz_results),
            "sample_titles": [r.title[:60] for r in kfz_results[:5]],
        })

        for r in kfz_results:
            if _is_trailer_related(r.title, "de"):
                result["trailer_hits"].append({
                    "title": r.title[:80],
                    "authority": r.authority[:40],
                    "url": r.url,
                })
    except Exception as e:
        logger.error(f"DE: KFZ filter failed: {e}")

    # Deduplicate trailer hits
    seen_urls = set()
    deduped = []
    for h in result["trailer_hits"]:
        if h["url"] not in seen_urls:
            seen_urls.add(h["url"])
            deduped.append(h)
    result["trailer_hits"] = deduped

    # Conclusion
    auth_hit = len(result["authority_matches"])
    trailer_hit = len(result["trailer_hits"])
    result["found"] = auth_hit
    result["not_found"] = len(known_tenders) - min(auth_hit, len(known_tenders))

    if auth_hit == 0 and trailer_hit == 0:
        result["conclusion"] = (
            f"Portal does NOT carry BAAINBw/military defence tenders "
            f"(0 authority matches, 0 trailer notices in {result['portal_results_vsv']} VSVgV + "
            f"{result['portal_results_kfz']} KFZ results)"
        )
    elif trailer_hit > 0 and auth_hit == 0:
        result["conclusion"] = (
            f"Portal HAS trailer notices ({trailer_hit} hits) but NOT from known military "
            f"authorities — may carry defence tenders but not same ones as TED"
        )
    else:
        result["conclusion"] = (
            f"Portal carries defence tenders — {auth_hit} authority match(es), "
            f"{trailer_hit} trailer notice(s) found"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PL-specific validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_pl(adapter, known_tenders: list[dict]) -> dict:
    """
    Validate eZamowienia BZP against known Polish military trailer tenders.

    Approach: Use the REST API with OrganizationName for each known authority.
    """
    result = {
        "portal": "PL-BZP (ezamowienia.gov.pl)",
        "country": "Poland",
        "tenders_checked": len(known_tenders),
        "known_authorities": [],
        "authority_matches": [],
        "trailer_hits": [],
        "search_attempts": [],
        "found": 0,
        "not_found": 0,
        "conclusion": "",
    }

    known_auths = list({_authority_name(n) for n in known_tenders if _authority_name(n)})
    result["known_authorities"] = known_auths
    logger.info(f"PL: known authorities from TED: {known_auths}")

    def _to_sr(raw: dict):
        """Convert a raw PL API dict to a lightweight SearchResult-like namespace."""
        class _R:
            pass
        r = _R()
        r.title = str(raw.get("orderObject", "") or raw.get("announcementTitle", "") or "")
        r.authority = str(raw.get("organizationName", "") or "")
        r.url = (
            f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{raw.get('objectId', '')}"
            if raw.get("objectId") else ""
        )
        r.reference_id = str(raw.get("noticeNumber", "") or "")
        r.snippet = str(raw.get("cpvCode", "") or "")
        return r

    # Search each known authority on BZP
    for auth in known_auths:
        query_org = auth[:40]
        logger.info(f"PL: searching OrganizationName='{query_org}'")

        try:
            raw_items = adapter._api_search(
                {"OrganizationName": query_org, "pageSize": 20},
                max_results=20,
            )
            org_results = [_to_sr(item) for item in raw_items]
            result["search_attempts"].append({
                "query": f"OrganizationName={query_org}",
                "results_count": len(org_results),
                "sample_titles": [r.title[:60] for r in org_results[:5]],
            })
            logger.info(f"PL: '{query_org}' → {len(org_results)} results")

            for r in org_results:
                r_auth_lower = (r.authority or "").lower()
                auth_words = [w for w in auth.lower().split() if len(w) > 3]
                if any(w in r_auth_lower for w in auth_words):
                    result["authority_matches"].append({
                        "known_authority": auth,
                        "national_authority": r.authority[:60],
                        "national_title": r.title[:80],
                        "national_url": r.url,
                    })

                if _is_trailer_related(r.title, "pl"):
                    result["trailer_hits"].append({
                        "title": r.title[:80],
                        "authority": r.authority[:50],
                        "url": r.url,
                    })

        except Exception as e:
            logger.error(f"PL: org search '{query_org}' failed: {e}")
            result["search_attempts"].append({
                "query": f"OrganizationName={query_org}",
                "error": str(e),
            })

    # Also try combined CPV+wojsk query to check if there ARE military trailers
    logger.info("PL: combined CPV 34223300 + OrganizationName='wojsk'...")
    try:
        raw_combined = adapter._api_search(
            {"CpvCode": "34223300", "OrganizationName": "wojsk", "pageSize": 20},
            max_results=20,
        )
        combined = [_to_sr(item) for item in raw_combined]
        result["search_attempts"].append({
            "query": "CpvCode=34223300 + OrganizationName=wojsk",
            "results_count": len(combined),
            "sample_titles": [r.title[:60] for r in combined[:5]],
        })
        logger.info(f"PL: CPV+wojsk combined → {len(combined)} results")
        for r in combined:
            result["trailer_hits"].append({
                "title": r.title[:80],
                "authority": r.authority[:50],
                "url": r.url,
                "note": "CPV+wojsk combined query",
            })
    except Exception as e:
        logger.error(f"PL: combined query failed: {e}")

    # Deduplicate
    seen = set()
    deduped = []
    for h in result["trailer_hits"]:
        if h["url"] not in seen:
            seen.add(h["url"])
            deduped.append(h)
    result["trailer_hits"] = deduped

    auth_hit = len(result["authority_matches"])
    trailer_hit = len(result["trailer_hits"])
    result["found"] = auth_hit
    result["not_found"] = len(known_tenders) - min(auth_hit, len(known_tenders))

    if auth_hit == 0 and trailer_hit == 0:
        result["conclusion"] = (
            f"Portal does NOT carry military trailer tenders "
            f"(0 authority matches, 0 trailer notices from org searches)"
        )
    elif trailer_hit > 0 and auth_hit == 0:
        result["conclusion"] = (
            f"Portal HAS military trailer notices ({trailer_hit} via CPV+wojsk) "
            f"but authority name mismatch — scraper can find them with right queries"
        )
    elif trailer_hit > 0:
        result["conclusion"] = (
            f"Portal carries military trailer tenders — "
            f"{auth_hit} authority match(es), {trailer_hit} trailer notice(s)"
        )
    else:
        result["conclusion"] = (
            f"Authority found ({auth_hit} match(es)) but no trailer notices — "
            f"authority buys other equipment on this portal"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_validation(countries: list[str], headless: bool = True) -> dict:
    """Run portal validation for specified countries. Returns results dict."""
    from .core import BrowserCore

    adapter_registry = {}
    try:
        from .adapters.de_adapter import DEAdapter, create_de_config
        adapter_registry["de"] = (DEAdapter, create_de_config, _validate_de)
    except ImportError:
        pass
    try:
        from .adapters.pl_adapter import PLAdapter, create_pl_config
        adapter_registry["pl"] = (PLAdapter, create_pl_config, _validate_pl)
    except ImportError:
        pass

    all_results = {}
    screenshot_dir = str(Path("data/raw/screenshots"))

    print("\n" + "=" * 60)
    print("  PORTAL VALIDATION")
    print("=" * 60)

    with BrowserCore(headless=headless, slow_mo=100,
                     screenshot_dir=screenshot_dir) as browser:
        for code in countries:
            code = code.lower()
            if code not in adapter_registry:
                print(f"  [!] No validator for '{code}' — supported: {list(adapter_registry.keys())}")
                continue

            AdapterClass, config_factory, validate_fn = adapter_registry[code]
            adapter = AdapterClass(browser, config_factory())

            # Get known tenders
            known = get_known_tenders_by_country(code)
            if not known:
                print(f"\n  [{code.upper()}] No known TED tenders — cannot validate")
                all_results[code] = {
                    "conclusion": "No known TED tenders to validate against",
                    "tenders_checked": 0,
                }
                continue

            print(f"\n  [{code.upper()}] Validating {adapter.config.country_name} "
                  f"({len(known)} known TED tenders)")
            for n in known:
                print(f"    • {n.get('tender_id','?')}: {_authority_name(n)[:40]} — "
                      f"{_get_title_str(n)[:50]}")

            print()
            res = validate_fn(adapter, known)
            all_results[code] = res

            # Print summary
            print(f"\n  ┌─ Result: {res.get('conclusion', '?')}")
            if res.get("authority_matches"):
                print(f"  │  Authority matches ({len(res['authority_matches'])}):")
                for m in res["authority_matches"][:3]:
                    print(f"  │    ✓ {m.get('known_authority','')[:30]}")
                    print(f"  │      → '{m.get('national_title','')[:55]}'")
            if res.get("trailer_hits"):
                print(f"  │  Trailer notices ({len(res['trailer_hits'])}):")
                for h in res["trailer_hits"][:3]:
                    print(f"  │    🚛 [{h.get('authority','')[:25]}] {h.get('title','')[:50]}")
            if res.get("search_attempts"):
                print(f"  │  Searches run: {len(res['search_attempts'])}")
                for a in res["search_attempts"]:
                    if "error" not in a:
                        print(f"  │    • {a.get('query','')[:50]} → {a.get('results_count',0)} hits")
            print(f"  └─ Portal results: "
                  f"VSVgV={res.get('portal_results_vsv','?')}, "
                  f"KFZ={res.get('portal_results_kfz','?')}"
                  if code == "de" else
                  f"  └─ Searches: {len(res.get('search_attempts', []))}")

    # Save results
    output_path = Path("data/portal_validation.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n  [OK] Validation results saved → {output_path}")

    # Decision table
    print("\n  ─── Decision ───────────────────────────────────────")
    for code, res in all_results.items():
        conclusion = res.get("conclusion", "?")
        trailer_hits = len(res.get("trailer_hits", []))
        auth_hits = len(res.get("authority_matches", []))
        if trailer_hits >= 2:
            verdict = "✓ FIX ADAPTER — portal has military trailers"
        elif trailer_hits == 1:
            verdict = "~ MAYBE — 1 trailer hit, borderline"
        elif auth_hits > 0:
            verdict = "~ PARTIAL — authority present, no trailers"
        else:
            verdict = "✗ ABANDON — portal does not carry defence trailers"
        print(f"  {code.upper()}: {verdict}")
    print()

    return all_results

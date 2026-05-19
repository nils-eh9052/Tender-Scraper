"""
URL Validator (Phase 3l) — health-check ``source_url_national`` per tender.

Why this exists
  Adapters can drift: a portal changes its URL pattern (AusTender did so —
  ``/cn/{id}/View`` returned 404, the working pattern is ``/cn/Show/{id}``)
  and downstream users silently get a "Seite nicht gefunden" without the
  pipeline noticing.  This module attaches a lightweight ``_url_status``
  signal to every notice so the frontend can either hide dead links or
  flag them with a warning.

Status values
  ``alive``        HTTP 200 within timeout AND no soft-404 body signal.
  ``soft_404``     HTTP 200 but body contains "not found" / "page not found"
                   or matches a known SPA-shell fingerprint (e.g. EE React
                   shell, AusTender legacy /View redirect target). These are
                   server-side routing responses that look alive at HTTP level
                   but are functionally dead.
  ``dead``         HTTP 4xx (other than 401/403) or DNS / connection failure.
  ``auth_walled``  HTTP 401/403 — endpoint exists but requires login (e.g.
                   EE riigihanked.riik.ee, CZ NEN eIDAS). Not a true 404 —
                   the URL is genuinely there, the user just can't see it
                   without credentials. Frontend should treat as "valid but
                   external auth needed".
  ``timeout``      Connection / read timeout — usually transient, retry next run.
  ``redirect_loop``    Too many redirects.
  ``unknown``      Anything else (1xx, 5xx, weird codes).

Cache
  ``data/.url_health_cache.json``  keyed by URL (not tender_id — same portal
  page often serves multiple tenders).  Entries have a ``checked_at`` ISO
  timestamp; entries older than ``TTL_DAYS`` are re-validated.

Pipeline placement
  Phase 3l runs LATE in ``--all``: after document extraction / award-match,
  BEFORE Phase 4 export, so the exporter can pull ``_url_status`` into the
  exported ``tenders.json``.  Standalone via ``python main.py --url-check``.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests
import urllib3

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / ".url_health_cache.json"

# Re-check URLs older than this. URLs change rarely; 30 d keeps the daily run
# cheap while still catching slow drift like the AU /Cn/Show/ rename.
TTL_DAYS = 30

# HEAD requests are cheaper but many portals 405 them (AusTender + most SPAs).
# Use a ranged GET — reads first 4 KB, enough for soft-404 body checks.
_DEFAULT_TIMEOUT = 12
_MAX_REDIRECTS = 5
_BODY_READ_BYTES = 4096   # bytes to read for soft-404 body checks

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ── Soft-404 detection ───────────────────────────────────────────────────────

# Plain-text substrings that indicate a "not found" page regardless of HTTP 200.
# All matched case-insensitively against the first 4 KB of the response body.
_SOFT404_BODY_TOKENS: tuple[str, ...] = (
    # Generic English
    "404 not found",
    "page not found",
    "the page you requested could not be found",
    "this page doesn't exist",
    "no tender found",
    "tender not found",
    "notice not found",
    "opportunity not found",
    "record not found",
    # AusTender legacy (/cn/{id}/View) — still serves HTML with this heading
    "we could not find the contract notice",
    "contract notice not found",
    # Canadian / French bilingual portals
    "page introuvable",
    "page non trouvée",
    "la page demandée n'existe pas",
    # Estonian portal (riigihanked) redirects within SPA — body is the React
    # shell; we fingerprint it by the div root id present in every EE SPA page
    # but NOT the data we want (so this catches every EE SPA-hash "route").
    # We do NOT flag this as soft_404 because the URL is genuinely a valid
    # deep-link that a real browser handles correctly; instead we use a
    # separate EE-specific check further below.
)

# Host → body fragment pairs that indicate the page is a real "not found" page
# even when those words don't appear in plain text (e.g. title tag patterns).
_HOST_SPECIFIC_SOFT404: dict[str, tuple[str, ...]] = {
    "tenders.gov.au": (
        # AusTender old /cn/{id}/View pattern lands on a page with this heading
        "we could not find",
        "page not found",
    ),
}

# React-shell fingerprint for Estonian SPA — marks the URL as functional but
# data-API-auth-required, so we classify as auth_walled rather than soft_404.
_EE_SPA_FINGERPRINT = "rhr-web"


def _detect_soft404(url: str, body_snippet: bytes) -> str | None:
    """Return a status override ('soft_404' or 'auth_walled') if the body
    signals that the 200 response is functionally not-found.  Returns None
    when the body looks like a genuine page."""
    try:
        text = body_snippet.decode("utf-8", errors="replace").lower()
    except Exception:
        return None

    # EE SPA fingerprint → classify as auth_walled (real page, just needs browser)
    if "riigihanked.riik.ee" in url and _EE_SPA_FINGERPRINT in text:
        return "auth_walled"

    # Generic soft-404 tokens
    for token in _SOFT404_BODY_TOKENS:
        if token in text:
            return "soft_404"

    # Host-specific patterns
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    for pattern_host, tokens in _HOST_SPECIFIC_SOFT404.items():
        if pattern_host in host:
            for token in tokens:
                if token in text:
                    return "soft_404"

    return None


# ── Cache I/O ────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_fresh(entry: dict, ttl_days: int = TTL_DAYS) -> bool:
    ts = entry.get("checked_at")
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - when
    return age < timedelta(days=ttl_days)


# ── Single-URL probe ─────────────────────────────────────────────────────────

def _classify(status_code: int) -> str:
    # 2xx — any success counts as alive. 206 happens because the probe sends
    # a Range: header; servers that honour Range respond 206 not 200, and we
    # must not call those dead.
    if 200 <= status_code < 300:
        return "alive"
    if status_code == 401:
        return "auth_walled"
    if status_code == 403:
        # 403 has two flavours:
        #  (a) "you need to log in" (EE eIDAS, gov portals)  → auth_walled
        #  (b) "your bot UA is blocked but the page is alive in a browser"
        #      (CanadaBuys, CloudFront-fronted portals).
        # We classify both as auth_walled — the frontend treats them the
        # same: "external link, may need a real browser". Better than 'dead'
        # which would hide working CA-CB notices.
        return "auth_walled"
    if 400 <= status_code < 500:
        return "dead"
    return "unknown"


def check_url(url: str, *, session: Optional[requests.Session] = None,
              timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Issue a small GET against ``url``, classify the HTTP result, then
    apply soft-404 body detection for 200 responses.

    Returns a dict with ``status`` (one of the status values documented at
    module top) and ``http_code``. Always returns — never raises.

    Soft-404 detection reads the first _BODY_READ_BYTES bytes of the response
    body and checks for "not found" tokens or known SPA-shell fingerprints.
    This catches:
      - AusTender legacy ``/cn/{id}/View`` targets that return 200 + error page
      - Estonian riigihanked SPA hash-routes (marks as ``auth_walled``)
      - Any portal with a generic "page not found" 200 page
    """
    if not url or not url.startswith(("http://", "https://")):
        return {"status": "dead", "http_code": None, "reason": "invalid_url"}

    sess = session or _make_session()
    try:
        r = sess.get(
            url,
            timeout=timeout,
            verify=False,
            allow_redirects=True,
            headers={"Range": f"bytes=0-{_BODY_READ_BYTES - 1}"},
            stream=True,
        )
        # Read up to _BODY_READ_BYTES bytes for body analysis.
        body_snippet = b""
        try:
            for chunk in r.iter_content(chunk_size=_BODY_READ_BYTES):
                body_snippet += chunk
                if len(body_snippet) >= _BODY_READ_BYTES:
                    break
        finally:
            r.close()

        http_status = _classify(r.status_code)
        final_url = r.url if r.url != url else None

        # Soft-404 override: only applies to 2xx responses
        if http_status == "alive" and body_snippet:
            override = _detect_soft404(r.url or url, body_snippet)
            if override:
                return {
                    "status": override,
                    "http_code": r.status_code,
                    "final_url": final_url,
                    "soft404_reason": f"body match on {r.url or url}",
                }

        return {
            "status": http_status,
            "http_code": r.status_code,
            "final_url": final_url,
        }
    except requests.exceptions.TooManyRedirects:
        return {"status": "redirect_loop", "http_code": None}
    except requests.exceptions.Timeout:
        return {"status": "timeout", "http_code": None}
    except requests.exceptions.ConnectionError as exc:
        return {"status": "dead", "http_code": None, "reason": f"conn_error: {type(exc).__name__}"}
    except Exception as exc:
        return {"status": "unknown", "http_code": None, "reason": f"{type(exc).__name__}: {exc}"}


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.max_redirects = _MAX_REDIRECTS
    return s


# ── Batch over notices ───────────────────────────────────────────────────────

def _candidate_url(notice: dict) -> Optional[str]:
    """Pick the canonical URL for a notice.

    Priority: ``source_url_national`` → ``ted_url`` → ``url`` → None.
    """
    for k in ("source_url_national", "ted_url", "url", "_source_url"):
        v = notice.get(k)
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            return v
    return None


def run_url_validation(
    notices: list[dict],
    *,
    force: bool = False,
    rate_limit_seconds: float = 0.5,
    only_sources: Optional[Iterable[str]] = None,
) -> dict:
    """Walk ``notices``, attach ``_url_status`` to each, and persist a cache.

    Args:
        notices:      List of tender dicts; mutated in place.
        force:        Bypass the cache TTL — re-probe everything.
        rate_limit_seconds: Sleep between cache-miss probes (be polite to portals).
        only_sources: Optional iterable of ``_source`` codes to limit the run
                      to (e.g. ``("AU-TEN", "EE-RP")``). None = all.

    Returns aggregate stats dict.
    """
    cache = _load_cache()
    session = _make_session()
    only = set(s.upper() for s in only_sources) if only_sources else None

    stats = {
        "total": len(notices),
        "checked": 0,
        "cache_hits": 0,
        "alive": 0,
        "soft_404": 0,
        "dead": 0,
        "auth_walled": 0,
        "timeout": 0,
        "redirect_loop": 0,
        "unknown": 0,
        "no_url": 0,
        "skipped_source": 0,
    }

    for n in notices:
        src = (n.get("_source") or "").upper()
        if only and src not in only:
            stats["skipped_source"] += 1
            continue

        url = _candidate_url(n)
        if not url:
            n["_url_status"] = "no_url"
            n["_url_checked_at"] = None
            stats["no_url"] += 1
            continue

        cached = cache.get(url)
        if not force and cached and _cache_fresh(cached):
            n["_url_status"] = cached["status"]
            n["_url_checked_at"] = cached.get("checked_at")
            n["_url_http_code"] = cached.get("http_code")
            stats["cache_hits"] += 1
            stats[cached["status"]] = stats.get(cached["status"], 0) + 1
            continue

        if cache.get(url) is None and stats["checked"] > 0:
            time.sleep(rate_limit_seconds)

        result = check_url(url, session=session)
        result["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cache[url] = result
        stats["checked"] += 1
        stats[result["status"]] = stats.get(result["status"], 0) + 1

        n["_url_status"] = result["status"]
        n["_url_checked_at"] = result["checked_at"]
        n["_url_http_code"] = result.get("http_code")

    _save_cache(cache)
    return stats


# ── CLI entry point ──────────────────────────────────────────────────────────

def _resolve_relevant_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "data" / "filtered" / "relevant.json"


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="URL health check for relevant.json")
    p.add_argument("--force", action="store_true",
                   help="Bypass 30-day cache, re-probe everything.")
    p.add_argument("--source", action="append", default=None,
                   help="Limit to source code(s), repeatable (e.g. --source AU-TEN).")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't write back to relevant.json.")
    args = p.parse_args()

    rel_path = _resolve_relevant_path()
    notices = json.loads(rel_path.read_text(encoding="utf-8"))
    print(f"  Loaded {len(notices)} notices from {rel_path.name}")

    stats = run_url_validation(
        notices, force=args.force, only_sources=args.source,
    )
    print("  Stats:")
    for k, v in sorted(stats.items()):
        print(f"    {k:<18} {v}")

    if not args.dry_run:
        rel_path.write_text(json.dumps(notices, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  Wrote {rel_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

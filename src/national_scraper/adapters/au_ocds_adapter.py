"""
AusTender OCDS API Adapter (post-award Contract Notices)

Source:     https://api.tenders.gov.au/ocds/
Coverage:   Contract Notices published from 2013-01-01, ≥ AUD 10,000.
            POST-AWARD only — open Approaches to Market (ATM) are handled
            by a separate au_atm_adapter (Window E, pre-award).
Auth:       None — API is publicly accessible (empirically verified 2026-05-10).
Licence:    CC BY 4.0 — Department of Finance, Australia.
            Attribution: "Source: Department of Finance, Australia (CC BY 4.0)"

OCDS data structure (AusTender-specific):
  release.ocid                         → unique contracting-process ID
  release.date                         → publication date
  release.parties[role=procuringEntity].name  → buyer / contracting authority
  release.contracts[0].id              → AusTender CN number (e.g. "CN4037763")
  release.contracts[0].description     → full contract description (title proxy)
  release.contracts[0].value           → {amount, currency}
  release.contracts[0].items[0].classification.id → UNSPSC code
  release.contracts[0].period          → {startDate, endDate}
  release.awards[0].suppliers[0].name  → winner
  release.awards[0].value              → award value (may differ from contract value)

Amendment handling:
  AusTender appends a new release (tag=contractAmendment) for each amendment,
  keeping the same ocid. We track ocid→amendment_count and always store the
  latest release as canonical.

Pagination:
  The API returns `links.next` cursor URL. Follow until null.
  A bare `cursor=` param causes HTTP 502 — always omit when not paginating.

Filter strategy (defence + BPW-relevant):
  (a) Buyer whitelist  → high confidence
  (b) UNSPSC 4-digit prefix match + keyword → medium confidence
  Any hit in (a) OR both (b) qualifies.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
import urllib3

from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..resilience import RetrySession

logger = logging.getLogger(__name__)
urllib3.disable_warnings()

# ── Constants ────────────────────────────────────────────────────────────────

AU_API_BASE = "https://api.tenders.gov.au/ocds"
AU_PORTAL_BASE = "https://www.tenders.gov.au"
# Empirically verified 2026-05-20 (docs/AU_URL_FORMAT_260520.md):
#   /cn/{id}/View        → 302 → 404   (old, broken)
#   /Cn/Show/{id}        → 302 → 200   (correct, case-insensitive)
AU_CN_DETAIL = f"{AU_PORTAL_BASE}/cn/Show/{{cn_id}}"

_ROOT = Path(__file__).resolve().parents[3]   # ted-scraper/ted-scraper/
CACHE_DIR = _ROOT / "data" / "au_ocds_raw"
STATE_FILE = _ROOT / "data" / ".au_ocds_state.json"

# Attribution required by CC BY 4.0
LICENCE_ATTRIBUTION = "Source: Department of Finance, Australia (CC BY 3.0 AU)"

# History start — OCDS API covers from 2013-01-01
AU_HISTORY_START = date(2013, 1, 1)

_UA = (
    "TenderRadar/1.0 (BPW Defence market observation; "
    "contact: mrosenfeld@sternstewart.com)"
)

# ── Defence buyer whitelist ───────────────────────────────────────────────────

_BUYER_WL_INCLUDE = frozenset([
    "department of defence",
    "capability acquisition and sustainment group",
    "casg",
    "defence materiel organisation",
    "dmo",
    "australian signals directorate",
    "asd",
    "australian submarine agency",
    "asa",
    "defence science and technology group",
    "dstg",
    "guided weapons and explosive ordnance group",
    "gweo",
    "naval shipbuilding and sustainment group",
    "nssg",
    "defence delivery group",
    "ddg",
])

_BUYER_WL_EXCLUDE = frozenset([
    "department of veterans' affairs",
    "veterans' affairs",
])

# ── UNSPSC 4-digit prefixes (BPW-relevant: trailers, vehicles, axles) ────────

_UNSPSC_PREFIXES = frozenset([
    "2510",  # Motor vehicles (incl. military)
    "2511",  # Non-motorised / marine — keep for broad search
    "2518",  # Trailers
    "2517",  # Vehicle accessories / suspension / axles
    "2516",  # Vehicle body/cab
    "2519",  # Vehicle fuelling/tyres
    "2520",  # Vehicular power/transmission
    "2530",  # Brake/steering/axle/wheel components
    "7810",  # Road cargo transport services
])

# ── Keywords for secondary filter ────────────────────────────────────────────

_TRAILER_KW = frozenset([
    "trailer", "semi-trailer", "semitrailer",
    "low-bed", "low loader", "flatbed",
    "tank trailer", "fuel tanker",
    "military vehicle", "b-vehicle",
    "protected mobility vehicle",
    "hawkei", "bushmaster",
    "land 121", "land 8113", "land 400", "land 8710",
    "axle", "suspension", "running gear",
    "hook lift", "palletised", "epls", "drops",
    "ammunition trailer", "cargo trailer",
    "load carrier", "mission module",
    "heavy equipment transporter",
])


def create_au_ocds_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="Australia",
        country_code="AU",
        source_code="AU-TEN",
        base_url=AU_API_BASE,
        search_url=f"{AU_API_BASE}/findByDates/contractPublished",
        language="en",
        trailer_keywords=sorted(_TRAILER_KW),
        defence_authorities=[
            "Department of Defence",
            "Capability Acquisition and Sustainment Group",
            "CASG",
            "Defence Materiel Organisation",
            "Australian Signals Directorate",
            "Australian Submarine Agency",
            "Defence Science and Technology Group",
            "Defence Delivery Group",
        ],
        min_interval_seconds=1.0,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_defence_buyer(name: str) -> bool:
    low = name.lower()
    if any(ex in low for ex in _BUYER_WL_EXCLUDE):
        return False
    return "defence" in low or any(kw in low for kw in _BUYER_WL_INCLUDE)


def _has_trailer_kw(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _TRAILER_KW)


def _has_unspsc_match(items: list) -> bool:
    for item in items:
        cls = item.get("classification", {})
        if cls.get("scheme", "").upper() != "UNSPSC":
            continue
        code = str(cls.get("id", ""))
        if any(code.startswith(pfx) for pfx in _UNSPSC_PREFIXES):
            return True
    return False


def _get_procuring_entity(parties: list) -> str:
    """Extract buyer name from parties array (procuringEntity role)."""
    for p in parties:
        roles = p.get("roles", []) or []
        if "procuringEntity" in roles or "buyer" in roles:
            return p.get("name", "")
    return ""


def _parse_period(period: dict) -> str:
    if not period:
        return ""
    start = (period.get("startDate") or "")[:10]
    end = (period.get("endDate") or "")[:10]
    if start and end:
        return f"{start} — {end}"
    return start or end


def _parse_amount(val_block) -> Optional[float]:
    if not val_block:
        return None
    amt = val_block.get("amount")
    if amt is None:
        return None
    try:
        return float(amt)
    except (TypeError, ValueError):
        return None


def _cn_portal_url(cn_id: str) -> str:
    cn_clean = re.sub(r"[^\w\-]", "", cn_id)
    return f"{AU_PORTAL_BASE}/cn/Show/{cn_clean}"


def _pick_publication_date(release: dict, contract: dict) -> tuple[str, str]:
    """Resolve the most accurate tender-publication date for an AusTender release.

    Priority chain — see docs/DATE_AUDIT_260520.md. AusTender's OCDS post-award
    feed currently never populates the first three candidates (the ``tender``
    block contains only ``id``/``procurementMethod``/``procurementMethodDetails``).
    The chain stays in place so that if the AusTender team starts emitting
    ``tender.tenderPeriod`` / ``tender.publishedDate`` we automatically use it
    instead of the post-award ``release.date``.

    Returns ``(iso_yyyymmdd, source_marker)`` where source_marker is one of
    the values documented in CLAUDE.md §5 (``tender_period_start``,
    ``tender_notice``, ``contract_notice_fallback``).
    """
    tender = release.get("tender") or {}

    tp = tender.get("tenderPeriod") or {}
    start = (tp.get("startDate") or "")[:10]
    if start:
        return start, "tender_period_start"

    pub = (tender.get("publishedDate") or "")[:10]
    if pub:
        return pub, "tender_notice"

    docs = tender.get("documents") or []
    if docs:
        first_doc = docs[0] if isinstance(docs, list) else {}
        dpub = (first_doc.get("datePublished") or "")[:10]
        if dpub:
            return dpub, "tender_notice"

    # Fallback: release.date is the contract-notice publication date — post-award.
    return (release.get("date") or "")[:10], "contract_notice_fallback"


def _release_to_search_result(release: dict) -> Optional[SearchResult]:
    """Map an OCDS release to SearchResult, return None if not defence-relevant."""
    parties = release.get("parties") or []
    buyer = _get_procuring_entity(parties)

    contracts = release.get("contracts") or []
    if not contracts:
        return None
    contract = contracts[0]

    desc = (contract.get("description") or "").strip()
    all_items = []
    for c in contracts:
        all_items.extend(c.get("items") or [])

    # ── Filter logic ─────────────────────────────────────────────────────────
    buyer_match = _is_defence_buyer(buyer)
    unspsc_match = _has_unspsc_match(all_items)
    kw_match = _has_trailer_kw(desc)

    # Require content evidence (keyword OR UNSPSC) in addition to buyer match.
    # "Defence buyer alone" is too broad — covers 30%+ of AU procurement (IT,
    # food, construction). Only include when there is trailer/vehicle evidence.
    #   HIGH:   defence buyer + (trailer kw OR vehicle UNSPSC)
    #   MEDIUM: any buyer + trailer kw + vehicle UNSPSC
    if buyer_match and (kw_match or unspsc_match):
        _tier = "high"
    elif not buyer_match and kw_match and unspsc_match:
        _tier = "medium"
    else:
        return None

    cn_id = contract.get("id", "") or release.get("ocid", "")
    portal_url = _cn_portal_url(cn_id) if cn_id else ""

    awards = release.get("awards") or []
    supplier = ""
    award_val = None
    if awards:
        award0 = awards[0]
        suppliers = award0.get("suppliers") or []
        if suppliers:
            supplier = suppliers[0].get("name", "")
        award_val = _parse_amount(award0.get("value"))

    val_block = contract.get("value") or {}
    amount = _parse_amount(val_block) or award_val

    pub_date = (release.get("date") or "")[:10]
    title = desc[:200] if desc else cn_id

    # Relevance score for sorting (higher = fetch detail first)
    _score = (
        (10 if kw_match else 0)
        + (5 if unspsc_match else 0)
        + (3 if buyer_match else 0)
        + (1 if (amount or 0) > 500_000 else 0)
    )

    return SearchResult(
        title=title,
        url=portal_url,
        authority=buyer,
        date=pub_date,
        value=amount,
        currency=val_block.get("currency", "AUD"),
        reference_id=cn_id,
        snippet=f"tier:{_tier} | score:{_score} | UNSPSC:{_first_unspsc(all_items)} | supplier:{supplier[:40]}",
    )


def _first_unspsc(items: list) -> str:
    for item in items:
        cls = item.get("classification", {})
        if cls.get("scheme", "").upper() == "UNSPSC":
            return cls.get("id", "")
    return ""


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Adapter class ─────────────────────────────────────────────────────────────

class AuOcdsAdapter(BaseAdapter):
    """
    AusTender OCDS REST API — post-award Contract Notices.

    Scans by date range using contractPublished, follows cursor pagination,
    filters client-side for Defence buyers and BPW-relevant UNSPSC codes.

    For full historical backfill: scan from AU_HISTORY_START (2013-01-01).
    For daily sync: contractLastModified with 48h sliding window.
    """

    def __init__(self, browser, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = RetrySession(max_retries=3, backoff_base=2.0, rotate_ua=False)
        self._session.update_headers({
            "Accept": "application/json",
            "User-Agent": _UA,
        })
        self._last_request = 0.0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # In-memory release cache populated during search_all_keywords scan.
        # get_detail() reads from here first — avoids findById API calls when
        # the scan already fetched the full OCDS release.
        self._release_mem: dict[str, dict] = {}
        # cn_id → _published_at_source marker; populated in _parse_release and
        # read back in to_standard_format so the source survives the
        # NoticeDetail dataclass boundary.
        self._pub_src_mem: dict[str, str] = {}

    def _wait(self) -> None:
        elapsed = time.time() - self._last_request
        gap = self.config.min_interval_seconds
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_request = time.time()

    def search(self, keyword: str, max_results: int = 200) -> list[SearchResult]:
        """Keyword not used — AusTender has no server-side text filter. Actual work in search_all_keywords."""
        return []

    def search_all_keywords(
        self,
        max_results_per_keyword: int = 200,
        test_mode: bool = False,
        since_date: Optional[date] = None,
        date_field: str = "contractPublished",
        max_pages: Optional[int] = None,
    ) -> list[SearchResult]:
        """
        Scan AusTender OCDS releases, filter for Defence + BPW trailer relevance.

        Args:
            test_mode:   Limit to last 90 days, max 5 pages.
            since_date:  Override start date (default: 2024-01-01 or test window).
            date_field:  One of contractPublished, contractLastModified,
                         contractStart, contractEnd.
            max_pages:   Hard cap on pages (None = unlimited for full scan).
        """
        today = date.today()

        if test_mode:
            scan_start = today - timedelta(days=90)
            _max_pages = max_pages or 5
        else:
            scan_start = since_date or date(2024, 1, 1)
            _max_pages = max_pages  # None = follow until end

        scan_end = today
        results: dict[str, SearchResult] = {}
        amendment_counts: dict[str, int] = {}

        start_iso = scan_start.strftime("%Y-%m-%dT00:00:00Z")
        end_iso = scan_end.strftime("%Y-%m-%dT23:59:59Z")
        initial_url = f"{AU_API_BASE}/findByDates/{date_field}/{start_iso}/{end_iso}"

        logger.info(
            f"AU-TEN: scanning {date_field} {scan_start} → {scan_end}"
            + (f" (test, max {_max_pages} pages)" if test_mode else "")
        )

        url: Optional[str] = initial_url
        page = 0
        total_releases = 0
        consecutive_errors = 0

        while url:
            if _max_pages is not None and page >= _max_pages:
                logger.info(f"AU-TEN: page cap {_max_pages} reached")
                break

            self._wait()
            try:
                resp = self._session.get(url, timeout=60)
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(f"AU-TEN: request error page {page}: {exc}")
                if consecutive_errors >= 3:
                    logger.error("AU-TEN: 3 consecutive errors — aborting")
                    break
                time.sleep(10)
                continue

            if resp.status_code == 502:
                logger.warning(
                    f"AU-TEN: 502 (cursor issue?) on page {page} — stopping pagination"
                )
                break
            if resp.status_code != 200:
                logger.warning(f"AU-TEN: HTTP {resp.status_code} on page {page}")
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                time.sleep(5)
                continue

            consecutive_errors = 0
            try:
                data = resp.json()
            except Exception as exc:
                logger.warning(f"AU-TEN: JSON decode error: {exc}")
                break

            releases = data.get("releases") or []
            total_releases += len(releases)
            page_hits = 0

            for release in releases:
                ocid = release.get("ocid", "")
                tag = release.get("tag", [])

                # Track amendment count per ocid
                if isinstance(tag, list) and "contractAmendment" in tag:
                    amendment_counts[ocid] = amendment_counts.get(ocid, 0) + 1

                sr = _release_to_search_result(release)
                if sr is None:
                    continue

                # For amendments: overwrite previous entry (latest is canonical)
                key = sr.reference_id or ocid
                if key:
                    results[key] = sr
                    page_hits += 1

                    # Keep full release in memory — get_detail() reads from here
                    # first, so no findById API call is needed after a scan.
                    self._release_mem[key] = release

                    # Also persist to disk cache (best-effort)
                    cache_file = CACHE_DIR / f"{re.sub(r'[^\\w\\-]', '_', key)}.json"
                    if not cache_file.exists():
                        try:
                            cache_file.write_text(
                                json.dumps(release, ensure_ascii=False),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass

            logger.debug(
                f"AU-TEN page {page}: {len(releases)} releases, "
                f"{page_hits} defence hits, {len(results)} total"
            )

            links = data.get("links") or {}
            next_url = links.get("next", "")
            url = next_url if next_url else None
            page += 1

        logger.info(
            f"AU-TEN: scan complete — {len(results)} defence notices "
            f"from {total_releases} releases ({page} pages)"
        )

        # Save cursor state for next daily-sync
        state = _load_state()
        state["last_sync"] = today.isoformat()
        state["last_total"] = total_releases
        state["last_defence_hits"] = len(results)
        _save_state(state)

        # Sort by relevance score (embedded in snippet) — highest first
        # so that main.py's detail_limit cap retains the best notices.
        def _score_from_snippet(sr: SearchResult) -> int:
            m = re.search(r"score:(\d+)", sr.snippet or "")
            return int(m.group(1)) if m else 0

        sorted_results = sorted(results.values(), key=_score_from_snippet, reverse=True)
        return sorted_results

    def search_daily_sync(self) -> list[SearchResult]:
        """48h sliding window on contractLastModified for incremental updates."""
        today = date.today()
        window_start = today - timedelta(days=2)
        return self.search_all_keywords(
            since_date=window_start,
            date_field="contractLastModified",
        )

    def filter_defence(self, results: list) -> list:
        """Already filtered during search_all_keywords — pass through."""
        return results

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """
        Return a NoticeDetail from the in-memory scan cache, disk cache, or API.

        Priority:
        1. _release_mem  — populated during search_all_keywords (no I/O needed)
        2. disk cache    — written during scan, survives process restarts
        3. findById API  — last resort, only when running get_detail standalone
        """
        cn_id = result.reference_id
        if not cn_id:
            return None

        # 1. In-memory cache from the scan (fastest, no API call)
        release = self._release_mem.get(cn_id)

        # 2. Disk cache
        if release is None:
            safe_id = re.sub(r"[^\w\-]", "_", cn_id)
            cache_file = CACHE_DIR / f"{safe_id}.json"
            if cache_file.exists():
                try:
                    release = json.loads(cache_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

        if release is None:
            # 3. API fallback (only needed when called outside of a scan run)
            self._wait()
            try:
                resp = self._session.get(
                    f"{AU_API_BASE}/findById/{cn_id}",
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    releases = data.get("releases") or []
                    if releases:
                        release = releases[0]
            except Exception as exc:
                logger.debug(f"AU-TEN: findById {cn_id} failed: {exc}")

        if release is None:
            # Return minimal detail from SearchResult
            return NoticeDetail(
                title=result.title[:200],
                authority=result.authority,
                date=result.date,
                value=result.value,
                currency=result.currency or "AUD",
                reference_id=cn_id,
                url=result.url,
                source_code="AU-TEN",
                status="Awarded",
                raw_text=f"{LICENCE_ATTRIBUTION}\n\n{result.title}",
            )

        return self._parse_release(release, result)

    def _parse_release(self, release: dict, sr: SearchResult) -> NoticeDetail:
        parties = release.get("parties") or []
        buyer = _get_procuring_entity(parties)

        contracts = release.get("contracts") or []
        contract = contracts[0] if contracts else {}

        desc = (contract.get("description") or "").strip()
        cn_id = contract.get("id", "") or sr.reference_id or ""
        val_block = contract.get("value") or {}
        amount = _parse_amount(val_block)
        currency = val_block.get("currency", "AUD")
        period = _parse_period(contract.get("period") or {})

        # Winner from awards
        awards = release.get("awards") or []
        winner = ""
        award_amount = None
        if awards:
            award0 = awards[0]
            suppliers = award0.get("suppliers") or []
            if suppliers:
                winner = suppliers[0].get("name", "")
            award_amount = _parse_amount(award0.get("value"))

        if amount is None:
            amount = award_amount

        all_items = []
        for c in contracts:
            all_items.extend(c.get("items") or [])
        unspsc = _first_unspsc(all_items)

        # Publication-date selection — see docs/DATE_AUDIT_260520.md.
        pub_date, pub_src = _pick_publication_date(release, contract)
        if cn_id:
            self._pub_src_mem[cn_id] = pub_src
        title = desc[:200] if desc else cn_id
        portal_url = _cn_portal_url(cn_id) if cn_id else sr.url

        # Assemble raw_text for AI pipeline (includes attribution)
        raw_lines = [
            LICENCE_ATTRIBUTION,
            "",
            f"Contract Notice: {cn_id}",
            f"OCID: {release.get('ocid', '')}",
            f"Published: {pub_date}",
            f"Buyer: {buyer}",
            f"Supplier: {winner}",
            f"Value: {amount} {currency}",
            f"Contract period: {period}",
            f"UNSPSC: {unspsc}",
            "",
            "Description:",
            desc,
        ]
        raw_text = "\n".join(raw_lines)

        return NoticeDetail(
            title=title,
            description=desc[:500],
            authority=buyer,
            date=pub_date,
            value=amount,
            currency=currency,
            winner=winner,
            duration=period,
            reference_id=cn_id,
            url=portal_url,
            source_code="AU-TEN",
            raw_text=raw_text[:10000],
            status="Awarded",
        )

    def to_standard_format(self, detail: NoticeDetail) -> dict:
        """Override to include AU-specific fields and licence attribution."""
        result = super().to_standard_format(detail)
        result["_licence_attribution"] = LICENCE_ATTRIBUTION
        result["_source"] = "AU-TEN"
        # Publication-date source marker (see docs/DATE_AUDIT_260520.md).
        # AusTender's OCDS post-award feed never populates the tenderPeriod /
        # publishedDate fields, so this lands on contract_notice_fallback in
        # practice. The default protects records that never went through
        # _parse_release (minimal-detail path in get_detail).
        result["_published_at_source"] = self._pub_src_mem.get(
            detail.reference_id, "contract_notice_fallback"
        )
        return result

    def _default_currency(self) -> str:
        return "AUD"

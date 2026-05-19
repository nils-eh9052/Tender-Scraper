"""
NSPA (NATO Support and Procurement Agency) Adapter — eProcurement5G portal.

Portal: https://eportal.nspa.nato.int/eProcurement5G/Opportunities/OpportunitiesList
Investigation: docs/NSPA_PORTAL_INVESTIGATION_260514.md (Sprint 14k, 2026-05-14)

KEY FINDINGS:
- **No login required for read-only browsing** — public access.
- Anti-scraping: Dynatrace/Ruxit + bot-detection cookies (TS01*, TS2fcfcedb*).
  Connection-reset on burst requests. Adapter throttles 4-5s between page-loads
  and uses Playwright to inherit browser cookies / fingerprint.
- ASP.NET MVC backend with server-rendered HTML + Knockout.js for some interactions.
- Listing endpoint: POST /OpportunitiesList/OpportunitiesListPager
- Detail URL:       /Opportunities/DetailsOpportunity?RowIDEncrypted=<id>&reference=<ref>
- Total in scope:   ~329 FBOs + 97 active RFPs = ~426 opportunities (as of 2026-05-14).
- **Yield warning:** As of the investigation date, NSPA's PreFilter=FBO contains
  almost exclusively munitions / weapons spare parts (PzH2000, TOW, Boxer
  subsystems). Trailer/vehicle opportunities are RARE — but the adapter is
  infrastructure that catches them when they appear (and the Boxer RegSan
  Retrofit Drive Module Kit is one current borderline case).

LICENSE / COMPLIANCE:
- The opportunities list is public — by design open to non-NATO suppliers so
  they can register their interest.
- Specifications inside attachments may be export-controlled (the adapter does
  NOT auto-download attachments — only metadata; full doc-pipeline integration
  is opt-in via separate document fetch).
- BPW Defense is a registered NATO supplier (NCAGE-eligible) — pulling the
  public list for prospect screening is the intended use of the portal.

SCHEMA MAPPING:
  Opportunity Id          → reference_id          → tender_id = "NSPA-{ref}"
  Product Name            → title                 → _title_final
  Type (Supply/Services)  → _ai-helper "type"     → stored in raw_text
  Purchasing Organisation → authority             → _authority_name
  Publication Date        → date                  → _pub_date_clean
  Tentative RFP / Closing → deadline              → kept in raw_text
  Status                  → _status               → "Open" for FBO Published

NSPA is NATO-wide (32 member states) — for the pipeline we tag it as country
"NATO" with iso2 "NATO" (special, not in ISO-3166).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail
from ..core import BrowserCore

logger = logging.getLogger(__name__)

BASE_URL = "https://eportal.nspa.nato.int"
LIST_URL_FMT = BASE_URL + "/eProcurement5G/Opportunities/OpportunitiesList?PreFilter={prefilter}"
DETAIL_URL_PREFIX = BASE_URL + "/eProcurement5G/Opportunities/Opportunities/DetailsOpportunity"

# Pre-filters we actually search (Yield > 0 historically; FBO + RFP cover most defence work).
# RFQ/RFI/NOA return ~6236 each but are mostly aviation/HVAC noise.
DEFAULT_PREFILTERS = ("FBO", "RFP")

# Between-page wait (anti rate-limit). Bumped to 5s after early connection-resets.
PAGE_WAIT_MS = 5000
DETAIL_WAIT_MS = 3500

# Trailer/vehicle keywords (subset of pipeline-wide list; intentionally generous
# because NSPA pages are short and exact-match is sufficient).
NSPA_TRAILER_KEYWORDS = [
    # Direct trailer terms
    "trailer", "trailers", "anhänger", "anhanger", "remorque", "remorques",
    "przyczepa", "przyczepy", "rimorchio", "rimorchi", "släp", "släpvagn",
    # Semi-trailer + heavy haul
    "semi-trailer", "semitrailer", "sattelauflieger", "auflieger", "naczepa",
    "tieflader", "low-bed", "low bed", "lowboy", "heavy equipment transporter",
    # Vehicle / chassis (broader — NSPA often lists by vehicle family)
    "vehicle", "vehicles", "fahrzeug", "fahrzeuge", "véhicule",
    "chassis", "axle", "tow ", "towing", "drive module",
    # Specific armored / military vehicle families that often carry trailer programmes
    "boxer", "marder", "leopard", "fuchs", "wolf", "dingo", "eagle",
    "hmmwv", "humvee", "lmtv", "fmtv", "het ", "mtvr",
    # Logistics / support
    "tank ", "tanker", "fuel ", "water bowser", "decontamination",
    "field kitchen", "feldküche", "mobile kitchen",
    "container", "shelter", "iso container",
    "platform trailer", "flatbed", "recovery",
    # Loading / handling systems
    "hook-lift", "hook lift", "loading system", "palletized",
    "drops", "epls",
]


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# NSPA internal division codes → human-readable names.
# Source: NSPA organisational structure (public, nspa.nato.int/about).
_NSPA_ORG_CODES: dict[str, str] = {
    "LM":   "NSPA Logistics Management",
    "AM":   "NSPA Acquisition Management",
    "FM":   "NSPA Financial Management",
    "IT":   "NSPA Information Technology",
    "HR":   "NSPA Human Resources",
    "CIS":  "NSPA Communication & Information Systems",
    "ENG":  "NSPA Engineering",
    "OPS":  "NSPA Operations",
    "PC":   "NSPA Procurement & Contracting",
    "LOG":  "NSPA Logistics",
}

def _clean_nspa_org(raw: str) -> str:
    """Normalise NSPA Purchasing Organisation codes like 'LM   -' to readable names.

    The NSPA portal stores division abbreviations as org codes. A raw value
    consisting of only 1-4 uppercase letters + optional separators/dashes is
    treated as a division code and mapped to its full name (or generic
    'NSPA' fallback). Proper organisation names are returned as-is.
    """
    cleaned = re.sub(r"\s+", " ", (raw or "").strip())
    # Strip trailing separators like " -", " /", " |"
    cleaned = re.sub(r"[\s\-/|]+$", "", cleaned).strip()
    if not cleaned:
        return "NSPA - NATO Support and Procurement Agency"
    # Check if it looks like a bare division code (≤6 chars, all uppercase/digits)
    if re.fullmatch(r"[A-Z0-9]{1,6}", cleaned):
        return _NSPA_ORG_CODES.get(cleaned, f"NSPA - {cleaned}")
    return cleaned


def _is_trailer_relevant(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    return any(kw in text for kw in NSPA_TRAILER_KEYWORDS)


# ── AdapterConfig factory ─────────────────────────────────────────────────────

def create_nspa_config() -> AdapterConfig:
    return AdapterConfig(
        country_name="NATO",
        country_code="NATO",            # special — not an ISO-3166 code
        source_code="NSPA-EP",
        base_url=BASE_URL,
        search_url=LIST_URL_FMT.format(prefilter="FBO"),
        language="en",
        trailer_keywords=NSPA_TRAILER_KEYWORDS,
        defence_authorities=[],          # NSPA itself is THE defence authority
        min_interval_seconds=5.0,
    )


# ── Adapter ───────────────────────────────────────────────────────────────────

class NSPAAdapter(BaseAdapter):
    """Polite scraper for NSPA eProcurement5G — FBO + RFP listings.

    Uses Playwright through ``BrowserCore`` (inherited from BaseAdapter) so
    cookies and Dynatrace fingerprint persist. Reading-only — no document
    download (attachments need Knockout.js DownloadFile() ; out of scope here).
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._page = None

    # ── Lifecycle helpers ─────────────────────────────────────────────────────

    def _get_page(self):
        """Return the shared Playwright Page from BrowserCore (already opened in start())."""
        return self.browser.page

    # ── List walking ──────────────────────────────────────────────────────────

    def _parse_listing_html(self, html: str) -> list[dict]:
        """Return raw row dicts parsed from a rendered listing page."""
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table.table-condensed tr.selectable")
        out: list[dict] = []
        for r in rows:
            cells = r.find_all("td")
            if len(cells) < 6:
                continue
            ref_link = cells[0].find("a", href=True)
            ref_href = ref_link["href"] if ref_link else ""
            # The "Reference|Title" cell contains the reference + a separate title row
            ref_text = cells[0].get_text(separator="|", strip=True)
            parts = [p.strip() for p in ref_text.split("|") if p.strip()]
            reference = parts[0] if parts else ""
            title = " ".join(parts[1:]) if len(parts) > 1 else ""

            otype = _normalize_text(cells[1].get_text(separator=" / ", strip=True))
            org = _normalize_text(cells[2].get_text(separator=" / ", strip=True))
            status = _normalize_text(cells[3].get_text(separator=" ", strip=True))
            pubdate_raw = cells[4].get_text(separator=" | ", strip=True)
            rfp_raw = cells[5].get_text(separator=" | ", strip=True)

            url = BASE_URL + ref_href if ref_href else ""

            out.append({
                "reference": reference,
                "title": title,
                "type": otype,
                "org": org,
                "status": status,
                "pubdate_raw": pubdate_raw,
                "rfp_raw": rfp_raw,
                "url": url,
            })
        return out

    def _scan_prefilter(self, prefilter: str, *, test_mode: bool = False) -> list[dict]:
        """Walk all pages for one PreFilter (FBO or RFP). Returns row dicts."""
        page = self._get_page()
        url = LIST_URL_FMT.format(prefilter=prefilter)
        logger.info("NSPA: opening %s listing — %s", prefilter, url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            logger.warning("NSPA: goto failed for %s: %s", prefilter, e)
            return []
        page.wait_for_timeout(PAGE_WAIT_MS)

        # Wait for table to populate
        try:
            page.wait_for_selector("table.table-condensed tr.selectable", timeout=30_000)
        except Exception:
            logger.warning("NSPA: %s listing did not render", prefilter)
            return []

        # Total opportunity count
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        total_input = soup.find("input", id="GridPagerTotalRowCount")
        total = int(total_input["value"]) if total_input and total_input.get("value") else 0
        page_size = 10
        total_pages = (total + page_size - 1) // page_size
        logger.info("NSPA: %s has %d opportunities across %d pages",
                    prefilter, total, total_pages)

        if test_mode:
            total_pages = min(total_pages, 3)

        collected: list[dict] = []
        seen_refs: set[str] = set()

        # Page 1 — already loaded
        for row in self._parse_listing_html(page.content()):
            if row["reference"] and row["reference"] not in seen_refs:
                seen_refs.add(row["reference"])
                row["_prefilter"] = prefilter
                collected.append(row)

        for p in range(2, total_pages + 1):
            # Snapshot the first row's reference BEFORE the click — when the table
            # actually updates, that reference changes. This is more reliable than
            # a fixed wait.
            try:
                first_ref_before = page.evaluate(
                    "() => { const r = document.querySelector('table.table-condensed tr.selectable td a');"
                    "         return r ? r.getAttribute('href') : null; }"
                )
            except Exception:
                first_ref_before = None

            try:
                # NSPA pager links: <a class="page-link" command load-page='{"pageIndex": N}'>N</a>
                # The `load-page` attribute holds the JSON config; `command` is a flag.
                clicked = page.evaluate(
                    f"() => {{ const links = document.querySelectorAll('a.page-link[load-page]');"
                    f"          for (const a of links) {{ if (a.textContent.trim() === '{p}') {{ a.click(); return true; }} }}"
                    f"          return false; }}"
                )
            except Exception as e:
                logger.warning("NSPA: pager click for page %d failed: %s", p, e)
                break
            if not clicked:
                logger.info("NSPA: %s pager link for page %d not found — stopping", prefilter, p)
                break

            # Poll for table update (new first-row reference). Up to 12 s.
            updated = False
            for _ in range(12):
                page.wait_for_timeout(1000)
                try:
                    first_ref_after = page.evaluate(
                        "() => { const r = document.querySelector('table.table-condensed tr.selectable td a');"
                        "         return r ? r.getAttribute('href') : null; }"
                    )
                except Exception:
                    first_ref_after = None
                if first_ref_after and first_ref_after != first_ref_before:
                    updated = True
                    break
            if not updated:
                logger.info("NSPA: %s page %d did not update first row in 12s — stopping", prefilter, p)
                break

            before = len(collected)
            for row in self._parse_listing_html(page.content()):
                if row["reference"] and row["reference"] not in seen_refs:
                    seen_refs.add(row["reference"])
                    row["_prefilter"] = prefilter
                    collected.append(row)
            after = len(collected)
            if after == before:
                logger.info("NSPA: %s page %d yielded 0 new rows — stopping", prefilter, p)
                break

        logger.info("NSPA: %s scan complete — %d unique rows", prefilter, len(collected))
        return collected

    # ── BaseAdapter API ───────────────────────────────────────────────────────

    def search(self, keyword: str, max_results: int = 50) -> list[SearchResult]:
        """Single-keyword search not natively supported by NSPA UI — we scan
        the listing and filter client-side. ``keyword`` is honored only as a
        substring match against title (case-insensitive)."""
        all_rows: list[dict] = []
        for pf in DEFAULT_PREFILTERS:
            all_rows.extend(self._scan_prefilter(pf))

        kw = (keyword or "").lower().strip()
        matched: list[SearchResult] = []
        for row in all_rows:
            if kw and kw not in row["title"].lower():
                continue
            matched.append(SearchResult(
                title=row["title"],
                url=row["url"],
                authority=_clean_nspa_org(row["org"]),
                date=self._extract_pub_date(row["pubdate_raw"]),
                reference_id=row["reference"],
                snippet=json.dumps({
                    "type": row["type"],
                    "status": row["status"],
                    "rfp": row["rfp_raw"],
                    "prefilter": row.get("_prefilter"),
                }, ensure_ascii=False)[:400],
            ))
            if len(matched) >= max_results:
                break
        return matched

    def search_all_keywords(self, max_results_per_keyword: int = 30,  # noqa: ARG002 (kept for BaseAdapter compat)
                             test_mode: bool = False) -> list[SearchResult]:
        """Fetch all FBO + RFP rows once, then filter by trailer-keyword list.

        Overrides the BaseAdapter default (per-keyword loop) because NSPA's
        listing is small enough to scan once. Avoids the rate-limit problem of
        hitting the portal N times.
        """
        all_rows: list[dict] = []
        for pf in DEFAULT_PREFILTERS:
            all_rows.extend(self._scan_prefilter(pf, test_mode=test_mode))

        # Dedup by reference (FBO and RFP can overlap)
        unique: dict[str, dict] = {}
        for row in all_rows:
            ref = row["reference"]
            if ref and ref not in unique:
                unique[ref] = row

        # Filter by trailer keywords
        matched: list[SearchResult] = []
        for row in unique.values():
            if not _is_trailer_relevant(row["title"], row.get("type","")):
                continue
            matched.append(SearchResult(
                title=row["title"],
                url=row["url"],
                authority=_clean_nspa_org(row["org"]),
                date=self._extract_pub_date(row["pubdate_raw"]),
                reference_id=row["reference"],
                snippet=json.dumps({
                    "type": row["type"],
                    "status": row["status"],
                    "rfp": row["rfp_raw"],
                    "prefilter": row.get("_prefilter"),
                }, ensure_ascii=False)[:400],
            ))
        logger.info("NSPA: scanned %d total, matched %d trailer-relevant",
                    len(unique), len(matched))
        return matched

    def filter_defence(self, results: list[SearchResult]) -> list[SearchResult]:
        """NSPA is defence-by-definition — every opportunity is defence."""
        return results

    # ── Detail fetch ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_pub_date(text: str) -> str:
        """Pull an ISO-ish YYYY-MM-DD from 'Publication Date 06 May 2026 | …'."""
        m = re.search(
            r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})",
            text,
        )
        if not m:
            return ""
        months = {"Jan":1, "Feb":2, "Mar":3, "Apr":4, "May":5, "Jun":6,
                  "Jul":7, "Aug":8, "Sep":9, "Oct":10, "Nov":11, "Dec":12}
        d = int(m.group(1)); mo = months[m.group(2)]; y = int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """Open the detail page and pull description + attachment list (names only)."""
        if not result.url:
            return self._detail_from_search_result(result)

        page = self._get_page()
        try:
            page.goto(result.url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            logger.warning("NSPA: detail goto failed for %s: %s", result.reference_id, e)
            return self._detail_from_search_result(result)
        page.wait_for_timeout(DETAIL_WAIT_MS)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Extract field-value pairs from the labeled data section
        data_fields: dict[str, str] = {}
        # The page text contains "Label\nValue" lines (we used inner_text in the probe)
        text = soup.get_text("\n", strip=True)
        # Heuristic: lines that look like field labels
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if ln in ("Opportunity Id","Product Name","Type","Purchasing Organisation",
                     "Tentative RFP Date","Publication Date","Closing Date"):
                if i + 1 < len(lines):
                    data_fields[ln] = lines[i+1]

        # Attachment filenames (links bound via Knockout data-bind="click: DownloadFile")
        attachments: list[str] = []
        for a in soup.find_all("a"):
            if a.get("data-bind") and "DownloadFile" in a["data-bind"]:
                name = a.get_text(strip=True)
                if name:
                    attachments.append(name)

        title = data_fields.get("Product Name") or result.title
        org = _clean_nspa_org(data_fields.get("Purchasing Organisation") or result.authority)
        pub_date = data_fields.get("Publication Date") or ""
        date_iso = self._extract_pub_date(pub_date) or result.date

        # Build description from field-value pairs (no free-text body on NSPA detail page)
        desc_parts = []
        for k in ("Type", "Tentative RFP Date", "Closing Date"):
            if data_fields.get(k):
                desc_parts.append(f"{k}: {data_fields[k]}")
        if attachments:
            desc_parts.append("Attachments: " + ", ".join(attachments[:5]))
        description = " | ".join(desc_parts)[:500]

        raw_blob = {
            "data_fields": data_fields,
            "attachments": attachments,
            "url": result.url,
            "source": "NSPA-EP",
        }

        return NoticeDetail(
            title=title,
            description=description,
            authority=org,
            date=date_iso,
            reference_id=result.reference_id,
            url=result.url,
            source_code="NSPA-EP",
            raw_text=json.dumps(raw_blob, ensure_ascii=False)[:10000],
        )

    def _detail_from_search_result(self, result: SearchResult) -> NoticeDetail:
        return NoticeDetail(
            title=result.title,
            description="",
            authority=result.authority,
            date=result.date,
            reference_id=result.reference_id,
            url=result.url,
            source_code="NSPA-EP",
            raw_text=json.dumps({"source":"NSPA-EP","url":result.url}, ensure_ascii=False),
        )

    # ── DocumentRef discovery (called by document_pipeline) ───────────────────

    def list_documents(self, detail: NoticeDetail) -> list[dict]:
        """Return attachment names. URLs are NOT directly fetchable (Knockout
        DownloadFile()) — returned for visibility only; document_pipeline will
        skip these since URLs are empty."""
        try:
            raw = json.loads(detail.raw_text) if detail.raw_text else {}
        except Exception:
            raw = {}
        attachments = raw.get("attachments") or []
        return [{"name": a, "url": "", "source": "NSPA-EP"} for a in attachments]

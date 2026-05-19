"""
DE National Fallback — evergabe-online.de + service.bund.de

Search strategy (in priority order):
1. If tender_documents_url contains evergabe-online.de?id=N → direct fetch of
   that page (no JS needed — detail pages are server-rendered HTML).
   Also try tenderdocuments.html?id=N for the document bundle page.
2. If internal_reference exists → search service.bund.de full-text
   (static GET with no JS, just query param).
3. Fallback: service.bund.de free-text search with buyer + title keywords.

Returns dict with portal_url, documents (DocumentRef list), additional_fields
or None if nothing found.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
_TIMEOUT = 20

_EVERGABE_BASE = "https://www.evergabe-online.de"
_EVERGABE_DETAILS = f"{_EVERGABE_BASE}/tenderdetails.html"
_EVERGABE_DOCS    = f"{_EVERGABE_BASE}/tenderdocuments.html"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _session() -> requests.Session:
    s = requests.Session()
    s.verify = _SSL_VERIFY
    s.headers.update({"User-Agent": _UA, "Accept": "text/html,*/*"})
    return s


def search_de(
    internal_ref: str,
    buyer: str,
    title_keywords: list[str],
    tender_documents_url: str = "",
) -> Optional[dict]:
    """
    Try to find procurement documents on German national portals.

    Args:
        internal_ref:          Buyer's internal reference (e.g. "Q/U2BP/RA029/NA103").
        buyer:                 Contracting authority name (e.g. "BAAINBw").
        title_keywords:        List of significant title words for fallback search.
        tender_documents_url:  The (possibly dead) tender_documents_access URL.

    Returns:
        {portal_url, documents, additional_fields} or None.
    """
    sess = _session()

    # ── Strategy 1: evergabe-online.de by tender-ID ──────────────────────────
    ev_id = _extract_evergabe_id(tender_documents_url)
    if ev_id:
        logger.info(f"DE-fallback: evergabe id={ev_id} → fetching detail page")
        result = _fetch_evergabe(sess, ev_id)
        if result:
            return result

    # ── Strategy 2: service.bund.de by internal_reference ────────────────────
    if internal_ref:
        logger.info(f"DE-fallback: service.bund.de search by ref='{internal_ref}'")
        result = _search_service_bund(sess, internal_ref)
        if result:
            return result

    # ── Strategy 3: service.bund.de by buyer + title keywords ────────────────
    kw_query = " ".join(filter(None, [buyer] + title_keywords[:3]))
    if kw_query.strip():
        logger.info(f"DE-fallback: service.bund.de search by keywords='{kw_query[:60]}'")
        result = _search_service_bund(sess, kw_query)
        if result:
            return result

    logger.info("DE-fallback: no result found")
    return None


# ── Strategy-A: proactive Vergabeunterlagen fetch ─────────────────────────────

def fetch_vergabeunterlagen(
    buyer_profile_url: str,
    internal_reference: str = "",
    title_keywords: Optional[list[str]] = None,
    buyer: str = "",
) -> list:
    """Strategy A — proactively fetch Vergabeunterlagen PDFs for a DE tender.

    Builds on the same evergabe-online.de and service.bund.de scrapers as
    the B2-fallback ``search_de`` but is intended to run alongside (not
    instead of) the TED notice PDF. Returns DocumentRef list with
    ``doc_type="vergabeunterlagen"``; empty when nothing reachable.

    Args:
        buyer_profile_url:    Best-effort URL pointing at the buyer's portal.
                               Accepts ``…/tenderdetails.html?id=<n>`` deeplinks
                               and the bare portal stem.
        internal_reference:    Buyer's free-text reference (used for
                               service.bund.de full-text search fallback).
        title_keywords:        Significant title words (last-resort search).
        buyer:                 Contracting authority short name (e.g. "BAAINBw").
    """
    if not buyer_profile_url and not internal_reference and not title_keywords:
        return []
    sess = _session()
    docs: list = []

    ev_id = _extract_evergabe_id(buyer_profile_url)
    if ev_id:
        result = _fetch_evergabe(sess, ev_id)
        if result and result.get("documents"):
            docs.extend(_tag_vergabeunterlagen(result["documents"], "DE-EV"))
    elif buyer_profile_url and "evergabe-online.de" in buyer_profile_url:
        # Portal-stem URL — no tender-id available, can't deeplink. Skip.
        logger.info("DE strategy-a: evergabe URL has no id parameter, skipping")

    # service.bund.de fallback — useful when evergabe gave nothing
    if not docs and internal_reference:
        result = _search_service_bund(sess, internal_reference)
        if result and result.get("documents"):
            docs.extend(_tag_vergabeunterlagen(result["documents"], "DE-SB"))

    if not docs and (title_keywords or buyer):
        kw_query = " ".join(filter(None, [buyer] + (title_keywords or [])[:3]))
        if kw_query.strip():
            result = _search_service_bund(sess, kw_query)
            if result and result.get("documents"):
                docs.extend(_tag_vergabeunterlagen(result["documents"], "DE-SB"))

    return docs


def _tag_vergabeunterlagen(docs: list, source: str) -> list:
    """Re-tag DocumentRefs as Strategy-A Vergabeunterlagen."""
    out = []
    for d in docs:
        d.doc_type = "vergabeunterlagen"
        if not d.source or d.source == "":
            d.source = source
        out.append(d)
    return out


# ── evergabe-online.de helpers ─────────────────────────────────────────────────

def _extract_evergabe_id(url: str) -> str:
    """Extract numeric evergabe ID from tenderdetails/tenderdocuments URL."""
    if not url:
        return ""
    m = re.search(r"[?&]id=(\d+)", url)
    return m.group(1) if m else ""


def _fetch_evergabe(sess: requests.Session, ev_id: str) -> Optional[dict]:
    """
    Fetch the evergabe tender detail page + document bundle page.
    Returns result dict or None.
    """
    portal_url = f"{_EVERGABE_DETAILS}?id={ev_id}"
    html = _get_html(sess, portal_url)

    if html is None:
        # Try the document bundle URL variant
        portal_url = f"{_EVERGABE_DOCS}?id={ev_id}"
        html = _get_html(sess, portal_url)

    if html is None or len(html) < 500:
        logger.debug(f"DE-fallback: evergabe page empty/missing for id={ev_id}")
        return None

    docs = _extract_evergabe_documents(html, ev_id)
    if not docs:
        # Also fetch the document list subpage
        doc_url = f"{_EVERGABE_DOCS}?id={ev_id}"
        if portal_url != doc_url:
            html2 = _get_html(sess, doc_url)
            if html2:
                docs = _extract_evergabe_documents(html2, ev_id)

    additional = _parse_de_fields(html)

    logger.info(
        f"DE-fallback: evergabe id={ev_id} → "
        f"{len(docs)} document(s), winner={additional.get('winner', '')[:30]}"
    )
    return {
        "portal_url": portal_url,
        "documents": docs,
        "additional_fields": additional,
    }


def _get_html(sess: requests.Session, url: str) -> Optional[str]:
    """GET a URL, return decoded HTML or None on error."""
    try:
        resp = sess.get(url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            logger.debug(f"DE-fallback: GET {url[:80]} → {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.debug(f"DE-fallback: GET {url[:80]} failed: {exc}")
        return None


def _extract_evergabe_documents(html: str, ev_id: str) -> list:
    """
    Parse evergabe HTML for downloadable procurement documents.

    evergabe-online.de serves documents as:
    - <a href="/tenderDocuments.html?..."> or /Download?...
    - <a href="...filename.pdf">
    - <a class="... download ...">
    """
    from src.document_pipeline.discovery import DocumentRef

    docs = []
    seen_urls: set[str] = set()

    # Patterns for download links on evergabe
    patterns = [
        r'href="([^"]*(?:Download|tenderDocuments|downloadDocument|/doc/)[^"]*)"',
        r'href="([^"]*\.pdf(?:\?[^"]*)?)"',
        r'href="([^"]*\.docx?(?:\?[^"]*)?)"',
        r'href="([^"]*\.xlsx?(?:\?[^"]*)?)"',
    ]
    for pat in patterns:
        for href in re.findall(pat, html, re.IGNORECASE):
            if not href or href in seen_urls:
                continue
            if href.startswith("/"):
                href = _EVERGABE_BASE + href
            elif not href.startswith("http"):
                href = _EVERGABE_BASE + "/" + href
            seen_urls.add(href)
            fmt = _guess_fmt(href)
            # Try to find a label near this link
            label = _find_link_label(html, href.replace(_EVERGABE_BASE, "")) or href.split("/")[-1][:60]
            docs.append(DocumentRef(
                url=href,
                format=fmt,
                language="DEU",
                title=label[:120],
                source="DE-EV",
                tender_id=f"ev-{ev_id}",
                doc_type="tender_document",
            ))

    return docs[:8]  # cap at 8 documents


def _find_link_label(html: str, href_fragment: str) -> str:
    """Find the text label near an href fragment in HTML."""
    esc = re.escape(href_fragment[:40])
    m = re.search(
        rf'href="[^"]*{esc}[^"]*"[^>]*>([^<]{{3,80}})<',
        html, re.IGNORECASE
    )
    return m.group(1).strip() if m else ""


def _guess_fmt(url: str) -> str:
    path = url.split("?")[0].lower()
    for ext in ("pdf", "docx", "doc", "xlsx", "xls"):
        if path.endswith(f".{ext}"):
            return ext
    return "pdf"  # evergabe mostly serves PDFs


# ── service.bund.de helpers ────────────────────────────────────────────────────

def _search_service_bund(sess: requests.Session, query: str) -> Optional[dict]:
    """
    Try service.bund.de static search (no JS). Returns first plausible result
    with its URL as portal_url (no direct document downloads here).
    """
    import urllib.parse
    search_url = (
        "https://www.service.bund.de/Content/DE/Ausschreibungen/Suche/Formular.html"
        f"?nn=4641514&templateQueryString={urllib.parse.quote(query)}&submit=Finden"
    )
    html = _get_html(sess, search_url)
    if html is None or len(html) < 500:
        return None

    # Extract result links (service.bund.de result links contain "IMPORTE")
    links = re.findall(r'href="([^"]*IMPORTE[^"]*)"', html)
    if not links:
        return None

    href = links[0]
    if not href.startswith("http"):
        href = "https://www.service.bund.de" + href

    # Fetch the detail page for text content
    detail_html = _get_html(sess, href)
    additional = _parse_de_fields(detail_html) if detail_html else {}

    # service.bund.de detail pages describe the tender but rarely have direct PDF links
    # Return the detail page as an HTML DocumentRef for AI extraction
    docs = []
    if detail_html and len(detail_html) > 200:
        from src.document_pipeline.discovery import DocumentRef
        docs.append(DocumentRef(
            url=href,
            format="html",
            language="DEU",
            title="service.bund.de detail",
            source="DE-SB",
            tender_id="",
            doc_type="tender_notice_html",
        ))

    logger.info(f"DE-fallback: service.bund.de '{query[:40]}' → {len(docs)} doc(s) at {href[:60]}")
    return {
        "portal_url": href,
        "documents": docs,
        "additional_fields": additional,
    } if docs else None


# ── Field extraction ───────────────────────────────────────────────────────────

def _parse_de_fields(html: str) -> dict:
    """Extract structured fields from a German tender HTML page."""
    if not html:
        return {}
    # Replace block-level closing tags with newlines to preserve field boundaries
    text = re.sub(r"</(?:p|div|li|h[1-6]|tr|td)[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<(?:br|hr)[^/]*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize horizontal whitespace only — keep newlines for field-boundary detection
    text = re.sub(r"[ \t]+", " ", text)

    return {
        "winner":            _de_winner(text),
        "quantity":          _de_quantity(text),
        "contract_duration": _de_duration(text),
        "value":             _de_value(text),
    }


def _de_winner(text: str) -> str:
    for pat in [
        r"(?:Auftragnehmer|Zuschlag erteilt an|Zuschlag an|Bieter)[:\s]+([^\n|<]{5,100})",
        r"(?:Zuschlag wurde erteilt)[^.]{0,30}([A-Z][a-zA-Z\s&.,-]{5,80})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip().split("|")[0].strip()
            if len(name) > 4:
                return name[:100]
    return ""


def _de_quantity(text: str) -> Optional[int]:
    for pat in [
        r"(\d[\d.]*)\s*(?:Stück|Stk\.?|Einheit(?:en)?|Fahrzeuge?|Anhänger)",
        r"(?:Menge|Anzahl|Stückzahl)[:\s]+(\d[\d.]*)",
        r"(\d+)\s*(?:[Ss]t(?:ück)?\.?)\b",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(".", ""))
            except ValueError:
                continue
    return None


def _de_duration(text: str) -> str:
    for pat in [
        r"(?:Laufzeit|Vertragsdauer|Lieferfrist)[:\s]+([^\n|<]{3,60})",
        r"(\d+)\s*(?:Monate?|Wochen|Jahre?)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:60]
    return ""


def _de_value(text: str) -> Optional[float]:
    for pat in [
        r"(?:Auftragswert|Schätzwert|Gesamtwert|Auftragswert)[^\d]{0,20}([\d.,]+)\s*(?:EUR|€)",
        r"([\d.,]+)\s*EUR\b",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                v = float(raw)
                if v > 100:
                    return v
            except ValueError:
                continue
    return None

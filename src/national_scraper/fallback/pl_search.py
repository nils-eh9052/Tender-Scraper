"""
PL National Fallback — ezamowienia.gov.pl REST API

Search strategy:
1. If buyer_profile_url contains platformazakupowa.pl/pn/{code} → extract buyer_code
   and search ezamowienia API by OrganizationName derived from the buyer code.
2. Search ezamowienia.gov.pl Board/Search API by OrganizationName (buyer name).
3. Match results against internal_reference or title_keywords to pick the right notice.
4. Fetch notice HTML body via GetNoticeHtmlBodyById → return as DocumentRef (txt).

The ezamowienia API does not expose SWZ-PDF URLs directly, but the HTML notice text
contains the full structured tender content (description, quantities, requirements)
suitable for AI extraction.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
_TIMEOUT = 15
_API_BASE = "https://ezamowienia.gov.pl/mo-board/api/v1/Board"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Polish military organisation patterns extracted from platformazakupowa buyer codes
_BUYER_CODE_TO_ORG = {
    "12wog":   "12 Wojskowy Oddział Gospodarczy",
    "4rblog":  "4 Regionalna Baza Logistyczna",
    "3fog":    "3 Flotylla Okrętów",
    "inspek":  "Inspektorat Uzbrojenia",
    "witu":    "Wojskowy Instytut Techniczny Uzbrojenia",
    "1wog":    "1 Wojskowy Oddział Gospodarczy",
    "2wog":    "2 Wojskowy Oddział Gospodarczy",
    "41bl":    "41 Baza Lotnictwa Szkolnego",
    "mon":     "Ministerstwo Obrony Narodowej",
    "amw":     "Agencja Mienia Wojskowego",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.verify = _SSL_VERIFY
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "application/json",
        "Origin": "https://ezamowienia.gov.pl",
        "Referer": "https://ezamowienia.gov.pl/mo-client-board/bzp/list",
    })
    return s


def search_pl(
    internal_ref: str,
    buyer: str,
    title_keywords: list[str],
    buyer_profile_url: str = "",
) -> Optional[dict]:
    """
    Try to find procurement notice on ezamowienia.gov.pl.

    Args:
        internal_ref:       Buyer's internal reference (e.g. "D/08/12WOG/2025").
        buyer:              Contracting authority name.
        title_keywords:     Significant title words for matching.
        buyer_profile_url:  Buyer profile URL (e.g. "https://platformazakupowa.pl/pn/12wog").

    Returns:
        {portal_url, documents, additional_fields} or None.
    """
    sess = _session()

    # Build list of organisation name candidates to try
    org_candidates = _build_org_candidates(buyer, buyer_profile_url)

    for org_name in org_candidates:
        logger.info(f"PL-fallback: searching ezamowienia by org='{org_name}'")
        items = _api_search(sess, {"OrganizationName": org_name}, max_results=100)
        if not items:
            continue

        # Try to match against internal_ref or title_keywords
        matched = _match_notice(items, internal_ref, title_keywords)
        if matched is None:
            logger.debug(f"PL-fallback: no match in {len(items)} results for '{org_name}'")
            continue

        result = _build_result(sess, matched)
        if result:
            return result

    logger.info("PL-fallback: no result found")
    return None


# ── Strategy-A: proactive SWZ document fetch ──────────────────────────────────

def fetch_swz_documents(
    buyer_profile_url: str,
    internal_reference: str = "",
    title_keywords: Optional[list[str]] = None,
    buyer: str = "",
) -> list:
    """Strategy A — proactively fetch SWZ (Specyfikacja Warunków Zamówienia) PDFs.

    Tries three sources in order:
        1. **ezamowienia.gov.pl** Board/Search API. The API exposes a documents
           endpoint per notice (``Board/GetNoticeAttachments``); we pull the
           list and surface each as a DocumentRef.
        2. **platformazakupowa.pl** buyer-profile HTML scrape — extracts links
           ending in ``.pdf``/``.docx``/``.zip``.
        3. **portalsmartpzp.pl** (SmartPZP, used by 12 WOG) — best-effort HTML
           link extraction.

    ZIP-archives are surfaced as ``format="zip"`` DocumentRefs; the downloader
    must unpack them downstream (Strategy-A orchestrator handles that).
    """
    sess = _session()
    docs: list = []

    # 1. ezamowienia by org+ref — first try the Attachments endpoints,
    #    then fall back to the notice HTML body wrapped as text DocumentRef.
    try:
        org_cands = _build_org_candidates(buyer, buyer_profile_url)
        for org_name in org_cands:
            items = _api_search(sess, {"OrganizationName": org_name}, max_results=80)
            if not items:
                continue
            matched = _match_notice(items, internal_reference, title_keywords or [])
            if matched is None:
                continue
            object_id = matched.get("objectId", "")
            if not object_id:
                continue
            api_docs = _fetch_ezamowienia_attachments(sess, object_id, matched)
            if api_docs:
                docs.extend(api_docs)
                break
            # Attachment endpoints returned 404 — pull the HTML notice body
            # and surface it as a text DocumentRef. Less spec-dense than a
            # raw SWZ PDF but still feeds AI structurer reasonably.
            html_body = _fetch_notice_html(sess, object_id)
            if html_body and len(html_body) > 500:
                from src.document_pipeline.discovery import DocumentRef
                notice_num = (matched.get("noticeNumber")
                              or matched.get("referenceNumber") or object_id)
                docs.append(DocumentRef(
                    url=f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{object_id}",
                    format="txt",
                    language="POL",
                    title=f"{notice_num}_bzp_notice.txt",
                    source="PL-EZP",
                    tender_id="",
                    doc_type="vergabeunterlagen",
                    extra={"text": html_body[:15000], "fallback": "notice_html_body"},
                ))
                break
    except Exception as exc:
        logger.warning(f"PL strategy-a: ezamowienia error: {exc}")

    # 2. platformazakupowa / portalsmartpzp HTML scrape
    if buyer_profile_url:
        if "platformazakupowa.pl" in buyer_profile_url:
            docs.extend(_scrape_platformazakupowa(sess, buyer_profile_url, title_keywords or []))
        elif "portalsmartpzp.pl" in buyer_profile_url or "smartpzp.pl" in buyer_profile_url:
            docs.extend(_scrape_smartpzp(sess, buyer_profile_url))

    # De-dup by URL
    seen: set[str] = set()
    dedup = []
    for d in docs:
        if d.url in seen:
            continue
        seen.add(d.url)
        d.doc_type = "vergabeunterlagen"
        dedup.append(d)
    return dedup


def _fetch_ezamowienia_attachments(
    sess: requests.Session, object_id: str, item: dict,
) -> list:
    """Pull attachments endpoint for an ezamowienia notice."""
    from src.document_pipeline.discovery import DocumentRef

    out: list = []
    notice_num = item.get("noticeNumber") or item.get("referenceNumber") or object_id
    candidates = [
        f"{_API_BASE}/GetAttachmentList",
        f"{_API_BASE}/GetNoticeAttachments",
        f"{_API_BASE}/GetDocuments",
    ]
    for endpoint in candidates:
        try:
            resp = sess.get(endpoint, params={"noticeId": object_id}, timeout=_TIMEOUT)
            if resp.status_code != 200:
                continue
            try:
                payload = resp.json()
            except Exception:
                continue
            items = payload if isinstance(payload, list) else (payload.get("items") or payload.get("attachments") or [])
            if not items:
                continue
            for att in items:
                if not isinstance(att, dict):
                    continue
                url = att.get("url") or att.get("downloadUrl") or att.get("fileUrl") or ""
                name = att.get("fileName") or att.get("name") or att.get("title") or "swz_document"
                if not url:
                    # synthesise URL using attachment id
                    att_id = att.get("id") or att.get("attachmentId")
                    if att_id:
                        url = f"{_API_BASE}/DownloadAttachment?attachmentId={att_id}"
                if not url:
                    continue
                fmt = _fmt_from_ext(name) or "pdf"
                out.append(DocumentRef(
                    url=url,
                    format=fmt,
                    language="POL",
                    title=str(name)[:120],
                    source="PL-EZP",
                    tender_id="",
                    doc_type="vergabeunterlagen",
                    extra={"notice_num": notice_num, "object_id": object_id},
                ))
            if out:
                return out
        except Exception as exc:
            logger.debug(f"PL strategy-a: {endpoint} error: {exc}")
    return out


def _scrape_platformazakupowa(
    sess: requests.Session, profile_url: str, title_keywords: list[str],
) -> list:
    """Scrape a platformazakupowa.pl buyer profile for SWZ document links.

    The buyer-profile page lists active tenders; each tender has a detail
    page with downloadable SWZ attachments. We do a static GET and harvest
    any direct ``.pdf/.docx/.zip`` hrefs — good enough for a smoke check;
    deeper navigation would need Playwright.
    """
    from src.document_pipeline.discovery import DocumentRef
    docs: list = []
    seen: set[str] = set()
    try:
        resp = sess.get(profile_url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        html = resp.text
    except Exception as exc:
        logger.debug(f"PL strategy-a: platformazakupowa fetch failed: {exc}")
        return []

    for pat in [
        r'href="([^"]*\.pdf(?:\?[^"]*)?)"',
        r'href="([^"]*\.docx?(?:\?[^"]*)?)"',
        r'href="([^"]*\.zip(?:\?[^"]*)?)"',
    ]:
        for href in re.findall(pat, html, re.IGNORECASE):
            if href in seen:
                continue
            seen.add(href)
            full = href if href.startswith("http") else (
                "https://platformazakupowa.pl" + ("" if href.startswith("/") else "/") + href
            )
            fmt = _fmt_from_ext(full) or "pdf"
            label = full.split("/")[-1].split("?")[0][:100] or "swz"
            docs.append(DocumentRef(
                url=full,
                format=fmt,
                language="POL",
                title=label,
                source="PL-PZK",
                tender_id="",
                doc_type="vergabeunterlagen",
            ))
    return docs[:8]


def _scrape_smartpzp(sess: requests.Session, profile_url: str) -> list:
    """SmartPZP buyer-portal HTML scrape — same approach as platformazakupowa."""
    from src.document_pipeline.discovery import DocumentRef
    docs: list = []
    try:
        resp = sess.get(profile_url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        html = resp.text
    except Exception as exc:
        logger.debug(f"PL strategy-a: smartpzp fetch failed: {exc}")
        return []

    for pat in [
        r'href="([^"]*\.pdf(?:\?[^"]*)?)"',
        r'href="([^"]*\.docx?(?:\?[^"]*)?)"',
        r'href="([^"]*\.zip(?:\?[^"]*)?)"',
    ]:
        for href in re.findall(pat, html, re.IGNORECASE):
            full = href if href.startswith("http") else (
                "https://portalsmartpzp.pl" + ("" if href.startswith("/") else "/") + href
            )
            fmt = _fmt_from_ext(full) or "pdf"
            label = full.split("/")[-1].split("?")[0][:100] or "swz"
            docs.append(DocumentRef(
                url=full,
                format=fmt,
                language="POL",
                title=label,
                source="PL-SPZP",
                tender_id="",
                doc_type="vergabeunterlagen",
            ))
    return docs[:8]


def _fmt_from_ext(name: str) -> str:
    name = (name or "").lower().split("?")[0]
    for ext in ("pdf", "docx", "doc", "xlsx", "xls", "zip"):
        if name.endswith(f".{ext}"):
            return ext
    return ""


def _build_org_candidates(buyer: str, profile_url: str) -> list[str]:
    """Build a list of organisation name strings to try."""
    candidates: list[str] = []

    # From platformazakupowa buyer code (e.g. "12wog" from ".../pn/12wog")
    if profile_url:
        m = re.search(r"/pn/([a-z0-9]+)", profile_url.lower())
        if m:
            code = m.group(1)
            if code in _BUYER_CODE_TO_ORG:
                candidates.append(_BUYER_CODE_TO_ORG[code])
            else:
                # Numeric code: try "Wojskowy Oddział Gospodarczy {N}"
                num_m = re.match(r"(\d+)wog", code)
                if num_m:
                    candidates.append(f"{num_m.group(1)} Wojskowy Oddział Gospodarczy")

    # From buyer name directly
    if buyer and buyer not in candidates:
        candidates.append(buyer)

    # Fallback: generic military patterns from buyer string
    if buyer:
        for kw in ["Wojsk", "Inspektorat", "Regionalna Baza", "Agencja Mienia"]:
            if kw.lower() in buyer.lower() and buyer not in candidates:
                candidates.append(buyer[:60])
                break

    return candidates


def _api_search(sess: requests.Session, params: dict, max_results: int = 100) -> list:
    """Paginate the Board/Search API and return raw notice dicts."""
    base_params = {
        "SortingColumnName": "PublicationDate",
        "SortingDirection":  "DESC",
        "publicationDateFrom": "2023-01-01T00:00:00Z",
    }
    all_items: list[dict] = []
    page = 1
    page_size = min(100, max_results)

    while len(all_items) < max_results:
        call_params = {**base_params, **params, "PageNumber": page, "PageSize": page_size}
        try:
            resp = sess.get(f"{_API_BASE}/Search", params=call_params, timeout=_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(f"PL-fallback: API {resp.status_code} page {page}")
                break
            pagination = json.loads(resp.headers.get("X-Pagination", "{}"))
            items = resp.json()
            if not items:
                break
            all_items.extend(items)
            if not pagination.get("HasNext", False) or len(all_items) >= max_results:
                break
            page += 1
            time.sleep(0.5)
        except Exception as exc:
            logger.error(f"PL-fallback: API error page {page}: {exc}")
            break

    return all_items[:max_results]


def _match_notice(items: list[dict], internal_ref: str, title_keywords: list[str]) -> Optional[dict]:
    """
    Pick the best matching notice from API results.
    Priority: exact internal_ref match > title keyword overlap > first result.
    """
    if not items:
        return None

    ref_lower = internal_ref.lower() if internal_ref else ""
    kw_lower = [k.lower() for k in title_keywords if k]

    best: Optional[dict] = None
    best_score = -1

    for item in items:
        order_obj = (item.get("orderObject", "") or "").lower()
        notice_num = (item.get("noticeNumber", "") or "").lower()

        # Exact internal_ref match
        if ref_lower and (ref_lower in notice_num or ref_lower in order_obj):
            return item  # immediate winner

        # Title keyword score
        score = sum(1 for kw in kw_lower if kw in order_obj)
        if score > best_score:
            best_score = score
            best = item

    # Accept if we matched at least one keyword, otherwise take first
    if best_score > 0:
        return best
    return items[0] if items else None


def _build_result(sess: requests.Session, item: dict) -> Optional[dict]:
    """
    Build a fallback result dict from an ezamowienia API notice item.
    Fetches the full HTML body for AI extraction.
    """
    object_id = item.get("objectId", "")
    notice_num = item.get("noticeNumber", "") or item.get("referenceNumber", "")

    portal_url = ""
    if object_id:
        portal_url = (
            f"https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{object_id}"
        )

    # Fetch full HTML notice body
    html_text = ""
    if object_id:
        html_text = _fetch_notice_html(sess, object_id)

    if not html_text:
        logger.debug(f"PL-fallback: empty notice body for objectId={object_id}")
        return None

    from src.document_pipeline.discovery import DocumentRef

    doc = DocumentRef(
        url=portal_url or f"internal://pl_fallback/{object_id}",
        format="txt",
        language="POL",
        title=f"{notice_num}_bzp_notice.txt",
        source="PL-BZP",
        tender_id="",
        doc_type="national_page_text",
        extra={"text": html_text[:15000]},
    )

    additional = _parse_pl_fields(html_text)

    logger.info(
        f"PL-fallback: found {notice_num} ({len(html_text)} chars), "
        f"winner={additional.get('winner','')[:30]}"
    )
    return {
        "portal_url": portal_url,
        "documents": [doc],
        "additional_fields": additional,
    }


def _fetch_notice_html(sess: requests.Session, object_id: str) -> str:
    """Fetch notice HTML body from GetNoticeHtmlBodyById API."""
    try:
        resp = sess.get(
            f"{_API_BASE}/GetNoticeHtmlBodyById",
            params={"noticeId": object_id},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f"PL-fallback: GetNoticeHtmlBodyById {resp.status_code}")
            return ""
        raw = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
        if isinstance(raw, str):
            return _html_to_text(raw)
        return ""
    except Exception as exc:
        logger.error(f"PL-fallback: GetNoticeHtmlBodyById error: {exc}")
        return ""


def _html_to_text(html: str) -> str:
    """Strip HTML tags to plain text."""
    import html as _html_mod
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(h[1-6]|p|div|li|br|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html_mod.unescape(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


# ── Field extraction ───────────────────────────────────────────────────────────

def _parse_pl_fields(text: str) -> dict:
    return {
        "winner":            _pl_winner(text),
        "quantity":          _pl_quantity(text),
        "contract_duration": _pl_duration(text),
        "value":             _pl_value(text),
    }


def _pl_winner(text: str) -> str:
    for pat in [
        r"7\.3\.1\)[^\n]*zamówienia[:\s]+([^\n]{5,120})",
        r"(?:Nazwa \(firma\) wykonawcy)[^\n]*:\s+([^\n]{5,120})",
        r"(?:Nazwa wykonawcy|Wybrany wykonawca)[:\s]+([^\n]{5,100})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if not re.match(r"^[\d\s,.\+]+$", name):
                return name[:120]
    return ""


def _pl_quantity(text: str) -> Optional[int]:
    for pat in [
        r"(\d[\d\s]*)\s*(?:sztuk|szt\.?|egzemplarz|egz\.|komplet|zestawów)",
        r"(?:Ilość|Liczba)[:\s]+(\d[\d\s]*)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                v = int(m.group(1).replace(" ", ""))
                if 1 <= v <= 10000:
                    return v
            except ValueError:
                continue
    return None


def _pl_duration(text: str) -> str:
    for pat in [
        r"8\.3\.\)[^\n]*realizacji[^\n]*:\s+([^\n]{3,80})",
        r"(?:Okres realizacji|Czas trwania zamówienia)[:\s]+([^\n]{3,60})",
        r"(\d+)\s*(?:miesięcy|miesiące|tygodni|lat|dni)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:80]
    return ""


def _pl_value(text: str) -> Optional[float]:
    for pat in [
        r"4\.3\.\)[^\n]*zamówienia[:\s]*([\d\s]+)\s*PLN",
        r"8\.2\.\)[^\n]*umow[^\n]*:\s*([\d\s,.]+)\s*PLN",
        r"(?:Wartość zamówienia|Szacunkowa wartość)[^\d]{0,20}([\d\s,.]+)\s*(?:PLN|zł)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(" ", "").replace(",", ".")
            try:
                v = float(raw)
                if v > 100:
                    return v
            except ValueError:
                continue
    return None

"""
CZ National Fallback — verejnezakazky.vop.cz + nen.nipez.cz

Search strategy:
1. If tender_documents_url is verejnezakazky.vop.cz/vz* → direct HTTP GET.
   VOP portal serves static HTML, no JS required.
2. If internal_reference exists → try constructing NEN detail URL from it.
   NEN detail URL pattern: /en/verejne-zakazky/detail-zakazky/{dashed-sys-num}
   The internal_reference from TED XML is the buyer's own ID, not the NEN system num.
   We search NEN by trying the internal_reference as a query parameter.
3. For nen.nipez.cz profile URLs (e.g. /profil/MO) → extract tenders from the
   buyer profile page via a static GET.
4. Generic NEN search via static GET on the search URL (server renders result HTML).

NEN note: nen.nipez.cz is a React SPA but the initial server-rendered HTML often
contains tender data in a <script id="__NEXT_DATA__"> JSON blob or in the SSR HTML.
We try a static GET first; if the result HTML is too thin, we fall back to the VOP
portal approach.
"""
from __future__ import annotations

import json
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

_VOP_BASE = "https://verejnezakazky.vop.cz"
_NEN_BASE = "https://nen.nipez.cz"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _session() -> requests.Session:
    s = requests.Session()
    s.verify = _SSL_VERIFY
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
    })
    return s


def search_cz(
    internal_ref: str,
    buyer: str,
    title_keywords: list[str],
    tender_documents_url: str = "",
) -> Optional[dict]:
    """
    Try to find procurement documents on Czech national portals.

    Args:
        internal_ref:          Buyer's internal reference (e.g. "OVZ/018/3/2025").
        buyer:                 Contracting authority name (e.g. "VOP CZ, s.p.").
        title_keywords:        Significant title words.
        tender_documents_url:  The (possibly dead) tender_documents_access URL.

    Returns:
        {portal_url, documents, additional_fields} or None.
    """
    sess = _session()

    # ── Strategy 1: direct VOP portal URL ────────────────────────────────────
    if tender_documents_url and "verejnezakazky.vop.cz" in tender_documents_url:
        vop_id = _extract_vop_id(tender_documents_url)
        if vop_id:
            logger.info(f"CZ-fallback: VOP direct id={vop_id}")
            result = _fetch_vop(sess, vop_id)
            if result:
                return result

    # ── Strategy 2: NEN search by internal_reference ─────────────────────────
    if internal_ref:
        logger.info(f"CZ-fallback: NEN search by internal_ref='{internal_ref}'")
        result = _search_nen(sess, internal_ref)
        if result:
            return result

    # ── Strategy 3: NEN profile URL → extract tender list ────────────────────
    if tender_documents_url and "nen.nipez.cz" in tender_documents_url:
        result = _fetch_nen_profile(sess, tender_documents_url, title_keywords)
        if result:
            return result

    # ── Strategy 4: NEN keyword search ───────────────────────────────────────
    keywords = [k for k in title_keywords if len(k) > 3][:2]
    for kw in keywords:
        logger.info(f"CZ-fallback: NEN search by keyword='{kw}'")
        result = _search_nen(sess, kw)
        if result:
            return result

    logger.info("CZ-fallback: no result found")
    return None


# ── Strategy-A: proactive Zadávací dokumentace fetch ─────────────────────────

def fetch_lv_documents(
    buyer_profile_url: str,
    internal_reference: str = "",
    title_keywords: Optional[list[str]] = None,
    buyer: str = "",
) -> list:
    """Strategy A — proactively fetch CZ Zadávací dokumentace (LV-equivalent).

    Routes by buyer-profile host:
        * verejnezakazky.vop.cz → direct VOP scrape (static HTML)
        * nen.nipez.cz/profil/MO → buyer-profile listing + detail-page scrape
        * other ``*.gov.cz`` / ``*.vz`` portals → best-effort
          ``_get_html`` + ``.pdf/.docx`` extraction

    eIDAS-protected attachments (302 → SSO redirect, 403 on HEAD) are skipped
    silently with an ``auth_blocked`` marker in ``DocumentRef.extra`` so the
    orchestrator can record the limit without throwing.
    """
    if not buyer_profile_url and not internal_reference and not title_keywords:
        return []
    sess = _session()
    docs: list = []

    # 1. VOP portal direct deeplink
    vop_id = _extract_vop_id(buyer_profile_url or "")
    if vop_id:
        result = _fetch_vop(sess, vop_id)
        if result and result.get("documents"):
            docs.extend(_tag_strategy_a(result["documents"]))

    # 2. NEN buyer profile (e.g. /profil/MO) → tender list + detail scrape
    if not docs and buyer_profile_url and "nen.nipez.cz" in buyer_profile_url:
        result = _fetch_nen_profile(sess, buyer_profile_url, title_keywords or [])
        if result and result.get("documents"):
            docs.extend(_tag_strategy_a(result["documents"]))

    # 3. Fallback: NEN search by internal_reference or keyword
    if not docs and internal_reference:
        result = _search_nen(sess, internal_reference)
        if result and result.get("documents"):
            docs.extend(_tag_strategy_a(result["documents"]))

    if not docs and title_keywords:
        for kw in title_keywords[:2]:
            if len(kw) < 4:
                continue
            result = _search_nen(sess, kw)
            if result and result.get("documents"):
                docs.extend(_tag_strategy_a(result["documents"]))
                break

    # 4. Generic buyer-portal static GET (other CZ portals)
    if not docs and buyer_profile_url and buyer_profile_url.startswith("http"):
        docs.extend(_scrape_generic_cz(sess, buyer_profile_url))

    return docs


def _tag_strategy_a(docs: list) -> list:
    out = []
    for d in docs:
        d.doc_type = "vergabeunterlagen"
        # Heuristic: VOP/.cz attachments with /soubor/, /priloha/, /Download
        # are sometimes behind a CZ-POINT SSO (eIDAS). Mark them so the
        # orchestrator can skip gracefully on 401/403.
        if any(tok in d.url.lower() for tok in ("soubor", "priloha", "/download")):
            d.extra = {**(d.extra or {}), "auth_risk": "eidas"}
        out.append(d)
    return out


def _scrape_generic_cz(sess: requests.Session, url: str) -> list:
    """Best-effort static scrape of an unknown CZ procurement portal."""
    from src.document_pipeline.discovery import DocumentRef
    html = _get_html(sess, url)
    if html is None or len(html) < 500:
        return []
    docs: list = []
    seen: set[str] = set()
    base = re.match(r"^(https?://[^/]+)", url).group(1)
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
                base + ("" if href.startswith("/") else "/") + href
            )
            fmt = _guess_fmt(full)
            docs.append(DocumentRef(
                url=full,
                format=fmt,
                language="CES",
                title=full.split("/")[-1].split("?")[0][:100] or "lv",
                source="CZ-GEN",
                tender_id="",
                doc_type="vergabeunterlagen",
            ))
    return docs[:8]


# ── VOP portal (verejnezakazky.vop.cz) ───────────────────────────────────────

def _extract_vop_id(url: str) -> str:
    """Extract VOP tender ID like 'vz00002751' from a VOP URL."""
    m = re.search(r"/vz(\d{8})", url)
    return m.group(0).lstrip("/") if m else ""


def _fetch_vop(sess: requests.Session, vop_id: str) -> Optional[dict]:
    """Fetch VOP portal tender detail page."""
    portal_url = f"{_VOP_BASE}/{vop_id}"
    html = _get_html(sess, portal_url)
    if html is None or len(html) < 500:
        # Try English version
        portal_url_en = f"{_VOP_BASE}/en/{vop_id}"
        html = _get_html(sess, portal_url_en)
        if html is None or len(html) < 500:
            logger.debug(f"CZ-fallback: VOP page empty for {vop_id}")
            return None
        portal_url = portal_url_en

    text = _html_to_text(html)
    docs = _extract_vop_documents(html, sess)
    additional = _parse_cz_fields(text)

    # If no downloadable PDFs, wrap the page text as a synthetic DocumentRef
    if not docs and len(text) > 300:
        from src.document_pipeline.discovery import DocumentRef
        docs.append(DocumentRef(
            url=portal_url,
            format="html",
            language="CES",
            title=f"{vop_id}_vop_detail.html",
            source="CZ-VOP",
            tender_id="",
            doc_type="national_page_text",
            extra={"text": text[:15000]},
        ))

    logger.info(
        f"CZ-fallback: VOP {vop_id} → {len(docs)} doc(s), "
        f"winner={additional.get('winner','')[:30]}"
    )
    return {
        "portal_url": portal_url,
        "documents": docs,
        "additional_fields": additional,
    }


def _extract_vop_documents(html: str, sess: requests.Session) -> list:
    """Parse VOP HTML for downloadable PDF/document links."""
    from src.document_pipeline.discovery import DocumentRef

    docs = []
    seen: set[str] = set()

    for pat in [
        r'href="([^"]*\.pdf(?:\?[^"]*)?)"',
        r'href="([^"]*\.docx?(?:\?[^"]*)?)"',
        r'href="([^"]*(?:download|soubor|priloha|prilohy|attachment)[^"]*)"',
    ]:
        for href in re.findall(pat, html, re.IGNORECASE):
            if not href or href in seen:
                continue
            if not href.startswith("http"):
                href = _VOP_BASE + ("" if href.startswith("/") else "/") + href
            seen.add(href)
            fmt = _guess_fmt(href)
            label = href.split("/")[-1].split("?")[0][:80] or "document"
            docs.append(DocumentRef(
                url=href,
                format=fmt,
                language="CES",
                title=label,
                source="CZ-VOP",
                tender_id="",
                doc_type="tender_document",
            ))

    return docs[:6]


# ── NEN (nen.nipez.cz) ────────────────────────────────────────────────────────

def _search_nen(sess: requests.Session, query: str) -> Optional[dict]:
    """
    Search NEN via the static server-rendered search URL.

    NEN uses Next.js (React SSR). The initial HTML may contain a
    __NEXT_DATA__ JSON blob with pre-fetched search results.
    If not, parse the HTML for tender rows.
    """
    import urllib.parse

    encoded = urllib.parse.quote(query, safe="")
    search_url = f"{_NEN_BASE}/en/verejne-zakazky/p:vz:query={encoded}"
    html = _get_html(sess, search_url)
    if html is None or len(html) < 1000:
        return None

    # Try Next.js SSR data blob first (most reliable)
    nen_id = _extract_nen_from_next_data(html, query)
    if nen_id:
        return _fetch_nen_detail(sess, nen_id)

    # Fallback: parse tender table rows from SSR HTML
    rows = _parse_nen_table(html)
    if not rows:
        logger.debug(f"CZ-fallback: NEN search '{query[:40]}' → no rows in HTML")
        return None

    # Take the first row that looks relevant
    first = rows[0]
    nen_id = first.get("sys_num", "")
    if nen_id:
        return _fetch_nen_detail(sess, nen_id)

    # Wrap search result page text directly
    text = _html_to_text(html)
    if len(text) > 500:
        from src.document_pipeline.discovery import DocumentRef
        doc = DocumentRef(
            url=search_url,
            format="html",
            language="CES",
            title=f"nen_search_{query[:30]}.txt",
            source="CZ-NEN",
            tender_id="",
            doc_type="national_page_text",
            extra={"text": text[:15000]},
        )
        return {
            "portal_url": search_url,
            "documents": [doc],
            "additional_fields": _parse_cz_fields(text),
        }

    return None


def _extract_nen_from_next_data(html: str, query: str) -> str:
    """
    Extract NEN system number from __NEXT_DATA__ JSON blob if present.
    Returns dashed sys_num (e.g. "N006-25-V00008153") or "".
    """
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return ""
    try:
        nd = json.loads(m.group(1))
        # Drill into the pageProps → tenderList or similar
        page_props = (
            nd.get("props", {})
              .get("pageProps", {})
        )
        tenders = (
            page_props.get("tenderList")
            or page_props.get("data", {}).get("items")
            or []
        )
        if not isinstance(tenders, list) or not tenders:
            return ""
        # Return system number of first result
        first = tenders[0]
        sys_num = (
            first.get("systemNumber")
            or first.get("sysNum")
            or first.get("id", "")
        )
        return str(sys_num).replace("/", "-") if sys_num else ""
    except Exception:
        return ""


def _parse_nen_table(html: str) -> list[dict]:
    """Parse NEN server-rendered result table for tender rows."""
    rows = []
    # NEN table rows: <tr> cells with sys_num, title, status, authority
    row_pattern = re.compile(
        r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE
    )
    cell_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    link_pattern = re.compile(r'href="([^"]*detail-zakazky[^"]*)"')

    for row_m in row_pattern.finditer(html):
        row_html = row_m.group(1)
        cells = [re.sub(r"<[^>]+>", " ", c.group(1)).strip()
                 for c in cell_pattern.finditer(row_html)]
        if len(cells) < 3:
            continue
        href_m = link_pattern.search(row_html)
        href = href_m.group(1) if href_m else ""
        # Cells: [Detail] [SysNum] [Title] [Status] [Authority] [Deadline]
        rows.append({
            "sys_num": cells[1] if len(cells) > 1 else "",
            "title":   cells[2] if len(cells) > 2 else "",
            "url":     href,
        })

    return rows


def _fetch_nen_detail(sess: requests.Session, sys_num: str) -> Optional[dict]:
    """Fetch NEN tender detail page by system number (dashed format)."""
    dashed = sys_num.replace("/", "-")
    # Try English URL first
    candidates = [
        f"{_NEN_BASE}/en/verejne-zakazky/detail-zakazky/{dashed}",
        f"{_NEN_BASE}/verejne-zakazky/detail-zakazky/{dashed}",
    ]
    for url in candidates:
        html = _get_html(sess, url)
        if html and len(html) > 1000:
            text = _html_to_text(html)
            docs = _extract_nen_documents(html, sess)
            additional = _parse_cz_fields(text)

            if not docs and len(text) > 300:
                from src.document_pipeline.discovery import DocumentRef
                docs.append(DocumentRef(
                    url=url,
                    format="html",
                    language="CES",
                    title=f"{dashed}_nen_detail.html",
                    source="CZ-NEN",
                    tender_id="",
                    doc_type="national_page_text",
                    extra={"text": text[:15000]},
                ))

            logger.info(f"CZ-fallback: NEN {sys_num} → {len(docs)} doc(s)")
            return {
                "portal_url": url,
                "documents": docs,
                "additional_fields": additional,
            }
    return None


def _fetch_nen_profile(
    sess: requests.Session,
    profile_url: str,
    title_keywords: list[str],
) -> Optional[dict]:
    """
    Fetch a NEN buyer profile page and find the relevant tender.
    e.g. https://nen.nipez.cz//profil/MO → Ministry of Defence tenders.
    """
    # Normalise double-slash
    clean_url = profile_url.replace("//profil", "/profil")
    html = _get_html(sess, clean_url)
    if not html or len(html) < 1000:
        return None

    rows = _parse_nen_table(html)
    if not rows:
        return None

    kw_lower = [k.lower() for k in title_keywords if k]
    best = None
    best_score = -1
    for row in rows:
        title_lower = row.get("title", "").lower()
        score = sum(1 for kw in kw_lower if kw in title_lower)
        if score > best_score:
            best_score = score
            best = row

    if best is None:
        best = rows[0]

    sys_num = best.get("sys_num", "")
    url     = best.get("url", "")

    if sys_num:
        return _fetch_nen_detail(sess, sys_num)

    if url:
        if not url.startswith("http"):
            url = _NEN_BASE + url
        html = _get_html(sess, url)
        if html and len(html) > 1000:
            text = _html_to_text(html)
            from src.document_pipeline.discovery import DocumentRef
            doc = DocumentRef(
                url=url,
                format="html",
                language="CES",
                title="nen_profile_result.html",
                source="CZ-NEN",
                tender_id="",
                doc_type="national_page_text",
                extra={"text": text[:15000]},
            )
            return {
                "portal_url": url,
                "documents": [doc],
                "additional_fields": _parse_cz_fields(text),
            }

    return None


def _extract_nen_documents(html: str, sess: requests.Session) -> list:
    """Parse NEN detail page HTML for downloadable documents."""
    from src.document_pipeline.discovery import DocumentRef

    docs = []
    seen: set[str] = set()

    for pat in [
        r'href="([^"]*\.pdf(?:\?[^"]*)?)"',
        r'href="([^"]*\.docx?(?:\?[^"]*)?)"',
        r'href="([^"]*(?:soubor|priloha|download|file)[^"]*)"',
    ]:
        for href in re.findall(pat, html, re.IGNORECASE):
            if not href or href in seen:
                continue
            if not href.startswith("http"):
                href = _NEN_BASE + ("" if href.startswith("/") else "/") + href
            seen.add(href)
            fmt = _guess_fmt(href)
            label = href.split("/")[-1].split("?")[0][:80] or "document"
            docs.append(DocumentRef(
                url=href,
                format=fmt,
                language="CES",
                title=label,
                source="CZ-NEN",
                tender_id="",
                doc_type="tender_document",
            ))

    return docs[:6]


# ── Field extraction ───────────────────────────────────────────────────────────

def _parse_cz_fields(text: str) -> dict:
    return {
        "winner":            _cz_winner(text),
        "quantity":          _cz_quantity(text),
        "contract_duration": _cz_duration(text),
        "value":             _cz_value(text),
    }


def _cz_winner(text: str) -> str:
    for pat in [
        r"(?:Vítěz|Dodavatel|Vybraný dodavatel|Winner|Supplier)[:\s]+([^\n]{5,120})",
        r"SUPPLIER\s*\n\s*([^\n]{5,120})",
        r"SELECTED TENDERER\s*\n\s*([^\n]{5,120})",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if not re.match(r"^[\d\s,.]+$", name):
                return name[:120]
    return ""


def _cz_quantity(text: str) -> Optional[int]:
    for pat in [
        r"(\d[\d\s]*)\s*(?:ks|kusů|kus|přívěsů|návěsů|vozidel)",
        r"(?:Počet|Množství|Quantity)[:\s]+(\d[\d\s]*)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                v = int(m.group(1).replace(" ", ""))
                if 1 <= v <= 9999:
                    return v
            except ValueError:
                pass
    return None


def _cz_duration(text: str) -> str:
    for pat in [
        r"(?:Doba trvání|Délka smlouvy|Duration)[:\s]+([^\n]{3,80})",
        r"(\d+)\s*(?:měsíců|měsíce|měsíc|týdnů|let|dní)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:80]
    return ""


def _cz_value(text: str) -> Optional[float]:
    m = re.search(r"ESTIMATED VALUE \(EXCL\. VAT\)\s*\n\s*([\d,. ]+)", text)
    if m:
        raw = m.group(1).strip().replace(" ", "").replace(",", "")
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    for pat in [
        r"(?:Předpokládaná hodnota|Odhadovaná hodnota)[^\d]{0,20}([\d\s,.]+)\s*(?:CZK|Kč)",
        r"([\d\s,.]+)\s*(?:CZK|Kč)\b",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().replace(" ", "")
            if "," in raw and "." not in raw:
                raw = raw.replace(",", ".")
            try:
                v = float(raw)
                if v > 100:
                    return v
            except ValueError:
                pass
    return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _get_html(sess: requests.Session, url: str) -> Optional[str]:
    try:
        resp = sess.get(url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            logger.debug(f"CZ-fallback: GET {url[:80]} → {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.debug(f"CZ-fallback: GET {url[:80]} failed: {exc}")
        return None


def _html_to_text(html: str) -> str:
    import html as _html_mod
    text = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(h[1-6]|p|div|li|br|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html_mod.unescape(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)


def _guess_fmt(url: str) -> str:
    path = url.split("?")[0].lower()
    for ext in ("pdf", "docx", "doc", "xlsx", "xls"):
        if path.endswith(f".{ext}"):
            return ext
    return "pdf"

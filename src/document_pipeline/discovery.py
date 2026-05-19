"""
Document discovery — given a notice dict, return a list of DocumentRef objects.

Source coverage:
  TED  — links.pdf.ENG (or first available language)
  UA   — re-fetch Prozorro API to get fresh time-signed document URLs
  UK   — no direct document links in current data (stub)
  CZ   — auth-blocked (eIDAS required); stub returns empty list
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")

PROZORRO_API = "https://public.api.openprocurement.org/api/2.5"

# Formats we can extract text from
_EXTRACTABLE_FORMATS = {"pdf", "docx", "doc", "xlsx", "xls", "html", "htm"}

# Minimum content size considered "alive" (bytes)
_MIN_CONTENT_BYTES = 1024


def url_is_healthy(url: str, timeout: int = 15) -> bool:
    """
    HEAD-request health check for a tender document URL.

    Returns False when:
    - HTTP 404 / 410 / 403 / 401 / 5xx
    - Connection error or timeout
    - Content-Length header present and < 1 KB
    - URL is empty or not http(s)

    A True result means the URL *appears* reachable; the caller should still
    handle download failures gracefully.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        resp = requests.head(
            url,
            timeout=timeout,
            verify=_SSL_VERIFY,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TenderBot/1.0)"},
        )
        if resp.status_code in (404, 410, 403, 401) or resp.status_code >= 500:
            logger.debug(f"url_is_healthy: {resp.status_code} → dead: {url[:80]}")
            return False
        cl = resp.headers.get("Content-Length")
        if cl and int(cl) < _MIN_CONTENT_BYTES:
            logger.debug(f"url_is_healthy: Content-Length={cl} < 1KB → dead: {url[:80]}")
            return False
        return True
    except Exception as exc:
        logger.debug(f"url_is_healthy: exception → dead: {url[:80]} ({exc})")
        return False


@dataclass
class DocumentRef:
    """A single procurement document associated with a tender."""
    url: str
    format: str           # "pdf", "docx", "xlsx", "html", …
    language: str         # "ENG", "UKR", "DEU", …
    title: str            # document filename / display title
    source: str           # "TED", "UA", "UK", "CZ", …
    tender_id: str
    doc_type: str = ""    # Prozorro documentType or "notice_pdf"
    extra: dict = field(default_factory=dict)  # source-specific metadata

    @property
    def is_extractable(self) -> bool:
        return self.format.lower() in _EXTRACTABLE_FORMATS


def _fmt_from_url(url: str) -> str:
    """Guess format from URL extension or path."""
    path = url.split("?")[0].lower()
    for ext in ("pdf", "docx", "doc", "xlsx", "xls", "html", "htm"):
        if path.endswith(f".{ext}"):
            return ext
    # TED notice PDFs end in /pdf
    if path.endswith("/pdf"):
        return "pdf"
    return "bin"


# ── TED ───────────────────────────────────────────────────────────────────────

_TED_LANG_PRIORITY = ["ENG", "DEU", "FRA", "POL", "CES", "RON", "NLD", "SWE", "FIN"]


def _discover_ted(notice: dict) -> list[DocumentRef]:
    tid = notice.get("tender_id", "")
    docs: list[DocumentRef] = []

    links = notice.get("links", {}) or {}
    pdf_links = links.get("pdf", {}) or {}
    if pdf_links:
        # Pick English first, then first available
        chosen_lang = None
        for lang in _TED_LANG_PRIORITY:
            if pdf_links.get(lang):
                chosen_lang = lang
                break
        if chosen_lang is None:
            chosen_lang = next(iter(pdf_links))

        url = pdf_links[chosen_lang]
        docs.append(DocumentRef(
            url=url,
            format="pdf",
            language=chosen_lang,
            title=f"{tid}_notice.pdf",
            source="TED",
            tender_id=tid,
            doc_type="notice_pdf",
        ))

    # Sprint 2026-05-09: Vergabeunterlagen-URL (buyer's tender-documents
    # bundle) gleaned from the TED-API ``buyer-internet-address``.
    # Sprint 2026-05-10: prefer the TED-XML deeplink
    # ``_xml.tender_documents_access`` (carries the buyer-side tender-id
    # parameter, e.g. ``…/tenderdetails.html?id=771723``). Falls back to
    # ``_xml.buyer_profile_url_full`` (often includes a buyer-code path)
    # and finally the JSON-API ``buyer-internet-address`` (host-only).
    raw = notice.get("_raw") or {}
    if isinstance(raw, dict):
        xml_block = raw.get("_xml") if isinstance(raw.get("_xml"), dict) else {}
        # Priority order — best deeplink first
        candidate = (
            xml_block.get("tender_documents_access")
            or xml_block.get("buyer_profile_url_full")
            or _first_str(raw.get("buyer-internet-address"))
        )
        if candidate and candidate.startswith(("http://", "https://")):
            guessed = _fmt_from_url(candidate)
            if guessed == "bin":
                guessed = "html"
            docs.append(DocumentRef(
                url=candidate,
                format=guessed,
                language="—",
                title=f"{tid}_vergabeunterlagen",
                source="TED",
                tender_id=tid,
                doc_type="vergabeunterlagen",
                extra={
                    "buyer_profile_url": xml_block.get("buyer_profile_url_full")
                                         or _first_str(raw.get("buyer-internet-address")),
                    "internal_reference": xml_block.get("internal_reference"),
                    "contract_folder_id": xml_block.get("contract_folder_id"),
                },
            ))

    return docs


_TED_XML_CACHE = Path(__file__).parent.parent.parent / "data" / "ted_xml_cache"

_STRATEGY_A_COUNTRIES = {"DEU": "DE", "POL": "PL", "CZE": "CZ"}


def _xml_inputs_from_cache(tid: str) -> dict:
    """Read buyer_profile_url + tender_documents_access + internal_reference
    from data/ted_xml_cache/{tid}.xml.

    Used by ``_discover_strategy_a`` as a fallback when the notice has no
    ``_raw._xml`` block (i.e. the XML backfill hasn't been run on this
    relevant.json snapshot). Pure regex parsing — keeps the dependency
    surface small.
    """
    path = _TED_XML_CACHE / f"{tid}.xml"
    if not path.exists():
        return {}
    try:
        xml = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    out: dict = {}
    m = re.search(r"<cbc:BuyerProfileURI[^>]*>([^<]+)</cbc:BuyerProfileURI>", xml)
    if m:
        out["buyer_profile_url"] = m.group(1).strip()

    # CallForTendersDocumentReference → Attachment → URI
    m = re.search(
        r"<cac:CallForTendersDocumentReference[^>]*>.*?"
        r"<cac:Attachment[^>]*>.*?<cbc:URI[^>]*>([^<]+)</cbc:URI>",
        xml, re.DOTALL,
    )
    if m:
        out["tender_documents_access"] = m.group(1).strip()
    else:
        m = re.search(
            r"<cac:Attachment[^>]*>.*?<cac:ExternalReference[^>]*>.*?"
            r"<cbc:URI[^>]*>([^<]+)</cbc:URI>",
            xml, re.DOTALL,
        )
        if m:
            out["tender_documents_access"] = m.group(1).strip()

    # internal_reference — look for the ProcurementProject ID, skip the
    # standard eForms template placeholders (ORG-/RES-/TEN-/LOT-/TPO-/TPA-).
    _PLACEHOLDER = re.compile(r"^(ORG|RES|TEN|LOT|TPO|TPA|GLO|PAR|REV|GRO|RCM)-\d+$")
    for m in re.finditer(r"<cbc:ID(?:\s[^>]*)?>([^<]+)</cbc:ID>", xml):
        val = m.group(1).strip()
        if not val or _PLACEHOLDER.match(val):
            continue
        # Prefer references that contain a slash, dot or underscore — typical
        # for real buyer codes (e.g. "Q/U2BP/RA029/NA103", "OVZ/018/3/2025").
        if re.match(r"^[A-Z0-9][A-Z0-9./_-]{4,40}$", val) and re.search(r"[./_]", val):
            out["internal_reference"] = val
            break
    return out


def _strategy_a_inputs(notice: dict) -> dict:
    """Resolve the four Strategy-A inputs (buyer_profile_url, tender_documents_access,
    internal_reference, country) from `_raw._xml` first, then from the local
    TED XML cache. Country is the ISO-2 code used by the discover dispatcher.
    """
    tid = str(notice.get("tender_id", ""))
    raw = notice.get("_raw") or {}
    xml_block = raw.get("_xml") if isinstance(raw.get("_xml"), dict) else {}

    inputs: dict = {
        "buyer_profile_url": xml_block.get("buyer_profile_url_full", "") or "",
        "tender_documents_access": xml_block.get("tender_documents_access", "") or "",
        "internal_reference": xml_block.get("internal_reference", "") or "",
    }

    if not inputs["buyer_profile_url"] or not inputs["tender_documents_access"]:
        cached = _xml_inputs_from_cache(tid)
        inputs["buyer_profile_url"] = inputs["buyer_profile_url"] or cached.get("buyer_profile_url", "")
        inputs["tender_documents_access"] = (
            inputs["tender_documents_access"] or cached.get("tender_documents_access", "")
        )
        inputs["internal_reference"] = inputs["internal_reference"] or cached.get("internal_reference", "")

    # Country resolution via organisation-country-buyer (TED-API field)
    cc_iso2 = ""
    org_country = raw.get("organisation-country-buyer", [])
    if isinstance(org_country, list) and org_country:
        cc_iso2 = _STRATEGY_A_COUNTRIES.get(str(org_country[0]).strip(), "")
    if not cc_iso2:
        # Fallback: heuristic from URL
        for url in (inputs["buyer_profile_url"], inputs["tender_documents_access"]):
            u = (url or "").lower()
            if not u:
                continue
            if "evergabe-online.de" in u or ".bund.de" in u:
                cc_iso2 = "DE"
                break
            if "ezamowienia.gov.pl" in u or "platformazakupowa.pl" in u or "portalsmartpzp.pl" in u:
                cc_iso2 = "PL"
                break
            if "nipez.cz" in u or "vop.cz" in u or ".gov.cz" in u:
                cc_iso2 = "CZ"
                break
    inputs["country"] = cc_iso2
    return inputs


def _discover_strategy_a(notice: dict) -> list:
    """Strategy A — fetch national-portal Vergabeunterlagen for DE/PL/CZ tenders.

    Trigger conditions (all must hold):
      1. country resolves to DE / PL / CZ
      2. ``buyer_profile_url`` is known (from _xml or the local XML cache)
      3. ``tender_documents_access`` deeplink is **missing** — otherwise the
         standard TED ``_discover_ted`` path already surfaces it as
         ``doc_type="vergabeunterlagen"``

    Returns DocumentRef list (may be empty). Caller decides whether to merge
    with results from ``_discover_ted``.
    """
    inputs = _strategy_a_inputs(notice)
    country = inputs.get("country", "")
    if country not in ("DE", "PL", "CZ"):
        return []

    buyer_profile = inputs.get("buyer_profile_url", "")
    tender_docs = inputs.get("tender_documents_access", "")
    if not buyer_profile and not tender_docs:
        return []
    # Note: for DE we keep going even when tender_documents_access is present —
    # the goal is to scrape the LV PDFs ON the linked page, not just record
    # the URL (TED already does that in _discover_ted).

    tid = str(notice.get("tender_id", ""))
    title = (notice.get("title_en") or notice.get("_title_final")
             or notice.get("title") or "")
    if isinstance(title, dict):
        title = title.get("eng") or title.get("ENG") or next(iter(title.values()), "")
    keywords = _strategy_a_keywords(str(title))
    buyer = notice.get("_authority_name") or ""
    if isinstance(buyer, dict):
        buyer = buyer.get("name", "") or ""
    if not buyer:
        # Fallback: pull from TED-API _raw blocks (buyer-name /
        # organisation-name-buyer — both can be multilingual dicts).
        raw = notice.get("_raw") or {}
        for fld in ("buyer-name", "organisation-name-buyer", "contracting_authority"):
            val = raw.get(fld) or notice.get(fld)
            if isinstance(val, dict):
                for lang in ("eng", "ENG", "deu", "DEU", "pol", "POL", "ces", "CES"):
                    if val.get(lang):
                        v = val[lang]
                        buyer = v[0] if isinstance(v, list) else str(v)
                        break
                if not buyer and val:
                    first = next(iter(val.values()), "")
                    buyer = first[0] if isinstance(first, list) else str(first)
            elif isinstance(val, list) and val:
                buyer = str(val[0])
            elif isinstance(val, str):
                buyer = val
            if buyer:
                break

    docs: list = []
    try:
        if country == "DE":
            from src.national_scraper.fallback.de_search import fetch_vergabeunterlagen
            docs = fetch_vergabeunterlagen(
                buyer_profile_url=tender_docs or buyer_profile,
                internal_reference=inputs.get("internal_reference", ""),
                title_keywords=keywords,
                buyer=buyer,
            )
        elif country == "PL":
            from src.national_scraper.fallback.pl_search import fetch_swz_documents
            docs = fetch_swz_documents(
                buyer_profile_url=buyer_profile,
                internal_reference=inputs.get("internal_reference", ""),
                title_keywords=keywords,
                buyer=buyer,
            )
        elif country == "CZ":
            from src.national_scraper.fallback.cz_search import fetch_lv_documents
            docs = fetch_lv_documents(
                buyer_profile_url=buyer_profile,
                internal_reference=inputs.get("internal_reference", ""),
                title_keywords=keywords,
                buyer=buyer,
            )
    except Exception as exc:
        logger.warning(f"Strategy-A {country} error for {tid}: {exc}")
        return []

    for d in docs:
        if not d.tender_id:
            d.tender_id = tid
    return docs


def _strategy_a_keywords(title: str) -> list:
    stop = {"and", "or", "the", "for", "of", "in", "with", "und", "oder",
            "für", "der", "die", "das", "i", "oraz", "dla", "do", "na", "z",
            "a", "pro", "za", "ze"}
    words = re.findall(r"\b[a-zA-ZÀ-žА-я]{4,}\b", title or "")
    out: list = []
    seen: set = set()
    for w in words:
        wl = w.lower()
        if wl in stop or wl in seen:
            continue
        seen.add(wl)
        out.append(w)
        if len(out) >= 5:
            break
    return out


def _first_str(value: object) -> Optional[str]:
    """Return the first non-empty string element of a list/string value."""
    if isinstance(value, list):
        for v in value:
            if v:
                return str(v).strip()
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


# ── UA (Prozorro) ──────────────────────────────────────────────────────────────

def _ua_internal_id_from_notice(notice: dict) -> Optional[str]:
    """Extract Prozorro internal UUID (hex) from a UA notice.

    Priority:
    1. _raw.internal_id (set by ua_adapter after our fix)
    2. UUID extracted from _national_raw_text (JSON with "id": "<32-hex>")
    3. tenderID from URL path — NOT the UUID, but try as last resort

    The Prozorro API detail endpoint requires the 32-hex UUID, not the tenderID.
    """
    # 1. Explicitly stored UUID (future scrapes after adapter fix)
    raw = notice.get("_raw") or {}
    explicit = raw.get("internal_id", "")
    if explicit and re.match(r"^[a-f0-9]{32}$", explicit):
        return explicit

    # 2. UUID from _national_raw_text JSON blob
    raw_text = notice.get("_national_raw_text", "") or ""
    if raw_text:
        m = re.search(r'"id":\s*"([a-f0-9]{32})"', raw_text)
        if m:
            return m.group(1)

    return None


def _discover_ua(notice: dict) -> list[DocumentRef]:
    tid = notice.get("tender_id", "")
    internal_id = _ua_internal_id_from_notice(notice)
    if not internal_id:
        logger.debug(f"UA discover: no internal ID for {tid}")
        return []

    try:
        resp = requests.get(
            f"{PROZORRO_API}/tenders/{internal_id}",
            timeout=30,
            verify=_SSL_VERIFY,
        )
        if resp.status_code != 200:
            logger.warning(f"UA discover: Prozorro API {resp.status_code} for {internal_id}")
            return []
        data = resp.json().get("data", {})
    except Exception as e:
        logger.warning(f"UA discover: fetch error for {internal_id}: {e}")
        return []

    docs: list[DocumentRef] = []
    for doc in data.get("documents", []) or []:
        url = doc.get("url", "")
        if not url:
            continue
        doc_type = doc.get("documentType", "")
        title = doc.get("title", "") or doc.get("id", "doc")
        fmt = _fmt_from_url(url)
        if fmt not in _EXTRACTABLE_FORMATS:
            continue
        docs.append(DocumentRef(
            url=url,
            format=fmt,
            language="UKR",
            title=title,
            source="UA",
            tender_id=tid,
            doc_type=doc_type,
            extra={"datePublished": doc.get("datePublished", "")},
        ))

    logger.info(f"UA discover: {len(docs)} document(s) for {tid}")
    return docs


# ── National text-as-doc fallback ─────────────────────────────────────────────

_NATIONAL_TEXT_MIN_LEN = 80   # ignore stub entries with only a few words

def _discover_national_text(notice: dict) -> list[DocumentRef]:
    """Synthetic DocumentRef backed by scraped page text (_national_raw_text).

    Used for national sources (FR, NO, EE, NL, …) where no document URLs are
    available.  The AI structurer can accept raw text directly instead of a
    downloaded PDF.  Quality is lower than a full Leistungsverzeichnis, but
    description + CPV + value still provide useful signal.
    """
    tid = notice.get("tender_id", "")
    raw_text = notice.get("_national_raw_text", "") or ""
    # Also accept description as fallback when raw_text is absent
    if len(raw_text) < _NATIONAL_TEXT_MIN_LEN:
        raw_text = (
            notice.get("_description_final")
            or notice.get("description")
            or ""
        )
    if len(raw_text) < _NATIONAL_TEXT_MIN_LEN:
        return []

    src = notice.get("source", "NAT")
    return [DocumentRef(
        url="internal://national_raw_text",
        format="txt",
        language="—",
        title=f"{tid}_national_text.txt",
        source=src,
        tender_id=tid,
        doc_type="national_page_text",
        extra={"text": raw_text},
    )]


# ── Portal-URL helper (AU/CA) ─────────────────────────────────────────────────

def _portal_html_ref(notice: dict, *, source: str) -> Optional[DocumentRef]:
    """Append the canonical portal detail URL as an HTML DocumentRef.

    Used by AU-OCDS and CA-CB where the OCDS / CSV payload does not carry a
    documents[] array, but the portal detail page HTML is publicly reachable
    and often surfaces attachment links. The orchestrator can try this URL
    when the synthetic national_page_text ref yielded insufficient text.

    Returns None when no portal URL is present.
    """
    tid = notice.get("tender_id", "")
    portal_url = (
        notice.get("source_url_national")
        or notice.get("_source_url_national")
        or notice.get("ted_url")
        or ""
    )
    if not portal_url or not portal_url.startswith(("http://", "https://")):
        return None

    return DocumentRef(
        url=portal_url,
        format=_fmt_from_url(portal_url) if _fmt_from_url(portal_url) != "bin" else "html",
        language="—",
        title=f"{tid}_portal_page",
        source=source,
        tender_id=tid,
        doc_type="portal_detail_page",
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _discover_au_ocds(notice: dict) -> list[DocumentRef]:
    """AusTender OCDS document discovery.

    Empirically (2026-05-18 cache survey) AusTender OCDS releases do NOT
    populate `tender.documents[]` even though the OCDS schema allows it.
    The contract description is the only structured field. We therefore:
      1. Yield the synthetic national_page_text ref (description as document).
      2. Append a portal-page HTML ref (`/cn/{id}/View`) so the orchestrator
         can optionally try the rendered detail page when synthetic text is
         too short.
    """
    docs: list[DocumentRef] = list(_discover_national_text(notice))
    portal = _portal_html_ref(notice, source="AU-TEN")
    if portal:
        docs.append(portal)
    return docs


def _discover_au_atm(notice: dict) -> list[DocumentRef]:
    """AusTender ATM document discovery.

    ATM attachment downloads require an authenticated session (403 without
    login). The detail page text already contains description + UNSPSC and
    is sufficient for AI classification, so we return it as a synthetic text
    document, then append the portal page URL as a fallback.
    """
    docs: list[DocumentRef] = list(_discover_national_text(notice))
    portal = _portal_html_ref(notice, source="AU-AT")
    if portal:
        docs.append(portal)
    return docs


def _discover_ca(notice: dict) -> list[DocumentRef]:
    """CanadaBuys document discovery.

    The CanadaBuys Open Data CSV does not list attachment URLs; the notice
    detail HTML on canadabuys.canada.ca carries them but requires a real-time
    HTML scrape per notice (out of scope for the CSV-only loader). For now
    we surface the synthetic national_page_text ref plus the portal URL so
    the orchestrator can attempt to fetch the HTML detail page.
    """
    docs: list[DocumentRef] = list(_discover_national_text(notice))
    portal = _portal_html_ref(notice, source="CA-CB")
    if portal:
        docs.append(portal)
    return docs


def discover_for_notice(notice: dict) -> list[DocumentRef]:
    """Return all downloadable DocumentRefs for a notice.

    Source is inferred from tender_id prefix and links fields.
    """
    tid = notice.get("tender_id", "")

    if tid.startswith("UA-"):
        return _discover_ua(notice)

    # AU-CN = OCDS post-award contract notice (AU-TEN)
    if tid.startswith("AU-CN"):
        return _discover_au_ocds(notice)

    # All other AU-* = ATM (pre-award)
    if tid.startswith("AU-"):
        return _discover_au_atm(notice)

    # CanadaBuys
    if tid.startswith("CA-"):
        return _discover_ca(notice)

    # UK / CZ: no extractable documents in current data
    if tid.startswith("UK-") or tid.startswith("CZ-"):
        return []

    # TED (numeric ID with optional country prefix)
    if notice.get("links", {}) or notice.get("_raw", {}).get("links"):
        return _discover_ted(notice)

    # National notices without document links — use scraped page text as input
    if notice.get("_national_raw_text") or notice.get("_description_final"):
        return _discover_national_text(notice)

    return []

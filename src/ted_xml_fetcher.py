"""TED-XML fetcher + parser (Sprint 2026-05-10).

Pulls the XML representation of a TED notice from
``https://ted.europa.eu/{lang}/notice/{notice-id}/xml`` and extracts
fields that are not exposed by the JSON-search-API: namely the
human-readable ``internal_reference``, the
``tender_documents_access`` URL with tender-id parameter, the full
``buyer_profile_url``, and a few diagnostic UUIDs.

XPath documentation lives in ``docs/TED_XML_FIELD_PATHS.md``. This
module uses ``xml.etree.ElementTree`` (stdlib) to avoid an ``lxml``
runtime dependency. Namespace prefixes are stripped via
``tag.split('}')[-1]``.

Usage::

    from src.ted_xml_fetcher import fetch_xml, parse_xml_fields

    xml = fetch_xml("212474-2026")            # bytes
    fields = parse_xml_fields(xml)
    # → {"internal_reference": "Q/U2BP/RA029/NA103",
    #    "tender_documents_access": "https://www.evergabe-online.de/...",
    #    "buyer_profile_url_full": "http://www.evergabe-online.de/",
    #    "contract_folder_id": "e911c5fa-...",
    #    "notice_uuid": "976398c5-..."}

Cache: ``data/ted_xml_cache/{notice-id}.xml``.
"""
from __future__ import annotations

import logging
import os
import time
import urllib3
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

# ── SSL handling mirrors classifier.py
_SSL_VERIFY = (
    os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
    not in ("1", "true", "yes")
)
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration
XML_CACHE_DIR = Path(__file__).parent.parent / "data" / "ted_xml_cache"
XML_BASE_URL = "https://ted.europa.eu/{lang}/notice/{nid}/xml"
USER_AGENT = "TED-Defence-Trailer-Research/1.0 (Academic/Market Research)"
DEFAULT_LANG = "en"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


# ────────────────────────────────────────────────────────────────────
# Fetcher
# ────────────────────────────────────────────────────────────────────

def fetch_xml(
    notice_id: str,
    lang: str = DEFAULT_LANG,
    *,
    cache: bool = True,
    retries: int = 4,
) -> Optional[bytes]:
    """Fetch a notice's XML, with disk-cache + 429 back-off.

    Returns ``None`` when the notice is permanently unavailable (404, etc.).
    """
    safe_id = notice_id.replace("/", "_").replace("\\", "_")
    cache_path = XML_CACHE_DIR / f"{safe_id}.xml"

    if cache and cache_path.exists():
        try:
            return cache_path.read_bytes()
        except OSError as exc:  # pragma: no cover — disk error
            logger.warning("XML cache read failed for %s: %s", notice_id, exc)

    url = XML_BASE_URL.format(lang=lang, nid=notice_id)
    for attempt in range(retries):
        try:
            resp = _session.get(url, timeout=30, verify=_SSL_VERIFY)
        except requests.RequestException as exc:
            logger.warning("XML fetch network error %s (try %d/%d): %s",
                           notice_id, attempt + 1, retries, exc)
            if attempt + 1 < retries:
                time.sleep(3 * (attempt + 1))
                continue
            return None

        if resp.status_code == 200:
            data = resp.content
            if cache:
                XML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(data)
            return data
        if resp.status_code == 404:
            logger.info("XML 404 for %s — notice not in TED any more", notice_id)
            return None
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            logger.warning("XML 429 for %s — sleeping %ds (try %d/%d)",
                           notice_id, wait, attempt + 1, retries)
            time.sleep(wait)
            continue
        logger.warning("XML fetch HTTP %s for %s: %s",
                       resp.status_code, notice_id, resp.text[:120])
        return None
    return None


# ────────────────────────────────────────────────────────────────────
# Parser — pure functions on parsed ElementTree
# ────────────────────────────────────────────────────────────────────

def _localname(elem: ET.Element) -> str:
    """Strip namespace prefix from a tag, e.g.
    ``{urn:oasis:...}ContractNotice`` → ``ContractNotice``."""
    return elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag


def _find_path(root: ET.Element, *path_parts: str) -> Optional[str]:
    """Find first non-empty text under ``path_parts`` (namespace-blind).

    The path is *contiguous* — i.e. ``("ProcurementProject", "ID")``
    matches any descendant chain where ``ProcurementProject`` directly
    contains ``ID``. Other ``ID`` elements (lots, parties) are skipped
    until the parent matches.
    """
    target = list(path_parts)

    def rec(el: ET.Element, idx: int) -> Optional[str]:
        if idx >= len(target):
            return None
        tag = _localname(el)
        if tag == target[idx]:
            if idx == len(target) - 1:
                t = (el.text or "").strip()
                return t or None
            for c in el:
                r = rec(c, idx + 1)
                if r is not None:
                    return r
        for c in el:
            r = rec(c, idx)
            if r is not None:
                return r
        return None

    return rec(root, 0)


def _normalise_url(url: str) -> str:
    """Prepend ``https://`` to bare hosts (`www.foo.com`) commonly
    found on FR/PL TED-XML."""
    s = url.strip()
    if s and not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s


def _find_first(root: ET.Element, name: str) -> Optional[str]:
    """Return text of the first descendant element with local-name ``name``."""
    for el in root.iter():
        if _localname(el) == name:
            t = (el.text or "").strip()
            if t:
                return t
    return None


def parse_xml_fields(xml_bytes: bytes) -> dict[str, Any]:
    """Extract XML-only fields from a TED notice. Returns empty dict
    when parsing fails so callers can move on safely.

    Handles two distinct TED-XML schemas:

    1. **eForms / UBL** (root: ``ContractNotice`` or
       ``ContractAwardNotice``, namespace ``urn:oasis:...ubl:...``).
       Used for notices published from late-2023 onwards.
    2. **TED_EXPORT R2.0** (root: ``TED_EXPORT``, namespace
       ``http://publications.europa.eu/resource/schema/ted/R2.0.x/...``).
       Used for legacy 2008–2023 notices.

    Both branches map to the same output keys.
    """
    if not xml_bytes:
        return {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("XML parse error: %s", exc)
        return {}

    root_tag = _localname(root)

    if root_tag == "TED_EXPORT":
        return _parse_ted_export(root)
    return _parse_eforms(root)


def _parse_eforms(root: ET.Element) -> dict[str, Any]:
    """eForms / UBL parser (post-2023 notices)."""
    out: dict[str, Any] = {}

    # 1) internal_reference — buyer's free-text procurement ID
    ir = _find_path(root, "ProcurementProject", "ID")
    if ir:
        out["internal_reference"] = ir

    # 2) tender_documents_access — primary deeplink (with tender-id when present)
    td = (
        _find_path(root, "CallForTendersDocumentReference", "Attachment",
                   "ExternalReference", "URI")
        or _find_path(root, "TenderingProcess", "AccessToolsURI")
    )
    if td:
        out["tender_documents_access"] = _normalise_url(td)

    # 3) buyer_profile_url — full URL with buyer-code where present
    bp = _find_path(root, "ContractingParty", "BuyerProfileURI")
    if bp:
        out["buyer_profile_url_full"] = _normalise_url(bp)

    # 4) submit_tenders_endpoint — diagnostic confirmation
    se = _find_path(root, "TenderRecipientParty", "EndpointID")
    if se:
        out["submit_tenders_endpoint"] = _normalise_url(se)

    # 5) contract_folder_id — eForms procurement-folder UUID
    cf = _find_path(root, "ContractFolderID")
    if cf:
        out["contract_folder_id"] = cf

    # 6) notice_uuid — first <ID> child of root
    for child in root:
        if _localname(child) == "ID":
            t = (child.text or "").strip()
            if t:
                out["notice_uuid"] = t
            break

    # Fallback: tender_documents_access from buyer_profile_url_full
    # when the URL embeds a deeplink-marker (FR/PL CAN-Notices).
    if "tender_documents_access" not in out and out.get("buyer_profile_url_full"):
        bp_url = out["buyer_profile_url_full"]
        if any(seg in bp_url for seg in ("/vz", "?id=", "/pn/", "/notice", "/profil/")):
            out["tender_documents_access"] = bp_url

    return out


def _parse_ted_export(root: ET.Element) -> dict[str, Any]:
    """Legacy TED_EXPORT R2.0.x parser (2008–2023 notices).

    Field-name mapping is much rougher than eForms — the schema only
    carries free-form URLs and not a per-procurement free-text ID. We
    populate whatever exists.
    """
    out: dict[str, Any] = {}

    # 1) tender_documents_access
    td = _find_first(root, "URL_DOCUMENT") or _find_first(root, "URL_PARTICIPATION")
    if td:
        out["tender_documents_access"] = _normalise_url(td)

    # 2) buyer_profile_url
    bp = (
        _find_first(root, "URL_BUYER")
        or _find_first(root, "IA_URL_GENERAL")
        or _find_first(root, "URL_GENERAL")
    )
    if bp:
        out["buyer_profile_url_full"] = _normalise_url(bp)

    # 3) submit_tenders_endpoint
    se = _find_first(root, "URL_PARTICIPATION")
    if se:
        out["submit_tenders_endpoint"] = _normalise_url(se)

    # 4) DOC_ID is in the root attributes — useful as notice_uuid surrogate
    doc_id = root.get("DOC_ID")
    if doc_id:
        out["notice_uuid"] = doc_id

    # 5) NO_DOC_OJS is the publication-number (e.g. "2022/S 042-108413")
    nd = _find_first(root, "NO_DOC_OJS")
    if nd:
        out["no_doc_ojs"] = nd

    return out


# ────────────────────────────────────────────────────────────────────
# Convenience top-level helper
# ────────────────────────────────────────────────────────────────────

def fetch_and_parse(
    notice_id: str,
    *,
    lang: str = DEFAULT_LANG,
    cache: bool = True,
) -> dict[str, Any]:
    """Combine ``fetch_xml`` + ``parse_xml_fields``."""
    xml = fetch_xml(notice_id, lang=lang, cache=cache)
    if not xml:
        return {}
    return parse_xml_fields(xml)

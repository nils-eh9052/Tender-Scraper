"""
Poland BZP Scraper

Fetches Polish defence trailer procurement notices from:
  - searchbzp.uzp.gov.pl (old BZP search portal, 2017–2024 data)

The new ezamowienia.gov.pl platform requires OAuth + Angular SPA
rendering which is not accessible without a browser. The old BZP
at searchbzp.uzp.gov.pl has an ASP.NET WebForms UI that loads
results via a DevExpress grid callback — we simulate this callback
directly to get JSON-style data without a real browser.

Normalizes every notice to the standard classifier schema.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib3
from pathlib import Path
from typing import Optional

import requests

_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "raw" / "pl"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ────────────────────────────────────────────────────────────────

SEARCH_URL = "https://searchbzp.uzp.gov.pl/Search.aspx"
DETAIL_BASE = "https://searchbzp.uzp.gov.pl/"

DEFENCE_AUTHORITIES_PL = [
    "inspektorat uzbrojenia",
    "inspektorat wsparcia",
    "agencja uzbrojenia",
    "wojskowy instytut techniczny",
    "wojskowe zakłady",
    "ministerstwo obrony",
    "dowództwo",
    "batalion",
    "brygada",
    "szefost",
    "rejonowy zarząd",
    "regionalne centrum",
    "oddział gospodarczy",
    "oddział zabezpieczenia",
]

TRAILER_KEYWORDS_PL = [
    "przyczepa", "naczep", "niskopodwoziow", "niskopodłogow",
    "cystern", "kuchnia polowa", "shelter",
    "kontener", "platforma transportow",
    "wóz bojowy", "podwozie", "ciągnik",
]


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class PLBZPScraper:
    """
    Scrapes the Polish BZP (Biuletyn Zamówień Publicznych) search portal.

    Architecture:
      The searchbzp.uzp.gov.pl portal is an ASP.NET WebForms app with
      DevExpress grid controls. Search results are loaded via a grid
      callback POST to the same URL. We simulate this by:
        1. GET /Search.aspx → collect ViewState + hidden fields
        2. POST /Search.aspx with subject/authority and DevExpress callback params
        3. Parse HTML table results
        4. Fetch individual notice detail pages
    """

    def __init__(self, config: dict, cache_dir: Optional[str] = None):
        self.config = config or {}
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        })
        self.min_interval = 2.0
        self._last_request = 0.0
        self._form_state: dict = {}

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    # ── Form state ───────────────────────────────────────────────────────────

    def _load_form(self) -> dict:
        """GET the search form and extract all hidden ASP.NET fields."""
        self._rate_limit()
        try:
            r = self.session.get(SEARCH_URL, timeout=20)
            if r.status_code != 200:
                logger.warning(f"PL form load HTTP {r.status_code}")
                return {}

            form_data: dict = {}
            if HAS_BS4:
                soup = BeautifulSoup(r.text, "html.parser")
                for inp in soup.find_all("input"):
                    name = inp.get("name", "")
                    val = inp.get("value", "")
                    if name:
                        form_data[name] = val
            else:
                for m in re.finditer(r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', r.text):
                    form_data[m.group(1)] = m.group(2)
                for m in re.finditer(r'<input[^>]+value=["\']([^"\']*)["\'][^>]*name=["\']([^"\']+)["\']', r.text):
                    form_data[m.group(2)] = m.group(1)

            self._form_state = form_data
            logger.debug(f"PL form: {len(form_data)} fields loaded")
            return form_data

        except Exception as e:
            logger.error(f"PL form load error: {e}")
            return {}

    # ── Search ───────────────────────────────────────────────────────────────

    def search(self, subject: str = "", authority: str = "",
               cpv: str = "") -> list[dict]:
        """
        Search the BZP portal. Returns a list of notice dicts with
        at minimum title, notice_id, pub_date, authority, url.

        Note: Results are loaded server-side via ASP.NET postback.
        """
        form_data = dict(self._form_state) if self._form_state else self._load_form()
        if not form_data:
            logger.warning("PL: no form state — cannot search")
            return []

        # Set search params
        if subject:
            form_data["ctl00$MainContent$txtOrderSubject"] = subject
        if authority:
            form_data["ctl00$MainContent$txtOrdererName"] = authority
        if cpv:
            form_data["ctl00$MainContent$txtCPV"] = cpv

        # Trigger search button via __doPostBack
        form_data["__EVENTTARGET"] = "ctl00$MainContent$btnSearch"
        form_data["__EVENTARGUMENT"] = ""

        self._rate_limit()
        try:
            r = self.session.post(
                SEARCH_URL, data=form_data, timeout=30,
                headers={
                    "Referer": SEARCH_URL,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://searchbzp.uzp.gov.pl",
                }
            )
            logger.debug(f"PL search POST: {r.status_code} len={len(r.text)}")
            return self._parse_results(r.text)

        except Exception as e:
            logger.error(f"PL search error: {e}")
            return []

    def _parse_results(self, html_text: str) -> list[dict]:
        """
        Parse the HTML search results page.

        The DevExpress grid renders result rows as <tr> inside a table
        with class containing 'dxgv' or similar. Falls back to any link
        containing '/ZP400PodgladOpublikowanegoPDF.aspx?id='.
        """
        results = []

        # Primary: look for notice detail links (pattern common to BZP)
        notice_links = re.findall(
            r'href=["\']([^"\']*(?:ZP400|Notice|ogloszenie)[^"\']*)["\']',
            html_text, re.I
        )

        if HAS_BS4:
            soup = BeautifulSoup(html_text, "html.parser")

            # DevExpress grid rows
            for row in soup.select("tr.dxgvDataRow, tr[class*=dxgv], tr.dxGridView_R"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    link_el = row.find("a")
                    href = link_el.get("href", "") if link_el else ""
                    if href and not href.startswith("http"):
                        href = DETAIL_BASE + href.lstrip("/")
                    cell_texts = [c.get_text(" ", strip=True) for c in cells]
                    results.append({
                        "title": cell_texts[1] if len(cell_texts) > 1 else cell_texts[0],
                        "notice_id": cell_texts[0] if cell_texts else "",
                        "pub_date": cell_texts[2] if len(cell_texts) > 2 else "",
                        "authority": cell_texts[3] if len(cell_texts) > 3 else "",
                        "url": href,
                    })

            # Fallback: any table rows with notice links
            if not results:
                for a in soup.find_all("a", href=re.compile(r"ZP400|Notice|ogloszenie", re.I)):
                    href = a.get("href", "")
                    if href and not href.startswith("http"):
                        href = DETAIL_BASE + href.lstrip("/")
                    # Get row context
                    row = a.find_parent("tr")
                    cells = row.find_all("td") if row else []
                    cell_texts = [c.get_text(" ", strip=True) for c in cells]
                    results.append({
                        "title": a.get_text(strip=True) or (cell_texts[0] if cell_texts else ""),
                        "notice_id": "",
                        "pub_date": cell_texts[1] if len(cell_texts) > 1 else "",
                        "authority": cell_texts[2] if len(cell_texts) > 2 else "",
                        "url": href,
                    })
        else:
            # Regex fallback
            for href in notice_links[:50]:
                if not href.startswith("http"):
                    href = DETAIL_BASE + href.lstrip("/")
                results.append({"title": "", "notice_id": "", "url": href,
                                "pub_date": "", "authority": ""})

        logger.info(f"PL search: {len(results)} results parsed from HTML")
        return results

    # ── Detail page ───────────────────────────────────────────────────────────

    def fetch_detail(self, url: str) -> dict:
        """Fetch a BZP notice detail page and extract structured fields."""
        if not url or not url.startswith("http"):
            return {}
        self._rate_limit()
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code != 200:
                return {}
            return self._parse_detail(r.text, url)
        except Exception as e:
            logger.error(f"PL detail error {url}: {e}")
            return {}

    def _parse_detail(self, html_text: str, url: str) -> dict:
        """Extract fields from a BZP notice detail page."""
        fields: dict = {"detail_url": url}

        if HAS_BS4:
            soup = BeautifulSoup(html_text, "html.parser")
            for t in soup(["script", "style", "nav", "header", "footer"]):
                t.decompose()
            text = soup.get_text(" ", strip=True)
        else:
            text = _clean(html_text)

        fields["full_text"] = text[:8000]

        # Extract common fields via regex (Polish BZP uses label:value format)
        patterns = {
            "notice_id": r"Numer og[łl]oszenia[:\s]+(\d+/\d{4})",
            "pub_date": r"Data zamieszczenia[:\s]+(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})",
            "authority": r"Zamawiaj[ąa]cy[:\s]+([^\n]{10,100})",
            "title": r"Nazwa zamówienia[:\s]+([^\n]{10,200})",
            "value_pln": r"Warto[śs][ćc][:\s]+([0-9 ,.]+)\s*PLN",
            "cpv": r"CPV[:\s]+([0-9]{8}(?:-[0-9])?)",
            "deadline": r"Termin sk[łl]adania ofert[:\s]+(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})",
            "winner": r"Wykonawca[:\s]+([^\n]{5,100})",
        }
        for key, pat in patterns.items():
            m = re.search(pat, text, re.I)
            if m:
                fields[key] = m.group(1).strip()

        return fields

    # ── Full pipeline ─────────────────────────────────────────────────────────

    def is_defence(self, notice: dict) -> bool:
        text = (notice.get("authority", "") + " " + notice.get("title", "")).lower()
        return any(kw in text for kw in DEFENCE_AUTHORITIES_PL)

    def is_trailer(self, notice: dict) -> bool:
        text = (notice.get("title", "") + " " + notice.get("description_raw", "")).lower()
        return any(kw in text for kw in TRAILER_KEYWORDS_PL)

    def normalize(self, notice: dict, detail: dict) -> dict:
        """Convert BZP notice to the TED classifier schema."""
        notice_id = detail.get("notice_id") or notice.get("notice_id", "")
        title = detail.get("title") or notice.get("title", "")
        authority = detail.get("authority") or notice.get("authority", "")
        pub_date = detail.get("pub_date") or notice.get("pub_date", "")
        deadline = detail.get("deadline") or ""
        url = detail.get("detail_url") or notice.get("url", "")

        # Normalize date
        def fix_date(d: str) -> str:
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", d)
            if m:
                return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            return d

        tender_id = f"PL-BZP-{re.sub(r'[^A-Za-z0-9]', '-', notice_id)}" if notice_id else \
                    f"PL-BZP-{hash(title + pub_date) & 0xFFFFFF:06X}"

        # Value
        val_str = detail.get("value_pln", "")
        amount = None
        if val_str:
            try:
                amount = float(re.sub(r"[^0-9.,]", "", val_str).replace(",", "."))
            except (ValueError, TypeError):
                pass

        return {
            "tender_id": tender_id,
            "publication_number": tender_id,
            "source": "PL-BZP",
            "source_url_national": url,
            "ted_url": "",

            "title": f"Poland – {title}",
            "description": detail.get("full_text", "")[:2000],
            "cpv_codes": [detail["cpv"]] if detail.get("cpv") else [],
            "legal_basis": "",
            "publication_date": fix_date(pub_date),
            "submission_deadline": fix_date(deadline),
            "contracting_authority": {
                "name": authority,
                "name_short": authority,
                "country": "POL",
            },
            "estimated_value": ({"amount": amount, "currency": "PLN"} if amount else {}),
            "award": ({"winner_name": detail["winner"]} if detail.get("winner") else None),

            "_raw": notice,
        }

    def fetch_and_filter(self, existing_notices: Optional[list] = None,
                         test_mode: bool = False) -> list[dict]:
        """
        Full PL scraping pipeline.

        Searches for each combination of defence authority + trailer keyword,
        deduplicates, fetches detail pages, normalizes to schema.
        """
        # Load form state once
        self._load_form()

        all_raw: dict[str, dict] = {}  # url → notice

        keyword_pairs = [
            ("przyczepa", "Inspektorat Uzbrojenia"),
            ("przyczepa", "Agencja Uzbrojenia"),
            ("naczepa", "wojsk"),
            ("przyczepa", "12 Wojskowy"),
        ]

        if test_mode:
            keyword_pairs = keyword_pairs[:2]

        for subject, authority in keyword_pairs:
            logger.info(f"PL search: subject='{subject}' authority='{authority}'")
            results = self.search(subject=subject, authority=authority)
            for r in results:
                url = r.get("url", "")
                if url and url not in all_raw:
                    all_raw[url] = r
            logger.info(f"  After pair: {len(all_raw)} unique notices")
            time.sleep(1.0)

            if test_mode and len(all_raw) >= 10:
                break

        logger.info(f"PL: {len(all_raw)} unique candidates after dedup")

        # Filter for defence + trailer relevance (when title is available)
        candidates = list(all_raw.values())

        normalized: list[dict] = []
        for i, notice in enumerate(candidates):
            logger.info(f"PL [{i+1}/{len(candidates)}]: {notice.get('title','')[:60]} "
                        f"| {notice.get('authority','')[:40]}")
            detail = self.fetch_detail(notice.get("url", ""))
            norm = self.normalize(notice, detail)
            normalized.append(norm)

        # Cache
        raw_path = self.cache_dir / "pl_raw.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)

        norm_path = self.cache_dir / "pl_normalized.json"
        with open(norm_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

        logger.info(f"PL: {len(normalized)} notices saved to {norm_path}")
        return normalized

    @staticmethod
    def dedup_key(notice: dict) -> str:
        title = re.sub(r"^poland\s*[-–]\s*", "", notice.get("title", "").lower())
        title = re.sub(r"\s+", " ", title).strip()[:35]
        year = str(notice.get("publication_date", ""))[:4]
        return f"{title}|{year}"

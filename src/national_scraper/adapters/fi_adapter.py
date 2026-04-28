"""
Finland Adapter - Hilma (hankintailmoitukset.fi)

Hybrid REST API + Playwright browser scraper for Finland's official
national procurement portal.

Discovered portal structure (2026-04-28):
  - REST API patterns under /api/v1/ all returned 4xx or wrong content-type.
    Browser scraping used as primary strategy.
  - Search page: https://www.hankintailmoitukset.fi/fi/search
  - Search form field: input[placeholder*="haku"] (Sanahaku = word search)
  - Results table columns: LAAJUUS | NIMI | ILMOITUSTYYPPI |
    JULKAISTU (SUOMEN AIKAA) | MAARAIKA (SUOMEN AIKAA) | OSTAJAORGANISAATIO
  - Each row renders as: scope line (FI / EU / P) followed by tab-separated
    detail line with title, notice type, dates, and organisation.
  - Page text parser (scope-line detection) reliably extracts 30-50 results.
  - orgName URL parameter ignored by the React SPA -- shows default recent
    50 notices regardless of parameter value.

Defence procurement authorities:
  Puolustusvoimat, Puolustusministerio, Puolustusvoimien Logistiikkalaitos,
  Sotilaslaaketieteeen Keskus, Maavoimat, Merivoimat, Ilmavoimat

Finnish trailer vocabulary:
  peravaunu=trailer, puoliperavaunu=semitrailer, lavetti=low-bed,
  sailioeravaunu=tank trailer, kenttakeittioe=field kitchen
"""

import re
import time
import logging
import os
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

HILMA_BASE = "https://www.hankintailmoitukset.fi"
HILMA_SEARCH_URL = HILMA_BASE + "/fi/search"
HILMA_API_BASE = HILMA_BASE + "/api/v1"

HILMA_API_CANDIDATES = [
    HILMA_API_BASE + "/procurement-notices/published",
    HILMA_API_BASE + "/notices/search",
    HILMA_API_BASE + "/notices",
    HILMA_BASE + "/fi/rest/noticeIds/type/hilma/procurement/open",
    HILMA_BASE + "/fi/rest/noticeIds",
]


def create_fi_config():
    return AdapterConfig(
        country_name="Finland",
        country_code="FI",
        source_code="FI-HI",
        base_url=HILMA_BASE,
        search_url=HILMA_SEARCH_URL,
        language="fi",
        trailer_keywords=[
            "peravaunu",
            "puoliperavaunu",
            "lavetti",
            "kenttakeittioe",
            "kuljetusperavaunu",
            "sailioeravaunu",
        ],
        defence_authorities=[
            "Puolustusvoimat",
            "Puolustusministerio",
            "Puolustusvoimien Logistiikkalaitos",
            "Sotilaslaaketieteeen Keskus",
            "Maavoimat",
            "Merivoimat",
            "Ilmavoimat",
            "Puolustushallinnon rakennuslaitos",
        ],
        min_interval_seconds=2.0,
    )


class FIAdapter(BaseAdapter):
    """
    Finland adapter - Hilma procurement portal.
    Hybrid REST API + browser (page text parser primary, JS walker fallback).
    """

    def __init__(self, browser, config):
        super().__init__(browser, config)
        self._session = self._build_session()
        self._api_endpoint = None
        self._api_tested = False

    def _build_session(self):
        try:
            import requests
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            return None
        import requests as rl
        session = rl.Session()
        session.verify = not (
            os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower()
            in ("1", "true", "yes")
        )
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "fi-FI,fi;q=0.9,en-GB;q=0.8",
        })
        return session

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, keyword, max_results=50):
        if not self._api_tested or self._api_endpoint:
            results = self._search_rest_api(keyword, max_results)
            if results:
                return results
        return self._search_browser(keyword, max_results)

    def search_all_keywords(self, max_results_per_keyword=30, test_mode=False):
        """Keyword searches + Puolustusvoimat authority search."""
        all_results = {}

        keywords = (
            self.config.trailer_keywords[:2]
            if test_mode
            else self.config.trailer_keywords
        )
        for kw in keywords:
            for r in self.search(kw, max_results=max_results_per_keyword):
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            time.sleep(self.config.min_interval_seconds)

        logger.info("FI: running Puolustusvoimat authority search")
        auth_list = (
            ["Puolustusvoimat"]
            if test_mode
            else ["Puolustusvoimat", "Puolustusvoimien Logistiikkalaitos"]
        )
        for auth_kw in auth_list:
            for r in self._search_browser_authority(auth_kw, max_results=50):
                key = r.url or r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r

        logger.info("FI: search_all_keywords -> %d unique results", len(all_results))
        return list(all_results.values())

    def get_detail(self, result):
        if not result.url:
            return None
        logger.info("FI: fetching detail: %s", result.url[:80])
        if not self.browser.goto(result.url, wait_for="networkidle", timeout=30000):
            return None
        self.browser.wait_seconds(2)
        safe_id = re.sub(
            r"[^a-z0-9]", "_",
            (result.reference_id or result.title[:15]).lower()
        )
        self.browser._screenshot("fi_detail_" + safe_id)
        raw_text = self.browser.get_page_text()
        detail = NoticeDetail(
            title=result.title or self._find_title(raw_text),
            url=result.url,
            authority=result.authority or self._find_authority(raw_text),
            date=result.date or self._find_date(raw_text),
            reference_id=result.reference_id or self._find_ref_id(raw_text),
            source_code="FI-HI",
            raw_text=raw_text[:15000],
            currency="EUR",
        )
        detail.description = self._find_description(raw_text)
        detail.quantity = self._find_quantity(raw_text)
        detail.value = self._find_value(raw_text)
        detail.winner = self._find_winner(raw_text)
        detail.duration = self._find_duration(raw_text)
        return detail

    def filter_defence(self, results):
        kept = []
        fi_patterns = [
            "puolustusvoim", "puolustusministeri", "puolustushallinto",
            "maavoimat", "merivoimat", "ilmavoimat", "sotilaslaaket",
            "logistiikkalaitos",
        ]
        for r in results:
            all_text = " ".join([
                (r.authority or "").lower(),
                (r.title or "").lower(),
                (r.snippet or "").lower(),
            ])
            is_defence = (
                any(pat.lower() in all_text for pat in self.config.defence_authorities)
                or any(p in all_text for p in fi_patterns)
            )
            if is_defence:
                kept.append(r)
        logger.info("FI: filter_defence: %d -> %d", len(results), len(kept))
        return kept

    # ------------------------------------------------------------------
    # REST API
    # ------------------------------------------------------------------

    def _search_rest_api(self, keyword, max_results):
        if not self._session:
            return []
        self._api_tested = True
        candidates = (
            [self._api_endpoint] if self._api_endpoint else HILMA_API_CANDIDATES
        )
        for endpoint in (c for c in candidates if c):
            try:
                params = {
                    "keyword": keyword,
                    "pageSize": min(max_results, 100),
                    "page": 0,
                }
                resp = self._session.get(endpoint, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                if "json" not in resp.headers.get("content-type", ""):
                    continue
                results = self._parse_api_response(resp.json())
                logger.info("FI REST: %s -> %d (kw=%r)", endpoint, len(results), keyword)
                if not self._api_endpoint:
                    self._api_endpoint = endpoint
                return results
            except Exception as exc:
                logger.debug("FI REST %s: %s", endpoint, exc)
        logger.info("FI: all REST patterns failed")
        return []

    def _parse_api_response(self, data):
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("notices") or data.get("results")
                or data.get("items") or data.get("content")
                or data.get("data") or []
            )
        else:
            return []
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = (
                item.get("title") or item.get("projectName")
                or item.get("noticeName") or item.get("subject") or ""
            )
            if isinstance(title, dict):
                title = title.get("fi") or title.get("sv") or title.get("en") or ""
            notice_id = (
                item.get("noticeNumber") or item.get("id")
                or item.get("noticeId") or item.get("referenceNumber") or ""
            )
            authority = (
                item.get("organizationName") or item.get("authority")
                or item.get("contractingAuthority") or item.get("buyerName") or ""
            )
            if isinstance(authority, dict):
                authority = authority.get("fi") or authority.get("name") or ""
            date = (
                item.get("publishedDate") or item.get("publicationDate")
                or item.get("datePublished") or ""
            )
            if date and len(str(date)) >= 10:
                date = str(date)[:10]
            url = item.get("url") or item.get("noticeUrl") or ""
            if not url and notice_id:
                url = HILMA_BASE + "/fi/notice/" + str(notice_id)
            snippet = item.get("shortDescription") or item.get("description") or ""
            if isinstance(snippet, dict):
                snippet = snippet.get("fi") or snippet.get("en") or ""
            if not title and not notice_id:
                continue
            results.append(SearchResult(
                title=str(title)[:200],
                url=str(url),
                authority=str(authority)[:200],
                reference_id=str(notice_id),
                date=str(date)[:10],
                snippet=str(snippet)[:300],
            ))
        return results

    # ------------------------------------------------------------------
    # Browser search
    # ------------------------------------------------------------------

    def _search_browser(self, keyword, max_results):
        """Fill the Hilma search form and capture XHR or scrape page text."""
        import urllib.parse

        logger.info("FI: browser search for %r", keyword)
        captured = []

        def on_response(response):
            try:
                url = response.url
                ct = response.headers.get("content-type", "")
                if (response.status == 200 and "json" in ct
                        and any(p in url for p in ["/api/", "/rest/", "search", "notice"])):
                    data = response.json()
                    if data:
                        captured.append((url, data))
            except Exception:
                pass

        self.browser.page.on("response", on_response)
        try:
            ok = self.browser.goto(HILMA_SEARCH_URL, wait_for="networkidle", timeout=30000)
            self.browser.wait_seconds(2)
            if ok:
                kw_js = keyword.replace("'", "\\'").replace("\\", "\\\\")
                filled = self.browser.page.evaluate(
                    "() => {"
                    "  const sels = ["
                    "    'input[placeholder*=\"haku\"]',"
                    "    'input[placeholder*=\"Haku\"]',"
                    "    'input[type=\"search\"]',"
                    "    'input[name=\"keyword\"]',"
                    "    'input[name=\"q\"]',"
                    "    '#keyword',"
                    "    'input[class*=\"search\"]',"
                    "    'input[class*=\"input\"]',"
                    "  ];"
                    "  for (const s of sels) {"
                    "    const el = document.querySelector(s);"
                    "    if (el) {"
                    "      el.value = '" + kw_js + "';"
                    "      el.dispatchEvent(new Event('input', {bubbles: true}));"
                    "      el.dispatchEvent(new Event('change', {bubbles: true}));"
                    "      return s;"
                    "    }"
                    "  }"
                    "  return null;"
                    "}"
                )
                if filled:
                    logger.info("FI: filled %r with %r", filled, keyword)
                    self.browser.wait_seconds(0.5)
                    self.browser.page.evaluate(
                        "() => {"
                        "  const btns = Array.from(document.querySelectorAll('button'));"
                        "  const sb = btns.find(b => b.type === 'submit'"
                        "    || /haku|etsi|hae/i.test(b.textContent));"
                        "  if (sb) { sb.click(); return; }"
                        "  document.querySelectorAll('input[type=\"search\"],"
                        "    input[name=\"keyword\"]').forEach(i =>"
                        "    i.dispatchEvent(new KeyboardEvent('keypress',"
                        "      {key: 'Enter', bubbles: true})));"
                        "}"
                    )
                    self.browser.wait_seconds(3)
                    self.browser.wait_networkidle(timeout=10000)
                else:
                    url2 = (HILMA_SEARCH_URL
                            + "?keyword=" + urllib.parse.quote(keyword))
                    self.browser.goto(url2, wait_for="networkidle", timeout=30000)
                    self.browser.wait_seconds(3)
        finally:
            self.browser.page.remove_listener("response", on_response)

        safe_kw = re.sub(r"[^a-z0-9]", "_", keyword.lower()[:15])
        self.browser._screenshot("fi_search_" + safe_kw)
        self.browser.save_page_text("fi_search_" + safe_kw + ".txt")

        for url, data in captured:
            results = self._parse_api_response(data)
            if results:
                logger.info("FI: XHR -> %d from %s", len(results), url[:60])
                if not self._api_endpoint and "/api/" in url:
                    self._api_endpoint = url.split("?")[0]
                return results[:max_results]

        return self._parse_dom_results(max_results)

    def _search_browser_authority(self, authority, max_results=50):
        """Search Hilma filtered by buyer organisation name."""
        import urllib.parse
        url = (HILMA_SEARCH_URL
               + "?orgName=" + urllib.parse.quote(authority)
               + "&of=datePublished&od=desc")
        logger.info("FI: authority search -> %s", url)
        if not self.browser.goto(url, wait_for="networkidle", timeout=30000):
            return []
        self.browser.wait_seconds(3)
        safe = re.sub(r"[^a-z0-9]", "_", authority.lower()[:15])
        self.browser._screenshot("fi_org_" + safe)
        self.browser.save_page_text("fi_org_" + safe + ".txt")
        return self._parse_dom_results(max_results)

    # ------------------------------------------------------------------
    # DOM / page-text parsing
    # ------------------------------------------------------------------

    def _parse_dom_results(self, max_results):
        """
        Extract notice rows from the current Hilma results page.

        Priority:
        1. Page-text column parser (FI/EU/P scope -> title -> org) --
           most reliable because it uses visible text not React DOM.
        2. JS row-extraction (walks tr/li/article for notice links).
        3. Broad link scan (any href that looks like a notice URL).
        """
        results = self._parse_page_text_results(max_results)
        if len(results) >= 3:
            return results

        js_results = self._extract_via_js(max_results)
        if len(js_results) > len(results):
            results = js_results
        if results:
            return results

        # Last resort -- any anchor that looks like a notice page
        try:
            raw = self.browser.page.evaluate(
                "() => {"
                "  const seen = new Set();"
                "  return Array.from(document.querySelectorAll('a[href]'))"
                "    .filter(a => {"
                "      const h = a.href || '';"
                "      return h.length > 40"
                "        && !h.endsWith('/fi/')"
                "        && !h.includes('/search')"
                "        && !h.includes('/info')"
                "        && !h.includes('/ohjeet')"
                "        && !seen.has(h) && seen.add(h);"
                "    })"
                "    .slice(0, 50)"
                "    .map(a => ({href: a.href, text: (a.innerText||'').trim()}));"
                "}"
            ) or []
            for item in raw[:max_results]:
                href = item.get("href", "")
                text = item.get("text", "").strip()
                if text and len(text) > 8:
                    m = re.search(r"/([A-Za-z0-9\-]{6,})$", href.rstrip("/"))
                    results.append(SearchResult(
                        title=text[:200],
                        url=href,
                        reference_id=m.group(1) if m else "",
                    ))
        except Exception as exc:
            logger.debug("FI link fallback: %s", exc)

        logger.info("FI DOM: %d results total", len(results))
        return results

    def _extract_via_js(self, max_results):
        """Walk DOM for notice-link rows using JavaScript."""
        try:
            raw = self.browser.page.evaluate(
                "(base) => {"
                "  const results = [];"
                "  const seen = new Set();"
                "  function isNoticeHref(h) {"
                "    if (!h) return false;"
                "    if (h.endsWith('/fi/') || h.includes('/search')"
                "        || h.includes('/info') || h.includes('/ohjeet')"
                "        || h.includes('/register') || h.includes('/login')"
                "        || h.includes('#')) return false;"
                "    return /\\/[A-Za-z0-9\\-_]{6,}(\\?.*)?$/.test(h);"
                "  }"
                "  const containers = ["
                "    ...document.querySelectorAll('tr'),"
                "    ...document.querySelectorAll('[role=\"row\"]'),"
                "    ...document.querySelectorAll('li'),"
                "    ...document.querySelectorAll('article'),"
                "    ...document.querySelectorAll('[class*=\"notice\"]'),"
                "    ...document.querySelectorAll('[class*=\"row\"]'),"
                "  ];"
                "  for (const c of containers) {"
                "    if (c.querySelector('th')) continue;"
                "    const link = c.querySelector('a[href]');"
                "    if (!link) continue;"
                "    const href = link.href || '';"
                "    if (!isNoticeHref(href) || seen.has(href)) continue;"
                "    seen.add(href);"
                "    const text = (c.innerText || '').trim();"
                "    const lines = text.split('\\n').map(l=>l.trim()).filter(Boolean);"
                "    let title = (link.innerText || '').trim();"
                "    if (!title || title.length < 5)"
                "      title = lines.find(l => l.length > 10"
                "        && !l.match(/^\\d{2}\\.\\d{2}/) && !l.match(/^(FI|EU|P)$/)) || '';"
                "    let org = '';"
                "    for (let i = lines.length-1; i>=0; i--) {"
                "      const l = lines[i];"
                "      if (l.length > 4 && !l.match(/^\\d{2}\\.\\d{2}/)"
                "          && !l.match(/^(FI|EU|P)$/) && !l.toLowerCase().includes('ilmoitus')"
                "          && !l.toLowerCase().includes('notice')) { org = l; break; }"
                "    }"
                "    const dm = text.match(/(\\d{1,2}\\.\\d{1,2}\\.\\d{4})/);"
                "    if (title && title.length > 5)"
                "      results.push({href, title, org, date: dm ? dm[1] : ''});"
                "  }"
                "  return results;"
                "}",
                HILMA_BASE,
            ) or []

            results = []
            for item in raw[:max_results]:
                href = item.get("href", "")
                title = item.get("title", "").strip()
                if not title or not href:
                    continue
                m = re.search(r"/([A-Za-z0-9\-]{6,})$", href.rstrip("/"))
                raw_date = item.get("date", "")
                date_str = ""
                if raw_date:
                    p = raw_date.split(".")
                    if len(p) == 3:
                        date_str = (
                            p[2] + "-"
                            + str(int(p[1])).zfill(2) + "-"
                            + str(int(p[0])).zfill(2)
                        )
                results.append(SearchResult(
                    title=title[:200],
                    url=href,
                    authority=(item.get("org") or "")[:200],
                    reference_id=m.group(1) if m else "",
                    date=date_str,
                ))
            if results:
                logger.info("FI JS: %d notice rows", len(results))
            return results
        except Exception as exc:
            logger.debug("FI JS extract: %s", exc)
            return []

    def _parse_page_text_results(self, max_results=50):
        """
        Parse Hilma results table from visible page text.

        Table renders as:
          FI          <- scope line
          <Title>  <NoticeType>  <Date>  <Org>   <- tab/space-separated detail line
          EU
          ...
        """
        page_text = self.browser.get_page_text()
        lines = page_text.split("\n")
        results = []
        i = 0
        while i < len(lines) - 1 and len(results) < max_results:
            scope = lines[i].strip()
            if scope in ("FI", "EU", "P", "EU/FI", "EEA"):
                details = lines[i + 1].strip() if (i + 1) < len(lines) else ""
                if len(details) > 10:
                    parts = re.split(r"\t+|\s{3,}", details)
                    title = parts[0].strip() if parts else details[:150]
                    org = parts[-1].strip() if len(parts) > 1 else ""
                    date_str = ""
                    for p in parts:
                        dm = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", p.strip())
                        if dm:
                            date_str = (
                                dm.group(3) + "-"
                                + str(int(dm.group(2))).zfill(2) + "-"
                                + str(int(dm.group(1))).zfill(2)
                            )
                            break
                    if title and len(title) > 5:
                        results.append(SearchResult(
                            title=title[:200],
                            url="",
                            authority=org[:200],
                            date=date_str,
                            snippet=details[:300],
                        ))
                i += 2
            else:
                i += 1

        if results:
            logger.info("FI page text: %d results", len(results))
        return results

    # ------------------------------------------------------------------
    # Text extraction helpers
    # ------------------------------------------------------------------

    def _find_title(self, text):
        for pat in [
            r"(?:Hankinnan nimi|Hankintakohde|Ilmoituksen nimi)[:\s]+([^\n]{5,150})",
            r"(?:Subject|Title)[:\s]+([^\n]{5,150})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:150]
        return ""

    def _find_authority(self, text):
        for pat in [
            r"(?:Hankintaviranomainen|Hankintayksikko|Tilaaja)[:\s]+([^\n]{5,120})",
            r"(?:Contracting authority|Organisation name)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        for auth in self.config.defence_authorities:
            if auth.lower() in text.lower():
                return auth
        return ""

    def _find_date(self, text):
        for pat in [
            r"(?:Julkaisupaivamaara|Julkaistu)[:\s]+(\d{4}-\d{2}-\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
        ]:
            m = re.search(pat, text)
            if m:
                return m.group(1)[:10]
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
        if m:
            return (
                m.group(3) + "-"
                + str(int(m.group(2))).zfill(2) + "-"
                + str(int(m.group(1))).zfill(2)
            )
        return ""

    def _find_description(self, text):
        for pat in [
            r"(?:Hankinnan kuvaus|Lyhyt kuvaus|Kuvaus)[:\s]+(.{30,500}?)(?:\n\n|$)",
            r"(?:Description|Short description)[:\s]+(.{30,500}?)(?:\n\n|$)",
        ]:
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                return m.group(1).strip()[:400]
        return ""

    def _find_quantity(self, text):
        for pat in [
            r"(\d+)\s*(?:kappaletta|kpl\.?|yksikko|ajoneuvo|peravaunu)",
            r"(?:Maara|Lukumaara)[:\s]+(\d+)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1))
                    if 1 <= v <= 10000:
                        return v
                except ValueError:
                    pass
        return None

    def _find_value(self, text):
        for pat in [
            r"(?:Arvioitu arvo|Kokonaisarvo|Hankinnan arvo)[:\s]+([\d\s,]+)\s*(?:EUR|euro)",
            r"([\d\s]{5,})\s*(?:EUR|euro)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val_str = m.group(1).replace(" ", "").replace(",", ".")
                try:
                    v = float(val_str)
                    if v > 100:
                        return v
                except ValueError:
                    pass
        return None

    def _find_winner(self, text):
        for pat in [
            r"(?:Toimittaja|Voittanut tarjoaja|Sopimuspuoli)[:\s]+([^\n]{5,120})",
            r"(?:Winner|Successful tenderer|Awarded to)[:\s]+([^\n]{5,120})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        return ""

    def _find_duration(self, text):
        for pat in [
            r"(?:Sopimuksen kesto|Kesto)[:\s]+([^\n]{3,60})",
            r"(\d+)\s*(?:kuukautta|viikkoa|vuotta|paivaa)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:60]
        return ""

    def _find_ref_id(self, text):
        for pat in [
            r"(?:Viite|Hankinnan numero|Diaarinumero|Ilmoitusnumero)[:\s]+([A-Z0-9/\-_.]{4,50})",
            r"(?:Notice number|Reference number)[:\s]+([A-Z0-9/\-_.]{4,50})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

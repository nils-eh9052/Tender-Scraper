"""
Tests for src/national_scraper/fallback/ modules.

Tests are purely unit tests (no network calls) using mock HTTP responses.
Run with: python -m pytest tests/test_national_fallback.py -v
"""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Shared fixtures ────────────────────────────────────────────────────────────

_PAD = "<!-- padding for min-size threshold " + "x" * 100 + " -->\n"

EVERGABE_HTML = ("""
<html><body>
<h1>Ausschreibungsdetails — Bundesamt für Ausrüstung, Informationstechnik und Nutzung der Bundeswehr</h1>
<p>Vergabestelle: BAAINBw, Koblenz</p>
<p>Ausschreibungsnummer: Q/U2BP/RA029/NA103</p>
<p>Auftragswert: 5.200.000 EUR</p>
<p>Menge: 50 Stück</p>
<p>Laufzeit: 48 Monate</p>
<p>Vertragsgegenstand: Beschaffung von militärischen Schwerlastanhängern für die Bundeswehr</p>
<p>CPV: 34223300</p>
<ul>
  <li><a href="/tenderdocumentdetail.html?documentId=111">Leistungsverzeichnis.pdf</a></li>
  <li><a href="/Download?id=222&amp;filename=Technische_Anforderungen.pdf">Technische Anforderungen</a></li>
</ul>
<p>Zuschlag erteilt an: Acme Defence GmbH</p>
<p>Zuschlagsdatum: 2024-12-01</p>
""" + _PAD + "</body></html>\n")

SERVICE_BUND_RESULTS_HTML = ("""
<html><body>
<h1>Suchergebnisse — Bundesvergabeportal service.bund.de</h1>
<p>Gefunden: 1 Ausschreibung entspricht Ihren Suchkriterien für Vergabeverfahren Verteidigung</p>
<p>Bitte beachten Sie: Die Suchergebnisse werden täglich aktualisiert. Stand: 2024-11-08.</p>
<ul class="results-list">
  <li class="result-item">
    <a href="/Content/DE/Ausschreibungen/IMPORTE/ByMeldungsNr/2024/682847-2024.html">
      Military Cargo Trailers 3.5t und 12.5t (Kastenanhänger)
    </a>
    <span>BAAINBw, Koblenz — Veröffentlicht: 2024-11-08</span>
    <span>Vergabeverfahren: VSVgV — Verteidigung und Sicherheit</span>
  </li>
</ul>
""" + _PAD + "</body></html>\n")

SERVICE_BUND_DETAIL_HTML = ("""
<html><body>
<h1>Military Cargo Trailers 3.5t und 12.5t</h1>
<p>Vergabestelle: Bundesamt für Ausrüstung (BAAINBw), Koblenz</p>
<p>Ausschreibungsart: Verteidigungs- und Sicherheitsauftrag (VSVgV)</p>
<p>Anzahl: 30 Stück</p>
<p>Auftragswert: 3.100.000 EUR</p>
<p>Auftragnehmer: Acme Defence GmbH, München</p>
<p>Vertragslaufzeit: 36 Monate</p>
""" + _PAD + "</body></html>\n")

EZAMOWIENIA_SEARCH_RESP = [
    {
        "objectId":        "abc-123-def-456",
        "noticeNumber":    "2025/BZP 00261427/01",
        "orderObject":     "High-capacity transport trailers",
        "organizationName": "12 Wojskowy Oddział Gospodarczy",
        "publicationDate": "2025-04-23T08:00:00Z",
    }
]
EZAMOWIENIA_PAGINATION = json.dumps({
    "TotalCount": 1, "PageSize": 100, "CurrentPage": 1, "HasNext": False
})

EZAMOWIENIA_HTML_BODY = """
<html><body>
<h2>4.5.1.) Krótki opis przedmiotu zamówienia</h2>
<p>Przyczepy o dużej ładowności do transportu sprzętu wojskowego</p>
<p>Ilość: 20 sztuk</p>
<p>Czas trwania zamówienia: 12 miesięcy</p>
<p>7.3.1) Nazwa wykonawcy: Zasław Sp. z o.o.</p>
<p>Wartość zamówienia: 1 530 000 PLN</p>
</body></html>
"""

VOP_HTML = ("""
<html><body>
<h1>Semi-trailers - Low-bed for heavy military equipment — VOP CZ, s.p.</h1>
<p>Zadavatel: VOP CZ, s.p. — Výzkumný a zkušební ústav Plzeň s.r.o.</p>
<p>Evidenční číslo: OVZ/018/3/2025</p>
<p>Počet: 5 ks</p>
<p>Předpokládaná hodnota: 12 000 000 Kč</p>
<p>Doba trvání: 24 měsíců</p>
<p>Popis: Dodávka nízkoložných návěsů pro přepravu těžké vojenské techniky a bojových vozidel</p>
<p>CPV kód: 34223300 — Přívěsy</p>
<ul>
  <li><a href="/soubory/priloha1.pdf">Technické požadavky.pdf</a></li>
  <li><a href="/soubory/priloha2.pdf">Projektová dokumentace.pdf</a></li>
</ul>
<p>Vybraný dodavatel: Tatra Defence Vehicle a.s.</p>
<p>Hodnota smlouvy: 11 500 000 Kč</p>
""" + _PAD + "</body></html>\n")

NEN_SEARCH_HTML = ("""
<html><body>
<h1>Veřejné zakázky — Národní elektronický nástroj (NEN/NIPEZ)</h1>
<p>Výsledky hledání pro: OVZ/018/3/2025</p>
<p>Nalezeno: 1 zakázka odpovídající zadání v databázi Ministerstva pro místní rozvoj</p>
<p>Systém NEN je součástí Národní infrastruktury pro elektronické zadávání veřejných zakázek</p>
<p>Filtrování podle CPV kódu: 34223300, 34220000 — Přívěsy a návěsy pro vojenské účely</p>
<table class="gov-table gov-table--tablet-block gov-sortable-table">
<thead><tr>
  <th>Detail</th><th>Systémové číslo</th><th>Název</th>
  <th>Stav</th><th>Zadavatel</th><th>Lhůta</th>
</tr></thead>
<tbody>
<tr>
  <td><a href="/en/verejne-zakazky/detail-zakazky/N006-25-V00008153">Detail</a></td>
  <td>N006/25/V00008153</td>
  <td>Semi-trailers Heavy Military Equipment Transport</td>
  <td>Neukončen</td>
  <td>Ministerstvo obrany</td>
  <td>30/06/2025</td>
</tr>
</tbody>
</table>
<p>Stránka 1 z 1 — Celkem 1 zakázka nalezena pro vaše kritéria</p>
""" + _PAD * 5 + "</body></html>\n")

NEN_DETAIL_HTML = ("""
<html><body>
<h1>Semi-trailers Heavy Military Equipment Transport — Ministerstvo obrany</h1>
<p>Zadavatel: Ministerstvo obrany České republiky, Praha 6 — Dejvice</p>
<p>Systémové číslo zakázky: N006/25/V00008153</p>
<p>Interní číslo zadavatele: OVZ/018/3/2025</p>
<p>CURRENT STATUS OF THE PROCUREMENT PROCEDURE</p>
<p>Not terminated</p>
<p>Popis předmětu zakázky: Pořízení nízkoložných návěsů pro přepravu těžké vojenské techniky</p>
<p>Typ zakázky: Dodávky dle § 14 odst. 1 zákona č. 134/2016 Sb.</p>
<p>CPV kód: 34223300 — Přívěsy pro vojenské účely a bojovou techniku</p>
<p>Počet: 8 ks</p>
<p>ESTIMATED VALUE (EXCL. VAT)</p>
<p>85,000,000</p>
<p>Měna: CZK — Česká koruna</p>
<ul>
  <li><a href="/soubory/specifikace.pdf">Specifikace technických požadavků.pdf</a></li>
  <li><a href="/soubory/pozadavky.pdf">Technické požadavky a podmínky.pdf</a></li>
</ul>
<p>Datum zveřejnění: 17.07.2025 — Lhůta pro podání nabídek: 30.06.2025 13:00</p>
""" + _PAD * 5 + "</body></html>\n")


# ── url_is_healthy tests ───────────────────────────────────────────────────────

class TestUrlIsHealthy(unittest.TestCase):

    def _healthy(self, *args, **kwargs):
        from src.document_pipeline.discovery import url_is_healthy
        return url_is_healthy(*args, **kwargs)

    def test_empty_url_returns_false(self):
        self.assertFalse(self._healthy(""))

    def test_non_http_url_returns_false(self):
        self.assertFalse(self._healthy("ftp://example.com/doc.pdf"))

    def test_internal_url_returns_false(self):
        self.assertFalse(self._healthy("internal://national_raw_text"))

    @patch("src.document_pipeline.discovery.requests.head")
    def test_200_ok_returns_true(self, mock_head):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_head.return_value = mock_resp
        self.assertTrue(self._healthy("https://example.com/doc.pdf"))

    @patch("src.document_pipeline.discovery.requests.head")
    def test_404_returns_false(self, mock_head):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.headers = {}
        mock_head.return_value = mock_resp
        self.assertFalse(self._healthy("https://example.com/dead.pdf"))

    @patch("src.document_pipeline.discovery.requests.head")
    def test_403_returns_false(self, mock_head):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {}
        mock_head.return_value = mock_resp
        self.assertFalse(self._healthy("https://example.com/auth-blocked.pdf"))

    @patch("src.document_pipeline.discovery.requests.head")
    def test_small_content_length_returns_false(self, mock_head):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": "500"}  # < 1024
        mock_head.return_value = mock_resp
        self.assertFalse(self._healthy("https://example.com/tiny.pdf"))

    @patch("src.document_pipeline.discovery.requests.head")
    def test_connection_error_returns_false(self, mock_head):
        import requests as _req
        mock_head.side_effect = _req.ConnectionError("timeout")
        self.assertFalse(self._healthy("https://example.com/doc.pdf"))


# ── DE search tests ────────────────────────────────────────────────────────────

class TestDeSearch(unittest.TestCase):

    def _search(self, *args, **kwargs):
        from src.national_scraper.fallback.de_search import search_de
        return search_de(*args, **kwargs)

    def _ev_id(self, url):
        from src.national_scraper.fallback.de_search import _extract_evergabe_id
        return _extract_evergabe_id(url)

    def test_extract_evergabe_id(self):
        self.assertEqual(self._ev_id("https://www.evergabe-online.de/tenderdetails.html?id=771723"), "771723")
        self.assertEqual(self._ev_id("https://www.evergabe-online.de/tenderdocuments.html?id=816217"), "816217")
        self.assertEqual(self._ev_id("http://www.evergabe-online.de"), "")
        self.assertEqual(self._ev_id(""), "")

    @patch("src.national_scraper.fallback.de_search._get_html")
    def test_evergabe_detail_fetched_and_parsed(self, mock_get):
        mock_get.return_value = EVERGABE_HTML
        result = self._search(
            internal_ref="Q/U2BP/RA029/NA103",
            buyer="BAAINBw",
            title_keywords=["trailers", "cargo"],
            tender_documents_url="https://www.evergabe-online.de/tenderdetails.html?id=771723",
        )
        self.assertIsNotNone(result)
        self.assertIn("portal_url", result)
        self.assertIn("documents", result)
        self.assertIn("771723", result["portal_url"])
        # Should find PDF documents
        self.assertGreater(len(result["documents"]), 0)
        # Fields extracted
        af = result["additional_fields"]
        self.assertEqual(af["winner"], "Acme Defence GmbH")
        self.assertEqual(af["quantity"], 50)
        self.assertEqual(af["contract_duration"], "48 Monate")

    @patch("src.national_scraper.fallback.de_search._get_html")
    def test_evergabe_returns_none_on_empty(self, mock_get):
        mock_get.return_value = None
        result = self._search(
            internal_ref="",
            buyer="BAAINBw",
            title_keywords=["trailers"],
            tender_documents_url="https://www.evergabe-online.de/tenderdetails.html?id=99999",
        )
        # Should fall through to service.bund.de or return None
        # (service.bund.de also returns None since mock returns None)
        self.assertIsNone(result)

    @patch("src.national_scraper.fallback.de_search._get_html")
    def test_service_bund_fallback(self, mock_get):
        def get_side_effect(sess, url):
            if "IMPORTE" in url:
                return SERVICE_BUND_DETAIL_HTML
            if "service.bund.de" in url:
                return SERVICE_BUND_RESULTS_HTML
            return None

        mock_get.side_effect = get_side_effect
        result = self._search(
            internal_ref="682847-2024",
            buyer="BAAINBw",
            title_keywords=["Military", "Cargo", "Trailers"],
            tender_documents_url="",
        )
        # service.bund.de search should find something
        self.assertIsNotNone(result)

    def test_de_value_extraction(self):
        from src.national_scraper.fallback.de_search import _parse_de_fields
        html = "<p>Auftragswert: 5.200.000 EUR</p>"
        fields = _parse_de_fields(html)
        self.assertEqual(fields["value"], 5200000.0)

    def test_de_quantity_extraction(self):
        from src.national_scraper.fallback.de_search import _parse_de_fields
        html = "<p>Menge: 50 Stück</p>"
        fields = _parse_de_fields(html)
        self.assertEqual(fields["quantity"], 50)

    def test_de_winner_extraction(self):
        from src.national_scraper.fallback.de_search import _parse_de_fields
        html = "<p>Zuschlag erteilt an: Acme Defence GmbH</p>"
        fields = _parse_de_fields(html)
        self.assertEqual(fields["winner"], "Acme Defence GmbH")


# ── PL search tests ────────────────────────────────────────────────────────────

class TestPlSearch(unittest.TestCase):

    def _search(self, *args, **kwargs):
        from src.national_scraper.fallback.pl_search import search_pl
        return search_pl(*args, **kwargs)

    def test_buyer_code_extraction(self):
        from src.national_scraper.fallback.pl_search import _build_org_candidates
        candidates = _build_org_candidates(
            buyer="12 Wojskowy Oddział Gospodarczy",
            profile_url="https://platformazakupowa.pl/pn/12wog"
        )
        self.assertIn("12 Wojskowy Oddział Gospodarczy", candidates)

    def test_unknown_buyer_code_generates_wog_name(self):
        from src.national_scraper.fallback.pl_search import _build_org_candidates
        candidates = _build_org_candidates(
            buyer="",
            profile_url="https://platformazakupowa.pl/pn/7wog"
        )
        # Should generate "7 Wojskowy Oddział Gospodarczy"
        self.assertTrue(any("7 Wojskowy" in c for c in candidates))

    def test_match_notice_by_internal_ref(self):
        from src.national_scraper.fallback.pl_search import _match_notice
        items = [
            {"noticeNumber": "D/08/12WOG/2025", "orderObject": "High-capacity transport trailers"},
            {"noticeNumber": "D/07/12WOG/2025", "orderObject": "Vehicles and equipment"},
        ]
        match = _match_notice(items, "D/08/12WOG/2025", ["trailers"])
        self.assertEqual(match["noticeNumber"], "D/08/12WOG/2025")

    def test_match_notice_by_keyword_fallback(self):
        from src.national_scraper.fallback.pl_search import _match_notice
        items = [
            {"noticeNumber": "A/01/2025", "orderObject": "Computers and IT equipment"},
            {"noticeNumber": "A/02/2025", "orderObject": "High-capacity transport trailers SWZ"},
        ]
        match = _match_notice(items, "", ["trailer", "transport"])
        self.assertEqual(match["noticeNumber"], "A/02/2025")

    def test_match_notice_first_result_if_no_match(self):
        from src.national_scraper.fallback.pl_search import _match_notice
        items = [
            {"noticeNumber": "X/01/2025", "orderObject": "Something unrelated"},
        ]
        match = _match_notice(items, "", [])
        self.assertIsNotNone(match)

    @patch("src.national_scraper.fallback.pl_search._api_search")
    @patch("src.national_scraper.fallback.pl_search._fetch_notice_html")
    def test_full_search_returns_document(self, mock_html, mock_api):
        mock_api.return_value = EZAMOWIENIA_SEARCH_RESP
        mock_html.return_value = "Przyczepy o dużej ładowności\nIlość: 20 sztuk\n7.3.1) Zasław Sp. z o.o."
        result = self._search(
            internal_ref="D/08/12WOG/2025",
            buyer="12 Wojskowy Oddział Gospodarczy",
            title_keywords=["trailers", "transport"],
            buyer_profile_url="https://platformazakupowa.pl/pn/12wog",
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result["documents"]), 1)
        doc = result["documents"][0]
        self.assertEqual(doc.source, "PL-BZP")
        self.assertEqual(doc.format, "txt")

    def test_pl_winner_extraction(self):
        from src.national_scraper.fallback.pl_search import _parse_pl_fields
        text = "7.3.1) Nazwa (firma) zamówienia:\nZasław Sp. z o.o.\nWartość: 1530000 PLN"
        fields = _parse_pl_fields(text)
        # winner should be found
        self.assertIn("Zasław", fields.get("winner", ""))

    def test_pl_value_extraction(self):
        from src.national_scraper.fallback.pl_search import _parse_pl_fields
        text = "Wartość zamówienia: 1 530 000 PLN"
        fields = _parse_pl_fields(text)
        self.assertEqual(fields["value"], 1530000.0)

    def test_html_to_text_strips_tags(self):
        from src.national_scraper.fallback.pl_search import _html_to_text
        html = "<p>Hello <b>World</b></p><script>bad()</script>"
        text = _html_to_text(html)
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertNotIn("<b>", text)
        self.assertNotIn("bad()", text)


# ── CZ search tests ────────────────────────────────────────────────────────────

class TestCzSearch(unittest.TestCase):

    def _search(self, *args, **kwargs):
        from src.national_scraper.fallback.cz_search import search_cz
        return search_cz(*args, **kwargs)

    def test_extract_vop_id(self):
        from src.national_scraper.fallback.cz_search import _extract_vop_id
        self.assertEqual(_extract_vop_id("https://verejnezakazky.vop.cz/vz00002751"), "vz00002751")
        self.assertEqual(_extract_vop_id("https://verejnezakazky.vop.cz/vz00002665"), "vz00002665")
        self.assertEqual(_extract_vop_id("https://nen.nipez.cz//profil/MO"), "")

    @patch("src.national_scraper.fallback.cz_search._get_html")
    def test_vop_direct_fetch_parses_fields(self, mock_get):
        mock_get.return_value = VOP_HTML
        result = self._search(
            internal_ref="OVZ/018/3/2025",
            buyer="VOP CZ, s.p.",
            title_keywords=["semi-trailer", "military"],
            tender_documents_url="https://verejnezakazky.vop.cz/vz00002751",
        )
        self.assertIsNotNone(result)
        self.assertIn("vz00002751", result["portal_url"])
        self.assertGreater(len(result["documents"]), 0)
        af = result["additional_fields"]
        self.assertIn("Tatra", af.get("winner", ""))
        self.assertEqual(af["quantity"], 5)

    @patch("src.national_scraper.fallback.cz_search._get_html")
    def test_nen_search_by_internal_ref(self, mock_get):
        def side(sess, url):
            if "query=" in url:
                return NEN_SEARCH_HTML
            if "detail-zakazky" in url:
                return NEN_DETAIL_HTML
            return None

        mock_get.side_effect = side
        result = self._search(
            internal_ref="OVZ/018/3/2025",
            buyer="Ministerstvo obrany",
            title_keywords=["semi-trailer", "military"],
            tender_documents_url="https://nen.nipez.cz//profil/MO",
        )
        self.assertIsNotNone(result)
        self.assertGreater(len(result["documents"]), 0)

    def test_cz_value_extraction(self):
        from src.national_scraper.fallback.cz_search import _parse_cz_fields
        text = "ESTIMATED VALUE (EXCL. VAT)\n85,000,000"
        fields = _parse_cz_fields(text)
        self.assertEqual(fields["value"], 85000000.0)

    def test_cz_quantity_extraction(self):
        from src.national_scraper.fallback.cz_search import _parse_cz_fields
        text = "Počet: 5 ks\nDoba trvání: 24 měsíců"
        fields = _parse_cz_fields(text)
        self.assertEqual(fields["quantity"], 5)
        self.assertEqual(fields["contract_duration"], "24 měsíců")

    def test_cz_winner_extraction(self):
        from src.national_scraper.fallback.cz_search import _parse_cz_fields
        text = "Vybraný dodavatel: Tatra Defence Vehicle a.s."
        fields = _parse_cz_fields(text)
        self.assertIn("Tatra", fields["winner"])

    def test_cz_vop_document_extraction(self):
        from src.national_scraper.fallback.cz_search import _extract_vop_documents
        docs = _extract_vop_documents(VOP_HTML, MagicMock())
        self.assertGreater(len(docs), 0)
        # All should be PDFs
        for d in docs:
            self.assertEqual(d.format, "pdf")

    @patch("src.national_scraper.fallback.cz_search._get_html")
    def test_vop_empty_response_returns_none(self, mock_get):
        mock_get.return_value = None
        result = self._search(
            internal_ref="",
            buyer="VOP CZ",
            title_keywords=["trailer"],
            tender_documents_url="https://verejnezakazky.vop.cz/vz00009999",
        )
        self.assertIsNone(result)

    def test_nen_table_parsing(self):
        from src.national_scraper.fallback.cz_search import _parse_nen_table
        rows = _parse_nen_table(NEN_SEARCH_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sys_num"], "N006/25/V00008153")
        self.assertIn("semi-trailer", rows[0]["title"].lower())


# ── Orchestrator integration tests ────────────────────────────────────────────

class TestOrchestratorFallback(unittest.TestCase):

    def test_infer_country_from_evergabe_url(self):
        from src.document_pipeline.orchestrator import _infer_country_code
        notice = {"_raw": {"_xml": {
            "tender_documents_access": "https://www.evergabe-online.de/tenderdetails.html?id=771723"
        }}}
        self.assertEqual(_infer_country_code(notice), "DE")

    def test_infer_country_from_platformazakupowa(self):
        from src.document_pipeline.orchestrator import _infer_country_code
        notice = {"_raw": {"_xml": {
            "buyer_profile_url_full": "https://platformazakupowa.pl/pn/12wog"
        }}}
        self.assertEqual(_infer_country_code(notice), "PL")

    def test_infer_country_from_vop_url(self):
        from src.document_pipeline.orchestrator import _infer_country_code
        notice = {"_raw": {"_xml": {
            "tender_documents_access": "https://verejnezakazky.vop.cz/vz00002751"
        }}}
        self.assertEqual(_infer_country_code(notice), "CZ")

    def test_infer_country_from_nen_url(self):
        from src.document_pipeline.orchestrator import _infer_country_code
        notice = {"_raw": {"_xml": {
            "tender_documents_access": "https://nen.nipez.cz//profil/MO"
        }}}
        self.assertEqual(_infer_country_code(notice), "CZ")

    def test_infer_country_unknown(self):
        from src.document_pipeline.orchestrator import _infer_country_code
        notice = {"_raw": {}}
        self.assertEqual(_infer_country_code(notice), "")

    def test_title_keywords_extraction(self):
        from src.document_pipeline.orchestrator import _title_keywords
        title = "Germany - Military Cargo Trailers 3.5t and 12.5t"
        kws = _title_keywords(title)
        self.assertIn("Military", kws)
        self.assertIn("Cargo", kws)
        self.assertIn("Trailers", kws)
        # Stop words excluded
        self.assertNotIn("and", kws)
        self.assertLessEqual(len(kws), 5)

    def test_extract_fallback_inputs_de(self):
        from src.document_pipeline.orchestrator import _extract_fallback_inputs
        notice = {
            "tender_id": "682847-2024",
            "title": "Germany - Military Cargo Trailers",
            "_raw": {"_xml": {
                "internal_reference": "Q/U2BP/RA029/NA103",
                "tender_documents_access": "https://www.evergabe-online.de/tenderdetails.html?id=771723",
                "buyer_profile_url_full": "http://www.evergabe-online.de/",
            }},
            "contracting_authority": "BAAINBw",
        }
        inputs = _extract_fallback_inputs(notice)
        self.assertEqual(inputs["internal_ref"], "Q/U2BP/RA029/NA103")
        self.assertEqual(inputs["buyer"], "BAAINBw")
        self.assertIn("Military", inputs["title_keywords"])
        self.assertIn("771723", inputs["tender_documents_url"])

    def test_fallback_merges_winner_into_notice(self):
        from src.document_pipeline.orchestrator import _run_national_fallback
        from src.document_pipeline.discovery import DocumentRef

        fake_doc = DocumentRef(
            url="https://www.evergabe-online.de/tenderdetails.html?id=771723",
            format="html",
            language="DEU",
            title="test.html",
            source="DE-EV",
            tender_id="",
            doc_type="national_page_text",
            extra={"text": "Leistungsverzeichnis content"},
        )
        fake_result = {
            "portal_url": "https://www.evergabe-online.de/tenderdetails.html?id=771723",
            "documents": [fake_doc],
            "additional_fields": {
                "winner": "Acme Defence GmbH",
                "quantity": 50,
                "contract_duration": "48 Monate",
                "value": 5200000.0,
            },
        }

        notice = {
            "tender_id": "682847-2024",
            "_raw": {"_xml": {
                "tender_documents_access": "https://www.evergabe-online.de/tenderdetails.html?id=771723",
            }},
        }

        with patch("src.national_scraper.fallback.de_search.search_de", return_value=fake_result):
            docs = _run_national_fallback(notice, "DE")

        self.assertIsNotNone(docs)
        self.assertEqual(len(docs), 1)
        self.assertEqual(notice["_fallback_winner"], "Acme Defence GmbH")
        self.assertEqual(notice["_fallback_quantity"], 50)
        self.assertEqual(notice["_source_url_national"],
                         "https://www.evergabe-online.de/tenderdetails.html?id=771723")


if __name__ == "__main__":
    unittest.main()

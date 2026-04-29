"""
France Adapter - BOAMP (Bulletin Officiel des Annonces des Marches Publics)

Discovered structure (2026-04-28):
  REST API: https://www.boamp.fr/api/explore/v2.1/catalog/datasets/boamp/records
  - No authentication required
  - OpenDataSoft platform, SQL-like WHERE expressions
  - Offset-based pagination (limit + offset)
  - 1.66M records total

Key filters used:
  perimetre = 'DIRECTIVE-81'   <- notices under defence directive 2009/81/EC
  nomacheteur like '%MINARM%'  <- Ministere des Armees and sub-agencies
  nomacheteur like '%MINDEF%'  <- older MINDEF prefix

Main fields:
  idweb           = notice ID (format: YY-NNNNN)
  objet           = title / subject (searched for trailer keywords)
  nomacheteur     = buyer name (MINARM/DGA/DO/S2A, Marine/DCSSF, etc.)
  dateparution    = publication date (YYYY-MM-DD)
  datelimitereponse = submission deadline (ISO8601)
  titulaire       = winner name (list or None)
  famille         = JOUE (EU threshold) | FNS | MAPA | DSP
  perimetre       = DIRECTIVE-81 for defence procurement
  descripteur_libelle = BOAMP category labels (e.g. 'Vehicules', 'Armement')
  url_avis        = direct link to notice on boamp.fr
  donnees         = full notice JSON (contains value, quantity, etc.)

French defence authority naming in BOAMP:
  MINARM/DGA/DO/S2A              DGA armement
  MINARM/DMAe/SSAM33503          Direction de la Maintenance Aeronautique
  MINDEF/TERRE/SIMMT             Systeme integre maintien materiel terrestre
  Marine/DCSSF/DSSF Toulon       Marine Nationale
  Plate-Forme Affretement        SCA transport arm
  ARM/SCA/PFAF-RBT               Commissariat des Armees

French trailer vocabulary:
  remorque=trailer, semi-remorque=semitrailer, porte-char=tank transporter,
  porte-engins=equipment transporter, surbaissee=low-bed, citerne=tank,
  cuisine roulante=field kitchen, shelter=shelter/module, ampliroll=hook-lift
"""

import re
import time
import json as _json
import logging
import os
from typing import Optional

from ..core import BrowserCore
from ..base_adapter import BaseAdapter, AdapterConfig, SearchResult, NoticeDetail

logger = logging.getLogger(__name__)

BOAMP_API = "https://www.boamp.fr/api/explore/v2.1/catalog/datasets/boamp/records"
BOAMP_NOTICE_URL = "https://www.boamp.fr/pages/avis/?q=idweb:{idweb}"

# Defence authority substrings in nomacheteur field
DEFENCE_ORG_PATTERNS = [
    "MINARM",      # Ministere des Armees (all sub-units)
    "MINDEF",      # Older Ministere de la Defense prefix
    "DMAe",        # Direction de la Maintenance Aeronautique
    "SIMMT",       # Systeme integre maintien materiel terrestre
    "Marine/DC",   # Marine Nationale (DCSSF, DSSF)
    "ARM/SCA",     # Service du Commissariat des Armees
    "Plate-Form",  # Plate-Forme Affretement et Transport (SCA)
    "LSEA",        # Laboratoire du SEA (Service des Essences)
    "SEA/",        # Service des Essences des Armees
    "Armement",    # DGA Armement direct
]

# French trailer vocabulary for objet field search
FR_TRAILER_KEYWORDS = [
    "remorque",
    "semi-remorque",
    "porte-char",
    "porte-engin",
    "surbaissee",
    "citerne",
    "cuisine roulante",
    "shelter",
    "ampliroll",
    "porte-conteneur",
    "remorque militaire",
    "ravitaillement",
    "remorque citerne",
]


def create_fr_config():
    return AdapterConfig(
        country_name="France",
        country_code="FR",
        source_code="FR-BP",
        base_url="https://www.boamp.fr",
        search_url=BOAMP_API,
        language="fr",
        trailer_keywords=FR_TRAILER_KEYWORDS,
        defence_authorities=[
            "Direction Generale de l'Armement",
            "DGA",
            "Direction de la Maintenance Aeronautique",
            "DMAe",
            "SIMMT",
            "Armee de Terre",
            "Marine Nationale",
            "Commissariat des Armees",
            "MINARM",
            "MINDEF",
        ],
        min_interval_seconds=1.0,
    )


class FRAdapter(BaseAdapter):
    """
    France adapter - BOAMP REST API (requests-based, no browser needed).

    Search strategy:
    1. DIRECTIVE-81 + trailer keywords  (most precise: defence directive + trailers)
    2. MINARM/MINDEF authority + trailer keywords  (catches non-DIRECTIVE-81 entries)
    3. Full MINARM authority search  (all MINARM notices, for enrichment of TED entries)

    All three queries deduplicated by idweb.
    """

    def __init__(self, browser: BrowserCore, config: AdapterConfig):
        super().__init__(browser, config)
        self._session = self._build_session()

    def _build_session(self):
        try:
            import requests
            import urllib3
            urllib3.disable_warnings()
        except ImportError:
            logger.error("FR: 'requests' not installed")
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
            "Accept": "application/json",
            "Referer": "https://www.boamp.fr",
        })
        return session

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, keyword: str, max_results: int = 50) -> list:
        """Search BOAMP by keyword in objet field."""
        if not self._session:
            return []
        where = f"objet like '%{keyword}%'"
        return self._api_search(where, max_results)

    def search_all_keywords(self, max_results_per_keyword: int = 30,
                            test_mode: bool = False) -> list:
        """
        Three-phase search strategy:
        1. DIRECTIVE-81 + all trailer keywords (most precise)
        2. MINARM/MINDEF authority + trailer keywords
        3. Full MINARM sweep (for enrichment of existing TED notices)
        """
        if not self._session:
            return []

        all_results: dict = {}  # key = idweb

        # Phase 1: DIRECTIVE-81 + trailer keywords (union of all keywords)
        kw_list = self.config.trailer_keywords[:3] if test_mode else self.config.trailer_keywords
        kw_clause = " or ".join(f"objet like '%{kw}%'" for kw in kw_list)
        d81_where = f"perimetre='DIRECTIVE-81' and ({kw_clause})"
        logger.info("FR: Phase 1 — DIRECTIVE-81 + trailer keywords")
        limit_1 = 20 if test_mode else 200
        for r in self._api_search(d81_where, limit_1):
            key = r.reference_id or r.title[:50]
            if key and key not in all_results:
                all_results[key] = r

        logger.info(f"FR: Phase 1 -> {len(all_results)} results")

        if not test_mode:
            # Phase 2: MINARM/MINDEF authority + trailer keywords
            auth_clause = " or ".join(
                f"nomacheteur like '%{p}%'" for p in ["MINARM", "MINDEF", "Marine/DC", "ARM/SCA"]
            )
            auth_where = f"({auth_clause}) and ({kw_clause})"
            logger.info("FR: Phase 2 — authority + trailer keywords")
            for r in self._api_search(auth_where, 200):
                key = r.reference_id or r.title[:50]
                if key and key not in all_results:
                    all_results[key] = r
            logger.info(f"FR: Phase 2 -> {len(all_results)} total")

            # Phase 3 (full MINARM sweep) removed in sprint6/performance:
            # fetching 538 detail API calls to get only 13 relevant notices is wasteful.
            # Phase 1+2 already covers all DIRECTIVE-81 trailer notices (high precision).

        logger.info(f"FR: search_all_keywords -> {len(all_results)} unique results")
        return list(all_results.values())

    def get_detail(self, result: SearchResult) -> Optional[NoticeDetail]:
        """
        Fetch full notice from BOAMP API by idweb.
        Falls back to constructing detail from SearchResult if API fails.
        """
        if not result.reference_id:
            return self._detail_from_result(result)

        logger.info(f"FR: fetching detail for idweb={result.reference_id}")
        try:
            params = {
                "where": f"idweb='{result.reference_id}'",
                "select": "objet,nomacheteur,dateparution,datelimitereponse,titulaire,url_avis,idweb,donnees,famille,perimetre,descripteur_libelle",
                "limit": 1,
            }
            resp = self._session.get(BOAMP_API, params=params, timeout=20)
            if resp.status_code != 200:
                return self._detail_from_result(result)
            records = resp.json().get("results", [])
            if not records:
                return self._detail_from_result(result)
            return self._record_to_detail(records[0])
        except Exception as e:
            logger.error(f"FR: detail fetch error: {e}")
            return self._detail_from_result(result)

    def filter_defence(self, results: list) -> list:
        """Keep only notices from French defence authorities."""
        kept = []
        defence_patterns = [p.lower() for p in DEFENCE_ORG_PATTERNS]
        extra = ["minarm", "mindef", "dga", "simmt", "dmae", "marine/dc",
                 "arm/sca", "lsea", "sea/", "armees", "armee de terre",
                 "commissariat", "direction generale de l'armement"]
        for r in results:
            auth_lower = (r.authority or "").lower()
            title_lower = (r.title or "").lower()
            snippet_lower = (r.snippet or "").lower()
            all_text = f"{auth_lower} {snippet_lower}"
            is_defence = (
                any(p in all_text for p in defence_patterns)
                or any(p in all_text for p in extra)
                # DIRECTIVE-81 notices are always defence
                or "directive-81" in snippet_lower
                or "directive_81" in snippet_lower
            )
            if is_defence:
                kept.append(r)
        logger.info(f"FR: filter_defence: {len(results)} -> {len(kept)}")
        return kept

    # ------------------------------------------------------------------
    # BOAMP API helpers
    # ------------------------------------------------------------------

    def _api_search(self, where: str, max_results: int = 200) -> list:
        """
        Paginated BOAMP API search. Returns list of SearchResult.
        BOAMP uses offset-based pagination (limit + offset).
        """
        if not self._session:
            return []

        results = []
        seen_idweb = set()
        offset = 0
        limit = min(100, max_results)

        while len(results) < max_results:
            params = {
                "where": where,
                "select": "idweb,objet,nomacheteur,dateparution,url_avis,famille,perimetre,titulaire,datelimitereponse",
                "order_by": "dateparution desc",
                "limit": limit,
                "offset": offset,
            }
            try:
                resp = self._session.get(BOAMP_API, params=params, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"FR API: {resp.status_code} at offset {offset}")
                    break
                data = resp.json()
                total = data.get("total_count", 0)
                records = data.get("results", [])
                if not records:
                    break

                for rec in records:
                    idweb = rec.get("idweb", "")
                    if idweb and idweb in seen_idweb:
                        continue
                    if idweb:
                        seen_idweb.add(idweb)
                    r = self._record_to_search_result(rec)
                    results.append(r)

                logger.debug(
                    f"FR API: offset={offset}, got={len(records)}, "
                    f"total={total}, cumulative={len(results)}"
                )

                if offset + limit >= total or len(records) < limit:
                    break
                offset += limit
                time.sleep(0.3)

            except Exception as e:
                logger.error(f"FR API error at offset {offset}: {e}")
                break

        return results[:max_results]

    def _record_to_search_result(self, rec: dict) -> SearchResult:
        """Convert a BOAMP API record to SearchResult."""
        idweb = rec.get("idweb", "")
        url = rec.get("url_avis", "") or (
            BOAMP_NOTICE_URL.format(idweb=idweb) if idweb else ""
        )
        winner = rec.get("titulaire") or ""
        if isinstance(winner, list):
            winner = ", ".join(str(w) for w in winner if w)
        deadline = str(rec.get("datelimitereponse") or "")[:10]
        famille = rec.get("famille", "")
        perimetre = rec.get("perimetre", "")

        # Store metadata in snippet for filter_defence() and get_detail()
        snippet = _json.dumps({
            "famille": famille,
            "perimetre": perimetre,
            "winner": winner,
            "deadline": deadline,
        }, ensure_ascii=False)[:400]

        return SearchResult(
            title=(rec.get("objet") or "")[:200],
            url=url,
            authority=(rec.get("nomacheteur") or "")[:200],
            reference_id=idweb,
            date=(rec.get("dateparution") or "")[:10],
            snippet=snippet,
        )

    def _record_to_detail(self, rec: dict) -> NoticeDetail:
        """Convert a BOAMP API record (full fields) to NoticeDetail."""
        idweb = rec.get("idweb", "")
        url = rec.get("url_avis", "") or BOAMP_NOTICE_URL.format(idweb=idweb)

        winner = rec.get("titulaire") or ""
        if isinstance(winner, list):
            winner = ", ".join(str(w) for w in winner if w)

        # Extract value/quantity from donnees JSON
        donnees = rec.get("donnees") or {}
        if isinstance(donnees, str):
            try:
                donnees = _json.loads(donnees)
            except Exception:
                donnees = {}

        value, currency = self._extract_value(donnees)
        quantity = self._extract_quantity(donnees)
        description = self._extract_description(donnees, rec.get("objet", ""))
        duration = self._extract_duration(donnees)

        famille = rec.get("famille", "")
        perimetre = rec.get("perimetre", "")
        desc_labels = rec.get("descripteur_libelle") or []
        if isinstance(desc_labels, list):
            desc_labels = ", ".join(str(d) for d in desc_labels)

        raw_text = (
            f"Objet: {rec.get('objet', '')}\n"
            f"Acheteur: {rec.get('nomacheteur', '')}\n"
            f"Famille: {famille} | Perimetre: {perimetre}\n"
            f"Descripteurs: {desc_labels}\n"
            f"Titulaire: {winner}\n"
            f"Description: {description}\n"
        )

        detail = NoticeDetail(
            title=(rec.get("objet") or "")[:200],
            url=url,
            authority=(rec.get("nomacheteur") or "")[:200],
            date=(rec.get("dateparution") or "")[:10],
            deadline=(str(rec.get("datelimitereponse") or ""))[:10],
            winner=winner[:200] if winner else "",
            reference_id=idweb,
            source_code="FR-BP",
            raw_text=raw_text[:8000],
            currency=currency or "EUR",
            value=value,
            quantity=quantity,
            duration=duration,
        )
        detail.description = description[:500] if description else ""
        return detail

    def _detail_from_result(self, result: SearchResult) -> NoticeDetail:
        """Build minimal NoticeDetail from SearchResult when API unavailable."""
        meta = {}
        try:
            meta = _json.loads(result.snippet or "{}")
        except Exception:
            pass
        return NoticeDetail(
            title=result.title,
            url=result.url,
            authority=result.authority,
            date=result.date,
            reference_id=result.reference_id,
            source_code="FR-BP",
            winner=meta.get("winner", ""),
            deadline=meta.get("deadline", ""),
            currency="EUR",
            raw_text=f"{result.title}\n{result.authority}\n{result.snippet}",
        )

    # ------------------------------------------------------------------
    # donnees JSON extraction helpers
    # ------------------------------------------------------------------

    def _extract_value(self, donnees: dict):
        """Extract estimated value and currency from donnees JSON."""
        try:
            # Try common BOAMP donnees paths
            for path in [
                ("CRITERES", "VALEUR_ESTIMEE"),
                ("OBJET", "VALEUR_ESTIMEE"),
                ("ATTRIBUTION", "VALEUR_TOTALE"),
                ("DONNEES", "VALEUR"),
            ]:
                node = donnees
                for key in path:
                    node = node.get(key, {}) if isinstance(node, dict) else {}
                if isinstance(node, dict) and node:
                    val_str = str(node.get("MONTANT", node.get("val", node.get("", "")))).replace(" ", "").replace(",", ".")
                    if val_str and val_str.replace(".", "").isdigit():
                        cur = node.get("DEVISE", node.get("CURRENCY", "EUR"))
                        return float(val_str), str(cur)
                elif isinstance(node, (int, float, str)):
                    val_str = str(node).replace(" ", "").replace(",", ".")
                    if val_str.replace(".", "").isdigit():
                        return float(val_str), "EUR"
        except Exception:
            pass
        return None, "EUR"

    def _extract_quantity(self, donnees: dict) -> Optional[int]:
        """Extract quantity from donnees JSON."""
        try:
            raw = _json.dumps(donnees)
            for pat in [
                r'"QUANTITE"\s*:\s*["\']?(\d+)["\']?',
                r'"QTE"\s*:\s*["\']?(\d+)["\']?',
                r'"NOMBRE"\s*:\s*["\']?(\d+)["\']?',
            ]:
                m = re.search(pat, raw, re.IGNORECASE)
                if m:
                    v = int(m.group(1))
                    if 1 <= v <= 10000:
                        return v
        except Exception:
            pass
        return None

    def _extract_description(self, donnees: dict, fallback: str = "") -> str:
        """Extract longer description from donnees JSON."""
        try:
            raw = _json.dumps(donnees, ensure_ascii=False)
            for pat in [
                r'"DESCRIPTION"\s*:\s*"([^"]{30,500})"',
                r'"OBJET_MARCHE"\s*:\s*"([^"]{30,500})"',
                r'"NATURE_MARCHE"\s*:\s*"([^"]{10,200})"',
            ]:
                m = re.search(pat, raw, re.IGNORECASE)
                if m:
                    return m.group(1)[:500]
        except Exception:
            pass
        return fallback[:500]

    def _extract_duration(self, donnees: dict) -> str:
        """Extract contract duration from donnees JSON."""
        try:
            raw = _json.dumps(donnees)
            for pat in [
                r'"DUREE_MARCHE"\s*:\s*["\']?(\d+[^"\']{0,20})["\']?',
                r'"DUREE"\s*:\s*["\']?(\d+[^"\']{0,20})["\']?',
            ]:
                m = re.search(pat, raw, re.IGNORECASE)
                if m:
                    return m.group(1)[:80]
        except Exception:
            pass
        return ""

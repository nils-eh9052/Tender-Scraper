"""
Phase 1: Index Builder – Collect AND fetch all notice data from TED in one pass.

Since v1.3: The search API returns ALL fields we need directly in the bulk
query. This makes Phase 2 (Detail Fetcher) unnecessary. All detail data is
saved as individual JSON files during indexing.

Strategy:
1. Run multiple search queries (one per CPV tier + defence directive + text)
2. Deduplicate results by publication-number
3. Save each notice as individual JSON in details/ (crash-safe)
4. Save index summary
5. Support checkpoint/resume for interrupted runs
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from .api_client import TedApiClient, ALL_FIELDS
from .detail_fetcher import DetailFetcher

logger = logging.getLogger(__name__)

FORCE_INCLUDE_PATH = Path(__file__).parent.parent / "config" / "force_include.json"


class IndexBuilder:
    """Builds a comprehensive index and fetches all detail data in one pass."""

    def __init__(self, config: dict, output_dir: str = "data/raw"):
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.details_dir = self.output_dir / "details"
        self.details_dir.mkdir(parents=True, exist_ok=True)
        self.client = TedApiClient(config)
        self.detail_fetcher = DetailFetcher(config, raw_dir=str(self.output_dir))
        self.checkpoint_file = Path(config.get("output", {}).get(
            "checkpoint_file", "data/.checkpoint.json"))
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_checkpoint(self) -> dict:
        if self.checkpoint_file.exists():
            with open(self.checkpoint_file, "r") as f:
                return json.load(f)
        return {"completed_queries": [], "notice_ids": []}

    def _save_checkpoint(self, checkpoint: dict):
        with open(self.checkpoint_file, "w") as f:
            json.dump(checkpoint, f, indent=2)

    def _save_detail(self, notice_id: str, data: dict):
        """Save normalized notice as individual JSON file."""
        safe_id = notice_id.replace("/", "_").replace("\\", "_")
        path = self.details_dir / f"{safe_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _build_search_queries(self) -> list[dict]:
        """Build all search queries."""
        queries = []
        search_cfg = self.config.get("search", {})
        cpv_cfg = self.config.get("cpv_codes", {})
        legal_cfg = self.config.get("legal_basis", {})

        date_from = search_cfg.get("date_from", "2015-01-01")
        date_to = search_cfg.get("date_to", "2026-04-13")

        tier1_cpvs = cpv_cfg.get("tier1_trailer_direct", [])
        tier2_cpvs = cpv_cfg.get("tier2_defence_vehicles", [])
        tier3_cpvs = cpv_cfg.get("tier3_transport_broad", [])

        # ── Query 1: Defence directive + Trailer CPVs ──
        if tier1_cpvs:
            queries.append({
                "name": "defence_directive_trailer_cpv",
                "description": "Trailer CPVs under defence directive 2009/81",
                "payload": self.client.build_query(
                    cpv_codes=tier1_cpvs,
                    legal_basis=legal_cfg.get("defence_directive"),
                    date_from=date_from, date_to=date_to
                )
            })

        # ── Query 2: Defence directive + Military vehicle CPVs ──
        if tier2_cpvs:
            queries.append({
                "name": "defence_directive_military_vehicles",
                "description": "Military vehicle CPVs under defence directive",
                "payload": self.client.build_query(
                    cpv_codes=tier2_cpvs,
                    legal_basis=legal_cfg.get("defence_directive"),
                    date_from=date_from, date_to=date_to
                )
            })

        # ── Query 3: Defence directive + broad transport CPVs ──
        if tier3_cpvs:
            queries.append({
                "name": "defence_directive_transport",
                "description": "Broad transport CPVs under defence directive",
                "payload": self.client.build_query(
                    cpv_codes=tier3_cpvs,
                    legal_basis=legal_cfg.get("defence_directive"),
                    date_from=date_from, date_to=date_to
                )
            })

        # ── Query 4: Trailer CPVs under general directives ──
        for directive in legal_cfg.get("general_directives", []):
            queries.append({
                "name": f"general_{directive}_trailer_cpv",
                "description": f"Trailer CPVs under {directive}",
                "payload": self.client.build_query(
                    cpv_codes=tier1_cpvs,
                    legal_basis=directive,
                    date_from=date_from, date_to=date_to
                )
            })

        # ── Query 5: ALL Trailer CPVs (no legal basis filter) ──
        if tier1_cpvs:
            queries.append({
                "name": "all_trailer_cpv_no_filter",
                "description": "All trailer CPVs (no legal basis filter)",
                "payload": self.client.build_query(
                    cpv_codes=tier1_cpvs,
                    date_from=date_from, date_to=date_to
                )
            })

        # ── Query 6: Text-based search ──
        text_terms = [
            'FT~"military trailer" OR FT~"defence trailer" OR FT~"Militäranhänger"',
            'FT~"low-bed trailer" OR FT~"Tieflader" OR FT~"remorque surbaissée"',
            'FT~"hook-lift" OR FT~"Hakenladegerät"',
            'FT~"mission module" OR FT~"Missionsmodul"',
            'FT~"cargo trailer" OR FT~"Lastanhänger" OR FT~"off-road trailer"',
            # Military-specific loading systems (Sprint 9b)
            'FT~"DROPS" OR FT~"EPLS" OR FT~"Wechselladersystem" OR FT~"Palletized Load System"',
            'FT~"Panzertransportanhänger" OR FT~"tank transport trailer" OR FT~"armoured vehicle trailer"',
            'FT~"Munitionsanhänger" OR FT~"ammunition trailer" OR FT~"remorque munitions"',
            'FT~"Feldküche" OR FT~"field kitchen" OR FT~"cuisine de campagne"',
        ]
        for i, term in enumerate(text_terms):
            queries.append({
                "name": f"text_search_{i}",
                "description": f"Text search: {term[:60]}...",
                "payload": self.client.build_query(
                    cpv_codes=[], text_query=term,
                    date_from=date_from, date_to=date_to
                )
            })

        return queries

    def build_index(self, max_pages_per_query: Optional[int] = None) -> dict:
        """
        Run all search queries, deduplicate, normalize, and save details.

        This replaces both the old Phase 1 (index) AND Phase 2 (details).
        All data is fetched in bulk from the search API with ALL_FIELDS.
        """
        checkpoint = self._load_checkpoint()
        completed = set(checkpoint.get("completed_queries", []))
        all_notice_ids = set(checkpoint.get("notice_ids", []))

        # Check already-saved detail files for resume
        already_saved = {f.stem for f in self.details_dir.glob("*.json")}

        queries = self._build_search_queries()
        logger.info(f"Built {len(queries)} search queries. "
                     f"{len(completed)} already completed. "
                     f"{len(already_saved)} details already on disk.")

        new_saved = 0

        for query in queries:
            if query["name"] in completed:
                logger.info(f"Skipping completed query: {query['name']}")
                continue

            logger.info(f"\n{'='*60}")
            logger.info(f"Running query: {query['name']}")
            logger.info(f"Description: {query['description']}")
            logger.info(f"{'='*60}")

            results = self.client.search_all_pages(
                query["payload"],
                max_pages=max_pages_per_query
            )

            # Deduplicate, normalize, and save
            new_count = 0
            for notice in results:
                nid = notice.get("publication-number", "")
                if not nid or nid in all_notice_ids:
                    continue

                all_notice_ids.add(nid)
                new_count += 1

                # Normalize and save detail JSON immediately
                if nid not in already_saved:
                    normalized = self.detail_fetcher._normalize_notice(notice, nid)
                    self._save_detail(nid, normalized)
                    already_saved.add(nid)
                    new_saved += 1

            logger.info(f"Query '{query['name']}': {len(results)} results, "
                        f"{new_count} new (total unique: {len(all_notice_ids)}, "
                        f"saved: {new_saved})")

            # Checkpoint after each query
            completed.add(query["name"])
            checkpoint["completed_queries"] = list(completed)
            checkpoint["notice_ids"] = list(all_notice_ids)
            self._save_checkpoint(checkpoint)

        # Save index summary (lightweight, no full notice data)
        index = {
            "metadata": {
                "created_at": datetime.utcnow().isoformat(),
                "total_notices": len(all_notice_ids),
                "total_details_saved": len(already_saved),
                "queries_run": len(queries),
                "config_date_range": {
                    "from": self.config.get("search", {}).get("date_from"),
                    "to": self.config.get("search", {}).get("date_to")
                }
            },
            "notices": {nid: None for nid in all_notice_ids}
        }

        index_path = self.output_dir / "notice_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        logger.info(f"Index saved: {index_path} ({len(all_notice_ids)} notices, "
                     f"{new_saved} new details saved)")

        return index

    def fetch_force_include(self) -> int:
        """
        Fetch notices listed in config/force_include.json that are not yet on disk.

        Returns count of newly fetched notices.
        """
        if not FORCE_INCLUDE_PATH.exists():
            logger.info("No force_include.json found, skipping.")
            return 0

        with open(FORCE_INCLUDE_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        ids = cfg.get("force_include_ids", [])
        if not ids:
            return 0

        already_saved = {f.stem for f in self.details_dir.glob("*.json")}
        fetched_count = 0

        for notice_id in ids:
            safe_id = notice_id.replace("/", "_").replace("\\", "_")
            if safe_id in already_saved:
                logger.info(f"Force-include: {notice_id} already on disk, skipping.")
                continue

            logger.info(f"Force-include: fetching {notice_id} ...")
            raw = self.client.get_notice_detail(notice_id)
            if raw:
                normalized = self.detail_fetcher._normalize_notice(raw, notice_id)
                self._save_detail(notice_id, normalized)
                already_saved.add(safe_id)
                fetched_count += 1
                logger.info(f"Force-include: saved {notice_id}")
            else:
                logger.warning(f"Force-include: failed to fetch {notice_id}")

        logger.info(f"Force-include: fetched {fetched_count} new notices "
                    f"(out of {len(ids)} in list)")
        return fetched_count

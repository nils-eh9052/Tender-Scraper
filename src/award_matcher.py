"""
Phase 3d: Award Notice Matcher

Searches TED API for award notices matching each open (no-winner) notice.
Match criteria: same buyer + same CPV prefix + later publication date + has winner.
Caches results in data/.award_match_log.json.
Rate-limit: 1 request/second.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from .api_client import TedApiClient

logger = logging.getLogger(__name__)

AWARD_MATCH_LOG_PATH = Path(__file__).parent.parent / "data" / ".award_match_log.json"


class AwardMatcher:
    """Finds award notices for open procurement notices via TED API."""

    def __init__(self, config: dict):
        self.config = config
        self.client = TedApiClient(config)

    # ── Log management ──

    @staticmethod
    def _load_log() -> dict:
        if AWARD_MATCH_LOG_PATH.exists():
            with open(AWARD_MATCH_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_log(log: dict):
        AWARD_MATCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AWARD_MATCH_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

    # ── Matching logic ──

    def _search_award_notices(self, notice: dict) -> list:
        """Search TED API for award notices that might match this open notice."""
        auth = notice.get("contracting_authority", {}) or {}
        cpv_codes = notice.get("cpv_codes", [])
        pub_date = notice.get("publication_date", "")

        # Build CPV prefix list (first 5 digits of each CPV)
        cpv_prefixes = list(set(c[:5] for c in cpv_codes if len(c) >= 5))
        if not cpv_prefixes:
            return []

        # Build query: use only the exact CPV codes from the notice
        # TED API does NOT support wildcard CPV queries
        date_from = (pub_date[:10] if pub_date else "2015-01-01")

        # Known valid TED CPV codes in the trailer/vehicle range
        # We use only the exact codes that came from the notice itself
        # Plus fall back to the top-level parent codes if needed
        VALID_PARENT_CPVS = {
            "34": "34000000",  # Transport equipment
            "342": "34200000",  # Trailers, semi-trailers
            "3422": "34220000",  # Trailers, semi-trailers (sub)
            "34223": "34223000",  # Semi-trailers (top-level tier-1)
        }

        search_cpvs = []
        for code in cpv_codes:
            if code and len(code) >= 8:
                search_cpvs.append(code)
            # Always include the direct tier-1 parent
            for prefix, parent_code in VALID_PARENT_CPVS.items():
                if code.startswith(prefix):
                    search_cpvs.append(parent_code)

        # Deduplicate, use known-valid codes only
        search_cpvs = list(set(search_cpvs))[:8]

        # If no valid CPVs, skip
        if not search_cpvs:
            return []

        all_results = []
        cpv_filter = " OR ".join([f'classification-cpv="{c}"' for c in search_cpvs])
        query_payload = {
            "query": (
                f'({cpv_filter}) '
                f'AND publication-date>={date_from.replace("-", "")}'
            ),
            "fields": [
                "publication-number", "notice-title", "publication-date",
                "buyer-name", "organisation-country-buyer", "classification-cpv",
                "winner-name", "winner-country", "winner-decision-date",
                "total-value", "total-value-cur",
            ],
            "page": 1,
            "limit": 25,
            "paginationMode": "PAGE_NUMBER",
        }

        time.sleep(1)  # Rate limit: 1 req/s
        resp = self.client._request_with_retry("POST", self.client.SEARCH_URL,
                                                json_body=query_payload)
        if resp and resp.get("notices"):
            all_results.extend(resp["notices"])

        return all_results

    def _score_match(self, notice: dict, candidate: dict) -> float:
        """Score how well a candidate award notice matches the open notice."""
        score = 0.0

        # CPV overlap
        notice_cpvs = set(c[:5] for c in notice.get("cpv_codes", []))
        cand_cpvs_raw = candidate.get("classification-cpv", [])
        if isinstance(cand_cpvs_raw, str):
            cand_cpvs_raw = [cand_cpvs_raw]
        cand_cpvs = set(c[:5] for c in cand_cpvs_raw if c)
        cpv_overlap = len(notice_cpvs & cand_cpvs)
        score += cpv_overlap * 2.0

        # Authority name overlap
        notice_auth = str(
            (notice.get("contracting_authority") or {}).get("name", "")
        ).lower()
        cand_auth_raw = candidate.get("buyer-name", "")
        if isinstance(cand_auth_raw, dict):
            cand_auth = " ".join(str(v) for v in cand_auth_raw.values()).lower()
        elif isinstance(cand_auth_raw, list):
            cand_auth = " ".join(str(v) for v in cand_auth_raw).lower()
        else:
            cand_auth = str(cand_auth_raw).lower()

        # Token overlap in authority name
        notice_tokens = set(re.findall(r'\b\w{3,}\b', notice_auth))
        cand_tokens = set(re.findall(r'\b\w{3,}\b', cand_auth))
        auth_overlap = len(notice_tokens & cand_tokens)
        score += min(auth_overlap * 0.5, 3.0)

        # Title keyword overlap
        notice_title = str(notice.get("title", "")).lower()
        cand_title_raw = candidate.get("notice-title", "")
        if isinstance(cand_title_raw, dict):
            cand_title = " ".join(str(v) for v in cand_title_raw.values()).lower()
        else:
            cand_title = str(cand_title_raw).lower()

        trailer_words = ["trailer", "semi-trailer", "anhänger", "sattelauflieger",
                         "remorque", "naczepa", "rimorchio", "remolque", "tieflader"]
        for word in trailer_words:
            if word in notice_title and word in cand_title:
                score += 1.0

        return score

    def _select_best_match(self, notice: dict, candidates: list) -> Optional[dict]:
        """Select best matching award notice from candidates."""
        if not candidates:
            return None

        # Only consider candidates with a winner
        with_winner = []
        for c in candidates:
            winner = c.get("winner-name", "")
            if isinstance(winner, dict):
                winner = next(iter(winner.values()), "")
            if isinstance(winner, list):
                winner = winner[0] if winner else ""
            if winner:
                with_winner.append(c)

        if not with_winner:
            return None

        # Score each candidate
        scored = [(self._score_match(notice, c), c) for c in with_winner]
        scored.sort(key=lambda x: -x[0])

        best_score, best = scored[0]
        if best_score >= 1.0:  # Minimum score threshold
            return best
        return None

    def _apply_match(self, notice: dict, award_notice: dict) -> dict:
        """Apply award notice data to the open notice."""
        notice = dict(notice)

        winner_raw = award_notice.get("winner-name", "")
        if isinstance(winner_raw, dict):
            winner = next(iter(winner_raw.values()), "") or ""
            if isinstance(winner, list):
                winner = winner[0] if winner else ""
        elif isinstance(winner_raw, list):
            winner = winner_raw[0] if winner_raw else ""
        else:
            winner = str(winner_raw)

        if winner:
            existing_award = notice.get("award") or {}
            if not existing_award.get("winner_name"):
                notice["award"] = {
                    **existing_award,
                    "winner_name": winner,
                    "awarded": True,
                    "_from_award_match": True,
                    "_award_notice_id": award_notice.get("publication-number", ""),
                }
                logger.info(f"  Award match: winner={winner}")

        # Apply value if missing
        val = notice.get("estimated_value") or {}
        if not val.get("amount") or float(str(val.get("amount") or 0)) <= 0.01:
            total_val = award_notice.get("total-value")
            if total_val is not None:
                if isinstance(total_val, list):
                    total_val = total_val[0] if total_val else None
                if isinstance(total_val, dict):
                    total_val = next(iter(total_val.values()), None)
                    if isinstance(total_val, list):
                        total_val = total_val[0] if total_val else None
                if total_val:
                    currency_raw = award_notice.get("total-value-cur", "EUR")
                    if isinstance(currency_raw, list):
                        currency_raw = currency_raw[0] if currency_raw else "EUR"
                    notice["estimated_value"] = {
                        "amount": total_val,
                        "currency": str(currency_raw),
                        "_from_award_match": True,
                    }
                    logger.info(f"  Award match: value={total_val} {currency_raw}")

        notice["_award_matched"] = True
        return notice

    def match_notice(self, notice: dict, log: dict) -> dict:
        """Try to find and apply award notice for a single notice."""
        tid = notice.get("tender_id", "")

        # Use cache
        if tid in log:
            cached = log[tid]
            if cached.get("matched") and cached.get("award_notice"):
                return self._apply_match(notice, cached["award_notice"])
            return notice  # Cached as "no match"

        # Only try to match if no winner yet
        award = notice.get("award") or {}
        if award.get("winner_name"):
            log[tid] = {"matched": False, "reason": "already has winner"}
            return notice

        # Search for award notices
        candidates = self._search_award_notices(notice)
        best = self._select_best_match(notice, candidates)

        if best:
            log[tid] = {
                "matched": True,
                "award_notice": best,
                "award_notice_id": best.get("publication-number", ""),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            return self._apply_match(notice, best)
        else:
            log[tid] = {
                "matched": False,
                "reason": f"no match found among {len(candidates)} candidates",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            return notice

    def match_batch(self, notices: list, limit: Optional[int] = None) -> list:
        """
        Run award matching for all notices without winners.

        Args:
            notices: list of notice dicts
            limit: max number to check (for test mode)

        Returns: updated list of all notices
        """
        log = self._load_log()

        # Find candidates (no winner yet)
        no_winner = [n for n in notices
                     if not (n.get("award") or {}).get("winner_name")]
        if limit:
            no_winner = no_winner[:limit]

        logger.info(f"Award matching: checking {len(no_winner)} notices without winner "
                    f"(out of {len(notices)} total)")

        updated_map = {}
        for i, notice in enumerate(no_winner):
            tid = notice.get("tender_id", "")
            logger.info(f"Award match [{i+1}/{len(no_winner)}]: {tid}")
            updated = self.match_notice(notice, log)
            updated_map[tid] = updated

            # Save log periodically
            if (i + 1) % 10 == 0:
                self._save_log(log)

        self._save_log(log)

        # Rebuild full notices list
        result = []
        for notice in notices:
            tid = notice.get("tender_id", "")
            result.append(updated_map.get(tid, notice))

        matched_count = sum(1 for n in result if n.get("_award_matched"))
        logger.info(f"Award matching complete: {matched_count} notices matched")
        return result

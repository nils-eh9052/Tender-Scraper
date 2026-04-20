"""
Phase 3: Filter Engine – Score, classify, and filter notices.

Pipeline:
1. Load all fetched notice details
2. Apply keyword matching (multilingual)
3. Calculate relevance scores
4. Classify trailer category
5. Extract quantities where possible
6. Save filtered results with scores
"""

import json
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FilterEngine:
    """Scores and classifies notices based on keyword matching and CPV codes."""

    def __init__(self, config: dict):
        self.config = config
        self.keywords = config.get("keywords", {})
        self.scoring = config.get("scoring", {})
        self.weights = self.scoring.get("weights", {})
        self.cpv_codes = config.get("cpv_codes", {})

        # Build flat keyword lookup: category -> list of all keywords (all languages)
        self._keyword_index = self._build_keyword_index()

        # Build CPV lookup: code -> tier
        self._cpv_tier = self._build_cpv_tier_lookup()

    def _build_keyword_index(self) -> dict[str, list[str]]:
        """Flatten multilingual keywords into category -> [keywords]."""
        index = {}
        for category, langs in self.keywords.items():
            all_kw = []
            if isinstance(langs, dict):
                for lang, words in langs.items():
                    all_kw.extend([w.lower() for w in words])
            index[category] = all_kw
        return index

    def _build_cpv_tier_lookup(self) -> dict[str, str]:
        """Map each CPV code to its tier."""
        lookup = {}
        for tier_name, codes in self.cpv_codes.items():
            for code in codes:
                lookup[code] = tier_name
        return lookup

    def _get_searchable_text(self, notice: dict) -> str:
        """Extract all text content from a notice for keyword matching."""
        parts = []

        # Direct fields
        for field in ["title", "description"]:
            val = notice.get(field)
            if isinstance(val, str):
                parts.append(val)
            elif isinstance(val, dict):
                # Multilingual: {"en": "...", "de": "..."}
                parts.extend(str(v) for v in val.values())

        # Raw data deep search
        raw = notice.get("_raw", {})
        parts.append(self._deep_text_extract(raw))

        return " ".join(parts).lower()

    def _deep_text_extract(self, obj, max_depth: int = 5) -> str:
        """Recursively extract all string values from nested dict/list."""
        if max_depth <= 0:
            return ""
        parts = []
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                parts.append(self._deep_text_extract(v, max_depth - 1))
        elif isinstance(obj, list):
            for item in obj:
                parts.append(self._deep_text_extract(item, max_depth - 1))
        return " ".join(parts)

    def _get_title_text(self, notice: dict) -> str:
        """Extract title text specifically (for title bonus scoring)."""
        title = notice.get("title", "")
        if isinstance(title, dict):
            return " ".join(str(v) for v in title.values()).lower()
        return str(title).lower()

    def score_notice(self, notice: dict) -> dict:
        """
        Calculate a relevance score for a notice.

        Returns dict with:
            - total_score: int
            - score_breakdown: dict explaining each score component
            - matched_categories: list of detected trailer categories
            - matched_keywords: list of matched keywords
            - is_defence: bool
        """
        text = self._get_searchable_text(notice)
        title_text = self._get_title_text(notice)
        cpv_codes = notice.get("cpv_codes", [])

        score = 0
        breakdown = {}
        matched_keywords = []
        matched_categories = []

        # ── CPV Code Scoring ──
        for code in cpv_codes:
            # Check exact match and prefix match (34223 matches 34223000)
            for stored_code, tier in self._cpv_tier.items():
                if code.startswith(stored_code[:5]) or stored_code.startswith(code[:5]):
                    if "tier1" in tier:
                        pts = self.weights.get("cpv_tier1_match", 30)
                        score += pts
                        breakdown[f"cpv_tier1_{code}"] = pts
                    elif "tier2" in tier:
                        pts = self.weights.get("cpv_tier2_match", 20)
                        score += pts
                        breakdown[f"cpv_tier2_{code}"] = pts
                    elif "tier3" in tier:
                        pts = self.weights.get("cpv_tier3_match", 5)
                        score += pts
                        breakdown[f"cpv_tier3_{code}"] = pts
                    break

        # ── Legal Basis Scoring ──
        legal = notice.get("legal_basis", "")
        defence_dir = self.config.get("legal_basis", {}).get(
            "defence_directive", "")
        if defence_dir and defence_dir in str(legal):
            pts = self.weights.get("defence_directive", 25)
            score += pts
            breakdown["defence_directive"] = pts

        # ── Keyword Scoring (per category) ──
        trailer_categories = [
            "low_bed", "semitrailer", "dolly", "tank_trailer",
            "mission_module", "loading_system", "special_purpose"
        ]

        for category in trailer_categories:
            kws = self._keyword_index.get(category, [])
            for kw in kws:
                if kw in text:
                    pts = self.weights.get("keyword_category_match", 15)
                    score += pts
                    breakdown[f"kw_{category}_{kw}"] = pts
                    matched_keywords.append(kw)
                    if category not in matched_categories:
                        matched_categories.append(category)

                    # Title bonus
                    if kw in title_text:
                        bonus = self.weights.get("title_match_bonus", 10)
                        score += bonus
                        breakdown[f"title_bonus_{kw}"] = bonus
                    break  # Only count each category once

        # ── Generic Trailer Keywords ──
        generic_kws = self._keyword_index.get("generic_trailer", [])
        generic_matched = False
        for kw in generic_kws:
            if kw in text:
                if not generic_matched:
                    pts = self.weights.get("keyword_generic_trailer", 5)
                    score += pts
                    breakdown[f"generic_trailer_{kw}"] = pts
                    matched_keywords.append(kw)
                    generic_matched = True
                break

        # ── Defence Context Words ──
        defence_kws = self._keyword_index.get("defence_context", [])
        is_defence = False
        for kw in defence_kws:
            if kw in text:
                if not is_defence:
                    pts = self.weights.get("defence_context_word", 10)
                    score += pts
                    breakdown[f"defence_context_{kw}"] = pts
                    matched_keywords.append(kw)
                    is_defence = True
                break

        return {
            "total_score": score,
            "score_breakdown": breakdown,
            "matched_categories": matched_categories,
            "matched_keywords": matched_keywords,
            "is_defence": is_defence,
        }

    def detect_quantity(self, notice: dict) -> Optional[dict]:
        """
        Extract quantity from notice text.

        Handles German thousand separators (4.600 = 4600) and common patterns:
            - "4.600 Anhängern", "54 remorques", "12 units"
            - "bis zu 4.600", "up to 500 trailers"
            - "quantity: 12" / "Menge: 12"
        """
        text = self._get_searchable_text(notice)

        def parse_german_number(s: str) -> int:
            """Parse number with German thousand separator: 4.600 -> 4600"""
            s = s.strip().replace(' ', '')
            # German: 4.600 (dot = thousand sep) vs English: 4,600
            # If it has dots followed by exactly 3 digits, treat as thousand sep
            if re.match(r'^\d{1,3}(\.\d{3})+$', s):
                return int(s.replace('.', ''))
            if re.match(r'^\d{1,3}(,\d{3})+$', s):
                return int(s.replace(',', ''))
            return int(s)

        # Patterns — group 1 = number (may include thousand separators)
        patterns = [
            # "bis zu 4.600 Anhängern" / "up to 500 trailers"
            (r'(?:bis zu|up to|jusqu.{1,3}à|fino a)\s+([\d.,]+)\s+(?:anhänger|trailer|remorque|rimorchi|przycze)',
             'up_to_N_trailer'),
            # "4.600 Anhängern" / "54 remorques" — number + trailer word
            (r'([\d.,]+)\s+(?:anhänger|trailer|remorque|semi-trailer|sattelanhänger|przycze|rimorchi|påhängsvogn)',
             'N_trailer'),
            # "12 Stück/units"
            (r'([\d.,]+)\s*(?:stück|units?|pièces?|items?|stk\.?|pcs\.?|stuks?|szt\.?)',
             'N_units'),
            # "quantity: 12"
            (r'(?:quantity|menge|quantité|cantidad|antal)\s*[:=]\s*([\d.,]+)',
             'quantity_field'),
            # "5x trailer"
            (r'([\d.,]+)\s*[xX×]\s+(?:anhänger|trailer|remorque)',
             'Nx_trailer'),
        ]

        for pattern, source in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    qty = parse_german_number(match.group(1))
                    if 1 <= qty <= 100000:
                        return {
                            "quantity": qty,
                            "source": source,
                            "pattern_matched": pattern[:40],
                            "context": text[max(0, match.start()-30):match.end()+30]
                        }
                except (ValueError, IndexError):
                    continue
        return None

    def _is_defence_notice(self, notice: dict, score_result: dict) -> bool:
        """
        Strict defence check: notice must have defence directive OR
        defence context keywords in text.
        """
        # Check legal basis
        legal = str(notice.get("legal_basis", ""))
        defence_dir = self.config.get("legal_basis", {}).get("defence_directive", "")
        if defence_dir and defence_dir in legal:
            return True

        # Check if defence keywords matched
        if score_result.get("is_defence"):
            return True

        # Check authority name for defence indicators
        auth_name = str(
            (notice.get("contracting_authority") or {}).get("name", "")
        ).lower()
        defence_auth_terms = [
            "defense", "defence", "ministry of defence", "verteidigung",
            "bundeswehr", "militär", "military", "armed forces",
            "streitkräfte", "défense", "difesa", "armée", "army",
            "navy", "marine", "air force", "luftwaffe", "mod ",
            "forces armées", "bwfuhrpark", "baindir", "nato",
        ]
        for term in defence_auth_terms:
            if term in auth_name:
                return True

        return False

    @staticmethod
    def _extract_base_tender_id(tender_id: str) -> str:
        """
        Extract base tender reference for deduplication.
        TED publishes multiple notices per tender (announcement, result, etc).
        The publication-number format is typically NNNNNN-YYYY.
        Related notices share similar titles/CPV/authority.
        """
        return tender_id.strip()

    def _deduplicate(self, notices: list[dict]) -> list[dict]:
        """
        Deduplicate notices: prefer award/result notices over announcements.
        Groups by (authority + CPV + title-prefix) and keeps the latest or
        the one with a winner.
        """
        from collections import defaultdict

        groups = defaultdict(list)
        for n in notices:
            # Build grouping key from authority + first CPV + title prefix + year
            auth = str((n.get("contracting_authority") or {}).get("name", "")).lower()[:30]
            cpvs = sorted(n.get("cpv_codes", []))[:2]
            cpv_key = ",".join(cpvs)
            title = str(n.get("title", "")).lower()[:40]
            # Include publication year so notices from different years are NOT duplicates
            pub_date = str(n.get("publication_date", "") or "")
            pub_year = pub_date[:4] if len(pub_date) >= 4 else "unknown"
            group_key = f"{auth}|{cpv_key}|{title}|{pub_year}"
            groups[group_key].append(n)

        deduped = []
        for key, group in groups.items():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            # Prefer notice with winner (= result/award)
            with_winner = [n for n in group if (n.get("award") or {}).get("winner_name")]
            if with_winner:
                # Take most recent award notice
                with_winner.sort(key=lambda n: n.get("publication_date", ""), reverse=True)
                deduped.append(with_winner[0])
            else:
                # No winner yet: take latest publication
                group.sort(key=lambda n: n.get("publication_date", ""), reverse=True)
                deduped.append(group[0])

        logger.info(f"Deduplication: {len(notices)} -> {len(deduped)} "
                     f"(removed {len(notices) - len(deduped)} duplicates)")
        return deduped

    @staticmethod
    def shorten_authority(name: str) -> str:
        """
        Shorten authority name to the relevant organization.
        Removes verbose legal text, addresses, generic descriptions.
        """
        if not name:
            return ""

        # Common patterns to strip: "Auftraggeber sind die ...", "vertreten durch ..."
        import re

        # Take first meaningful sentence/clause
        # Split on common delimiters
        for sep in [", vertreten durch", ", diese vertreten",
                    "; Anschrift:", " – ", " - Abteilung"]:
            if sep in name:
                name = name.split(sep)[0]

        # Remove leading filler
        prefixes_to_strip = [
            r"^Auftraggeber\s+(sind|ist)\s+(die|der|das)\s+",
            r"^(Die|Der|Das)\s+Auftraggeber(in)?\s+(ist|sind)\s+",
        ]
        for pat in prefixes_to_strip:
            name = re.sub(pat, "", name, flags=re.IGNORECASE)

        # Truncate at reasonable length
        if len(name) > 80:
            # Try to cut at a natural boundary
            for cutoff in [", ", " (", " /", " –"]:
                idx = name.find(cutoff, 30)
                if 30 < idx < 80:
                    name = name[:idx]
                    break
            else:
                name = name[:80].rsplit(" ", 1)[0]

        return name.strip().rstrip(",;.")

    def filter_and_score_all(self, details_dir: str = "data/raw/details",
                              output_dir: str = "data/filtered") -> dict:
        """
        Process all fetched notices: score, classify, filter.

        Applies:
        - Relevance scoring
        - STRICT defence-only filter
        - Deduplication (prefer award/result over announcement)
        - Authority name shortening

        Returns summary statistics.
        """
        details_path = Path(details_dir)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        threshold_relevant = self.scoring.get("threshold_relevant", 25)
        threshold_high = self.scoring.get("threshold_high_confidence", 50)

        all_scored = []
        relevant = []
        high_confidence = []
        stats = {
            "total_processed": 0,
            "total_relevant": 0,
            "total_high_confidence": 0,
            "total_defence": 0,
            "total_non_defence_skipped": 0,
            "total_deduped": 0,
            "by_category": {},
            "by_country": {},
            "score_distribution": {},
        }

        # Process each notice
        for json_file in sorted(details_path.glob("*.json")):
            notice = json.load(open(json_file, "r", encoding="utf-8"))

            if notice.get("_fetch_failed"):
                continue

            stats["total_processed"] += 1

            # Score
            score_result = self.score_notice(notice)
            notice["_scoring"] = score_result

            # Strict defence filter
            is_defence = self._is_defence_notice(notice, score_result)
            if not is_defence:
                stats["total_non_defence_skipped"] += 1
                continue

            stats["total_defence"] += 1

            # Shorten authority name
            auth = notice.get("contracting_authority") or {}
            if auth.get("name"):
                auth["name_short"] = self.shorten_authority(auth["name"])

            # Detect quantity
            qty = self.detect_quantity(notice)
            if qty:
                notice["_quantity"] = qty

            # Build enriched record
            enriched = {
                **notice,
                "relevance_score": score_result["total_score"],
                "trailer_categories": score_result["matched_categories"],
                "is_defence": True,
            }

            all_scored.append(enriched)

            total = score_result["total_score"]
            bucket = f"{(total // 10) * 10}-{(total // 10) * 10 + 9}"
            stats["score_distribution"][bucket] = \
                stats["score_distribution"].get(bucket, 0) + 1

            if total >= threshold_relevant:
                relevant.append(enriched)

                for cat in score_result["matched_categories"]:
                    stats["by_category"][cat] = \
                        stats["by_category"].get(cat, 0) + 1

                country = (notice.get("contracting_authority", {})
                           .get("country", "unknown"))
                stats["by_country"][country] = \
                    stats["by_country"].get(country, 0) + 1

            if total >= threshold_high:
                high_confidence.append(enriched)

        # Deduplicate
        relevant = self._deduplicate(relevant)
        high_confidence = self._deduplicate(high_confidence)

        stats["total_relevant"] = len(relevant)
        stats["total_high_confidence"] = len(high_confidence)

        # Sort by score descending
        relevant.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        high_confidence.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        # Save results
        self._save_json(output_path / "all_scored.json", all_scored)
        self._save_json(output_path / "relevant.json", relevant)
        self._save_json(output_path / "high_confidence.json", high_confidence)
        self._save_json(output_path / "filter_stats.json", stats)

        logger.info(f"\nFilter Results:")
        logger.info(f"  Total processed: {stats['total_processed']}")
        logger.info(f"  Defence notices: {stats['total_defence']}")
        logger.info(f"  Non-defence skipped: {stats['total_non_defence_skipped']}")
        logger.info(f"  Relevant (>={threshold_relevant}): {stats['total_relevant']}")
        logger.info(f"  High confidence (>={threshold_high}): {stats['total_high_confidence']}")
        logger.info(f"  Categories: {stats['by_category']}")
        logger.info(f"  Countries: {stats['by_country']}")

        return stats

    @staticmethod
    def _save_json(path: Path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

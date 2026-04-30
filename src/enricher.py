"""
Phase 3c: Fulltext Enricher

For each notice needing enrichment: download fulltext, call Claude Sonnet
to extract missing fields (value, quantity, winner).

Caches results in data/.enrichment_fulltext_log.json.
Only updates fields that are currently null/missing.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

from .fulltext_fetcher import FulltextFetcher

logger = logging.getLogger(__name__)

FULLTEXT_LOG_PATH = Path(__file__).parent.parent / "data" / ".enrichment_fulltext_log.json"

FULLTEXT_ENRICHMENT_PROMPT = """You are a defence procurement data analyst. Extract ONLY the missing fields from this EU procurement notice.

Notice text (truncated):
{fulltext}

Original notice metadata:
- Title: {title}
- Authority: {authority}
- Country: {country}
- CPV codes: {cpv_codes}
- Current value: {current_value}
- Current winner: {current_winner}
- Current quantity: {current_quantity}

Extract ONLY these fields (null if not found):
{{
  "value_amount": null_or_number (contract/estimated value as a number),
  "value_currency": "EUR" or "USD" etc. or null,
  "winner_name": "company name" or null,
  "trailer_quantity": null_or_integer (number of trailers/semi-trailers),
  "contract_duration": "e.g. 48 months" or null,
  "notes": "brief note if something unusual found" or null
}}

RULES:
- Only extract what is clearly stated in the text
- Do not invent or guess values
- 0.01 or 1.00 EUR is a framework placeholder, not a real value — return null for value if you only find this
- Respond with ONLY the JSON object. No markdown, no explanation."""


class FulltextEnricher:
    """Enriches notices with fulltext-extracted data using Claude Sonnet."""

    API_URL = "https://api.anthropic.com/v1/messages"
    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 500

    def __init__(self, config: dict):
        self.config = config
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.fetcher = FulltextFetcher(config)
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01"
            })

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    # ── Log management ──

    @staticmethod
    def _load_log() -> dict:
        if FULLTEXT_LOG_PATH.exists():
            with open(FULLTEXT_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_log(log: dict):
        FULLTEXT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FULLTEXT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

    # ── Enrichment logic ──

    def _build_enrichment_prompt(self, notice: dict, fulltext: str) -> str:
        title = notice.get("title", "") or ""
        if isinstance(title, dict):
            title = title.get("eng") or title.get("deu") or next(iter(title.values()), "")

        auth = notice.get("contracting_authority", {}) or {}
        authority = auth.get("name_short") or auth.get("name", "")
        country = auth.get("country", "")
        cpv_codes = ", ".join(notice.get("cpv_codes", []))

        val = notice.get("estimated_value") or {}
        current_value = f"{val.get('amount', 'N/A')} {val.get('currency', '')}"
        award = notice.get("award") or {}
        current_winner = award.get("winner_name", "N/A")
        current_quantity = notice.get("_trailer_quantity_ai", "N/A")

        return FULLTEXT_ENRICHMENT_PROMPT.format(
            fulltext=fulltext[:12000],
            title=title,
            authority=authority,
            country=country,
            cpv_codes=cpv_codes,
            current_value=current_value,
            current_winner=current_winner,
            current_quantity=current_quantity,
        )

    def _call_claude(self, prompt: str) -> Optional[dict]:
        """Call Claude API for enrichment extraction."""
        for attempt in range(3):
            try:
                resp = self.session.post(self.API_URL, json={
                    "model": self.MODEL,
                    "max_tokens": self.MAX_TOKENS,
                    "messages": [{"role": "user", "content": prompt}]
                }, timeout=30)

                if resp.status_code == 200:
                    text = resp.json()["content"][0]["text"].strip()
                    text = text.replace("```json", "").replace("```", "").strip()
                    text = re.sub(r',\s*}', '}', text)
                    text = re.sub(r',\s*]', ']', text)
                    return json.loads(text)
                elif resp.status_code in (429, 529):
                    wait = 10 * (attempt + 1)
                    logger.warning(f"Rate limited ({resp.status_code}), waiting {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"Claude API error: {resp.status_code}")
                    return None
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Enrichment API error: {e}")
                if attempt < 2:
                    time.sleep(5)
        return None

    def _apply_enrichment(self, notice: dict, enrichment: dict) -> dict:
        """Apply enrichment result to notice — only update null/missing fields."""
        notice = dict(notice)

        # Value
        if enrichment.get("value_amount") is not None:
            current_val = notice.get("estimated_value") or {}
            current_amount = current_val.get("amount")
            if not current_amount or float(str(current_amount) or 0) <= 0.01:
                notice["estimated_value"] = {
                    "amount": enrichment["value_amount"],
                    "currency": enrichment.get("value_currency") or current_val.get("currency", "EUR"),
                }
                logger.info(f"  Enriched value: {enrichment['value_amount']} {enrichment.get('value_currency', '')}")

        # Winner — also update status to Awarded if we found one
        if enrichment.get("winner_name"):
            award = notice.get("award") or {}
            if not award.get("winner_name"):
                notice["award"] = {
                    **award,
                    "winner_name": enrichment["winner_name"],
                    "awarded": True,
                    "_enriched": True,
                }
                logger.info(f"  Enriched winner: {enrichment['winner_name']}")
            if notice.get("_status") != "Awarded":
                notice["_status"] = "Awarded"

        # Quantity — write to both the legacy field and the slot-1 field so the
        # exporter can find it regardless of which field name is checked.
        if enrichment.get("trailer_quantity") is not None:
            qty = enrichment["trailer_quantity"]
            if notice.get("_trailer_quantity_ai") is None:
                notice["_trailer_quantity_ai"] = qty
            # Also populate the slot-based field used by classifier + exporter
            if not notice.get("_trailer_quantity_1_ai"):
                notice["_trailer_quantity_1_ai"] = qty
                logger.info(f"  Enriched quantity: {qty}")

        # Contract duration
        if enrichment.get("contract_duration"):
            if not notice.get("_contract_duration_ai"):
                notice["_contract_duration_ai"] = enrichment["contract_duration"]
                logger.info(f"  Enriched duration: {enrichment['contract_duration']}")

        notice["_fulltext_enriched"] = True
        if enrichment.get("notes"):
            notice["_enrichment_notes"] = enrichment["notes"]

        return notice

    def _get_enrichment_text(self, notice: dict) -> Optional[str]:
        """Get text for enrichment. Priority: national raw text > TED HTML/PDF download."""
        national_text = notice.get("_national_raw_text")
        if national_text and len(str(national_text)) > 200:
            return str(national_text)
        tid = notice.get("tender_id", "")
        links = notice.get("links") or (notice.get("_raw") or {}).get("links") or {}
        return self.fetcher.fetch(tid, links=links)

    def enrich_notice(self, notice: dict) -> dict:
        """Enrich a single notice. Returns updated notice dict."""
        tid = notice.get("tender_id", "")
        log = self._load_log()

        # Use cache if available
        if tid in log:
            cached = log[tid].get("result")
            if cached:
                return self._apply_enrichment(notice, cached)
            return notice

        # Get fulltext (national raw text or TED download)
        fulltext = self._get_enrichment_text(notice)
        if not fulltext:
            logger.warning(f"  No fulltext for {tid}, skipping enrichment")
            return notice

        # Build prompt and call Claude
        prompt = self._build_enrichment_prompt(notice, fulltext)
        result = self._call_claude(prompt)

        if result is None:
            logger.warning(f"  Claude enrichment failed for {tid}")
            return notice

        # Cache result
        log[tid] = {
            "result": result,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "title": str(notice.get("title", ""))[:100],
        }
        self._save_log(log)

        return self._apply_enrichment(notice, result)

    def enrich_batch(self, notices: list, limit: Optional[int] = None) -> list:
        """
        Enrich notices that need it.

        Args:
            notices: list of notice dicts
            limit: max number to enrich (for test mode)

        Returns: updated list of all notices
        """
        if not self.is_available:
            logger.warning("FulltextEnricher: ANTHROPIC_API_KEY not set")
            return notices

        candidates = [n for n in notices if self.fetcher.needs_enrichment(n)]
        if limit:
            candidates = candidates[:limit]

        logger.info(f"Fulltext enrichment: {len(candidates)} notices need enrichment "
                    f"(out of {len(notices)} total)")

        enriched_ids = set()
        enriched_map = {}
        for i, notice in enumerate(candidates):
            tid = notice.get("tender_id", "")
            logger.info(f"Enriching [{i+1}/{len(candidates)}]: {tid}")
            updated = self.enrich_notice(notice)
            enriched_map[tid] = updated
            enriched_ids.add(tid)
            time.sleep(0.5)  # Rate limit

        # Rebuild notices list with enriched versions
        result = []
        for notice in notices:
            tid = notice.get("tender_id", "")
            result.append(enriched_map.get(tid, notice))

        enriched_count = sum(1 for n in result if n.get("_fulltext_enriched"))
        logger.info(f"Fulltext enrichment complete: {enriched_count} notices enriched")
        return result

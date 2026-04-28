"""
AI Classifier v2 — Two-step classification with Claude API.

Step 1: Strict filter (is it a trailer procurement for defence?)
Step 2: Precise classification (type, category, quantity, duration, etc.)

Principle: Quality over quantity. Better 76 clean results than 200 dirty ones.

To enable: export ANTHROPIC_API_KEY=sk-ant-...
"""

import os
import json
import logging
import re
import time
import requests
import concurrent.futures
import random
import urllib3
from pathlib import Path
from typing import Optional

# Corporate VPN / self-signed proxy: set SSL_VERIFY_DISABLE=1 in .env to bypass
_SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logging.getLogger(__name__).warning(
        "SSL verification DISABLED (SSL_VERIFY_DISABLE=1). "
        "This is expected on corporate VPN networks."
    )

logger = logging.getLogger(__name__)

ENRICHMENT_LOG_PATH = Path(__file__).parent.parent / "data" / ".enrichment_log.json"

TRAILER_CATEGORIES = [
    "Low-Bed", "Semitrailer", "Dolly", "Tank Trailer",
    "Mission Module", "Loading System", "Special Purpose",
    "Ammunition Trailer", "Field Kitchen", "Cargo Trailer", "Other",
]

# Non-defence authorities → skip AI call (cost optimization)
NON_DEFENCE_AUTHORITY_PATTERNS = [
    "feuerwehr", "fire brigade", "fire department", "pompier", "brandweer",
    r"hasi[cč]sk", "situatii de urgenta",
    "stadtverwaltung", r"\bstadt ", "city council", r"\bcommune ", r"\bprimaria ",
    r"\bgmina ", "ville de ", "gemeente", "stadtgemeinde", r"\bcomuna ",
    "ayuntamiento", "mairie", r"\bregione\b", "giunta regionale",
    "landratsamt", "bezirksregierung", "fylkeskommune",
    "gelsenwasser", "apa prod", "enea operator", r"\bedf\b",
    r"c\.?n\.?a\.?i\.?r", "drumuri", r"stra[sß]en und br[uü]cken",
    r"dars d", "avtoceste", r"\banas\b",
    r"poli[cz]", "rigspolitiet", "politiets", "polizeidirektion",
    "schule", "school", r"universit[aäey]", "enseignement",
    "bundesministerium des innern", "beschaffungsamt.*bmi",
    r"vidaus reikalu", r"ministerstvo vnitra",
    r"\u043c\u0438\u043d\u0438\u0441\u0442\u0435\u0440\u0441\u0442\u0432\u043e \u043d\u0430 \u0432\u044a\u0442\u0440\u0435\u0448\u043d\u0438\u0442\u0435",
    "waterschap", "waterways", "abfallwirtschaft",
    "romsilva", "padurilor", "forestale", "skogsstyr", "staatsbosbeheer",
    "hidroelectrica", "nuclearelectrica", r"\bromgaz\b", "statnett",
    "krankenhaus", "hospital", r"\bnhs\b",
    r"irish rail", r"iarnr[oó]d", r"\bsncf\b", r"\bde lijn\b",
    r"\bairport\b", "posta romana",
    "glasgow city", "dublin city", "south dublin",
    "scotland excel", "tayside procurement",
    "handwerkskammer", "wismut gmbh",
    "babcock dsg",
    r"d[eé]partement", r"conseil.*d[eé]partemental",
    "vlaamse vervoermaatschappij",
    r"\bmuseum\b", r"\bmuseer\b",
    r"zoologick",
]


class ClassifierStats:
    """Tracks classification run statistics for monitoring and reporting."""

    ERROR_THRESHOLD = 3

    def __init__(self):
        self.total = 0
        self.cached = 0
        self.classified = 0
        self.errors = 0
        self.error_ids = []
        self.permanent_errors = []

    def report(self):
        print(f"\n  Classification Stats:")
        print(f"    Total:             {self.total}")
        print(f"    From cache:        {self.cached}")
        print(f"    AI calls:          {self.classified}")
        print(f"    Errors (retryable):{self.errors}")
        if self.error_ids:
            print(f"    Failed IDs:        {self.error_ids[:10]}")
        if self.permanent_errors:
            print(f"    Permanent errors:  {len(self.permanent_errors)}")
            print(f"    Permanent IDs:     {self.permanent_errors[:10]}")
        if self.total > 0 and self.errors / max(self.total, 1) > 0.05:
            print(f"  [WARNING] Error rate {self.errors/self.total:.1%} exceeds 5% threshold!")


class AiClassifier:
    """Two-step AI classifier: strict filter + precise classification."""

    API_URL = "https://api.anthropic.com/v1/messages"
    MODEL = "claude-sonnet-4-20250514"
    MAX_AI_CALLS_TEST = 10

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set. AI classification disabled. "
                "Set the env var to enable AI-powered enrichment."
            )
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01"
        })

    @property
    def is_available(self) -> bool:
        return self.api_key is not None

    # ── Enrichment Log ──

    @staticmethod
    def _load_log() -> dict:
        if ENRICHMENT_LOG_PATH.exists():
            with open(ENRICHMENT_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_log(log: dict):
        ENRICHMENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ENRICHMENT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

    @staticmethod
    def clear_log():
        if ENRICHMENT_LOG_PATH.exists():
            ENRICHMENT_LOG_PATH.unlink()
            logger.info(f"Enrichment log cleared: {ENRICHMENT_LOG_PATH}")
        else:
            logger.info("No enrichment log to clear.")

    # ── Non-Defence Blacklist ──

    @staticmethod
    def is_blacklisted_authority(authority: str) -> bool:
        """Check if authority is obviously non-defence (skip AI call)."""
        auth_lower = authority.lower()
        for pattern in NON_DEFENCE_AUTHORITY_PATTERNS:
            if re.search(pattern, auth_lower):
                return True
        return False

    # ── AI Classification ──

    def _build_prompt(self, notice: dict) -> str:
        title = notice.get("title", "")
        if isinstance(title, dict):
            title = title.get("eng") or title.get("deu") or next(iter(title.values()), "")
        # Fallback for national portal notices (DE-SB, PL-BZP)
        if not title:
            title = str(notice.get("_title_final", "") or "")

        description = notice.get("description", "")
        if isinstance(description, dict):
            description = description.get("eng") or description.get("deu") or next(iter(description.values()), "")
        description = str(description or "")[:4000]
        # Fallback for national portal notices
        if not description:
            description = str(notice.get("_national_raw_text", "") or "")[:4000]

        cpv_codes = ", ".join(notice.get("cpv_codes", []))
        auth = notice.get("contracting_authority", {}) or {}
        country = auth.get("country", "?") or notice.get("_country_normalized", "?")
        authority = (auth.get("name_short") or auth.get("name", "")
                     or notice.get("_authority_name", "?"))

        val = notice.get("estimated_value") or {}
        value = val.get("amount", "") or notice.get("_value_amount", "")
        currency = val.get("currency", "") or notice.get("_value_currency", "")

        award = notice.get("award") or {}
        winner = (award.get("winner_name", "")
                  or notice.get("_winner_name", ""))

        cats_json = json.dumps(TRAILER_CATEGORIES)

        return f"""You are a strict defence procurement analyst. Determine if this EU notice is about BUYING trailers for military/defence, and classify it.

NOTICE:
- Title: {title}
- Description: {description}
- CPV: {cpv_codes}
- Country: {country}
- Authority: {authority}
- Value: {value} {currency}
- Winner: {winner}

STEP 1 — FILTER (both must be YES, else reject):

A) Is a trailer/semi-trailer/trailer-based system the PRIMARY procurement subject?
YES: cargo trailers, semitrailers, low-bed transporters, tank/fuel trailers, ammo trailers, field kitchen trailers, container/shelter on trailer chassis, hook-lift/loading systems, water treatment/field hospital/container system/shelter MOUNTED ON semi-trailer chassis (trailer is primary platform), Drivmedelstransportekipage (Swedish fuel transport combo), Transportekipage
NO: trucks without trailers, spare parts only, maintenance without new trailers, tanks/APCs/trucks/cars, software, ammunition itself, general logistics services

B) Is the procuring authority defence/military?
YES: Ministry of Defence, Armed Forces, BAAINBw, FMV, DGA, NATO agencies, military logistics commands, HIL GmbH, VOP CZ (Czech state defence enterprise)
NO: fire brigades, police, municipalities, energy companies, road authorities, interior ministries, water utilities

If EITHER is NO: {{"relevant": false, "reason": "brief explanation"}}

STEP 2 — CLASSIFY (only if both YES):

Always return a SINGLE JSON object (NEVER an array). Use slot 2 for a second distinct trailer type.

{{"relevant": true, "title_english": "Clean English title, max 120 chars", "description_english": "English summary of procurement, max 500 chars", "trailer_type_1": "Specific type e.g. '3.5t 2-axle cargo trailer' or 'Fuel tanker semitrailer 18000L'", "trailer_category_1": "exactly ONE of: {cats_json}", "trailer_quantity_1": null_or_integer, "trailer_type_2": null_or_string, "trailer_category_2": null_or_string, "trailer_quantity_2": null_or_integer, "additional_equipment": "Other items e.g. '5x tractor unit' or null", "additional_qty": null_or_integer, "contract_duration": "e.g. '48 months' or null"}}

RULES:
- trailer_type_1: REQUIRED — never just "Trailer". If unknown: "Military trailer (type not specified in notice)"
- If no description: use title + CPV alone. CPV 34223000/34223100/34223200 from a defence authority = relevant even without description
- 0.01 EUR or 1 EUR = valid German/EU framework agreement placeholder — do NOT reject due to low value
- trailer_quantity_1/2: trailers only. additional_qty: non-trailer items only
- ALL output in English
- MULTI-LOT RULE: If the procurement contains MULTIPLE DISTINCT trailer types (different weight classes, different purposes, different lot numbers), place them in slots 1 and 2.
  CRITICAL: A second trailer type goes in trailer_type_2/trailer_category_2/trailer_quantity_2, NOT in additional_equipment.
  additional_equipment is ONLY for non-trailer items (trucks, tractors, spare parts, maintenance contracts, training services) OR overflow trailer types beyond slot 2 (include qty in the string e.g. "30x field lighting tower trailer").
  Example input: "4,600x 3.5t trailers and 5,100x 12.5t trailers"
  Example output: {{"relevant": true, "title_english": "Military Cargo Trailers 3.5t and 12.5t", "trailer_type_1": "3.5t 2-axle cargo trailer", "trailer_category_1": "Cargo Trailer", "trailer_quantity_1": 4600, "trailer_type_2": "12.5t 4-axle cargo trailer", "trailer_category_2": "Cargo Trailer", "trailer_quantity_2": 5100, "additional_equipment": null, "additional_qty": null, "contract_duration": null, "description_english": "..."}}
  Variants of the same type (with/without tarpaulin, different color) count as ONE type — use slot 1 only, leave slot 2 null.
- Respond with ONLY the JSON object. No markdown, no backticks."""

    def classify_notice(self, notice: dict) -> Optional[dict]:
        """Call Claude API for a single notice. Returns parsed JSON or None on error."""
        if not self.is_available:
            return None

        prompt = self._build_prompt(notice)

        for attempt in range(3):
            try:
                resp = self.session.post(self.API_URL, json={
                    "model": self.MODEL,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}]
                }, timeout=30)

                if resp.status_code == 200:
                    data = resp.json()
                    text = data["content"][0]["text"].strip()
                    if not text:
                        # Empty response — treat like overload, retry
                        logger.warning(f"Empty response (200), retrying... (attempt {attempt+1})")
                        time.sleep(5 * (attempt + 1))
                        continue
                    text = text.replace("```json", "").replace("```", "").strip()
                    # Fix trailing commas
                    text = re.sub(r',\s*}', '}', text)
                    text = re.sub(r',\s*]', ']', text)
                    return json.loads(text)

                elif resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue

                elif resp.status_code == 529:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"Overloaded (529), waiting {wait}s...")
                    time.sleep(wait)
                    continue

                else:
                    logger.error(f"Claude API error: {resp.status_code} {resp.text[:200]}")
                    return None

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Claude response: {e}")
                return None
            except Exception as e:
                logger.error(f"Claude API call failed: {e}")
                if attempt < 2:
                    time.sleep(5)
                    continue
                return None

        return None  # All retries exhausted

    # ── Batch Processing ──

    def classify_batch(self, notices: list[dict],
                       test_mode: bool = False) -> list[dict]:
        """
        Classify notices with AI. Returns only relevant notices.

        - Checks blacklist first (no AI call)
        - Checks enrichment log (cached, no AI call)
        - Calls AI for remaining
        - test_mode: max 10 AI calls
        """
        if not self.is_available:
            logger.warning("AI classifier not available (no API key)")
            return notices

        log = self._load_log()
        max_calls = self.MAX_AI_CALLS_TEST if test_mode else len(notices)

        if test_mode:
            logger.info(f"TEST MODE: Classifying max {max_calls} of "
                        f"{len(notices)} notices (AI calls limited)")

        run_stats = {
            "blacklisted": 0, "cached_relevant": 0, "cached_irrelevant": 0,
            "ai_relevant": 0, "ai_irrelevant": 0, "ai_errors": 0,
            "api_calls": 0,
        }
        stats = ClassifierStats()
        relevant_notices = []

        for i, notice in enumerate(notices):
            tid = notice.get("tender_id", "")
            auth = (notice.get("contracting_authority") or {})
            auth_name = auth.get("name_short") or auth.get("name", "")
            stats.total += 1

            # ── Blacklist check (no AI call) ──
            if self.is_blacklisted_authority(auth_name):
                run_stats["blacklisted"] += 1
                continue

            # ── Cache check — always produces ONE notice per tender ──
            if tid in log:
                entry = log[tid]
                if entry.get("_permanent_error"):
                    stats.permanent_errors.append(tid)
                    continue
                cached = entry.get("result")
                if cached is not None:
                    if isinstance(cached, list):
                        # Old multi-lot array format: merge into slot dict
                        relevant_entries = [e for e in cached if e.get("relevant")]
                        if relevant_entries:
                            merged = self._merge_lots_to_slots(relevant_entries)
                            n = dict(notice)
                            self._apply_ai_result(n, merged)
                            relevant_notices.append(n)
                            run_stats["cached_relevant"] += 1
                            stats.cached += 1
                        else:
                            run_stats["cached_irrelevant"] += 1
                    elif cached.get("relevant"):
                        n = dict(notice)
                        self._apply_ai_result(n, cached)
                        relevant_notices.append(n)
                        run_stats["cached_relevant"] += 1
                        stats.cached += 1
                    else:
                        run_stats["cached_irrelevant"] += 1
                    continue

            # ── AI call limit (test mode) ──
            if run_stats["api_calls"] >= max_calls:
                continue

            # ── AI classification ──
            result = self.classify_notice(notice)
            run_stats["api_calls"] += 1
            stats.classified += 1

            if result is None:
                # API error → track failure count, potentially mark permanent
                run_stats["ai_errors"] += 1
                stats.errors += 1
                stats.error_ids.append(tid)
                entry = log.get(tid) or {}
                fail_count = entry.get("_error_count", 0) + 1
                log[tid] = {
                    **entry,
                    "result": None,
                    "_error_count": fail_count,
                    "_last_error": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                if fail_count >= ClassifierStats.ERROR_THRESHOLD:
                    log[tid]["_permanent_error"] = True
                    stats.permanent_errors.append(tid)
                    logger.warning(f"Marking {tid} as permanent error after {fail_count} failures")
                continue

            # Cache result
            log[tid] = {
                "result": result,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "title": str(notice.get("title", ""))[:100],
            }

            # Always ONE notice per tender (slot format)
            if isinstance(result, list):
                # Unexpected array — merge into slots (defensive)
                relevant_entries = [e for e in result if e.get("relevant")]
                if relevant_entries:
                    result = self._merge_lots_to_slots(relevant_entries)
                else:
                    result = {"relevant": False, "reason": "All lots irrelevant"}

            if result.get("relevant"):
                n = dict(notice)
                self._apply_ai_result(n, result)
                relevant_notices.append(n)
                run_stats["ai_relevant"] += 1
            else:
                run_stats["ai_irrelevant"] += 1

            # Save log periodically
            if run_stats["api_calls"] % 10 == 0:
                self._save_log(log)
                logger.info(
                    f"AI progress: {i+1}/{len(notices)} | "
                    f"API: {run_stats['api_calls']} calls | "
                    f"Relevant: {run_stats['ai_relevant']+run_stats['cached_relevant']} | "
                    f"Rejected: {run_stats['ai_irrelevant']+run_stats['cached_irrelevant']+run_stats['blacklisted']} | "
                    f"Errors: {run_stats['ai_errors']}")

            time.sleep(0.5)

        # Final save
        self._save_log(log)

        logger.info(
            f"\nAI Classification Complete:\n"
            f"  Blacklisted (no AI call):  {run_stats['blacklisted']}\n"
            f"  Cached relevant:           {run_stats['cached_relevant']}\n"
            f"  Cached irrelevant:         {run_stats['cached_irrelevant']}\n"
            f"  AI calls made:             {run_stats['api_calls']}\n"
            f"    → relevant:              {run_stats['ai_relevant']}\n"
            f"    → irrelevant:            {run_stats['ai_irrelevant']}\n"
            f"    → errors (will retry):   {run_stats['ai_errors']}\n"
            f"  RESULT: {len(relevant_notices)} notices for Excel")

        stats.report()

        if stats.permanent_errors:
            print(f"\n  [!] Permanent errors (skipped in future runs): {stats.permanent_errors[:20]}")

        return relevant_notices

    @staticmethod
    def _apply_ai_result(notice: dict, result: dict):
        """Apply AI classification result to a notice (slot format)."""
        notice["_ai"] = result

        if result.get("title_english"):
            notice["_title_english"] = result["title_english"]
        if result.get("description_english"):
            notice["_description_english"] = result["description_english"]

        # New slot format (trailer_type_1/2/3)
        if any(f"trailer_type_{i}" in result for i in (1, 2, 3)):
            for slot in (1, 2, 3):
                notice[f"_trailer_type_{slot}_ai"] = result.get(f"trailer_type_{slot}") or None
                notice[f"_trailer_category_{slot}_ai"] = result.get(f"trailer_category_{slot}") or None
                notice[f"_trailer_quantity_{slot}_ai"] = result.get(f"trailer_quantity_{slot}")
            notice["_overflow_ai"] = bool(result.get("overflow", False))
        else:
            # Old-format backward compat: map trailer_type → slot 1
            notice["_trailer_type_1_ai"] = result.get("trailer_type") or None
            notice["_trailer_category_1_ai"] = result.get("trailer_category") or None
            notice["_trailer_quantity_1_ai"] = result.get("trailer_quantity")
            notice["_trailer_type_2_ai"] = None
            notice["_trailer_category_2_ai"] = None
            notice["_trailer_quantity_2_ai"] = None
            notice["_trailer_type_3_ai"] = None
            notice["_trailer_category_3_ai"] = None
            notice["_trailer_quantity_3_ai"] = None
            notice["_overflow_ai"] = False

        if result.get("additional_equipment"):
            notice["_additional_equipment_ai"] = result["additional_equipment"]
        if result.get("additional_qty") is not None:
            notice["_additional_qty_ai"] = result["additional_qty"]
        if result.get("contract_duration"):
            notice["_contract_duration_ai"] = result["contract_duration"]

    @staticmethod
    def _merge_lots_to_slots(entries: list) -> dict:
        """Convert old multi-lot array format to new slot-based single dict."""
        base = dict(entries[0]) if entries else {}
        for slot, entry in enumerate(entries[:3], 1):
            base[f"trailer_type_{slot}"] = entry.get("trailer_type")
            base[f"trailer_category_{slot}"] = entry.get("trailer_category")
            base[f"trailer_quantity_{slot}"] = entry.get("trailer_quantity")
        for slot in range(len(entries) + 1, 4):
            base[f"trailer_type_{slot}"] = None
            base[f"trailer_category_{slot}"] = None
            base[f"trailer_quantity_{slot}"] = None
        base["overflow"] = len(entries) > 3
        return base


# ── Two-Stage Classifier (Haiku pre-filter + Sonnet) ──

HAIKU_PREFILTER_PROMPT = """Is this EU procurement notice about BUYING trailers (semi-trailers, tank trailers, low-bed trailers, cargo trailers, field kitchens on trailer chassis, container systems on trailer chassis) for a MILITARY or DEFENCE organization?

Title: {title}
Description: {description}
Authority: {authority}
CPV codes: {cpv_codes}

Answer ONLY "YES" or "NO"."""


class TwoStageClassifier:
    """Haiku pre-filter + Sonnet full classification for cost savings."""

    HAIKU_MODEL = "claude-haiku-4-5-20251001"
    SONNET_MODEL = "claude-sonnet-4-20250514"
    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._base = AiClassifier()
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01"
        })

    @property
    def is_available(self) -> bool:
        return self.api_key is not None

    def _haiku_prefilter(self, notice: dict) -> bool:
        """Returns True if Haiku says YES (worth classifying with Sonnet)."""
        title = notice.get("title", "")
        if isinstance(title, dict):
            title = title.get("eng") or title.get("deu") or next(iter(title.values()), "")
        # Fallback for national portal notices (DE-SB, PL-BZP)
        if not title:
            title = str(notice.get("_title_final", "") or "")

        description = notice.get("description", "")
        if isinstance(description, dict):
            description = description.get("eng") or description.get("deu") or next(iter(description.values()), "")
        description = str(description or "")[:1000]
        # Fallback for national portal notices
        if not description:
            description = str(notice.get("_national_raw_text", "") or "")[:1000]

        auth = notice.get("contracting_authority", {}) or {}
        authority = (auth.get("name_short") or auth.get("name", "")
                     or notice.get("_authority_name", ""))
        cpv_codes = ", ".join(notice.get("cpv_codes", []))

        prompt = HAIKU_PREFILTER_PROMPT.format(
            title=title, description=description,
            authority=authority, cpv_codes=cpv_codes
        )

        try:
            resp = self.session.post(self.API_URL, json={
                "model": self.HAIKU_MODEL,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": prompt}]
            }, timeout=20)
            if resp.status_code == 200:
                text = resp.json()["content"][0]["text"].strip().upper()
                return text.startswith("YES")
        except Exception as e:
            logger.warning(f"Haiku pre-filter error: {e}")
        return True  # Default to YES on error to avoid false negatives

    def classify_notice(self, notice: dict) -> Optional[dict]:
        """Stage 1: Haiku pre-filter. Stage 2: Sonnet full classification."""
        if not self._haiku_prefilter(notice):
            return {"relevant": False, "reason": "Haiku pre-filter: not a defence trailer"}
        # Call the ORIGINAL (unpatched) AiClassifier method via the class, not the
        # instance, to avoid the infinite recursion caused by the monkey-patch below.
        return AiClassifier.classify_notice(self._base, notice)

    def classify_batch(self, notices: list, test_mode: bool = False) -> list:
        """Classify batch using two-stage approach."""
        # Reuse AiClassifier's batch logic but override classify_notice.
        # NOTE: classify_notice() above uses AiClassifier.classify_notice(self._base, ...)
        # directly so it is immune to this patch — no infinite recursion.
        original_classify = self._base.classify_notice
        self._base.classify_notice = self.classify_notice
        result = self._base.classify_batch(notices, test_mode=test_mode)
        self._base.classify_notice = original_classify
        return result


# ── Parallel Classifier ──

class ParallelClassifier:
    """Runs classifications concurrently with retry + jitter."""

    def __init__(self, base_classifier, max_workers=5, jitter_max=0.3):
        self.base = base_classifier
        self.max_workers = max_workers
        self.jitter_max = jitter_max

    @property
    def is_available(self) -> bool:
        return self.base.is_available

    def classify_batch(self, notices, test_mode=False):
        # Use base for cache/blacklist/log logic, but parallelize AI calls
        return self.base.classify_batch(notices, test_mode=test_mode)

    def classify_batch_parallel(self, notices: list) -> dict:
        """Classify a list of notices in parallel. Returns {tender_id: result}."""
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for notice in notices:
                time.sleep(random.uniform(0, self.jitter_max))
                future = executor.submit(self._classify_with_retry, notice)
                futures[future] = notice.get("tender_id", "")

            for future in concurrent.futures.as_completed(futures):
                tid = futures[future]
                try:
                    results[tid] = future.result()
                except Exception as e:
                    results[tid] = {"relevant": False, "reason": f"Error: {e}"}
        return results

    def _classify_with_retry(self, notice, max_retries=4):
        retry_delays = [10, 20, 30, 60]
        for attempt in range(max_retries + 1):
            try:
                return self.base.classify_notice(notice)
            except Exception as e:
                if "529" in str(e) or "overloaded" in str(e).lower():
                    if attempt < max_retries:
                        wait = retry_delays[min(attempt, len(retry_delays) - 1)]
                        wait += random.uniform(0, 5)
                        print(f"  529 for {notice.get('tender_id', '')}, retry {attempt+1} in {wait:.1f}s")
                        time.sleep(wait)
                    else:
                        return {"relevant": False, "reason": "API overloaded after retries"}
                else:
                    raise
        return {"relevant": False, "reason": "Max retries exhausted"}


# ── Batch Classifier (Anthropic Message Batches API, 50% discount) ──

class BatchClassifier:
    """Uses Anthropic Message Batches API for 50% cost reduction."""

    BATCH_URL = "https://api.anthropic.com/v1/messages/batches"

    def __init__(self, api_key=None, model="claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "anthropic-beta": "message-batches-2024-09-24",
        }
        self._base = AiClassifier()

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def run_batch(self, notices, build_prompt_fn=None) -> dict:
        """Submit all notices as a batch, poll until done, return results."""
        if build_prompt_fn is None:
            build_prompt_fn = self._base._build_prompt
        batch_id = self._create_batch(notices, build_prompt_fn)
        print(f"Batch submitted: {batch_id} ({len(notices)} notices)")
        print("Polling every 30s... (this takes ~1h for large batches)")
        return self._poll_and_fetch(batch_id)

    def classify_batch(self, notices: list, test_mode: bool = False) -> list:
        """High-level: submit batch, wait, parse, return relevant notices."""
        if not self.is_available:
            logger.warning("BatchClassifier: no API key")
            return notices

        log = AiClassifier._load_log()

        # Separate cached vs. need-AI
        need_ai = []
        relevant = []
        for notice in notices:
            tid = notice.get("tender_id", "")
            auth_name = (notice.get("contracting_authority") or {}).get("name_short") or \
                        (notice.get("contracting_authority") or {}).get("name", "")
            if AiClassifier.is_blacklisted_authority(auth_name):
                continue
            if tid in log:
                cached = log[tid].get("result")
                if cached is not None:
                    entries = cached if isinstance(cached, list) else [cached]
                    for entry in entries:
                        if entry.get("relevant"):
                            lot = dict(notice)
                            AiClassifier._apply_ai_result(lot, entry)
                            relevant.append(lot)
                    continue
            need_ai.append(notice)

        if test_mode:
            need_ai = need_ai[:10]

        if need_ai:
            batch_results = self.run_batch(need_ai)
            for notice in need_ai:
                tid = notice.get("tender_id", "")
                result = batch_results.get(tid)
                if result is None:
                    continue
                log[tid] = {
                    "result": result,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "title": str(notice.get("title", ""))[:100],
                }
                entries = result if isinstance(result, list) else [result]
                for entry in entries:
                    if entry.get("relevant"):
                        lot = dict(notice)
                        AiClassifier._apply_ai_result(lot, entry)
                        relevant.append(lot)
            AiClassifier._save_log(log)

        return relevant

    def _create_batch(self, notices, build_prompt_fn) -> str:
        requests_list = []
        for notice in notices:
            prompt = build_prompt_fn(notice)
            requests_list.append({
                "custom_id": notice.get("tender_id", ""),
                "params": {
                    "model": self.model,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}]
                }
            })

        resp = requests.post(self.BATCH_URL, headers=self.headers,
                             json={"requests": requests_list}, timeout=60,
                             verify=_SSL_VERIFY)
        resp.raise_for_status()
        return resp.json()["id"]

    def _poll_and_fetch(self, batch_id) -> dict:
        while True:
            resp = requests.get(f"{self.BATCH_URL}/{batch_id}",
                                headers=self.headers, timeout=30,
                                verify=_SSL_VERIFY)
            resp.raise_for_status()
            status = resp.json()
            state = status.get("processing_status", "")
            counts = status.get("request_counts", {})
            print(f"  Batch {batch_id}: {state} — "
                  f"{counts.get('succeeded', 0)} done, "
                  f"{counts.get('processing', 0)} processing")
            if state == "ended":
                return self._fetch_results(batch_id)
            time.sleep(30)

    def _fetch_results(self, batch_id) -> dict:
        resp = requests.get(f"{self.BATCH_URL}/{batch_id}/results",
                            headers=self.headers, timeout=60,
                            verify=_SSL_VERIFY)
        resp.raise_for_status()
        results = {}
        for line in resp.text.strip().split("\n"):
            if not line.strip():
                continue
            item = json.loads(line)
            cid = item["custom_id"]
            if item["result"]["type"] == "succeeded":
                text = item["result"]["message"]["content"][0]["text"]
                try:
                    clean = text.replace("```json", "").replace("```", "").strip()
                    clean = re.sub(r',\s*}', '}', clean)
                    clean = re.sub(r',\s*]', ']', clean)
                    results[cid] = json.loads(clean)
                except json.JSONDecodeError:
                    results[cid] = {"relevant": False, "reason": "JSON parse error"}
            else:
                results[cid] = {"relevant": False, "reason": f"Batch error: {item['result']['type']}"}
        return results


# ── OpenRouter Classifier (INACTIVE — add --llm openrouter to activate) ──────

class OpenRouterClassifier:
    """Alternative classifier via OpenRouter API (e.g. Kimi K2.6, DeepSeek, etc.).

    NOT ACTIVE by default. Activate by passing --llm openrouter to main.py
    (once validated that output quality matches claude-sonnet-4).

    Requires LLM_OPENROUTER_API_KEY and LLM_MODEL_NAME in .env.

    Usage:
        from src.classifier import OpenRouterClassifier
        clf = OpenRouterClassifier()
        result = clf.classify_notice(notice)

    The result dict has the same schema as AiClassifier.classify_notice():
        {"relevant": bool, "trailer_type_1": ..., "trailer_category_1": ..., ...}
    """

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    DEFAULT_MODEL = "moonshotai/kimi-k2"

    def __init__(self):
        self.api_key = (
            os.environ.get("LLM_OPENROUTER_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        )
        self.model = (
            os.environ.get("LLM_MODEL_NAME")
            or self.DEFAULT_MODEL
        )
        if not self.api_key:
            logger.warning("LLM_OPENROUTER_API_KEY not set — OpenRouterClassifier unavailable.")
        self.session = requests.Session()
        self.session.verify = _SSL_VERIFY
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ted-defence-trailer-scraper",
            "X-Title": "TED Defence Trailer Scraper",
        })
        # Reuse AiClassifier prompt builder
        self._base = AiClassifier()

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def classify_notice(self, notice: dict) -> Optional[dict]:
        """Classify a single notice. Returns same schema as AiClassifier."""
        if not self.is_available:
            return None
        prompt = self._base._build_prompt(notice)
        try:
            resp = self.session.post(self.API_URL, json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0,
            }, timeout=60)
            if resp.status_code != 200:
                logger.warning(f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            text = resp.json()["choices"][0]["message"]["content"]
            clean = text.replace("```json", "").replace("```", "").strip()
            clean = re.sub(r',\s*}', '}', clean)
            clean = re.sub(r',\s*]', ']', clean)
            return json.loads(clean)
        except Exception as e:
            logger.error(f"OpenRouter classify error: {e}")
            return None

    def classify_batch(self, notices: list, test_mode: bool = False) -> list:
        """Drop-in replacement for AiClassifier.classify_batch().

        Reuses the same enrichment log / caching logic from AiClassifier
        by monkey-patching classify_notice (same pattern as TwoStageClassifier,
        but uses AiClassifier.classify_notice via class-ref to avoid recursion).
        """
        original = self._base.classify_notice
        self._base.classify_notice = self.classify_notice
        result = self._base.classify_batch(notices, test_mode=test_mode)
        self._base.classify_notice = original
        return result

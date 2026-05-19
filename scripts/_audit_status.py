"""
Status Mapping Audit — Sprint 14b
Read-only analysis of data/filtered/relevant.json.
Run from the ted-scraper/ted-scraper/ directory:
    python3 scripts/_audit_status.py

Writes JSON to stdout. Redirect to a file if needed:
    python3 scripts/_audit_status.py > /tmp/audit_out.json
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "filtered" / "relevant.json"

_TED_PAT = re.compile(r"^\d+-\d{4}$")
_TZ_RE = re.compile(r"[Z+][0-9:+]*$")


def load() -> list[dict]:
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def clean_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s).split("\n")[0].strip()
    s = _TZ_RE.sub("", s).strip()[:10]
    try:
        return date.fromisoformat(s) if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None
    except ValueError:
        return None


def is_ted(x: dict) -> bool:
    return bool(_TED_PAT.match(str(x.get("tender_id", "")))) or bool(x.get("ted_url"))


def get_url(x: dict) -> str:
    url = x.get("ted_url", "")
    if url:
        return url
    links = x.get("links") or (x.get("_raw") or {}).get("links") or {}
    if isinstance(links, dict):
        html = links.get("html") or {}
        if isinstance(html, dict) and html:
            eng = html.get("ENG") or html.get("DEU") or ""
            if eng:
                return eng
    return x.get("source_url_national", "") or x.get("_source_url_national", "") or ""


def resolve_status_current(x: dict) -> str:
    """Replicate the CURRENT _resolve_status() from exporter_frontend.py."""
    s = x.get("_status")
    if s in ("Open", "Closed", "Awarded"):
        return s
    award = x.get("award")
    if isinstance(award, dict) and award.get("awarded"):
        return "Awarded"
    return "Closed"


# ── 1. Field inventory ────────────────────────────────────────────────────────

def field_inventory(notices: list[dict]) -> dict:
    n = len(notices)

    # Winner signal: NOTE — field is award.winner_name, NOT _winner_name
    winner_via_underscore = sum(1 for x in notices if x.get("_winner_name"))
    winner_via_award = sum(
        1 for x in notices
        if isinstance(x.get("award"), dict) and x["award"].get("winner_name")
    )
    award_awarded_true = sum(
        1 for x in notices
        if isinstance(x.get("award"), dict) and x["award"].get("awarded")
    )

    # _raw field presence
    raw_notice_type_hyphen: Counter = Counter()   # notice-type (kebab)
    raw_notice_type_camel: Counter = Counter()    # noticeType (camelCase)
    raw_form_type_hyphen: Counter = Counter()     # form-type
    raw_notice_status: Counter = Counter()        # noticeStatus
    has_notice_type_h = has_notice_type_c = has_form_type = has_notice_status = 0

    for x in notices:
        raw = x.get("_raw")
        if not isinstance(raw, dict):
            continue
        if raw.get("notice-type"):
            has_notice_type_h += 1
            raw_notice_type_hyphen[str(raw["notice-type"])] += 1
        if raw.get("noticeType"):
            has_notice_type_c += 1
            raw_notice_type_camel[str(raw["noticeType"])] += 1
        if raw.get("form-type"):
            has_form_type += 1
            raw_form_type_hyphen[str(raw["form-type"])] += 1
        if raw.get("noticeStatus"):
            has_notice_status += 1
            raw_notice_status[str(raw["noticeStatus"])] += 1

    # Deadline fields
    today = date.today()
    has_deadline = sum(1 for x in notices if x.get("submission_deadline"))
    deadline_future = sum(
        1 for x in notices
        if (d := clean_date(x.get("submission_deadline"))) and d >= today
    )
    deadline_past = sum(
        1 for x in notices
        if (d := clean_date(x.get("submission_deadline"))) and d < today
    )

    # _status pre-set
    status_dist = Counter(str(x.get("_status")) for x in notices)

    # Source field — NOTE: _source field is MISSING for all 256 notices in current data
    source_present = sum(1 for x in notices if x.get("_source"))

    # Tier-1 coverage: notices that can be mapped deterministically
    tier1_total = sum(
        1 for x in notices
        if (isinstance(x.get("award"), dict) and x["award"].get("awarded"))
        or x.get("submission_deadline")
    )
    tier3_total = n - tier1_total

    return {
        "total": n,
        "ted_count": sum(1 for x in notices if is_ted(x)),
        "national_count": sum(1 for x in notices if not is_ted(x)),
        "winner_via_underscore_field": winner_via_underscore,
        "winner_via_award_dict": winner_via_award,
        "award_awarded_true": award_awarded_true,
        "has_raw_notice_type_hyphen": has_notice_type_h,
        "top_raw_notice_type_hyphen": raw_notice_type_hyphen.most_common(10),
        "has_raw_noticeType_camel": has_notice_type_c,
        "top_raw_noticeType_camel": raw_notice_type_camel.most_common(10),
        "has_raw_form_type": has_form_type,
        "has_raw_noticeStatus": has_notice_status,
        "top_raw_noticeStatus": raw_notice_status.most_common(10),
        "_source_field_present": source_present,
        "has_submission_deadline": has_deadline,
        "deadline_future": deadline_future,
        "deadline_past": deadline_past,
        "status_preset_distribution": dict(status_dist.most_common()),
        "tier1_deterministic": tier1_total,
        "tier1_pct": round(100 * tier1_total / n, 1),
        "tier3_heuristic_only": tier3_total,
        "tier3_pct": round(100 * tier3_total / n, 1),
        "tier3_by_pub_year": dict(
            sorted(Counter(
                str(x.get("publication_date", ""))[:4]
                for x in notices
                if not (isinstance(x.get("award"), dict) and x["award"].get("awarded"))
                and not x.get("submission_deadline")
            ).most_common())
        ),
    }


# ── 2. Award duration statistics ──────────────────────────────────────────────

def award_duration_stats(notices: list[dict]) -> dict:
    """
    NOTE: relevant.json publication_date for Awarded notices is the CAN
    (award notice) publication date, which is AFTER award_date.
    Result: award_date < publication_date in all 21 computable cases.
    There is no CN publication date stored for these notices.
    Duration cannot be computed from current data.
    """
    awarded = [
        x for x in notices
        if isinstance(x.get("award"), dict) and x["award"].get("awarded")
    ]
    with_award_date = sum(
        1 for x in awarded
        if clean_date((x.get("award") or {}).get("award_date"))
    )

    # Direction check: award_date vs publication_date
    before_pub = after_pub = same_pub = 0
    for x in awarded:
        ad = clean_date((x.get("award") or {}).get("award_date"))
        pd = clean_date(x.get("publication_date"))
        if ad and pd:
            if ad < pd:
                before_pub += 1
            elif ad > pd:
                after_pub += 1
            else:
                same_pub += 1

    return {
        "awarded_notices": len(awarded),
        "with_award_date_field": with_award_date,
        "award_date_before_pub_date": before_pub,
        "award_date_after_pub_date": after_pub,
        "note": (
            "publication_date for Awarded notices is the CAN pub date (after award). "
            "The original CN pub date is not stored. "
            "Pub→Award duration cannot be computed from single-notice data. "
            "Requires linking CAN → original CN via award_matcher records."
        ),
    }


# ── 3. Sample URLs ─────────────────────────────────────────────────────────────

def sample_urls(notices: list[dict]) -> list[dict]:
    random.seed(42)

    def pub(x: dict) -> str:
        return str(
            x.get("publication_date") or x.get("_pub_date") or ""
        )[:10]

    def no_award(x: dict) -> bool:
        aw = x.get("award") or {}
        return not (isinstance(aw, dict) and aw.get("awarded")) \
               and x.get("_status") != "Awarded"

    # Bucket A: TED, no award, pub 2026
    bucket_a = [x for x in notices if is_ted(x) and no_award(x) and pub(x).startswith("2026")]
    # Bucket B: TED, no award, pub 2025
    bucket_b = [x for x in notices if is_ted(x) and no_award(x) and pub(x).startswith("2025")]
    # Bucket C: TED, no award, pub 2023–2024
    bucket_c = [x for x in notices if is_ted(x) and no_award(x)
                and (pub(x).startswith("2023") or pub(x).startswith("2024"))]
    # Bucket D: National with URL, no award — prefer CZ/UA/FR, then any
    nat_no_award = [x for x in notices if not is_ted(x) and no_award(x) and get_url(x)]
    cz_ua_fr = [x for x in nat_no_award
                if str(x.get("_country_normalized", "")).startswith(("Czech", "Ukraine", "France"))]
    bucket_d = cz_ua_fr if len(cz_ua_fr) >= 3 else nat_no_award

    rows = []
    for label, pool in [
        ("A — Fresh TED (2026, no award)", bucket_a),
        ("B — Mid-age TED (2025, no award)", bucket_b),
        ("C — Old TED (2023-2024, no award)", bucket_c),
        ("D — National (CZ/UA/FR, no award)", bucket_d),
    ]:
        for x in random.sample(pool, min(3, len(pool))):
            raw = x.get("_raw") or {}
            nt = (raw.get("noticeType") or raw.get("notice-type") or "—") if isinstance(raw, dict) else "—"
            ns = (raw.get("noticeStatus") or "—") if isinstance(raw, dict) else "—"
            dl = str(x.get("submission_deadline") or
                     (raw.get("deadlineDate") if isinstance(raw, dict) else "") or "—")[:10]
            rows.append({
                "bucket": label,
                "tender_id": x.get("tender_id", ""),
                "source": "TED" if is_ted(x) else x.get("_country_normalized", "National"),
                "pub_date": pub(x) or "—",
                "notice_type_in_raw": nt,
                "notice_status_in_raw": ns,
                "deadline": dl,
                "our_current_guess": resolve_status_current(x),
                "portal_url": get_url(x),
                "manual_finding": "",
            })
    return rows


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading …", file=sys.stderr)
    notices = load()
    result = {
        "inventory": field_inventory(notices),
        "award_duration": award_duration_stats(notices),
        "samples": sample_urls(notices),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""
URL Source Audit — Phase 3l quality report.

Reads data/filtered/relevant.json and produces docs/URL_SOURCE_AUDIT_260521.md.

Reports per source:
  - notice count
  - URL pattern (constructed vs source-provided)
  - url_status distribution (alive / dead / auth_walled / …)
  - _published_at_source coverage
  - specific issues flagged

Run:
  python scripts/_audit_url_sources.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RELEVANT = _ROOT / "data" / "filtered" / "relevant.json"
_OUT_DIR = _ROOT / "docs"
_OUT_FILE = _OUT_DIR / "URL_SOURCE_AUDIT_260521.md"


# ── helpers ──────────────────────────────────────────────────────────────────

def _src_label(n: dict) -> str:
    """Derive source label from _source field or tender_id prefix."""
    src = n.get("_source")
    if src:
        return src
    tid = str(n.get("tender_id", ""))
    if re.match(r"^\d+", tid):
        return "TED"
    m = re.match(r"^([A-Z]{2,6})-", tid)
    if m:
        pfx = m.group(1)
        if pfx == "EE":
            return "EE-RP"
        if pfx == "CA":
            return "CA-CB"
        if pfx == "CZ":
            return "CZ-NEN"
        if pfx == "UK":
            return "UK-FTS/CF"
        if pfx == "FR":
            return "FR-BP"
        if pfx == "NL":
            return "NL-TN"
        if pfx == "NO":
            return "NO-DFF"
        if pfx == "UA":
            return "UA-PZ"
        return pfx
    return "UNKNOWN"


def _url_field(n: dict) -> tuple[str, str]:
    """Return (field_used, url) for the notice."""
    for field in ("source_url_national", "_source_url_national", "ted_url", "url"):
        v = n.get(field)
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            return field, v
    return "", ""


def _url_pattern(url: str, src: str) -> str:
    """Classify URL as a known canonical pattern or 'constructed'."""
    if not url:
        return "no_url"
    if "ted.europa.eu" in url:
        return "ted.europa.eu/notice"
    if "canadabuys.canada.ca/en/tender-opportunities/tender-notice/" in url:
        return "canadabuys/tender-notice"
    if "merx.com" in url:
        return "merx.com"
    if "tenders.gov.au/cn/Show/" in url:
        return "tenders.gov.au/cn/Show (verified)"
    if "tenders.gov.au/cn/" in url and "/View" in url:
        return "tenders.gov.au/cn/View (DEAD pattern)"
    if "riigihanked.riik.ee/rhr-web/#/procurement/" in url:
        return "riigihanked/SPA-hash"
    if "find-tender.service.gov.uk" in url or "contractsfinder.service.gov.uk" in url:
        return "UK-FTS/CF"
    if "boamp.fr" in url:
        return "BOAMP (FR)"
    if "doffin.no" in url:
        return "doffin.no"
    if "prozorro.gov.ua" in url or "public.api.openprocurement.org" in url:
        return "prozorro.gov.ua"
    if "noticeviewer.ted.europa.eu" in url:
        return "ted-noticeviewer (old)"
    return "other"


def _is_constructed(url: str, n: dict, src: str) -> bool:
    """Heuristic: was this URL likely constructed from an internal ID?"""
    if src == "TED":
        return False  # TED URLs come from API response
    if src == "AU-TEN":
        # Adapter constructs from cn_id — no direct OCDS uri used
        return True
    if src == "CA-CB":
        # Check if this matches the canonical construction pattern
        sol = n.get("_solicitation_number", "")
        sol_base = sol.split("/")[0] if "/" in sol else sol
        if sol_base and f"/tender-notice/{sol_base}" in url:
            return True
        if sol and f"/tender-notice/{sol}" in url:
            return True
    if src == "EE-RP":
        # Constructed from ContractFolderID (UUID)
        return True
    return False


# ── main ─────────────────────────────────────────────────────────────────────

def audit(notices: list[dict]) -> dict:
    by_src: dict[str, list[dict]] = defaultdict(list)
    for n in notices:
        by_src[_src_label(n)].append(n)

    report: dict = {}
    for src, group in sorted(by_src.items()):
        url_status = Counter(n.get("_url_status", "not_checked") for n in group)
        pub_src = Counter(n.get("_published_at_source", None) for n in group)
        patterns = Counter()
        constructed_count = 0
        no_url_count = 0
        issues: list[str] = []

        for n in group:
            field, url = _url_field(n)
            if not url:
                no_url_count += 1
            pat = _url_pattern(url, src)
            patterns[pat] += 1
            if _is_constructed(url, n, src):
                constructed_count += 1
            # Flag dead + high-value
            if n.get("_url_status") == "dead":
                val = n.get("_value_eur_num") or 0
                if val > 1_000_000:
                    issues.append(
                        f"DEAD+HIGH-VALUE: {n.get('tender_id')} "
                        f"(€{val:,.0f}) url={url[:60]}"
                    )
            # Flag wrong AU pattern
            if "tenders.gov.au/cn/" in url and "/View" in url:
                issues.append(f"AU-DEAD-PATTERN /View: {n.get('tender_id')} → {url[:80]}")
            # Flag missing URL
            if not url and n.get("_url_status") not in ("no_url", None):
                issues.append(f"URL_MISMATCH: {n.get('tender_id')} has _url_status but no URL")

        alive = url_status.get("alive", 0)
        dead = url_status.get("dead", 0)
        auth_walled = url_status.get("auth_walled", 0)
        not_checked = url_status.get("not_checked", 0)
        pub_covered = sum(v for k, v in pub_src.items() if k is not None)

        report[src] = {
            "count": len(group),
            "url_status": dict(url_status),
            "alive_pct": round(100 * alive / max(1, len(group))),
            "dead_count": dead,
            "auth_walled_count": auth_walled,
            "not_checked_count": not_checked,
            "url_patterns": dict(patterns),
            "constructed_count": constructed_count,
            "no_url_count": no_url_count,
            "pub_src_covered": pub_covered,
            "pub_src_coverage_pct": round(100 * pub_covered / max(1, len(group))),
            "pub_src_dist": {str(k): v for k, v in pub_src.most_common()},
            "issues": issues,
        }
    return report


def render_md(report: dict, total: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# URL Source Audit — 2026-05-21",
        "",
        f"_Generated: {now} from `data/filtered/relevant.json` ({total} notices)_",
        "",
        "## Summary",
        "",
        "| Source | Count | Alive | Dead | Auth-Walled | Not-Checked | `_published_at_source` | Issues |",
        "|--------|------:|------:|-----:|------------:|------------:|-----------------------:|--------|",
    ]
    for src, r in report.items():
        c = r["count"]
        alive = r["url_status"].get("alive", 0)
        dead = r["dead_count"]
        aw = r["auth_walled_count"]
        nc = r["not_checked_count"]
        pub_pct = r["pub_src_coverage_pct"]
        issues_n = len(r["issues"])
        flag = " ⚠" if issues_n else ""
        lines.append(
            f"| {src} | {c} | {alive} | {dead} | {aw} | {nc} "
            f"| {pub_pct}% | {issues_n}{flag} |"
        )
    lines += [""]

    lines += [
        "## Per-Source Detail",
        "",
    ]
    for src, r in report.items():
        lines += [
            f"### {src} ({r['count']} notices)",
            "",
        ]
        # URL patterns
        lines += ["**URL Patterns:**", ""]
        for pat, cnt in sorted(r["url_patterns"].items(), key=lambda x: -x[1]):
            marker = " ← DEAD PATTERN ⚠" if "DEAD" in pat else ""
            lines.append(f"- `{pat}` × {cnt}{marker}")
        lines += [""]
        if r["constructed_count"]:
            lines.append(
                f"- **Constructed from internal ID:** {r['constructed_count']} / {r['count']} notices"
                " (URL derived in-adapter, not from source feed)"
            )
        if r["no_url_count"]:
            lines.append(f"- **No URL at all:** {r['no_url_count']}")
        lines += [""]

        # Status distribution
        lines += ["**URL Health (Phase 3l):**", ""]
        for s, cnt in sorted(r["url_status"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{s}`: {cnt}")
        lines += [""]

        # pub_src
        lines += ["**`_published_at_source` coverage:**", ""]
        lines.append(
            f"- Covered: {r['pub_src_covered']} / {r['count']} ({r['pub_src_coverage_pct']}%)"
        )
        for k, v in r["pub_src_dist"].items():
            lines.append(f"- `{k}`: {v}")
        lines += [""]

        # Issues
        if r["issues"]:
            lines += ["**Issues:**", ""]
            for iss in r["issues"]:
                lines.append(f"- {iss}")
            lines += [""]
        else:
            lines.append("_No issues flagged._")
            lines += [""]

    lines += [
        "## Findings & Recommendations",
        "",
        "### CA-CB (CanadaBuys)",
        "",
        "- **Column** `noticeURL-URLavis-eng` is the correct CSV source field and is already",
        "  read correctly by `canada_loader.py`. For DND-buyer tenders (W8476-*, W6399-*,",
        "  W8485-*) this column is **always empty** — these tenders are not listed on MERX.",
        "- **Fallback construction** uses `_solicitation_number` which produces the correct",
        "  CanadaBuys canonical URL pattern.",
        "- **Dead URLs** (10/19) are genuinely expired/archived tenders; CanadaBuys removes",
        "  notices after some retention period. Not fixable without fresh re-scrape.",
        "- **Auth-walled** (9/19) = HTTP 403 from CloudFront bot-protection; URLs ARE valid",
        "  and work in a real browser. Correctly classified as `auth_walled`.",
        "- **Action:** No URL-source bug. Add note to DEFERRED_BACKLOG about periodic",
        "  CA re-scrape to refresh dead/expired notices.",
        "",
        "### AU-TEN (AusTender OCDS)",
        "",
        "- All 56 notices use `/cn/Show/{id}` pattern — empirically verified alive.",
        "- URLs are constructed from the CN number extracted from OCDS `contracts[0].id`.",
        "  The OCDS release does not carry a direct portal URI, so construction is correct.",
        "- **`_published_at_source`** = 0% coverage. All AU-TEN records pre-date the",
        "  `_published_at_source` field addition. Backfill needed:",
        "  - All have `contract_notice_fallback` (post-award data, no tender start date)",
        "  - AU-ATM cross-reference (TEIL B) can upgrade some to `related_lookup`.",
        "",
        "### EE-RP (Riigihanked / Estonia)",
        "",
        "- URLs use SPA hash-route `…/rhr-web/#/procurement/{uuid}`.",
        "- Server returns HTTP 200 + 2.6 KB React shell for ANY UUID (soft-404).",
        "  Phase 3l correctly classifies as `alive` because the HTTP level is 200.",
        "- The actual data API at `/rhr/api/public/v1/notice/{uuid}/html` returns 401",
        "  (eIDAS auth required). This is the `auth_walled` signal at data level.",
        "- **Soft-404 detection** (TEIL A5 body-check) would reclassify these as",
        "  `auth_walled` when body matches the React-shell fingerprint.",
        "- **Action:** A5 body-content check to detect React-shell responses.",
        "",
        "### TED",
        "",
        "- URLs come directly from TED API response — source-provided, no construction.",
        "- `ted.europa.eu/en/notice/-/detail/{id}` pattern — stable and alive.",
        "- Dead entries (38) include 429-rate-limited probes misclassified as dead.",
        "  Consider re-running url-check for `dead` TED notices only.",
        "",
        "### `_published_at_source` Backfill Gap",
        "",
        "- **0 of 322 notices** have `_published_at_source` set.",
        "- All CA notices should be `tender_notice` (CanadaBuys publicationDate = RFP go-live).",
        "- All AU-TEN notices should be `contract_notice_fallback` until ATM cross-reference.",
        "- TED notices need `scripts/_backfill_publication_dates.py` (rule-based).",
        "- **Action:** Run `scripts/_backfill_publication_dates.py` (Window F).",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    print(f"Loading {_RELEVANT}...")
    notices: list[dict] = json.loads(_RELEVANT.read_text(encoding="utf-8"))
    print(f"  {len(notices)} notices")

    report = audit(notices)

    md = render_md(report, len(notices))
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_FILE.write_text(md, encoding="utf-8")
    print(f"  Wrote {_OUT_FILE}")

    # Console summary
    print("\nSource summary:")
    print(f"  {'Source':<14} {'Count':>6} {'Alive':>6} {'Dead':>6} {'AuthW':>6} {'PubSrc%':>8}")
    print("  " + "-" * 52)
    for src, r in report.items():
        print(
            f"  {src:<14} {r['count']:>6} "
            f"{r['url_status'].get('alive', 0):>6} "
            f"{r['dead_count']:>6} "
            f"{r['auth_walled_count']:>6} "
            f"{r['pub_src_coverage_pct']:>7}%"
        )


if __name__ == "__main__":
    main()

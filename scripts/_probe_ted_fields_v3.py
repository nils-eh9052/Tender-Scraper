"""TED v3 search-API exhaustive field probe — Sprint 2026-05-17.

Builds a generous candidate list from the eForms SDK domains we suspect
exist (organisation/lot/award/strategic-procurement/modification/…) and
binary-search-tests each one against ``api.ted.europa.eu``. Outputs the
union of *validated* field names plus sample values pulled across 6
notices that span CN / CAN / PIN / VEAT / MOD types.

Usage::

    python3 scripts/_probe_ted_fields_v3.py
    python3 scripts/_probe_ted_fields_v3.py --quick     # uses cached field-validity result

Output:
- ``data/.ted_fields_v3_probe.json`` — full per-notice payloads
- ``data/.ted_fields_v3_valid.json`` — sorted list of API-valid field names
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
import urllib3

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_SSL = os.environ.get("SSL_VERIFY_DISABLE", "").strip().lower() not in ("1", "true", "yes")
if not _SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.api_client import ALL_FIELDS  # noqa: E402

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "TED-Defence-Trailer-Research/1.0",
}
VALID_PATH = ROOT / "data" / ".ted_fields_v3_valid.json"
PROBE_PATH = ROOT / "data" / ".ted_fields_v3_probe.json"

# Six notices spanning notice-types for the sample-value pull.
SAMPLE_NOTICES = (
    "212474-2026",  # DE CN-standard (eForms)
    "326948-2025",  # NL CAN-standard (eForms, awarded)
    "77247-2026",   # FR CN-standard with PIN-like budget breakdown
    "798124-2025",  # CZ CN-standard (eForms)
    "261427-2025",  # PL CAN-standard
    "182178-2026",  # SE CAN-standard with winner + lots
)

# Generous candidate field-name list derived from eForms SDK (BT-* codes
# mapped to API path-names) + intuition. The API drops unknown names with
# HTTP 400, so we binary-search to find the validated subset.
def candidates() -> list[str]:
    base = set(ALL_FIELDS)
    extra = {
        # Organisation / contracting party
        "organisation-name", "organisation-name-part", "organisation-name-buyer",
        "organisation-identifier-part", "organisation-identifier-buyer",
        "organisation-website-part",
        "buyer-legal-type", "buyer-legal-type-description",
        "buyer-contracting-type", "buyer-activity-authority",
        "contracting-party-name", "contracting-party-id",
        # Email / contact for AdditionalInformation
        "additional-information", "additional-information-address",
        "email-buyer", "email-contracting-party",
        "contracting-party-email", "ContactInformation-email",
        # Lot / project structure
        "lot-id", "lot-title", "title-lot", "description-lot-procedure",
        "lot-internal-identifier", "lot-internal-identifier-part",
        "lot-cpv", "cpv-lot", "additional-cpv-lot",
        # Award / contract result
        "contract-conclusion-date", "contract-conclusion-date-lot",
        "tenders-received", "tenders-received-lot", "tenders-received-electronic",
        "tenders-received-sme", "tenders-received-non-eu",
        "tenders-received-other-eu",
        "tender-amount", "tender-amount-currency",
        "award-decision-date", "award-decision-date-lot",
        "award-criterion-type", "award-criterion-name",
        "award-criterion-weight", "award-criterion-description",
        # Subcontracting (BT-731, BT-553)
        "subcontracting", "subcontracting-description", "subcontracting-percentage",
        "subcontracting-value", "subcontracting-obligation",
        # Strategic / reserved / innovation / green (BT-771 / BT-755 / BT-805)
        "strategic-procurement", "strategic-procurement-lot",
        "innovation-procurement", "innovation-procurement-lot",
        "green-procurement", "green-procurement-lot",
        "social-procurement", "social-procurement-lot",
        "reserved-procurement", "reserved-procurement-lot",
        "reserved-execution",
        "accessibility-criteria", "accessibility-justification",
        # Justification / Direct-award (BT-135 / BT-136 / BT-1252)
        "procedure-justification", "procedure-justification-text",
        "procedure-justification-code",
        "direct-award-justification", "direct-award-justification-text",
        # Modification (CAN-modif / corrigendum)
        "change-publication-number", "change-description",
        "change-reason", "change-reason-description", "change-actor",
        "change-date",
        # Related-notice / reference
        "previous-publication-number", "reference-publication-number",
        "related-notice", "related-notice-publication-id",
        "changed-notice-identifier",
        # PIN-specific (Prior Information)
        "pin-launch-date", "pin-tender-launch-date",
        "future-procurement-launch-date",
        # Procurement project meta
        "procurement-project-id", "procurement-project-id-part",
        "framework-agreement", "framework-agreement-lot",
        "framework-duration", "framework-duration-lot",
        "framework-max-participants", "framework-max-participants-lot",
        "dynamic-purchasing-system", "dynamic-purchasing-system-lot",
        # Place of performance
        "place-of-performance-nuts", "place-of-performance-nuts-lot",
        "place-of-performance-street",
        # Review / appeals (BT-712 / BT-708)
        "review-procedure-body", "review-procedure-body-name",
        "review-info", "review-deadline-description",
        "review-receiver-party",
        # Document-language
        "communication-language", "communication-language-lot",
        "submission-language", "submission-language-lot",
        # GPA / Trade-agreement applicability
        "gpa-applicability", "gpa-applicability-lot",
        # Concession-specific
        "concession-revenue-buyer", "concession-revenue-user",
        "concession-value", "concession-value-currency",
        # Variant tender / Bids
        "variants-permitted", "variants-permitted-lot",
        "tenders-multiple-permitted",
        # Performance contract data
        "performance-conditions", "performance-conditions-text",
        "performance-staff-qualification",
        # Compliance / electronic invoice
        "electronic-invoice", "electronic-payment",
        # Award-criteria-method (BT-543)
        "award-criteria-order-of-importance", "award-criteria-complicated",
        # Bidder list (rare but valuable when present)
        "winner-list", "all-tenderers", "bidder-list",
        # Misc
        "submission-method", "submission-method-lot",
        "submission-electronic", "submission-postal",
        "tool-name", "tool-uri",
    }
    return sorted(base | extra)


def probe(pub_num: str, fields: list[str], retries: int = 4):
    payload = {
        "query": f'publication-number="{pub_num}"',
        "fields": fields,
        "page": 1, "limit": 1, "paginationMode": "PAGE_NUMBER",
    }
    for attempt in range(retries):
        try:
            r = requests.post(SEARCH_URL, json=payload, headers=HEADERS,
                              timeout=30, verify=_SSL)
        except Exception as exc:
            if attempt + 1 < retries:
                time.sleep(3 * (attempt + 1)); continue
            return {}, {"error": f"network: {exc}"}
        if r.status_code == 200:
            body = r.json()
            return (body.get("notices") or [{}])[0], {}
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1)); continue
        return {}, {"status": r.status_code, "body": r.text[:160]}
    return {}, {"status": 429}


def binary_search_valid(pub_num: str, fields_to_test: list[str]) -> set[str]:
    """Recursive halving on 400 errors → returns the set the API accepts."""
    valid: set[str] = set()

    def rec(batch):
        if not batch: return
        _, err = probe(pub_num, batch)
        if not err:
            valid.update(batch)
            return
        if len(batch) == 1:
            return  # invalid
        mid = len(batch) // 2
        rec(batch[:mid]); rec(batch[mid:])

    rec(list(fields_to_test))
    return valid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="Reuse cached valid-fields list; only re-fetch sample values.")
    args = ap.parse_args()

    cands = candidates()
    new_cands = sorted(set(cands) - set(ALL_FIELDS))
    print(f"  {len(cands)} total candidates ({len(new_cands)} beyond ALL_FIELDS)")

    if args.quick and VALID_PATH.exists():
        valid = set(json.loads(VALID_PATH.read_text())["valid"])
        print(f"  [quick] using cached {len(valid)} valid field names")
    else:
        print("  Probing validity (binary-search per notice, may take 2-3 min) …")
        valid: set[str] = set()
        for nid in SAMPLE_NOTICES[:2]:
            print(f"    probing {nid}")
            valid |= binary_search_valid(nid, new_cands)
            time.sleep(2)
        valid |= set(ALL_FIELDS)
        VALID_PATH.write_text(json.dumps({"valid": sorted(valid)},
                                         ensure_ascii=False, indent=2))

    new_valid = sorted(valid - set(ALL_FIELDS))
    print()
    print(f"  Validated {len(new_valid)} NEW fields beyond ALL_FIELDS:")
    for f in new_valid:
        print(f"    + {f}")

    # ── Phase 2: pull values across 6 sample notices ──
    fetch_set = sorted(set(ALL_FIELDS) | valid)
    samples: dict = {}
    for nid in SAMPLE_NOTICES:
        time.sleep(2)
        body, err = probe(nid, fetch_set)
        if err:
            print(f"    [data-fetch] {nid} err: {err}")
            continue
        samples[nid] = body

    PROBE_PATH.write_text(json.dumps({
        "valid_new_fields": new_valid,
        "samples": samples,
    }, ensure_ascii=False, indent=2))
    print(f"\n  Wrote samples → {PROBE_PATH}")

    # ── Phase 3: per-field summary
    print()
    print("=== Sample-value coverage per new field ===")
    for f in new_valid:
        examples = []
        for nid, body in samples.items():
            v = body.get(f)
            if v not in (None, "", [], {}):
                examples.append((nid, v))
        cov = f"{len(examples)}/{len(samples)}"
        ex_str = (json.dumps(examples[0][1], ensure_ascii=False)[:80]
                  if examples else "—")
        ex_nid = examples[0][0] if examples else "—"
        print(f"  {f:55s} {cov}  (e.g. {ex_nid}: {ex_str})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

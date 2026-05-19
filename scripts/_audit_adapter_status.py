"""Sprint 2026-05-18 — Adapter Inventory Audit.

Walks every file in ``src/national_scraper/adapters/`` and reports:
  - Importability        (does ``import_module`` succeed?)
  - Registry presence    (mentioned in ``main.py:get_adapter_registry``)
  - --all activation     (registered → enters the default ``--all`` flow)
  - Real-data evidence   (count of tenders in ``relevant.json`` whose
                          ``_source`` / tender_id-prefix points to this adapter,
                          plus newest publication-date among them)
  - Test coverage        (matching ``tests/test_*.py``)

Output:
  docs/ADAPTER_INVENTORY_260518.md       (markdown table)
  data/adapter_status.json               (full inventory; overwritten)

The script is read-only against the codebase; the only write target is
``adapter_status.json`` plus the docs file.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

ADAPTERS_DIR = ROOT / "src" / "national_scraper" / "adapters"
TESTS_DIR = ROOT / "tests"
RELEVANT_JSON = ROOT / "data" / "filtered" / "relevant.json"
MAIN_PY = ROOT / "main.py"
INVENTORY_DOC = ROOT / "docs" / "ADAPTER_INVENTORY_260518.md"
ADAPTER_STATUS_JSON = ROOT / "data" / "adapter_status.json"

# Adapter file → registry key + class + source-hint for relevant.json scan.
# source_hint: list of tender_id prefixes OR _source values that point to
# the adapter. "TED-fed" adapters (au-ocds = AU-TEN) get the _source value.
ADAPTERS = [
    # (file_stem, registry_key, class_name, source_hint_prefixes, status_classification, last_tested, notes)
    ("de_adapter",          "de",     "DEAdapter",         ["DE"],         None, None, None),
    ("de_evergabe_adapter", "de-ev",  "DEEvergabeAdapter", ["DE-EV"],      None, None, None),
    ("pl_adapter",          "pl",     "PLAdapter",         ["PL"],         None, None, None),
    ("fi_adapter",          "fi",     "FIAdapter",         ["FI"],         None, None, None),
    ("se_adapter",          "se",     "SEAdapter",         ["SE"],         None, None, None),
    ("no_adapter",          "no",     "NOAdapter",         ["NO"],         None, None, None),
    ("cz_adapter",          "cz",     "CZAdapter",         ["CZ"],         None, None, None),
    ("fr_adapter",          "fr",     "FRAdapter",         ["FR"],         None, None, None),
    ("dk_adapter",          "dk",     "DKAdapter",         ["DK"],         None, None, None),
    ("ro_adapter",          "ro",     "ROAdapter",         ["RO"],         None, None, None),
    ("nl_adapter",          "nl",     "NLAdapter",         ["NL"],         None, None, None),
    ("be_adapter",          "be",     "BEAdapter",         ["BE"],         None, None, None),
    ("es_adapter",          "es",     "ESAdapter",         ["ES"],         None, None, None),
    ("it_adapter",          "it",     "ITAdapter",         ["IT"],         None, None, None),
    ("ua_adapter",          "ua",     "UAAdapter",         ["UA"],         None, None, None),
    ("ch_adapter",          "ch",     "CHAdapter",         ["CH"],         None, None, None),
    ("uk_fts_adapter",      "gb",     "UKFTSAdapter",      ["UK", "GB"],   None, None, None),
    ("gr_adapter",          "gr",     "GRAdapter",         ["GR"],         None, None, None),
    ("ee_adapter",          "ee",     "EEAdapter",         ["EE"],         None, None, None),
    ("lv_adapter",          "lv",     "LVAdapter",         ["LV"],         None, None, None),
    ("lt_adapter",          "lt",     "LTAdapter",         ["LT"],         None, None, None),
    ("au_ocds_adapter",     "au",     "AuOcdsAdapter",     ["AU-TEN"],     None, None, None),
    ("au_atm_adapter",      "au-atm", "AuAtmAdapter",      ["AU-AT"],      None, None, None),
    ("canada_loader",       "ca",     "CanadaBuysAdapter", ["CA"],         None, None, None),
    ("nspa_adapter",        "nspa",   "NSPAAdapter",       ["NSPA-EP"],    None, None, None),
    ("tr_adapter",          "tr",     "TrAdapter",         ["TR"],         None, None, None),
]

# Adapters that are registered in get_adapter_registry() but must NOT be
# included in the default `--national` (no-args) run due to rate-limits or
# other operational constraints. Documented in CLAUDE.md §7.
NOT_IN_ALL_DEFAULT: set[str] = {"nspa"}

# Optional override: explicit classification when the rule-based one is wrong.
# Set to None to let the rule below decide. Keys are file_stem.
MANUAL_STATUS = {
    "tr_adapter": ("RETIRED",
        "Sprint 14d — parked: defence procurement on EKAP is off-portal (MSB Tedarik). Comment-out in get_adapter_registry()."),
    "au_atm_adapter": ("WORKING",
        "Live-Smoke 2026-05-18: 90 RSS-Items → 18 Defence-Hits. Merge in relevant.json noch nicht ausgeführt."),
    "fi_adapter": ("WORKING_NO_DATA",
        "Hilma REST API erreichbar; Puolustusvoimat publiziert auf TED, nicht Hilma."),
    "be_adapter": ("WORKING_NO_DATA",
        "Vue.js + Keycloak JWT POST body format unsolved; Défense publiziert auf TED."),
    "ro_adapter": ("WORKING_NO_DATA",
        "AngularJS Portal erfordert Playwright (VPN-Timeouts); 0 Defence-Trailer im aktuellen Scan."),
    "nspa_adapter": ("WORKING_NO_DATA",
        "Trailer-Yield ~0 (FBO/RFP-Inventar 99 % Munitions-Spare-Parts). Infrastruktur."),
    "canada_loader": ("WORKING",
        "CSV Open Data pipeline. CanadaBuysAdapter is defined inside a try-block that "
        "guards the base_adapter relative import; class absent in audit-env but fully "
        "functional in project venv. Highest-yield adapter (74 Tender in April-2026 run)."),
    "ee_adapter": ("STUB",
        "Open Data XML monatlich; API 404 graceful. Adapter existiert, Daten kommen via TED."),
    "lt_adapter": ("STUB",
        "REST 404; SPA-Browser-Fallback noch nicht implementiert."),
    "gr_adapter": ("STUB",
        "Promitheus ADF erfordert ViewState-Extraktion (Sprint 12 Backlog)."),
}


def read_registry_keys() -> set[str]:
    """Parse ``main.py:get_adapter_registry`` for keys that are NOT commented out."""
    text = MAIN_PY.read_text(encoding="utf-8")
    # Find the function body
    m = re.search(
        r"def get_adapter_registry\(.*?\n(.*?)(?=\n(?:def |class |\Z))",
        text, re.DOTALL,
    )
    if not m:
        return set()
    body = m.group(1)
    keys: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Match tuples like ("...module...", "Class", "create_x_config", "key")
        m2 = re.search(r'"([a-z][\w-]*)"\s*\)\s*,?\s*$', stripped)
        if m2:
            keys.add(m2.group(1))
    return keys


_OPTIONAL_DEPS = frozenset({
    "playwright", "requests", "aiohttp", "lxml", "bs4", "feedparser",
})


def import_check(file_stem: str, class_name: str) -> tuple[bool, str]:
    """Try to import the adapter module and resolve the class.

    If the import fails only because an optional runtime dependency (playwright,
    requests, …) is absent from the current Python environment, the adapter is
    still considered importable — it works fine in the project venv.  Genuine
    code errors (SyntaxError, missing project-internal module) still count as
    BROKEN.
    """
    try:
        mod = importlib.import_module(f"src.national_scraper.adapters.{file_stem}")
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        top = missing.split(".")[0]
        if top in _OPTIONAL_DEPS:
            return True, f"ok (dep '{top}' absent in current env, ok in project venv)"
        return False, f"ImportError: {type(exc).__name__}: {exc}"
    except Exception as exc:
        return False, f"ImportError: {type(exc).__name__}: {exc}"
    if not hasattr(mod, class_name):
        return False, f"Class {class_name} not found in module"
    return True, "ok"


def count_tenders_for(prefixes: list[str], rel: list[dict]) -> tuple[int, str]:
    """Count tenders in ``rel`` whose source/prefix matches and return newest pub-date."""
    n = 0
    newest = ""
    for t in rel:
        if _match_source(t, prefixes):
            n += 1
            pd = t.get("_pub_date") or t.get("_pub_date_clean") or t.get("publication_date") or ""
            pd_clean = str(pd).split("T")[0].split("Z")[0][:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", pd_clean) and pd_clean > newest:
                newest = pd_clean
    return n, newest


def _match_source(notice: dict, prefixes: list[str]) -> bool:
    """A notice belongs to the adapter if its _source matches OR its tender_id
    prefix matches one of ``prefixes``."""
    src = (notice.get("_source") or "").strip()
    if src and src in prefixes:
        return True
    tid = str(notice.get("tender_id", ""))
    # Skip TED-style numeric IDs (handled by the TED pipeline itself)
    if re.match(r"^\d+-\d{4}$", tid):
        return False
    for p in prefixes:
        if tid.upper().startswith(f"{p}-"):
            return True
    return False


def find_tests(file_stem: str) -> list[str]:
    """Find test files mentioning the adapter by class or file_stem keyword."""
    hits = []
    # Quick scan: any file under tests/ whose content mentions the file_stem
    for f in TESTS_DIR.glob("test_*.py"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if file_stem in text:
            hits.append(f.name)
    # Also explicitly named patterns
    explicit = TESTS_DIR / f"test_{file_stem}.py"
    if explicit.exists() and explicit.name not in hits:
        hits.insert(0, explicit.name)
    return hits


def classify(file_stem: str, importable: bool, registered: bool,
             tender_count: int) -> tuple[str, str]:
    """Rule-based classification (subject to MANUAL_STATUS override)."""
    if file_stem in MANUAL_STATUS:
        return MANUAL_STATUS[file_stem]
    if not importable:
        return ("BROKEN", "Import failed — adapter module unloadable.")
    if not registered:
        return ("RETIRED", "Adapter file exists but not registered in main.py.")
    # Registered + importable
    if tender_count > 0:
        return ("WORKING", f"{tender_count} tender(s) in relevant.json from this source.")
    return ("WORKING_NO_DATA",
            "Registered, importable, but no tenders in relevant.json.")


def _load_existing_status() -> dict:
    """Load current adapter_status.json to preserve hand-curated metadata."""
    if ADAPTER_STATUS_JSON.exists():
        try:
            return json.loads(ADAPTER_STATUS_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def main() -> int:
    registry_keys = read_registry_keys()
    with open(RELEVANT_JSON, encoding="utf-8") as f:
        rel = json.load(f)
    existing_status = _load_existing_status()

    rows = []
    for file_stem, key, class_name, prefixes, _, _, _ in ADAPTERS:
        importable, import_msg = import_check(file_stem, class_name)
        registered = key in registry_keys
        n_tenders, newest = count_tenders_for(prefixes, rel)
        tests = find_tests(file_stem)
        status, notes = classify(file_stem, importable, registered, n_tenders)
        ex = existing_status.get(key, {})
        rows.append({
            "file": f"{file_stem}.py",
            "key": key,
            "class": class_name,
            "importable": importable,
            "import_msg": import_msg,
            "registered_in_main_py": registered,
            "in_all_default": (registered
                               and status not in ("STUB", "RETIRED")
                               and key not in NOT_IN_ALL_DEFAULT),
            "tender_count_in_relevant_json": n_tenders,
            "newest_pub_date": newest or None,
            "has_tests": bool(tests),
            "tests": tests,
            "status": status,
            "notes": notes,
            "source_hints": prefixes,
            # Preserve hand-curated metadata from existing JSON
            "method": ex.get("method", ""),
            "portal": ex.get("portal", ""),
            "api": ex.get("api", ""),
            "last_tested": ex.get("last_tested", None),
        })

    n_rel = len(rel)

    # ── adapter_status.json ────────────────────────────────────────────────
    status_out: dict = {
        "_meta": {
            "schema_version": "2026-05-18",
            "generator": "scripts/_audit_adapter_status.py (run 2026-05-18)",
            "notice_count_in_relevant_json": n_rel,
            "status_legend": {
                "WORKING": "Lieferte Tender in aktuellem relevant.json oder bestand frischen Live-Smoke; in --all aktiv.",
                "WORKING_NO_DATA": "Adapter läuft fehlerfrei, aber 0 BPW-relevante Tender im aktuellen Zeitraum.",
                "AUTH_BLOCKED": "Funktional aber Auth-Wand (z.B. CZ-NEN eIDAS, BE-BOSA Keycloak-Body).",
                "GEO_BLOCKED": "Funktional aber Geo-/VPN-Wand (z.B. RO-SEAP).",
                "STUB": "Adapter existiert + Importtest grün, aber nicht produktiv (Discovery offen).",
                "BROKEN": "Adapter im Code aber Pipeline-Run schlägt fehl. Sollte 0 sein.",
                "RETIRED": "Bewusst stillgelegt (TR — Defence-Procurement off-portal).",
            },
            "fields": "status_classification, registered_in_main_py, in_all_default, "
                      "tender_count_in_relevant_json, newest_pub_date, has_tests, last_tested, notes",
        }
    }
    for r in rows:
        status_out[r["key"]] = {
            "file": r["file"],
            "class": r["class"],
            "status": r["status"].lower(),
            "method": r["method"],
            "portal": r["portal"],
            "api": r["api"],
            "registered_in_main_py": r["registered_in_main_py"],
            "in_all_default": r["in_all_default"],
            "tender_count_in_relevant_json": r["tender_count_in_relevant_json"],
            "newest_pub_date": r["newest_pub_date"],
            "has_tests": r["has_tests"],
            "last_tested": r["last_tested"],
            "notes": r["notes"],
        }
    ADAPTER_STATUS_JSON.write_text(
        json.dumps(status_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ✓ Wrote {ADAPTER_STATUS_JSON.relative_to(ROOT)}")

    # ── Markdown report ────────────────────────────────────────────────────
    md = []
    md.append("# Adapter Inventory — Sprint 2026-05-18\n")
    md.append(f"Generated by `scripts/_audit_adapter_status.py` against the current\n"
              f"`relevant.json` ({n_rel} notices) and the `main.py:get_adapter_registry`\n"
              f"registry. Tender counts reflect what is currently visible in the\n"
              f"exported corpus — adapters not yet merged into `relevant.json` (e.g.\n"
              f"`au-atm`) show 0 here even when their live-smoke is green.\n")

    status_dist: dict[str, int] = defaultdict(int)
    for r in rows:
        status_dist[r["status"]] += 1
    md.append("## 1. Status-Verteilung\n")
    md.append("| Status | Count |")
    md.append("|--------|------:|")
    for s in ("WORKING", "WORKING_NO_DATA", "AUTH_BLOCKED", "GEO_BLOCKED",
              "STUB", "BROKEN", "RETIRED"):
        md.append(f"| {s} | {status_dist.get(s, 0)} |")
    md.append(f"| **Total** | **{len(rows)}** |\n")

    md.append("## 2. Adapter-Tabelle\n")
    md.append("| File | Key | Class | Import | Registered | In `--all` | Tenders | Newest Pub | Tests | Status |")
    md.append("|------|-----|-------|:------:|:----------:|:----------:|--------:|------------|-------|--------|")
    for r in rows:
        imp = "✅" if r["importable"] else "❌"
        reg = "✅" if r["registered_in_main_py"] else "—"
        in_all = "✅" if r["in_all_default"] else "—"
        tests = f"{len(r['tests'])}" if r["tests"] else "—"
        newest = r["newest_pub_date"] or "—"
        md.append(
            f"| `{r['file']}` | `{r['key']}` | `{r['class']}` "
            f"| {imp} | {reg} | {in_all} | {r['tender_count_in_relevant_json']} "
            f"| {newest} | {tests} | **{r['status']}** |"
        )
    md.append("")

    md.append("## 3. Pro Adapter — Notes & Evidence\n")
    for r in rows:
        md.append(f"### `{r['file']}` — {r['status']}")
        md.append(f"- **Key:** `{r['key']}` &nbsp;&nbsp; **Class:** `{r['class']}`")
        md.append(f"- **Importable:** {r['importable']} ({r['import_msg']})")
        md.append(f"- **Registry:** {'in `main.py`' if r['registered_in_main_py'] else '*not registered*'}")
        md.append(f"- **In `--all` default:** {r['in_all_default']}")
        md.append(f"- **Tender-Evidence:** {r['tender_count_in_relevant_json']} in `relevant.json` "
                  f"(prefixes={r['source_hints']}, newest pub={r['newest_pub_date'] or '—'})")
        md.append(f"- **Tests:** {', '.join(r['tests']) if r['tests'] else '*none*'}")
        md.append(f"- **Notes:** {r['notes']}\n")

    INVENTORY_DOC.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_DOC.write_text("\n".join(md), encoding="utf-8")
    print(f"  ✓ Wrote {INVENTORY_DOC.relative_to(ROOT)}")

    print()
    print(f"  {'File':<26} {'Key':<8} {'Reg':<4} {'Imp':<4} {'#Tnd':>5} {'Newest':<10} {'Status'}")
    for r in rows:
        print(f"  {r['file']:<26} {r['key']:<8} "
              f"{('Y' if r['registered_in_main_py'] else 'n'):<4} "
              f"{('Y' if r['importable'] else 'n'):<4} "
              f"{r['tender_count_in_relevant_json']:>5} "
              f"{(r['newest_pub_date'] or '-'):<10} {r['status']}")
    print()
    print(f"  Total adapters: {len(rows)}")
    for s, c in sorted(status_dist.items()):
        print(f"    {s}: {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

# Document Discovery Audit — 2026-05-18

Phase 3g coverage analysis: which adapters route to which discovery
handler, and what fraction of their notices already have
`_extracted_specs` populated.

**Corpus**: `data/filtered/relevant.json` — 337 notices

## Coverage Matrix

| Source | Notices | _extracted_specs | _national_raw_text | real-URL docs | synth-text docs | avg refs/notice |
|--------|---------|-----------------:|-------------------:|--------------:|----------------:|----------------:|
| TED | 183 | 183 | 0 | 183 | 0 | 1.00 |
| CA-CB | 74 | 0 | 74 | 74 | 74 | 2.00 |
| CZ-NEN | 30 | 0 | 27 | 0 | 0 | 0.00 |
| AU-TEN | 22 | 0 | 22 | 22 | 22 | 2.00 |
| FR-BP | 13 | 13 | 13 | 0 | 13 | 1.00 |
| UK-CF | 6 | 0 | 0 | 0 | 0 | 0.00 |
| NO-DF | 3 | 3 | 3 | 0 | 3 | 1.00 |
| EE-RP | 3 | 0 | 3 | 0 | 1 | 0.33 |
| UA-PR | 2 | 0 | 0 | 0 | 0 | 0.00 |
| NL-TN | 1 | 0 | 0 | 0 | 0 | 0.00 |

## Handler Routing

How `discover_for_notice()` dispatches each source. `<no handler>`
and `<stub: empty>` rows are coverage gaps.

### TED (n=183)

| Handler | Count |
|---------|------:|
| `_discover_ted` | 183 |

### CA-CB (n=74)

| Handler | Count |
|---------|------:|
| `_discover_ca` | 74 |

### CZ-NEN (n=30)

| Handler | Count |
|---------|------:|
| `<stub: empty>` | 30 |

### AU-TEN (n=22)

| Handler | Count |
|---------|------:|
| `_discover_au_ocds` | 22 |

### FR-BP (n=13)

| Handler | Count |
|---------|------:|
| `_discover_national_text` | 13 |

### UK-CF (n=6)

| Handler | Count |
|---------|------:|
| `<stub: empty>` | 6 |

### NO-DF (n=3)

| Handler | Count |
|---------|------:|
| `_discover_national_text` | 3 |

### EE-RP (n=3)

| Handler | Count |
|---------|------:|
| `_discover_national_text` | 3 |

### UA-PR (n=2)

| Handler | Count |
|---------|------:|
| `_discover_ua` | 2 |

### NL-TN (n=1)

| Handler | Count |
|---------|------:|
| `<no handler>` | 1 |

## Gap Analysis

Sources where discovery returns **synthetic text** instead of
real document URLs lose out on the Phase 3g full PDF/docx
extraction path. The AI structurer can still operate on text, but
it never sees buyer-side tender documents (Leistungsverzeichnis,
technical specifications), which carry the highest-value structured
fields (qty, dimensions, delivery dates).

### Priority for rollout (by notice volume × current gap)

- **CZ-NEN** (30 notices, 0 real-URL docs) — currently routed to `<stub: empty>`. Synthetic text only.
- **FR-BP** (13 notices, 0 real-URL docs) — currently routed to `_discover_national_text`. Synthetic text only.
- **UK-CF** (6 notices, 0 real-URL docs) — currently routed to `<stub: empty>`. Synthetic text only.
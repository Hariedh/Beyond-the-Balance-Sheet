# Changed files and why

Audit and enhancement of the existing project; nothing was rewritten from scratch (the earlier `app.py` was replaced by a 7-step version because the workflow changed its structure; the prior copy is not shipped).

## Code
| File | Change | Why |
|---|---|---|
| `btb/persistence.py` (new) | Per-indicator streak/status logic | Persistent vs isolated, missing never "ok" |
| `btb/assessment.py` (new) | Rule explanations; layered year assessment | Show indicator/value/threshold/formula/why/history/peers/DQ/follow-up; separate breach, deterioration, convergence, conflict, data limitation, inconclusive |
| `btb/peers.py` (new) | Same-universe, comparable-period peer table and medians; OCF/EBIT, FCF margin | Fair benchmarking, no ranking |
| `btb/stress.py` (new) | Revenue/margin/fixed-cost stress with break-even | Explicit assumptions; safe edge cases |
| `btb/verification.py` (new) | Verification status helpers | Link filing checks to indicators |
| `btb/report.py` (new) | 8-section CSV report with basis labels | Separate observed, hypothesis, scenario |
| `btb/flags.py` | Persistence-based sustained rules, debt-rise materiality, NEGATIVE_FREE_CASH_FLOW, caveats | Fix B1/B2, avoid false reassurance |
| `btb/metrics.py` | `free_cash_flow_cr`, `context_notes` | FCF, ratio cautions |
| `btb/fmt.py` | Adaptive ratio precision; minus sign before ₹ | Fix B3/B4 |
| `btb/loader.py`, `btb/pipeline.py`, `btb/config.py` | Capex field; disclosure columns; verification loader; limitations text | Support new data |
| `btb/validation.py` | `negative_capex`; capex missing = info | Data quality |
| `btb/evidence.py`, `btb/ai_commentary.py` | Capex/FCF inputs; disclosure fields; follow-up for FCF rule | Keep AI/rules-only evidence consistent |
| `btb/db.py` | `db_is_stale()` | Fix B7 |
| `sql/schema.sql`, `views.sql`, `analysis_queries.sql` | capex, disclosure columns, `source_verification` table, debt-rise query matching Python | Parity between SQL and pandas |
| `app.py` | 7-step workflow UI | Phase 3 |
| `scripts/audit_recalc.py` (new) | Independent stdlib recompute -> reconciliation report | Phase 1 |
| `scripts/build_source_verification.py` (new) | Transcribed filing values -> `source_verification.csv` | Phase 2 |
| `scripts/make_verification_worksheet.py` (new) | Worksheet markdown | Deliverable 3 |
| `scripts/make_hand_check_sheet.py` | Hand-check worksheet CSV | Remaining years to check by hand |
| `scripts/build_real_financials.py` | Capex column, cross-check log, corrected EBIT/capex wording | Data transparency |

## Data
`data/raw/disclosures.csv` (5 entries), `data/raw/source_verification.csv` (61 rows), `data/raw/financials_real.csv` (capex added, numbers unchanged), `data/raw/financials_real_crosschecks.csv`.

## Tests (179 passing on Streamlit 1.66)
`tests/test_audit_features.py` (new, 37): persistence (consecutive, gap, missing, new/recovered, boundary, 15-month, empty), strict threshold boundary, stress (formulas, margin applied to scenario revenue, FCF, zero/missing interest, negative EBIT, invalid inputs, break-even round trip, 15-month), peers (universe separation, non-12-month exclusion, missing year, too few peers, empty), verification statuses and loader, `db_is_stale`, empty dataset, assessment (conflict, convergence, inconclusive, 15-month), explanation columns, report sections/labels. `tests/test_app.py`, `test_review_fixes.py`, `conftest.py` updated.

## Browser testing (Chromium via Playwright, headless, against the running app)
Covered: initial render and scrolling screenshots; switching to UltraTech, DEMOA (illustrative banner, DEMO-only peer medians n=2) and Ambuja (15-month warning); threshold inputs (coverage 30 and 1.5, persistence years 3); year-range slider; revenue, margin and fixed-share sliders (results and break-even changed); assumptions expander; CSV download (82 rows, 8 sections, all basis labels); no console errors.
Not covered: AI-assisted mode (no credentials; live Gemini/Ollama never called), the "Run rules-only commentary" button flow, tooltips, mobile layout, and a human visual review of every chart.

## Unresolved
Ambuja discrepancies (D1-D3), lease scope of debt, ~20 company-years never checked against filings, external indicators empty.


# Round 2 (final audit) changes

| File | Change | Why |
|---|---|---|
| `btb/uihelpers.py` (new), `app.py` | `show_df` rewritten: signature check, `use_container_width` fallback, no recursion, no duplicate kwargs | Confirmed defect R1 |
| `scripts/build_real_financials.py` | `CORRECTIONS` mechanism, `corrections_log.csv`, Ambuja FY2025-26 EBIT 3,007 -> 2,968.53 | R2, audit trail |
| `scripts/build_source_verification.py` | FY2025-26 for UltraTech, ACC, Dalmia; FY2023-24 comparatives for Dalmia and Shree; UltraTech FY25 leases; Ambuja restated-comparative rows; `date_checked`; status overrides | R3-R7: 61 -> 113 comparisons |
| `scripts/make_verification_worksheet.py`, `scripts/audit_recalc.py` | Coverage table with "not yet checked", corrections table, unresolved table | Do not describe the dataset as fully verified |
| `data/raw/disclosures.csv` | 5 -> 9 entries (Ambuja restatement, Ambuja one-time income, lease inclusion for UltraTech and Shree) | Source-backed explanations |
| `data/raw/corrections_log.csv` (new) | Original / revised value, source, reason, date | Auditable record |
| `sql/schema.sql`, `btb/loader.py` | `date_checked` column; four-way `relationship` classification | R13 |
| `btb/stress.py`, `app.py` | Assumption text (capex fixed, taxes / working capital / interest / financing not modelled), "simplified" labels, unit caption | R10 |
| `btb/assessment.py`, `btb/metrics.py` | `Threshold rationale` per rule shown in each warning; causal wording removed | R11, R12 |
| `btb/peers.py` | Notes on debt definition, restatement, five-company scope | Comparability disclosure |
| `btb/ai_commentary.py`, `btb/report.py` | `documented` needs an established disclosure; prompt rule 9; report labels unresolved items `unverified` | R14 |
| `tests/test_uihelpers.py` (new), `tests/test_audit_features.py`, `tests/test_ai.py` | 24 new tests incl. real-data regression tests and the independent recomputation | Phase tests |

| `app.py` (second pass) | Nested expander replaced by a checkbox; zero-baseline charts; non-12-month years labelled; stress margin change in points; coverage line in the evidence section; legend for `breach (?)`; restatement note in unresolved questions | R17, R18, evidence integrity |

## Dashboard QA performed (Chromium via Playwright against the running app, 2026-10-20)
Tested: all five real companies and DEMOA (renders, seven sections, no exception text, no "nan"/"None" text, illustrative banner only for DEMOA); expansion of every warning expander (threshold rationale, follow-up present); persistence grid; peer table and medians; stress sliders (revenue, margin, fixed share) and assumptions; sidebar thresholds (coverage 30 and 1.5, persistence years 3); year-range slider; rules-only commentary generation and the evidence-packet toggle; CSV download for each company (8 sections, all rows carry a basis label, stress rows never labelled observed); no browser console or page errors. I looked at screenshots of Ambuja's warnings, trend charts, peer table, stress section and unresolved questions.
Not tested: AI-assisted mode (no credentials; no live Gemini or Ollama call has ever been made); mobile layout; keyboard-only use; print/PDF; a human review of every chart for all five companies (only Ambuja's pages were inspected visually); the standalone basis (no real standalone data is loaded).

## Compatibility testing
Full suite run on Streamlit 1.66 (current) and Streamlit 1.40 (older, where `width` is an integer), both 171 passed. Streamlit 1.30 (the minimum in requirements.txt) could not be installed on this Python 3.13 environment (no compatible pyarrow wheel), so it was not tested. A clean virtual environment built from requirements.txt (Python 3.13, Streamlit 1.66, pandas 3.0.6) ran the pipeline and 171 tests successfully.

## Third pass: comparability statuses (2026-10-20)
| File | Change |
|---|---|
| `btb/comparability.py` (new) | Per-metric status (Comparable / Use with caution / Not comparable / Unverified), worst status wins; filing-check label |
| `btb/peers.py` | `peer_table` takes `ver`, adds `st__/why__/kind__` columns and corporate group; `peer_medians` reports `n`, `n_groups`, and a second median that also admits definition-only cautions; recent/history windows; group note |
| `btb/assessment.py`, `btb/report.py` | Peer context passes `ver`; report rows for non-comparable metrics and independent-group counts |
| `app.py` | Peer window selector, status matrix with reasons, Filing check column, special-period panel with optional illustrative annualised revenue |
| `tests/test_comparability.py` (new) | 8 tests; `tests/test_app.py` selects widgets by label rather than position |

Scope: existing five companies only. Not done: adding Ramco, JK Cement, JK Lakshmi, Birla Corp or Nuvoco. Tested: 179 pytest on Streamlit 1.66; headless Chromium check for Ambuja (window switch, status matrix, special-period panel, annualised option, CSV comparability rows). Not re-tested after this change: Streamlit 1.40, a clean virtualenv, mobile layout, AI mode in a browser.

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

## Tests (146 passing)
`tests/test_audit_features.py` (new, 37): persistence (consecutive, gap, missing, new/recovered, boundary, 15-month, empty), strict threshold boundary, stress (formulas, margin applied to scenario revenue, FCF, zero/missing interest, negative EBIT, invalid inputs, break-even round trip, 15-month), peers (universe separation, non-12-month exclusion, missing year, too few peers, empty), verification statuses and loader, `db_is_stale`, empty dataset, assessment (conflict, convergence, inconclusive, 15-month), explanation columns, report sections/labels. `tests/test_app.py`, `test_review_fixes.py`, `conftest.py` updated.

## Browser testing (Chromium via Playwright, headless, against the running app)
Covered: initial render and scrolling screenshots; switching to UltraTech, DEMOA (illustrative banner, DEMO-only peer medians n=2) and Ambuja (15-month warning); threshold inputs (coverage 30 and 1.5, persistence years 3); year-range slider; revenue, margin and fixed-share sliders (results and break-even changed); assumptions expander; CSV download (82 rows, 8 sections, all basis labels); no console errors.
Not covered: AI-assisted mode (no credentials; live Gemini/Ollama never called), the "Run rules-only commentary" button flow, tooltips, mobile layout, and a human visual review of every chart.

## Unresolved
Ambuja discrepancies (D1-D3), lease scope of debt, ~20 company-years never checked against filings, external indicators empty.

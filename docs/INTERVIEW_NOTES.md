# Interview preparation notes

## Business relevance
Credit-risk teams screen portfolios for early signs of weakening repayment capacity and need transparent, auditable logic. This project does the corporate version: rules are explicit, every flag cites its inputs, and data limits are surfaced. It is a different domain from consumer credit risk (corporate coverage and leverage vs borrower-level behaviour), but the habits transfer: definitions first, comparable periods, persistence vs one-offs, stress assumptions, documentation of limits. Say clearly that it is not a validated early-warning model.

## Financial logic (be ready to explain each)
* **EBIT** = revenue - (total expenses - finance costs): operating profit after depreciation, before other income and exceptional items.
* **Interest coverage** = EBIT / interest. Strong coverage can coexist with negative FCF (ACC, Ambuja FY25), so it never proves low risk.
* **D/E** = debt / equity (debt appears to include leases; equity excludes NCI). Near zero for ACC/Ambuja, so adaptive precision matters.
* **Current ratio** below 1 is structural for some firms (UltraTech); a threshold alone is not distress.
* **OCF/debt** is a flow over a stock: blank for non-12-month periods in peer views.
* **Revenue growth** only between consecutive 12-month years; the 15-month FY2022-23 is excluded.
* **FCF** = OCF - capex; capex stored positive; missing capex never becomes zero.
* **Stress**: R(1-d) revenue; fixed share f gives operating leverage; margin shock is applied to scenario revenue; OCF falls by the EBIT shortfall; break-even k = (I+fC)/(R(1-pp)-(1-f)C).

## SQL to know
* Views: `v_fin` (financials + company + `fy_start`), `v_ratios` (six ratios, NULL-safe division with `NULLIF`, `LAG()` partitioned by company/basis for growth, requiring consecutive years and 12-month periods).
* `debt_up_ebit_down_sql`: LAG of debt and EBIT, requires prior debt > 0, debt rise >= 10%, EBIT lower, 12-month periods.
* Constraints: CHECK on FY pattern and basis, UNIQUE(company, year, basis), foreign keys with `PRAGMA foreign_keys=ON`, NULL = unknown, raw table kept as text for audit.
* Expect questions on window functions, NULL handling, why a LEFT JOIN, why raw and clean tables.

## Python
`compute_metrics` (pandas, `safe_div`), `persistence_table` (loop per company/indicator with a streak counter and adjacency check on `fy_start`), `stress_test` (pure function over a row), `peer_table` (filter then median), `build_report` (list of dict rows). Tests: 179 with pytest, including SQL vs pandas parity and an independent stdlib recompute (`scripts/audit_recalc.py`, 0 disagreements over 287 values).

## Limitations to volunteer
* Five companies, 41 company-years including synthetic; no statistics possible.
* Aggregator data for most years; 113 inputs (12 of 26 company-years) compared with filings via automated text extraction (not a PDF viewer); 14 company-years not yet checked; three Ambuja FY2024-25 differences unresolved (OCF -32%, probably a restated year); one value corrected (Ambuja FY26 EBIT) with an audit trail.
* Debt/lease scope unverified for most firms; cash blank; thresholds illustrative; stress model ignores tax, working capital, refinancing and debt maturities.
* Live AI (Gemini/Ollama) never tested; rules-only mode is the tested path.

## Likely questions
1. Why no composite score? Hides assumptions, no validation sample, weights arbitrary.
2. Why is a missing year not "ok"? Absence of evidence is not evidence of health.
3. How did you check the numbers? Independent recompute, filing comparison, parity tests.
4. What would you change with more time? Resolve Ambuja gaps, widen filing checks, add sourced external indicators.


## Worked example: from a metric to a warning to a follow-up (real data)
**Ambuja Cements, consolidated, FY2025-26.** Operating cash flow is Rs 5,362 cr and capex Rs 6,344 cr, so free cash flow is -Rs 982 cr (OCF - capex). It was also negative in FY2024-25 (the loaded figure is provisional: the cash-flow input is an unresolved difference from the original filing). The rule NEGATIVE_FREE_CASH_FLOW fires and persistence says "persistent" (two directly consecutive observed years). Interest coverage is a comfortable 13.25x, so the assessment adds a "conflicting signals" line: coverage alone would have looked reassuring.
What the data do NOT say: that Ambuja is in distress. Capex exceeding operating cash flow is common during expansion, and the threshold (zero) is a sign boundary.
What the analyst investigates next: how the shortfall was financed (debt is tiny; cash and investments were large), what the capex is for (capacity vs maintenance), whether FY2024-25 cash flow was restated (Note 68(h)), and whether FY2024-25 EBIT includes the one-time income (about Rs 964 cr) the company discloses. The stress test then shows how far revenue would have to fall before coverage reaches 1.0x (about 92% at constant margin, much less with fixed costs) and that free cash flow, under the simplified assumption, would fall rupee for rupee with EBIT.

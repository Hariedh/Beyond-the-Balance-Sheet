# Revised risk-analysis workflow

Question the app answers: *which financial vulnerabilities are emerging in each company, how persistent are they, how do they compare with peers, and how sensitive are the company's financial metrics to adverse operating conditions?* It is a screening aid, not a rating, default predictor or validated early-warning model, and there is no composite score.

| Step | Dashboard section | What the analyst does | Logic (module) |
|---|---|---|---|
| 1 | Selection and comparability | Pick company, basis, year range. Notes appear for illustrative data, non-12-month periods and thin history. | `app.py`, `config.py` |
| 2 | Performance | Read six ratios plus OCF, capex, FCF for the latest year; caution notes (e.g. structural current ratio below 1). | `metrics.py` |
| 3 | Warnings | For each fired rule: indicator, observed value, threshold, formula, why it matters, persistence, history, peer context, data quality, follow-up. Layered reading: breach, deterioration, convergence, conflict, data limitation, inconclusive. Persistence grid by indicator and year. | `flags.py`, `persistence.py`, `assessment.py` |
| 4 | Trends and peers | Charts (gaps stay gaps); peer table and medians on comparable periods only; no ranking. | `peers.py` |
| 5 | Stress test | Revenue fall, EBIT-margin fall (points), fixed-cost share. Baseline vs scenario for revenue, EBIT, coverage, FCF; break-even revenue fall for 1.0x coverage. | `stress.py` |
| 6 | Evidence | Primary-source disclosures (established vs possible explanation), source-verification table, unresolved questions, data-quality issues. | `evidence.py`, `verification.py` |
| 7 | Summary and export | CSV with eight sections; each row labelled observed / checked vs filing / unverified / hypothesis / scenario / limitation. | `report.py` |

## Rules that keep the output honest
* Year-on-year is computed only between directly consecutive 12-month fiscal years. A 15-month period is shown but never compared as if it were a year.
* Missing data is "not assessable", never "fine". A first breach after a missing year is `history_unknown`, not `new`.
* "No rule fired" is reported as inconclusive, not as low risk.
* Peer medians use the same universe (real with real, synthetic with synthetic), basis and year, 12-month periods only; at least two other comparable peers are needed for a median.
* Thresholds are illustrative and adjustable; the sensitivity grid shows how flags change.
* Rules-only commentary works without any AI credentials; AI output is optional and checked against an evidence packet.

## Stress-test formulas
C = revenue - EBIT (cost base). With revenue fall d, fixed share f and margin shock pp:
revenue_s = R(1-d); EBIT_s = revenue_s - [fC + (1-f)C(1-d)] - pp x revenue_s.
f = 0 keeps the EBIT margin constant under a pure revenue shock. Interest, capex and debt are held constant; OCF falls by the full EBIT shortfall (pre-tax). Break-even revenue fall for 1.0x coverage: k = (I + fC) / (R(1-pp) - (1-f)C), fall = 1 - k. Negative EBIT, zero interest and missing inputs are handled with notes instead of numbers. Not a forecast.

# Raw data directory and source notes

Keep source files here exactly as obtained. Never edit a raw value to "fix" it; correct it in the CSV you load and say why in `notes`.

| File | Contents | Status |
|---|---|---|
| `financials_real.csv` | 26 company-years for 5 cement companies, consolidated, in INR crore | **Real data from secondary sources, collected 19 Oct 2026. Hand-check before treating as final** (see below) |
| `companies_candidates.csv` | The five candidate companies | Candidate sample, not a proven comparable set |
| `financials_demo_ILLUSTRATIVE.csv`, `companies_demo_ILLUSTRATIVE.csv` | Synthetic data for three fictional companies | Illustrative only, never real |
| `disclosures.csv` | Short attributed excerpts from annual reports and filings | Empty: add with page references |
| `external_indicators.csv` | Dated external series (fuel, freight, interest rates, ...) | Empty: add with sources |

## Where the real numbers came from

`scripts/build_real_financials.py` holds every transcribed figure, converts and derives values, runs cross-checks and writes `financials_real.csv`. Re-run it after editing a figure.

| Item | Source | Notes |
|---|---|---|
| Revenue, operating profit, interest (finance costs), depreciation, equity capital, reserves, borrowings, cash from operations | [Screener.in](https://www.screener.in/) consolidated pages (standardised from company filings) | Secondary aggregator |
| Current assets, current liabilities (FY2021-22 onward) | [stockanalysis.com](https://stockanalysis.com/) (S&P data) | Not available for FY2020-21: left blank |
| Operating cash flow and total debt (cross-check) | stockanalysis.com | Used to validate Screener |
| Primary-filing spot checks | UltraTech audited consolidated results for FY2022-23 (filed 28 Apr 2023, BSE); Ambuja board release of 2 May 2023 | See below |

### Definitions (identical for every company)

* **EBIT** = operating profit - depreciation. Other income is excluded (Screener derives "other income" as a balancing figure that can differ from the company's printed other income, e.g. UltraTech FY2021-22: 669 vs 507.6 printed).
* **Interest** = finance costs. **Total debt** = Screener "borrowings", which matched S&P total debt in every year checked and appears to include lease liabilities (so near-debt-free Ambuja and ACC show small non-zero debt).
* **Total equity** = equity capital + reserves, i.e. owners' equity **excluding non-controlling interests**. For Ambuja the S&P figure including minorities is roughly 20% higher (FY2024-25: about 63,947 vs 53,579 crore).
* **Cash** is deliberately blank: aggregator "cash" definitions are inconsistent (Ambuja's earnings call cites about 11,530 crore at Mar 2023 vs about 544 crore in the aggregator line).

### Automated cross-checks (80 of 82 pass)

1. Operating profit + other income - depreciation - interest equals reported profit before tax (+/- 2 crore).
2. Screener borrowings agree with S&P total debt (+/- 0.5%).
3. Screener operating cash flow agrees with S&P (+/- 1%). **Two disagreements** (Ambuja and ACC FY2022-23, the 15-month period): both values are left blank rather than choosing one.
4. Eleven comparisons against primary filings (UltraTech FY2021-22 and FY2022-23: revenue, finance costs, depreciation, current assets and liabilities, operating cash flow; Ambuja FY2022-23 revenue) match to rounding.

Everything else is **not** verified against primary documents. Per the project brief, hand-check at least one ratio per company against its annual report before relying on the data.

## Comparability issues you must know about

* **Ambuja Cements and ACC changed their year-end from December to March.** FY2022-23 is a **15-month** period (Jan 2022 to Mar 2023; confirmed for Ambuja in its 2 May 2023 board release). Their Dec-2020 and Dec-2021 calendar-year periods cannot be expressed as March fiscal years and are **not loaded**. The tool records `period_months = 15` and suppresses year-on-year changes into and out of that period. Flow ratios for that year (for example operating cash flow / debt) are not comparable with 12-month years.
* **Scope and ownership changes** (Adani group acquisition of the Ambuja/ACC stake in 2022, later acquisitions by Ambuja and UltraTech) can change what each consolidated figure covers. The rows carry a "verify" note; check the annual reports' consolidation notes before drawing conclusions.
* **Current ratio below 1 is structural for UltraTech** (0.73 to 0.88 in every year with data) and should not be read as distress on its own.
* The sample is purposive; Ambuja and ACC are now difficult to compare with the others over the full period. Consider replacing them with companies that have a clean March year-end history if the analysis needs five comparable firms.
* FY2025-26 (year to March 2026) is included in addition to the brief's FY2020-21 to FY2024-25. Drop it if you want exactly the original window.

## Filling in or extending the CSV

One row = one company, one financial year, one reporting basis.

| Column | Notes |
|---|---|
| `ticker`, `financial_year` | Year format `FY2020-21`. |
| `basis` | `standalone` or `consolidated`. Use one basis consistently per company. |
| `unit` | Unit of the numbers in that row: `rupees`, `thousands`, `lakhs`, `millions`, `crores`. |
| `period_months` | Length of the reporting period; blank means 12. |
| numeric fields | Blank stays NULL, never zero. Commas and `(1,234.5)` accounting negatives are accepted. |
| `definitions_note`, `source`, `source_url`, `notes` | Required in practice: traceability and definitions. |
| `is_illustrative` | `0` for real data. |

## Checks before trusting a row

1. Same financial-year end across companies, or documented differences (transitional / longer periods).
2. Standalone vs consolidated applied consistently.
3. Restated figures: prefer the latest restated comparatives and record that in `notes`.
4. Hand-check at least one ratio per company against the source statements.

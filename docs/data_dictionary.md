# Data dictionary

All monetary values in the cleaned tables are **INR crore** (1 crore = 10,000,000 rupees). `NULL` means "not available" and is never treated as zero.

## Input CSV: financials (`data/raw/financials_*.csv`)

| Column | Required | Description |
|---|---|---|
| `ticker` | yes | Must exist in a companies CSV. |
| `financial_year` | yes | `FYyyyy-yy`, e.g. `FY2023-24`. The last two digits must be the start year + 1. |
| `basis` | yes | `standalone` or `consolidated`. |
| `unit` | yes | Unit of the numbers in this row: `rupees`, `thousands`, `lakhs`, `millions`, `crores` (aliases such as `lakh`, `crore`, `mn` accepted). |
| `period_months` | no | Length of the reporting period in months (1 to 24); blank means 12. Year-on-year measures are only computed between two 12-month periods. |
| `revenue` | yes (may be blank) | Revenue from operations. |
| `ebit` | yes (may be blank) | EBIT / operating profit; define it in `definitions_note`. |
| `interest_expense` | yes (may be blank) | Finance costs; define it in `definitions_note`. |
| `total_debt` | yes (may be blank) | Borrowings; state whether current maturities and leases are included. |
| `total_equity` | yes (may be blank) | Total shareholders' equity. |
| `current_assets`, `current_liabilities` | yes (may be blank) | Balance-sheet totals. |
| `operating_cash_flow` | yes (may be blank) | Net cash from operating activities. |
| `cash_and_equivalents` | yes (may be blank) | Optional in practice; not used in the six ratios. |
| `capex` | no (column may be absent) | Capital expenditure as a **positive** cash outflow. Free cash flow = `operating_cash_flow` - `capex`, and is blank unless both are present. A negative value raises `negative_capex`. |
| `definitions_note` | no, but expected | How EBIT, finance costs and debt were defined. |
| `source`, `source_url` | no, but expected | Document and page, and URL. Missing source raises a warning. |
| `notes` | no | Restatements, mergers, longer periods, adjustments. |
| `is_illustrative` | no | `1` for synthetic data, `0` for real. |

Number formats accepted: `1,234.5`, `-50`, `(1,234.5)` (accounting negative). Blank, `NA`, `n/a`, `-`, `null` are treated as missing. Anything else non-numeric is stored as NULL **and** logged as an error.

## Input CSV: companies

`ticker`, `name`, `industry` (required); `exchange`, `notes`, `is_illustrative` (optional).

## Input CSV: disclosures

`ticker`, `excerpt`, `source_doc` (required); `financial_year`, `topic`, `page_ref`, `source_url`, `publication_date`, `related_metric`, `relationship` (`established` or `possible_explanation`; anything else is rejected), `is_illustrative` (optional). `established` means the filing itself states or arithmetically shows the link to the metric; a disclosure that merely appears in the same year is not a cause. Excerpts over 600 characters are truncated with a warning.

## Input CSV: source verification (`source_verification.csv`)

`ticker`, `financial_year`, `basis`, `item`, `app_value_cr`, `filing_value_cr`, `difference_cr`, `difference_pct`, `status` (`verified` <= max(1.5 cr, 0.1%); `approx` <= 1%; `discrepancy` > 1%; `unverified` not like-for-like), `method`, `source_doc`, `publication_date`, `location`, `source_url`, `notes`. A `discrepancy` row raises the validation warning `source_discrepancy`. Loaded values are never changed to match the filing.

## Input CSV: external indicators

`series_name`, `period`, `value` (numeric), `source` (required); `unit`, `source_url`, `notes`, `is_illustrative` (optional).

## Database tables

| Table | Purpose |
|---|---|
| `companies` | One row per company. |
| `financials_raw` | Every financials CSV row exactly as received, all TEXT, with source file and row number. |
| `financials` | Cleaned data, unique per company / financial year / basis, in INR crore, with `original_unit` and a link to `raw_id`. |
| `disclosures`, `external_indicators` | Evidence for the real-world event analysis. |
| `source_verification` | Loaded value vs primary filing, per input and company-year. |
| `flags` | One row per triggered rule with threshold, observed value and evidence text. |
| `validation_issues` | Data-quality findings (`error` / `warning` / `info`). |
| `ai_runs` | Every commentary run with manual-review columns. Preserved across pipeline re-runs. |

## Views

| View | Purpose |
|---|---|
| `v_fin` | `financials` joined to `companies`, plus `fy_start` for ordering. |
| `v_ratios` | The six ratios per company / basis / year, NULL-safe, using `LAG()` for year-on-year growth. |

## Validation checks

| Check | Severity | Meaning |
|---|---|---|
| `missing_value` | warning (cash and capex: info) | A field is NULL. |
| `missing_source` | warning | No source recorded. |
| `negative_capex` | warning | Capex entered with the wrong sign. |
| `nonpositive_revenue`, `negative_interest_expense`, `negative_debt` | error | Impossible or definition-suspect values. |
| `nonpositive_equity`, `nonpositive_current_liabilities` | warning | Ratio will be n/a. |
| `cash_exceeds_current_assets` | warning | Possible unit or definition problem. |
| `ebit_margin_implausible` | warning | `abs(margin) > 100%`. |
| `implied_interest_rate_outlier` | warning | Interest / debt outside 0.5%-40%; check units or definitions. |
| `large_revenue_change` | warning | More than 50% year-on-year; check restatements, mergers, scope or period length. |
| `missing_financial_year` | warning | A gap in the year sequence. |
| `mixed_reporting_basis` | info | Both standalone and consolidated rows loaded. |
| `non_standard_period` | info | Period is not 12 months; year-on-year measures into and out of it are n/a. |
| `zero_interest_expense`, `blank_row_skipped` | info | Informational. |
| Load errors (`unknown_ticker`, `invalid_*`, `duplicate_*`, `unparseable_number`) | error | Row rejected, or value stored as NULL. |

The plausibility bands are illustrative aids for spotting unit mistakes, not accounting rules.

## Metric definitions (all INR crore unless a ratio)

| Metric | Formula | Missing / edge behaviour |
|---|---|---|
| EBIT | revenue - (total expenses - finance costs); before other income and exceptional items | blank if an input is blank |
| Interest coverage | EBIT / interest expense | n/a if interest is missing or <= 0; negative EBIT gives a negative ratio (not hidden) |
| Debt-to-equity | total debt / total equity (equity excludes non-controlling interest; debt appears to include leases) | n/a if equity <= 0 |
| Current ratio | current assets / current liabilities | n/a if liabilities <= 0 |
| OCF / debt | operating cash flow / total debt | n/a if debt <= 0; blank for non-12-month periods in peer views |
| Revenue growth | revenue / prior revenue - 1 | only between directly consecutive FYs that are both 12 months; prior revenue must be > 0 |
| EBIT margin | EBIT / revenue | n/a if revenue <= 0 |
| Free cash flow | operating cash flow - capex (capex stored as a positive outflow) | n/a if either is missing; never treats missing capex as 0 |
| OCF / EBIT (peer) | operating cash flow / EBIT | n/a unless EBIT > 0 |
| FCF margin (peer) | free cash flow / revenue | n/a unless revenue > 0 |

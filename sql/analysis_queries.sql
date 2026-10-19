-- Beyond the Balance Sheet: example analysis queries
-- Each query starts with a "-- name:" marker so tests and scripts can run them
-- individually. Run any of them with:
--   sqlite3 data/btb.sqlite < sql/analysis_queries.sql
-- (or paste a single query into any SQLite client).

-- name: latest_year_ratios
-- Latest available financial year per company/basis with all six ratios.
SELECT r.ticker, r.basis, r.financial_year,
       ROUND(r.interest_coverage, 2) AS interest_coverage,
       ROUND(r.debt_to_equity, 2)    AS debt_to_equity,
       ROUND(r.current_ratio, 2)     AS current_ratio,
       ROUND(r.ocf_to_debt, 2)       AS ocf_to_debt,
       ROUND(r.revenue_growth * 100, 1) AS revenue_growth_pct,
       ROUND(r.ebit_margin * 100, 1)    AS ebit_margin_pct
FROM v_ratios AS r
WHERE r.fy_start = (SELECT MAX(r2.fy_start) FROM v_ratios AS r2
                    WHERE r2.company_id = r.company_id AND r2.basis = r.basis)
ORDER BY r.ticker;

-- name: interest_coverage_ranking
-- Rank companies by interest coverage within each financial year.
-- NULL coverage (missing data or zero interest) sorts last.
SELECT financial_year, ticker, basis,
       ROUND(interest_coverage, 2) AS interest_coverage,
       RANK() OVER (PARTITION BY financial_year, basis
                    ORDER BY interest_coverage IS NULL, interest_coverage DESC) AS rank_in_year
FROM v_ratios
ORDER BY financial_year, rank_in_year;

-- name: industry_average_leverage
-- GROUP BY / aggregate example: average debt-to-equity and EBIT margin by
-- industry and year. COUNT(x) ignores NULLs, so n shows how many companies
-- actually contribute to each average.
SELECT industry, financial_year, basis,
       COUNT(debt_to_equity)             AS n_companies,
       ROUND(AVG(debt_to_equity), 2)     AS avg_debt_to_equity,
       ROUND(AVG(ebit_margin) * 100, 1)  AS avg_ebit_margin_pct
FROM v_ratios
GROUP BY industry, financial_year, basis
ORDER BY industry, financial_year;

-- name: debt_up_ebit_down_sql
-- SQL version of the DEBT_UP_EBIT_DOWN rule using LAG(); the Python rules
-- engine implements the same logic and the tests compare the two.
WITH x AS (
    SELECT ticker, basis, financial_year, fy_start, total_debt_cr, ebit_cr,
           LAG(fy_start)      OVER w AS prev_fy,
           LAG(total_debt_cr) OVER w AS prev_debt,
           LAG(ebit_cr)       OVER w AS prev_ebit
    FROM v_fin
    WINDOW w AS (PARTITION BY company_id, basis ORDER BY fy_start)
)
SELECT ticker, basis, financial_year,
       prev_debt AS debt_prev_cr, total_debt_cr AS debt_cr,
       prev_ebit AS ebit_prev_cr, ebit_cr
FROM x
WHERE prev_fy = fy_start - 1
  AND total_debt_cr > prev_debt
  AND ebit_cr < prev_ebit
ORDER BY ticker, financial_year;

-- name: low_interest_coverage_years
-- Company-years below an illustrative coverage threshold (change 1.5 freely).
SELECT ticker, basis, financial_year, ROUND(interest_coverage, 2) AS interest_coverage
FROM v_ratios
WHERE interest_coverage < 1.5
ORDER BY interest_coverage;

-- name: missing_core_fields
-- NULL handling: which company-years are missing a core input?
SELECT ticker, basis, financial_year,
       (revenue_cr IS NULL) + (ebit_cr IS NULL) + (interest_expense_cr IS NULL)
     + (total_debt_cr IS NULL) + (total_equity_cr IS NULL)
     + (current_assets_cr IS NULL) + (current_liabilities_cr IS NULL)
     + (operating_cash_flow_cr IS NULL) AS n_missing_core_fields,
       cash_cr IS NULL AS cash_missing
FROM v_fin
WHERE n_missing_core_fields > 0 OR cash_missing
ORDER BY n_missing_core_fields DESC, ticker, financial_year;

-- name: data_completeness_by_company
-- Coverage of years and non-null core inputs per company/basis.
SELECT ticker, basis,
       COUNT(*)               AS years_loaded,
       MIN(financial_year)    AS first_year,
       MAX(financial_year)    AS last_year,
       COUNT(revenue_cr)      AS revenue_obs,
       COUNT(ebit_cr)         AS ebit_obs,
       COUNT(interest_expense_cr) AS interest_obs,
       COUNT(total_debt_cr)   AS debt_obs,
       COUNT(operating_cash_flow_cr) AS ocf_obs
FROM v_fin
GROUP BY ticker, basis
ORDER BY ticker;

-- name: raw_vs_clean_unit_audit
-- JOIN audit: show the raw text, the declared unit and the converted crore
-- value side by side, so unit conversion can be checked by eye.
SELECT f.ticker, f.financial_year, r.unit AS raw_unit,
       r.revenue AS raw_revenue_text, ROUND(f.revenue_cr, 2) AS revenue_cr,
       r.total_debt AS raw_debt_text, ROUND(f.total_debt_cr, 2) AS total_debt_cr
FROM v_fin AS f
JOIN financials AS fin ON fin.financial_id = f.financial_id
JOIN financials_raw AS r ON r.raw_id = fin.raw_id
ORDER BY f.ticker, f.financial_year;

-- name: flag_counts_by_rule
-- How often each rule fires, and for how many distinct companies.
SELECT rule_id, severity,
       COUNT(*)                      AS flagged_company_years,
       COUNT(DISTINCT company_id)    AS companies_affected
FROM flags
GROUP BY rule_id, severity
ORDER BY flagged_company_years DESC;

-- name: validation_summary
-- Data-quality findings grouped by check.
SELECT severity, check_name, COUNT(*) AS n
FROM validation_issues
GROUP BY severity, check_name
ORDER BY CASE severity WHEN 'error' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, n DESC;

-- Beyond the Balance Sheet: views
-- Ratio logic lives here in plain SQL AND in btb/metrics.py (pandas). The test
-- suite checks that the two implementations agree.
--
-- Conventions
--   * A ratio is NULL (never 0) when the denominator is missing, zero or
--     negative, or when the numerator is missing.
--   * Year-on-year measures are only computed when the prior row is the
--     immediately preceding financial year for the same company and basis AND
--     both periods are 12 months long.

DROP VIEW IF EXISTS v_ratios;
DROP VIEW IF EXISTS v_fin;

CREATE VIEW v_fin AS
SELECT
    f.financial_id,
    f.company_id,
    c.ticker,
    c.name,
    c.industry,
    f.financial_year,
    CAST(substr(f.financial_year, 3, 4) AS INTEGER) AS fy_start,
    f.basis,
    f.revenue_cr,
    f.ebit_cr,
    f.interest_expense_cr,
    f.total_debt_cr,
    f.total_equity_cr,
    f.current_assets_cr,
    f.current_liabilities_cr,
    f.operating_cash_flow_cr,
    f.cash_cr,
    f.original_unit,
    f.period_months,
    f.definitions_note,
    f.source,
    f.source_url,
    f.notes,
    f.is_illustrative
FROM financials AS f
JOIN companies  AS c ON c.company_id = f.company_id;

CREATE VIEW v_ratios AS
WITH base AS (
    SELECT
        v.*,
        LAG(fy_start)      OVER w AS prev_fy_start,
        LAG(revenue_cr)    OVER w AS prev_revenue_cr,
        LAG(period_months) OVER w AS prev_period_months
    FROM v_fin AS v
    WINDOW w AS (PARTITION BY company_id, basis ORDER BY fy_start)
)
SELECT
    company_id,
    ticker,
    name,
    industry,
    basis,
    financial_year,
    fy_start,
    is_illustrative,

    -- Interest coverage = EBIT / interest expense (interest must be > 0)
    CASE WHEN ebit_cr IS NOT NULL AND interest_expense_cr > 0
         THEN ebit_cr / interest_expense_cr END                         AS interest_coverage,

    -- Debt-to-equity = total debt / total equity (equity must be > 0)
    CASE WHEN total_debt_cr IS NOT NULL AND total_equity_cr > 0
         THEN total_debt_cr / total_equity_cr END                       AS debt_to_equity,

    -- Current ratio = current assets / current liabilities
    CASE WHEN current_assets_cr IS NOT NULL AND current_liabilities_cr > 0
         THEN current_assets_cr / current_liabilities_cr END            AS current_ratio,

    -- Operating cash flow to debt (debt must be > 0)
    CASE WHEN operating_cash_flow_cr IS NOT NULL AND total_debt_cr > 0
         THEN operating_cash_flow_cr / total_debt_cr END                AS ocf_to_debt,

    -- Revenue growth vs the immediately preceding financial year, only when both
    -- periods are 12 months long (a 15-month period is not comparable).
    CASE WHEN revenue_cr IS NOT NULL
          AND prev_fy_start = fy_start - 1
          AND period_months = 12 AND prev_period_months = 12
          AND prev_revenue_cr > 0
         THEN (revenue_cr - prev_revenue_cr) / prev_revenue_cr END      AS revenue_growth,

    -- EBIT margin = EBIT / revenue (revenue must be > 0)
    CASE WHEN ebit_cr IS NOT NULL AND revenue_cr > 0
         THEN ebit_cr / revenue_cr END                                  AS ebit_margin
FROM base;

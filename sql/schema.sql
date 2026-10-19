-- Beyond the Balance Sheet: SQLite schema
-- Re-running this script rebuilds every data table. ai_runs is kept so that
-- AI evaluation records survive a pipeline re-run.
--
-- NOTE: SQLite does not enforce foreign keys unless every connection runs
--       PRAGMA foreign_keys = ON (btb/db.py does this).

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_ratios;
DROP VIEW  IF EXISTS v_fin;
DROP TABLE IF EXISTS validation_issues;
DROP TABLE IF EXISTS flags;
DROP TABLE IF EXISTS external_indicators;
DROP TABLE IF EXISTS disclosures;
DROP TABLE IF EXISTS financials;
DROP TABLE IF EXISTS financials_raw;
DROP TABLE IF EXISTS companies;

-- ---------------------------------------------------------------------------
-- companies: one row per company
-- ---------------------------------------------------------------------------
CREATE TABLE companies (
    company_id      INTEGER PRIMARY KEY,
    ticker          TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    industry        TEXT    NOT NULL,
    exchange        TEXT,
    notes           TEXT,
    is_illustrative INTEGER NOT NULL DEFAULT 0 CHECK (is_illustrative IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- financials_raw: every CSV row exactly as received (all TEXT, nothing parsed)
-- ---------------------------------------------------------------------------
CREATE TABLE financials_raw (
    raw_id                 INTEGER PRIMARY KEY,
    source_file            TEXT    NOT NULL,
    source_row             INTEGER NOT NULL,
    ticker                 TEXT,
    financial_year         TEXT,
    basis                  TEXT,
    unit                   TEXT,
    period_months          TEXT,
    revenue                TEXT,
    ebit                   TEXT,
    interest_expense       TEXT,
    total_debt             TEXT,
    total_equity           TEXT,
    current_assets         TEXT,
    current_liabilities    TEXT,
    operating_cash_flow    TEXT,
    cash_and_equivalents   TEXT,
    definitions_note       TEXT,
    source                 TEXT,
    source_url             TEXT,
    notes                  TEXT,
    is_illustrative        TEXT
);

-- ---------------------------------------------------------------------------
-- financials: cleaned data, one row per company / financial year / basis.
-- All monetary values are in INR crore. NULL means "not available" and is
-- never silently converted to zero.
-- ---------------------------------------------------------------------------
CREATE TABLE financials (
    financial_id            INTEGER PRIMARY KEY,
    company_id              INTEGER NOT NULL REFERENCES companies (company_id),
    financial_year          TEXT    NOT NULL
        CHECK (financial_year GLOB 'FY[0-9][0-9][0-9][0-9]-[0-9][0-9]')
        CHECK (CAST(substr(financial_year, 8, 2) AS INTEGER)
               = (CAST(substr(financial_year, 5, 2) AS INTEGER) + 1) % 100),
    basis                   TEXT    NOT NULL CHECK (basis IN ('standalone', 'consolidated')),
    revenue_cr              REAL,
    ebit_cr                 REAL,
    interest_expense_cr     REAL,
    total_debt_cr           REAL,
    total_equity_cr         REAL,
    current_assets_cr       REAL,
    current_liabilities_cr  REAL,
    operating_cash_flow_cr  REAL,
    cash_cr                 REAL,
    original_unit           TEXT    NOT NULL
        CHECK (original_unit IN ('rupees', 'thousands', 'lakhs', 'millions', 'crores')),
    -- Length of the reporting period. 12 normally; e.g. 15 after a year-end change.
    -- Year-on-year measures are only computed between two 12-month periods.
    period_months           INTEGER NOT NULL DEFAULT 12 CHECK (period_months BETWEEN 1 AND 24),
    definitions_note        TEXT,
    source                  TEXT,
    source_url              TEXT,
    notes                   TEXT,
    is_illustrative         INTEGER NOT NULL DEFAULT 0 CHECK (is_illustrative IN (0, 1)),
    raw_id                  INTEGER REFERENCES financials_raw (raw_id),
    UNIQUE (company_id, financial_year, basis)
);

CREATE INDEX idx_financials_company ON financials (company_id, basis, financial_year);

-- ---------------------------------------------------------------------------
-- disclosures: short, attributable excerpts / summaries from company filings
-- ---------------------------------------------------------------------------
CREATE TABLE disclosures (
    disclosure_id   INTEGER PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies (company_id),
    financial_year  TEXT,
    topic           TEXT,
    excerpt         TEXT    NOT NULL,
    source_doc      TEXT    NOT NULL,
    page_ref        TEXT,
    source_url      TEXT,
    is_illustrative INTEGER NOT NULL DEFAULT 0 CHECK (is_illustrative IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- external_indicators: dated external series (fuel prices, rates, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE external_indicators (
    indicator_id    INTEGER PRIMARY KEY,
    series_name     TEXT    NOT NULL,
    period          TEXT    NOT NULL,
    value           REAL    NOT NULL,
    unit            TEXT,
    source          TEXT    NOT NULL,
    source_url      TEXT,
    notes           TEXT,
    is_illustrative INTEGER NOT NULL DEFAULT 0 CHECK (is_illustrative IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- flags: output of the rules engine (one row per triggered rule)
-- ---------------------------------------------------------------------------
CREATE TABLE flags (
    flag_id          INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies (company_id),
    basis            TEXT    NOT NULL,
    financial_year   TEXT    NOT NULL,
    rule_id          TEXT    NOT NULL,
    rule_description TEXT    NOT NULL,
    severity         TEXT    NOT NULL CHECK (severity IN ('warning', 'info')),
    threshold_used   TEXT,
    observed_value   REAL,
    evidence         TEXT    NOT NULL,
    is_illustrative  INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- validation_issues: data-quality findings from loading and validation
-- ---------------------------------------------------------------------------
CREATE TABLE validation_issues (
    issue_id        INTEGER PRIMARY KEY,
    severity        TEXT NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    check_name      TEXT NOT NULL,
    ticker          TEXT,
    financial_year  TEXT,
    field           TEXT,
    detail          TEXT NOT NULL,
    source_file     TEXT
);

-- ---------------------------------------------------------------------------
-- ai_runs: every AI / rules-only commentary run, with manual review columns
-- (kept across pipeline re-runs; no foreign keys on purpose)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_runs (
    run_id               INTEGER PRIMARY KEY,
    run_at               TEXT NOT NULL,
    ticker               TEXT NOT NULL,
    basis                TEXT NOT NULL,
    mode                 TEXT NOT NULL CHECK (mode IN ('rules_only', 'ai')),
    model                TEXT,
    evidence_json        TEXT NOT NULL,
    output_json          TEXT NOT NULL,
    auto_problem_count   INTEGER,
    manual_factual_errors      INTEGER,
    manual_unsupported_claims  INTEGER,
    manual_usefulness_1to5     INTEGER,
    manual_notes               TEXT
);

from __future__ import annotations

import pandas as pd
import pytest

from btb import config
from btb.db import connect, query_df, split_sql_queries

from conftest import fin_row

CO = [["T1", "Test One", "Cement", "NSE", "", 0]]


def issue_checks(db, severity=None):
    conn = connect(db)
    sql = "SELECT check_name FROM validation_issues" + (f" WHERE severity = '{severity}'" if severity else "")
    return set(query_df(conn, sql)["check_name"])


def test_validation_catches_planted_problems(run):
    db, _ = run(CO, [
        fin_row("T1", "FY2020-21", rev="1000", ebit="100", intr="-5", debt="500", eq="-10", ca="100", cl="50",
                ocf="10", cash="200"),                                          # neg interest, neg equity, cash > CA
        fin_row("T1", "FY2021-22", rev="3000", ebit="5000", intr="1", debt="500", eq="10", ca="100", cl="50",
                ocf="10"),                                                      # revenue +200%, EBIT margin >100%, tiny implied rate
        fin_row("T1", "FY2023-24", rev="3000", ebit="100", intr="50", debt="500", eq="10", ca="100", cl="50",
                ocf="10", src=""),                                              # gap year + missing source
    ])
    checks = issue_checks(db)
    assert {"negative_interest_expense", "nonpositive_equity", "cash_exceeds_current_assets",
            "large_revenue_change", "ebit_margin_implausible", "implied_interest_rate_outlier",
            "missing_financial_year", "missing_source"} <= checks


def test_validation_flags_missing_values_as_warnings(run):
    db, _ = run(CO, [fin_row("T1", "FY2020-21", rev="1000", ebit="100")])
    assert "missing_value" in issue_checks(db, "warning")


def test_clean_row_has_no_warnings_or_errors(run):
    db, _ = run(CO, [fin_row("T1", "FY2020-21", rev="1000", ebit="150", intr="40", debt="400", eq="800",
                             ca="300", cl="150", ocf="120", cash="50")])
    assert issue_checks(db, "error") == set()
    assert issue_checks(db, "warning") == set()


def test_all_analysis_queries_run(demo_db):
    conn = connect(demo_db)
    queries = split_sql_queries((config.SQL_DIR / "analysis_queries.sql").read_text())
    assert len(queries) >= 8
    for name, sql in queries.items():
        df = query_df(conn, sql)           # raises on any SQL error
        assert df is not None, name


def test_latest_year_query_returns_one_row_per_company(demo_db):
    conn = connect(demo_db)
    q = split_sql_queries((config.SQL_DIR / "analysis_queries.sql").read_text())["latest_year_ratios"]
    df = query_df(conn, q)
    assert not df.duplicated(["ticker", "basis"]).any()
    assert {"DEMOA", "DEMOB", "DEMOC", "ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "ACC"} == set(df["ticker"])
    demo = df[df["ticker"].str.startswith("DEMO")]
    assert (demo["financial_year"] == "FY2024-25").all()
    real = df[~df["ticker"].str.startswith("DEMO")]
    assert (real["financial_year"] == "FY2025-26").all()


def test_demo_unit_conversion_end_to_end(demo_db):
    """DEMOC is reported in lakhs: 300000 lakh must become 3000 crore."""
    conn = connect(demo_db)
    f = query_df(conn, "SELECT revenue_cr FROM v_fin WHERE ticker='DEMOC' AND financial_year='FY2020-21'")
    assert f.loc[0, "revenue_cr"] == 3000.0
    raw = query_df(conn, "SELECT revenue, unit FROM financials_raw WHERE ticker='DEMOC' AND financial_year='FY2020-21'")
    assert raw.loc[0, "revenue"] == "300000" and raw.loc[0, "unit"] == "lakhs"


def test_demo_rows_are_labelled_illustrative_and_real_rows_are_not(demo_db):
    conn = connect(demo_db)
    assert query_df(conn, "SELECT MIN(is_illustrative) AS m FROM v_fin WHERE ticker LIKE 'DEMO%'").loc[0, "m"] == 1
    assert query_df(conn, "SELECT MAX(is_illustrative) AS m FROM v_fin WHERE ticker NOT LIKE 'DEMO%'").loc[0, "m"] == 0
    assert query_df(conn, "SELECT COUNT(*) AS n FROM companies WHERE ticker LIKE 'DEMO%' AND is_illustrative = 0").loc[0, "n"] == 0


REAL = "is_illustrative = 0"


def test_real_data_is_complete_traceable_and_never_illustrative(demo_db):
    conn = connect(demo_db)
    df = query_df(conn, f"SELECT * FROM v_fin WHERE {REAL}")
    assert set(df["ticker"]) == {"ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "ACC"}
    assert len(df) == 26
    assert (df["basis"] == "consolidated").all() and (df["original_unit"] == "crores").all()
    assert df["source"].str.len().gt(20).all() and df["definitions_note"].str.len().gt(50).all()
    assert df["source_url"].str.startswith("https://").all()
    assert df["cash_cr"].isna().all()                       # deliberately not loaded (inconsistent definitions)
    assert not query_df(conn, "SELECT 1 FROM validation_issues WHERE severity = 'error'").shape[0]


def test_real_data_year_end_change_handled(demo_db):
    conn = connect(demo_db)
    for t in ("AMBUJACEM", "ACC"):
        d = query_df(conn, f"SELECT financial_year, period_months, operating_cash_flow_cr FROM v_fin WHERE ticker = '{t}' ORDER BY fy_start")
        assert list(d["financial_year"]) == ["FY2022-23", "FY2023-24", "FY2024-25", "FY2025-26"]
        assert list(d["period_months"]) == [15, 12, 12, 12]
        assert pd.isna(d.loc[0, "operating_cash_flow_cr"])    # sources disagreed, so left blank
        r = query_df(conn, f"SELECT financial_year, revenue_growth FROM v_ratios WHERE ticker = '{t}' ORDER BY fy_start")
        assert r["revenue_growth"].isna().tolist()[:2] == [True, True]   # no growth into or out of the 15-month period
        assert r["revenue_growth"].notna().tolist()[2:] == [True, True]


def test_real_data_matches_primary_filing_spot_checks(demo_db):
    """UltraTech audited consolidated results (28 Apr 2023) and Ambuja board release (2 May 2023)."""
    conn = connect(demo_db)

    def get(t, fy):
        return query_df(conn, f"SELECT * FROM v_fin WHERE ticker = '{t}' AND financial_year = '{fy}'").iloc[0]

    u23, u22, a23 = get("ULTRACEMCO", "FY2022-23"), get("ULTRACEMCO", "FY2021-22"), get("AMBUJACEM", "FY2022-23")
    assert u23["revenue_cr"] == pytest.approx(63239.98, abs=1.5)
    assert u23["interest_expense_cr"] == pytest.approx(822.72, abs=1.5)
    assert u23["current_liabilities_cr"] == pytest.approx(23431.79, abs=1.5)
    assert u23["ebit_cr"] == pytest.approx(10620 - 2888)         # operating profit - depreciation
    assert u22["revenue_cr"] == pytest.approx(52598.83, abs=1.5)
    assert u22["current_assets_cr"] == pytest.approx(17478.94, abs=2)
    assert u22["operating_cash_flow_cr"] == pytest.approx(9283.24, abs=1.5)
    assert a23["revenue_cr"] == pytest.approx(38937.0, abs=1.5) and a23["period_months"] == 15


def test_real_ratios_hand_check(demo_db):
    """Independent recomputation for one company-year from the raw CSV figures."""
    conn = connect(demo_db)
    r = query_df(conn, "SELECT * FROM v_ratios WHERE ticker = 'SHREECEM' AND financial_year = 'FY2023-24'").iloc[0]
    ebit = 4517 - 1897
    assert r["ebit_margin"] == pytest.approx(ebit / 20404)
    assert r["interest_coverage"] == pytest.approx(ebit / 258)
    assert r["debt_to_equity"] == pytest.approx(1656 / (36 + 20667))
    assert r["current_ratio"] == pytest.approx(12212.2 / 6127.8)
    assert r["revenue_growth"] == pytest.approx(20404 / 17852 - 1)

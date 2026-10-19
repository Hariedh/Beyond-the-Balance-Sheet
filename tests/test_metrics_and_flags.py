from __future__ import annotations

import math

import pandas as pd
import pytest

from btb.db import connect, load_fin, query_df
from btb.flags import Thresholds, evaluate_flags, sensitivity_table
from btb.metrics import RATIO_COLUMNS, compute_metrics

from conftest import fin_row

CO = [["T1", "Test One", "Cement", "NSE", "", 0], ["T2", "Test Two", "Cement", "NSE", "", 0]]


def metrics_for(run, rows, companies=CO):
    db, _ = run(companies, rows)
    conn = connect(db)
    return compute_metrics(load_fin(conn)), conn


def row_for(m, ticker, fy):
    return m[(m["ticker"] == ticker) & (m["financial_year"] == fy)].iloc[0]


def test_ratio_formulas_hand_checked(run):
    m, _ = metrics_for(run, [
        fin_row("T1", "FY2020-21", rev="1000", ebit="200", intr="50", debt="400", eq="800", ca="300", cl="150", ocf="180"),
        fin_row("T1", "FY2021-22", rev="1100", ebit="187", intr="55", debt="440", eq="880", ca="330", cl="165", ocf="99"),
    ])
    r = row_for(m, "T1", "FY2021-22")
    assert r["interest_coverage"] == pytest.approx(187 / 55)
    assert r["debt_to_equity"] == pytest.approx(0.5)
    assert r["current_ratio"] == pytest.approx(2.0)
    assert r["ocf_to_debt"] == pytest.approx(99 / 440)
    assert r["revenue_growth"] == pytest.approx(0.10)
    assert r["ebit_margin"] == pytest.approx(187 / 1100)
    assert math.isnan(row_for(m, "T1", "FY2020-21")["revenue_growth"])   # no prior year


def test_edge_cases_give_nan_not_zero(run):
    m, _ = metrics_for(run, [
        fin_row("T1", "FY2020-21", rev="1000", ebit="200", intr="0", debt="400", eq="-50", ca="300", cl="0", ocf="10"),
        fin_row("T1", "FY2021-22", rev="0", ebit="-30", intr="-5", debt="0", eq="0", ca="", cl="100", ocf="-20"),
    ])
    a, b = row_for(m, "T1", "FY2020-21"), row_for(m, "T1", "FY2021-22")
    assert math.isnan(a["interest_coverage"])      # zero interest
    assert math.isnan(a["debt_to_equity"])         # negative equity
    assert math.isnan(a["current_ratio"])          # zero current liabilities
    assert math.isnan(b["interest_coverage"])      # negative interest
    assert math.isnan(b["debt_to_equity"])         # zero equity
    assert math.isnan(b["ocf_to_debt"])            # zero debt
    assert math.isnan(b["ebit_margin"])            # zero revenue
    assert math.isnan(b["current_ratio"])          # missing current assets
    assert b["revenue_growth"] == pytest.approx(-1.0)   # 1000 -> 0 is a -100% change, valid


def test_negative_ebit_gives_negative_ratios(run):
    m, _ = metrics_for(run, [fin_row("T1", "FY2020-21", rev="1000", ebit="-100", intr="50", debt="10", eq="10",
                                     ca="1", cl="1", ocf="-10")])
    r = row_for(m, "T1", "FY2020-21")
    assert r["interest_coverage"] == pytest.approx(-2.0)
    assert r["ebit_margin"] == pytest.approx(-0.1)
    assert r["ocf_to_debt"] == pytest.approx(-1.0)


def test_growth_needs_consecutive_years(run):
    m, _ = metrics_for(run, [
        fin_row("T1", "FY2020-21", rev="100", ebit="10"),
        fin_row("T1", "FY2022-23", rev="150", ebit="12"),     # FY2021-22 missing
    ])
    assert math.isnan(row_for(m, "T1", "FY2022-23")["revenue_growth"])
    assert math.isnan(row_for(m, "T1", "FY2022-23")["margin_change"])


def test_non_12_month_period_blocks_year_on_year_measures(run):
    """A 15-month period (e.g. after a year-end change) must not produce growth or change figures."""
    rows = [
        fin_row("T1", "FY2022-23", rev="1250", ebit="100", intr="10", debt="100", eq="500", period="15"),
        fin_row("T1", "FY2023-24", rev="1000", ebit="80", intr="10", debt="150", eq="500"),
        fin_row("T1", "FY2024-25", rev="900", ebit="60", intr="10", debt="200", eq="500"),
    ]
    m, conn = metrics_for(run, rows)
    a, b, c = (row_for(m, "T1", fy) for fy in ("FY2022-23", "FY2023-24", "FY2024-25"))
    assert math.isnan(a["revenue_growth"]) and math.isnan(b["revenue_growth"])   # 15m is not comparable
    assert math.isnan(b["ebit_change_cr"]) and math.isnan(b["debt_change_cr"])
    assert c["revenue_growth"] == pytest.approx(-0.10)                          # 12m -> 12m is fine
    assert not b["has_prior_year"] and c["has_prior_year"]
    f = evaluate_flags(m)
    # Debt rose and EBIT fell in FY2023-24 vs the 15-month period, but that comparison is invalid
    assert not ((f["rule_id"] == "DEBT_UP_EBIT_DOWN") & (f["financial_year"] == "FY2023-24")).any()
    assert ((f["rule_id"] == "DEBT_UP_EBIT_DOWN") & (f["financial_year"] == "FY2024-25")).any()
    # ratios that are not flow-vs-prior-year still work for the 15-month row
    assert a["ebit_margin"] == pytest.approx(0.08)
    sql = query_df(conn, "SELECT revenue_growth FROM v_ratios WHERE financial_year = 'FY2023-24'")
    assert sql["revenue_growth"].isna().all()                                    # SQL view agrees


def test_growth_does_not_leak_across_companies(run):
    m, _ = metrics_for(run, [
        fin_row("T1", "FY2020-21", rev="100", ebit="10"),
        fin_row("T2", "FY2021-22", rev="500", ebit="50"),
    ])
    assert math.isnan(row_for(m, "T2", "FY2021-22")["revenue_growth"])


def test_sql_views_match_pandas(demo_db):
    conn = connect(demo_db)
    py = compute_metrics(load_fin(conn))
    sql = query_df(conn, "SELECT * FROM v_ratios")
    key = ["ticker", "basis", "financial_year"]
    merged = py.merge(sql, on=key, suffixes=("_py", "_sql"))
    assert len(merged) == len(py) == len(sql) > 0
    for col in RATIO_COLUMNS:
        a, b = merged[f"{col}_py"], merged[f"{col}_sql"]
        assert (a.isna() == b.isna()).all(), col
        assert ((a - b).abs().fillna(0) < 1e-9).all(), col


def test_sql_debt_up_ebit_down_matches_python_rule(demo_db):
    from btb.db import split_sql_queries
    from btb import config
    conn = connect(demo_db)
    sql_rows = query_df(conn, split_sql_queries((config.SQL_DIR / "analysis_queries.sql").read_text())["debt_up_ebit_down_sql"])
    py = evaluate_flags(compute_metrics(load_fin(conn)))
    py = py[py["rule_id"] == "DEBT_UP_EBIT_DOWN"]
    assert set(zip(sql_rows["ticker"], sql_rows["financial_year"])) == set(zip(py["ticker"], py["financial_year"]))


# --- flags -------------------------------------------------------------------
def flags_for(run, rows, t=None):
    m, conn = metrics_for(run, rows)
    return evaluate_flags(m, t), m


def test_each_rule_fires_with_evidence(run):
    f, _ = flags_for(run, [
        fin_row("T1", "FY2020-21", rev="1000", ebit="300", intr="50", debt="400", eq="800", ca="300", cl="150", ocf="100"),
        fin_row("T1", "FY2021-22", rev="950", ebit="200", intr="150", debt="500", eq="800", ca="100", cl="150", ocf="-5"),
        fin_row("T1", "FY2022-23", rev="900", ebit="120", intr="160", debt="600", eq="-10", ca="100", cl="150", ocf="20"),
    ])
    rules = set(f["rule_id"])
    assert {"LOW_INTEREST_COVERAGE", "NEGATIVE_OPERATING_CASH_FLOW", "DEBT_UP_EBIT_DOWN", "LOW_CURRENT_RATIO",
            "SUSTAINED_EBIT_MARGIN_DECLINE", "SUSTAINED_REVENUE_DECLINE", "NONPOSITIVE_EQUITY"} == rules
    assert f["evidence"].str.len().gt(10).all()
    low_cov = f[f["rule_id"] == "LOW_INTEREST_COVERAGE"]
    assert set(low_cov["financial_year"]) == {"FY2021-22", "FY2022-23"}   # 1.33x and 0.75x
    assert (f["rule_id"].isin(["SUSTAINED_EBIT_MARGIN_DECLINE", "SUSTAINED_REVENUE_DECLINE"])
            & (f["financial_year"] == "FY2022-23")).sum() == 2


def test_missing_data_never_triggers_flags(run):
    f, _ = flags_for(run, [fin_row("T1", "FY2020-21", rev="1000"), fin_row("T1", "FY2021-22", rev="1100")])
    assert f.empty


def test_zero_interest_does_not_flag_low_coverage(run):
    f, _ = flags_for(run, [fin_row("T1", "FY2020-21", rev="1000", ebit="10", intr="0")])
    assert "LOW_INTEREST_COVERAGE" not in set(f["rule_id"])


def test_threshold_changes_flags(run):
    rows = [fin_row("T1", "FY2020-21", rev="1000", ebit="200", intr="100")]   # coverage 2.0x
    strict, _ = flags_for(run, rows, Thresholds(interest_coverage_min=1.5))
    loose, _ = flags_for(run, rows, Thresholds(interest_coverage_min=3.0))
    assert "LOW_INTEREST_COVERAGE" not in set(strict["rule_id"])
    assert "LOW_INTEREST_COVERAGE" in set(loose["rule_id"])


def test_sustained_years_parameter(run):
    rows = [fin_row("T1", fy, rev=str(r), ebit="10") for fy, r in
            [("FY2020-21", 1000), ("FY2021-22", 900), ("FY2022-23", 800)]]
    f2, _ = flags_for(run, rows, Thresholds(sustained_years=2))
    f3, _ = flags_for(run, rows, Thresholds(sustained_years=3))
    assert "SUSTAINED_REVENUE_DECLINE" in set(f2["rule_id"])
    assert "SUSTAINED_REVENUE_DECLINE" not in set(f3["rule_id"])


def test_sensitivity_table_is_monotonic(demo_db):
    conn = connect(demo_db)
    m = compute_metrics(load_fin(conn))
    s = sensitivity_table(m)
    cov = s[s["rule_id"] == "LOW_INTEREST_COVERAGE"].sort_values("value")
    assert list(cov["flagged_company_years"]) == sorted(cov["flagged_company_years"])    # higher threshold flags more
    assert cov["is_base_value"].sum() == 1
    seq = s[s["rule_id"] == "SUSTAINED_REVENUE_DECLINE"].sort_values("value")
    assert list(seq["flagged_company_years"]) == sorted(seq["flagged_company_years"], reverse=True)


def test_demo_data_expected_flags(demo_db):
    conn = connect(demo_db)
    f = evaluate_flags(compute_metrics(load_fin(conn)))
    got = {(r.ticker, r.financial_year, r.rule_id) for r in f.itertuples()}
    assert ("DEMOB", "FY2023-24", "LOW_INTEREST_COVERAGE") in got
    assert ("DEMOC", "FY2022-23", "NEGATIVE_OPERATING_CASH_FLOW") in got
    assert ("DEMOC", "FY2023-24", "SUSTAINED_REVENUE_DECLINE") in got
    assert not any(r.ticker == "DEMOA" and r.rule_id == "LOW_INTEREST_COVERAGE" for r in f.itertuples())

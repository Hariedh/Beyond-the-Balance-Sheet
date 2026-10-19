"""Tests added after an external review of the screening logic: missing data, direction of warnings,
cash-flow context, basis separation, display precision and the optional capex input."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from btb import config
from btb.db import connect, load_fin, query_df
from btb.evidence import build_packet
from btb.flags import Thresholds, evaluate_flags
from btb.fmt import fmt_x
from btb.metrics import compute_metrics, context_notes
from btb.pipeline import run_pipeline

from conftest import COMPANY_HEADER, write_csv

CO = [["T1", "Test One", "Cement", "NSE", "", 0]]
HEADER = ["ticker", "financial_year", "basis", "unit", *config.NUMERIC_FIELDS, "capex",
          "definitions_note", "source", "source_url", "notes", "is_illustrative", "period_months"]


def row(fy, basis="consolidated", rev="", ebit="", intr="", debt="", eq="", ca="", cl="", ocf="", capex="", period=""):
    return ["T1", fy, basis, "crores", rev, ebit, intr, debt, eq, ca, cl, ocf, "", capex,
            "defs", "src", "", "", 0, period]


def build(tmp_path, rows, thresholds=None):
    c = write_csv(tmp_path / "c.csv", COMPANY_HEADER, CO)
    f = write_csv(tmp_path / "f.csv", HEADER, rows)
    db = tmp_path / "t.sqlite"
    run_pipeline(db_path=db, company_files=[c], financial_files=[f], disclosure_files=[], external_files=[], verification_files=[],
                 export_dir=None, thresholds=thresholds)
    conn = connect(db)
    return conn, compute_metrics(load_fin(conn))


# --- display precision ---------------------------------------------------------
def test_small_multiples_keep_three_decimals():
    assert fmt_x(0.016) == "0.016x"
    assert fmt_x(0.0) == "0.00x"
    assert fmt_x(16.43) == "16.43x"
    assert fmt_x(0.5) == "0.50x"
    assert fmt_x(0.123456, digits=1) == "0.1x"      # an explicit request still wins
    assert fmt_x(float("nan")) == "n/a"


# --- capex / free cash flow ------------------------------------------------------
def test_fcf_is_nan_when_capex_missing_never_zero(tmp_path):
    conn, m = build(tmp_path, [row("FY2021-22", rev="100", ebit="10", intr="2", ocf="30", capex=""),
                               row("FY2022-23", rev="110", ebit="11", intr="2", ocf="30", capex="45")])
    assert math.isnan(m.loc[m.financial_year == "FY2021-22", "free_cash_flow_cr"].iloc[0])
    assert m.loc[m.financial_year == "FY2022-23", "free_cash_flow_cr"].iloc[0] == pytest.approx(-15)
    flags = evaluate_flags(m)
    fcf = flags[flags.rule_id == "NEGATIVE_FREE_CASH_FLOW"]
    assert list(fcf.financial_year) == ["FY2022-23"]             # not fired for the year with no capex
    assert (fcf.severity == "info").all()


def test_capex_column_is_optional(tmp_path):
    header = [h for h in HEADER if h != "capex"]
    r = row("FY2021-22", rev="100", ebit="10", intr="2")
    del r[HEADER.index("capex")]
    c = write_csv(tmp_path / "c.csv", COMPANY_HEADER, CO)
    f = write_csv(tmp_path / "f.csv", header, [r])
    db = tmp_path / "t.sqlite"
    s = run_pipeline(db_path=db, company_files=[c], financial_files=[f], disclosure_files=[], external_files=[], verification_files=[],
                     export_dir=None)
    assert s["financial_rows_loaded"] == 1


def test_negative_capex_sign_is_flagged(tmp_path):
    conn, _ = build(tmp_path, [row("FY2021-22", rev="100", ebit="10", intr="2", ocf="30", capex="-20")])
    issues = query_df(conn, "SELECT check_name FROM validation_issues")
    assert "negative_capex" in set(issues.check_name)


# --- direction of warning logic -----------------------------------------------------
def test_flags_fire_only_in_the_adverse_direction(tmp_path):
    # Improving, healthy company: more coverage, less debt, positive cash flow, higher current ratio.
    conn, m = build(tmp_path, [
        row("FY2020-21", rev="100", ebit="10", intr="5", debt="50", eq="100", ca="60", cl="50", ocf="8", capex="2"),
        row("FY2021-22", rev="120", ebit="20", intr="4", debt="30", eq="120", ca="90", cl="50", ocf="25", capex="5"),
    ])
    assert evaluate_flags(m).empty


def test_debt_up_ebit_down_needs_both_moves(tmp_path):
    conn, m = build(tmp_path, [
        row("FY2020-21", rev="100", ebit="20", intr="2", debt="50", eq="100"),
        row("FY2021-22", rev="100", ebit="25", intr="2", debt="80", eq="100"),     # debt up, EBIT up
        row("FY2022-23", rev="100", ebit="10", intr="2", debt="40", eq="100"),     # debt down, EBIT down
        row("FY2023-24", rev="100", ebit="5", intr="2", debt="60", eq="100"),      # debt up, EBIT down
    ])
    fired = evaluate_flags(m)
    assert list(fired[fired.rule_id == "DEBT_UP_EBIT_DOWN"].financial_year) == ["FY2023-24"]


# --- interest coverage must not be read alone ------------------------------------------
def test_high_coverage_with_negative_cash_flow_gets_a_caution(tmp_path):
    conn, m = build(tmp_path, [row("FY2021-22", rev="100", ebit="80", intr="5", debt="2", eq="100", ocf="-30")])
    r = m.iloc[0]
    assert r["interest_coverage"] == pytest.approx(16.0)
    assert not (evaluate_flags(m).rule_id == "LOW_INTEREST_COVERAGE").any()           # coverage rule is quiet...
    assert any("not cash" in n for n in context_notes(r))                              # ...but a caution is raised
    assert (evaluate_flags(m).rule_id == "NEGATIVE_OPERATING_CASH_FLOW").any()


def test_current_ratio_flag_carries_industry_caveat(tmp_path):
    conn, m = build(tmp_path, [row("FY2021-22", rev="100", ebit="10", intr="2", ca="70", cl="100")])
    flag = evaluate_flags(m).query("rule_id == 'LOW_CURRENT_RATIO'").iloc[0]
    assert "normal for some business models" in flag["evidence"]


def test_growth_context_note_present_only_when_growth_exists(tmp_path):
    conn, m = build(tmp_path, [row("FY2020-21", rev="100", ebit="10", intr="2"),
                               row("FY2021-22", rev="119", ebit="12", intr="2")])
    assert not any("Revenue growth" in n for n in context_notes(m.iloc[0]))
    assert any("acquisitions" in n for n in context_notes(m.iloc[1]))


# --- reporting basis never mixed -----------------------------------------------------------
def test_standalone_and_consolidated_do_not_leak_into_growth(tmp_path):
    conn, m = build(tmp_path, [
        row("FY2020-21", basis="consolidated", rev="1000", ebit="100", intr="10"),
        row("FY2021-22", basis="standalone", rev="500", ebit="50", intr="5"),
    ])
    assert m["revenue_growth"].isna().all()           # different bases: no year-on-year comparison
    assert m["has_prior_year"].eq(False).all()


# --- year selection: gaps give n/a, not a bridged comparison ----------------------------------
def test_gap_year_gives_na_growth(tmp_path):
    conn, m = build(tmp_path, [row("FY2020-21", rev="100", ebit="10", intr="2"),
                               row("FY2022-23", rev="130", ebit="12", intr="2")])
    assert math.isnan(m.loc[m.financial_year == "FY2022-23", "revenue_growth"].iloc[0])


# --- evidence honesty ------------------------------------------------------------------------------
def test_packet_says_when_no_explanatory_evidence_is_loaded(tmp_path):
    conn, _ = build(tmp_path, [row("FY2021-22", rev="100", ebit="10", intr="2", ocf="5", capex="3")])
    packet = build_packet(conn, "T1", "consolidated")
    assert any("no_explanatory_evidence" in n for n in packet["data_quality_notes"])
    ids = {f["id"] for f in packet["figures"]}
    assert "F.capex_cr.FY2021-22" in ids and "F.free_cash_flow_cr.FY2021-22" in ids


# --- shipped real data -----------------------------------------------------------------------------
def test_real_data_capex_rows_and_unresolved_periods(tmp_path):
    db = tmp_path / "real.sqlite"
    run_pipeline(db_path=db, export_dir=None, financial_files=[config.RAW_DIR / "financials_real.csv"],
                 company_files=[config.RAW_DIR / "companies_candidates.csv"])
    m = compute_metrics(load_fin(connect(db)))
    assert m["capex_cr"].notna().sum() == 21
    for t in ("AMBUJACEM", "ACC"):                      # 15-month period with disputed cash flow: no capex, no FCF
        r = m[(m.ticker == t) & (m.financial_year == "FY2022-23")].iloc[0]
        assert pd.isna(r["capex_cr"]) and pd.isna(r["free_cash_flow_cr"])
    u = m[(m.ticker == "ULTRACEMCO") & (m.financial_year == "FY2025-26")].iloc[0]
    assert u["capex_cr"] == pytest.approx(9677.8)
    assert u["free_cash_flow_cr"] == pytest.approx(15316 - 9677.8, abs=1)
    acc = m[(m.ticker == "ACC") & (m.financial_year == "FY2025-26")].iloc[0]
    assert acc["debt_to_equity"] < 0.1 and fmt_x(acc["debt_to_equity"]).count(".") == 1
    assert len(fmt_x(acc["debt_to_equity"]).split(".")[1]) == 4      # "0.021x": three decimals plus the x

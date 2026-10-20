"""Tests for persistence, stress, peers, verification, assessment, report and DB staleness."""
from __future__ import annotations

import math
import os
import time

import pandas as pd
import pytest

from btb import config
from btb.db import connect, db_is_stale, load_fin
from btb.flags import Thresholds
from btb.metrics import compute_metrics
from btb.peers import peer_context, peer_medians, peer_table, same_universe
from btb.persistence import persistence_table
from btb.stress import StressInputs, stress_table, stress_test
from btb.verification import input_status, summary, worst_status

CO = [["AAA", "Alpha", "Cement", "NSE", "", 0], ["BBB", "Beta", "Cement", "NSE", "", 0],
      ["CCC", "Gamma", "Cement", "NSE", "", 0], ["DEMOX", "Demo X", "Cement", "NSE", "", 1],
      ["DEMOY", "Demo Y", "Cement", "NSE", "", 1]]


def row(t, fy, rev="1000", ebit="100", intr="50", debt="500", eq="1000", ca="400", cl="300", ocf="120",
        ill=0, period=""):
    return [t, fy, "consolidated", "crores", rev, ebit, intr, debt, eq, ca, cl, ocf, "", "defs", "src", "", "", ill, period]


def metrics(run, rows):
    db, _ = run(CO, rows)
    conn = connect(db)
    try:
        return compute_metrics(load_fin(conn))
    finally:
        conn.close()


def pstatus(pt, ticker, fy, ind):
    r = pt[(pt.ticker == ticker) & (pt.financial_year == fy) & (pt.indicator == ind)]
    return r.iloc[0]["status"], int(r.iloc[0]["streak"])


# ---------------- persistence ----------------
def low_cov(ebit):  # interest 100 => coverage = ebit/100
    return ebit


def test_persistence_consecutive_breaches_become_persistent(run):
    rows = [row("AAA", "FY2021-22", ebit="80", intr="100"), row("AAA", "FY2022-23", ebit="80", intr="100"),
            row("AAA", "FY2023-24", ebit="80", intr="100")]
    pt = persistence_table(metrics(run, rows), Thresholds(sustained_years=3))
    assert pstatus(pt, "AAA", "FY2021-22", "LOW_INTEREST_COVERAGE") == ("history_unknown", 1)
    assert pstatus(pt, "AAA", "FY2022-23", "LOW_INTEREST_COVERAGE") == ("building", 2)
    assert pstatus(pt, "AAA", "FY2023-24", "LOW_INTEREST_COVERAGE") == ("persistent", 3)


def test_persistence_gap_year_is_not_satisfactory_and_breaks_streak(run):
    # FY2022-23 missing entirely: the later breach must not inherit a streak, and 'new' is not claimed.
    rows = [row("AAA", "FY2021-22", ebit="80", intr="100"), row("AAA", "FY2023-24", ebit="80", intr="100")]
    pt = persistence_table(metrics(run, rows), Thresholds())
    assert pstatus(pt, "AAA", "FY2023-24", "LOW_INTEREST_COVERAGE") == ("history_unknown", 1)


def test_persistence_not_assessable_when_input_missing(run):
    rows = [row("AAA", "FY2021-22", intr=""), row("AAA", "FY2022-23", ebit="80", intr="100")]
    pt = persistence_table(metrics(run, rows), Thresholds())
    assert pstatus(pt, "AAA", "FY2021-22", "LOW_INTEREST_COVERAGE")[0] == "not_assessable"
    assert pstatus(pt, "AAA", "FY2022-23", "LOW_INTEREST_COVERAGE")[0] == "history_unknown"


def test_persistence_new_and_recovered(run):
    rows = [row("AAA", "FY2021-22"), row("AAA", "FY2022-23", ebit="80", intr="100"), row("AAA", "FY2023-24")]
    pt = persistence_table(metrics(run, rows), Thresholds())
    assert pstatus(pt, "AAA", "FY2021-22", "LOW_INTEREST_COVERAGE")[0] == "ok"
    assert pstatus(pt, "AAA", "FY2022-23", "LOW_INTEREST_COVERAGE")[0] == "new"
    assert pstatus(pt, "AAA", "FY2023-24", "LOW_INTEREST_COVERAGE")[0] == "recovered"


def test_persistence_sustained_years_boundary(run):
    rows = [row("AAA", "FY2021-22", ebit="80", intr="100"), row("AAA", "FY2022-23", ebit="80", intr="100")]
    m = metrics(run, rows)
    assert pstatus(persistence_table(m, Thresholds(sustained_years=2)), "AAA", "FY2022-23", "LOW_INTEREST_COVERAGE")[0] == "persistent"
    assert pstatus(persistence_table(m, Thresholds(sustained_years=3)), "AAA", "FY2022-23", "LOW_INTEREST_COVERAGE")[0] == "building"


def test_persistence_15_month_period_blocks_growth_streak(run):
    rows = [row("AAA", "FY2021-22", rev="1000"), row("AAA", "FY2022-23", rev="900", period="15"),
            row("AAA", "FY2023-24", rev="800")]
    pt = persistence_table(metrics(run, rows), Thresholds())
    assert pstatus(pt, "AAA", "FY2022-23", "REVENUE_DECLINE")[0] == "not_assessable"
    assert pstatus(pt, "AAA", "FY2023-24", "REVENUE_DECLINE")[0] == "not_assessable"


def test_persistence_empty_frame():
    assert persistence_table(pd.DataFrame(), Thresholds()).empty


def test_threshold_boundary_is_strict(run):
    rows = [row("AAA", "FY2021-22", ebit="150", intr="100")]   # coverage exactly 1.5
    pt = persistence_table(metrics(run, rows), Thresholds())
    assert pstatus(pt, "AAA", "FY2021-22", "LOW_INTEREST_COVERAGE")[0] == "ok"


# ---------------- stress ----------------
BASE = {"revenue_cr": 1000.0, "ebit_cr": 200.0, "interest_expense_cr": 50.0,
        "operating_cash_flow_cr": 180.0, "capex_cr": 100.0, "period_months": 12}


def test_stress_revenue_only_constant_margin():
    r = stress_test(BASE, StressInputs(revenue_decline=0.2))
    assert r["scenario"]["revenue"] == pytest.approx(800)
    assert r["scenario"]["ebit"] == pytest.approx(160)          # margin 20% kept
    assert r["scenario"]["ebit_margin"] == pytest.approx(0.20)
    assert r["scenario"]["interest_coverage"] == pytest.approx(3.2)


def test_stress_fixed_cost_share_operating_leverage():
    r = stress_test(BASE, StressInputs(revenue_decline=0.2, fixed_cost_share=1.0))
    assert r["scenario"]["ebit"] == pytest.approx(800 - 800)    # all costs fixed (cost 800)
    r2 = stress_test(BASE, StressInputs(revenue_decline=0.2, fixed_cost_share=0.5))
    assert r2["scenario"]["ebit"] == pytest.approx(800 - (400 + 400 * 0.8))


def test_stress_margin_shock_applied_to_scenario_revenue():
    r = stress_test(BASE, StressInputs(revenue_decline=0.1, margin_decline_pp=0.02))
    assert r["scenario"]["ebit"] == pytest.approx(900 - 800 * 0.9 - 0.02 * 900)


def test_stress_fcf_follows_ebit_shortfall():
    r = stress_test(BASE, StressInputs(revenue_decline=0.2))
    assert r["baseline"]["fcf"] == pytest.approx(80)
    assert r["scenario"]["fcf"] == pytest.approx(80 - 40)


def test_stress_no_fcf_without_capex():
    r = stress_test({**BASE, "capex_cr": float("nan")}, StressInputs(revenue_decline=0.1))
    assert "fcf" not in r["scenario"] and any("Free cash flow" in n for n in r["notes"])


def test_stress_zero_and_missing_interest():
    r = stress_test({**BASE, "interest_expense_cr": 0.0}, StressInputs(revenue_decline=0.1))
    assert r["scenario"]["interest_coverage"] is None and r["breakeven_revenue_decline"] is None
    r = stress_test({**BASE, "interest_expense_cr": None}, StressInputs(revenue_decline=0.1))
    assert r["available"] and r["scenario"]["interest_coverage"] is None


def test_stress_negative_ebit_baseline_and_scenario():
    r = stress_test({**BASE, "ebit_cr": -50.0}, StressInputs(revenue_decline=0.1))
    assert r["available"] and r["scenario"]["interest_coverage"] < 0
    assert any("negative" in n.lower() for n in r["notes"])


def test_stress_unavailable_inputs():
    assert not stress_test({**BASE, "revenue_cr": None}, StressInputs())["available"]
    assert not stress_test({**BASE, "revenue_cr": 0.0}, StressInputs())["available"]
    assert not stress_test({**BASE, "ebit_cr": None}, StressInputs())["available"]
    assert not stress_test(BASE, StressInputs(revenue_decline=1.0))["available"]
    assert not stress_test(BASE, StressInputs(fixed_cost_share=1.5))["available"]


def test_stress_breakeven_hits_one_times_coverage():
    f = 0.3
    r = stress_test(BASE, StressInputs(fixed_cost_share=f))
    k = r["breakeven_revenue_decline"]
    again = stress_test(BASE, StressInputs(revenue_decline=k, fixed_cost_share=f))
    assert again["scenario"]["interest_coverage"] == pytest.approx(1.0)


def test_stress_non_12_month_period_noted():
    r = stress_test({**BASE, "period_months": 15}, StressInputs(revenue_decline=0.1))
    assert any("15-month" in n for n in r["notes"])


def test_stress_table_shape():
    t = stress_table(stress_test(BASE, StressInputs(revenue_decline=0.1)))
    assert len(t) >= 3


# ---------------- peers ----------------
def peer_rows():
    return [row("AAA", "FY2024-25"), row("BBB", "FY2024-25", ebit="300"), row("CCC", "FY2024-25", period="15"),
            row("AAA", "FY2023-24"), row("DEMOX", "FY2024-25", ill=1), row("DEMOY", "FY2024-25", ill=1, ebit="500")]


def test_peer_universes_never_mix(run):
    m = metrics(run, peer_rows())
    real = peer_table(m, "consolidated", "FY2024-25", illustrative=False)
    demo = peer_table(m, "consolidated", "FY2024-25", illustrative=True)
    assert set(real.ticker) == {"AAA", "BBB", "CCC"} and set(demo.ticker) == {"DEMOX", "DEMOY"}
    assert set(same_universe(m, True).ticker) == {"DEMOX", "DEMOY"}


def test_peer_non_12_month_excluded_from_medians(run):
    m = metrics(run, peer_rows())
    t = peer_table(m, "consolidated", "FY2024-25", False)
    assert not t[t.ticker == "CCC"].iloc[0]["comparable"]
    med = peer_medians(t).set_index("metric")
    assert med.loc["ebit_margin", "n"] == 2
    assert med.loc["ebit_margin", "median"] == pytest.approx((0.10 + 0.30) / 2)


def test_peer_missing_year_is_listed_not_hidden(run):
    m = metrics(run, peer_rows())
    t = peer_table(m, "consolidated", "FY2023-24", False)
    assert set(t.ticker) == {"AAA", "BBB", "CCC"}
    assert "no data" in t[t.ticker == "BBB"].iloc[0]["status"]


def test_peer_context_needs_two_peers(run):
    m = metrics(run, peer_rows())
    c = peer_context(m, "AAA", "consolidated", "FY2024-25", "ebit_margin", False)
    assert c["median"] is None and "too few" in c["text"]


def test_peer_empty_dataset():
    t = peer_table(compute_metrics(pd.DataFrame()), "consolidated", "FY2024-25", False)
    assert t.empty


# ---------------- verification ----------------
VER = pd.DataFrame([
    {"ticker": "AAA", "financial_year": "FY2024-25", "item": "revenue", "status": "verified", "difference_pct": 0.0},
    {"ticker": "AAA", "financial_year": "FY2024-25", "item": "ebit", "status": "discrepancy", "difference_pct": 5.0},
    {"ticker": "AAA", "financial_year": "FY2024-25", "item": "total_debt", "status": "approx", "difference_pct": 0.4},
])


def test_verification_worst_status_and_unchecked():
    assert worst_status(VER, "AAA", "FY2024-25", ["revenue", "total_debt"]) == "approx"
    assert worst_status(VER, "AAA", "FY2024-25", ["revenue", "ebit"]) == "discrepancy"
    assert worst_status(VER, "AAA", "FY2024-25", ["revenue", "cash"]) == "unverified"
    assert worst_status(None, "AAA", "FY2024-25", ["revenue"]) == "unverified"
    assert "not checked" in input_status(VER, "BBB", "FY2024-25", ["revenue"])
    assert "DISCREPANCY" in input_status(VER, "AAA", "FY2024-25", ["ebit"])
    assert summary(VER, "AAA")["discrepancy"] == 1 and summary(VER, "ZZZ")["checked"] == 0


def test_verification_csv_loads_and_discrepancy_warns(tmp_path, tmp_inputs):
    from btb.pipeline import run_pipeline
    from tests.conftest import write_csv
    c, f = tmp_inputs(CO[:1], [row("AAA", "FY2024-25")])
    hdr = ["ticker", "financial_year", "basis", "item", "app_value_cr", "filing_value_cr", "difference_cr",
           "difference_pct", "status", "method", "source_doc", "publication_date", "location", "source_url", "notes"]
    v = write_csv(tmp_path / "v.csv", hdr, [["AAA", "FY2024-25", "consolidated", "revenue", 1000, 1100, -100, -9.09,
                                              "discrepancy", "m", "Annual report", "2025-05-01", "p.1", "", ""]])
    db = tmp_path / "v.sqlite"
    s = run_pipeline(db_path=db, company_files=[c], financial_files=[f], disclosure_files=[], external_files=[],
                     verification_files=[v], export_dir=None)
    assert s["source_verifications_loaded"] == 1 and s["issues_warning"] >= 1


# ---------------- DB staleness / empty data ----------------
def test_db_is_stale(tmp_path, monkeypatch):
    fake = tmp_path / "x.sqlite"
    monkeypatch.setattr(config, "DB_PATH", fake)
    assert db_is_stale()
    fake.write_text("x")
    future = time.time() + 100
    os.utime(fake, (future, future))
    assert not db_is_stale()
    past = time.time() - 10**6
    os.utime(fake, (past, past))
    assert db_is_stale()


def test_empty_dataset_pipeline_and_metrics(run):
    db, summary_ = run(CO[:1], [])
    assert summary_["flags"] == 0
    assert compute_metrics(pd.DataFrame()).empty


def test_capex_negative_and_free_cash_flow(run):
    m = metrics(run, [row("AAA", "FY2024-25")])
    assert "free_cash_flow_cr" in m.columns and math.isnan(m.iloc[0]["free_cash_flow_cr"])  # no capex loaded


# ---------------- assessment + report ----------------
from btb.assessment import assess_year, explain_flags  # noqa: E402
from btb.flags import evaluate_flags  # noqa: E402
from btb.peers import peer_table as _pt  # noqa: E402
from btb.report import build_report  # noqa: E402


def _assess(m, ticker="AAA", t=None, ver=None):
    t = t or Thresholds()
    flags = evaluate_flags(m, t)
    pers = persistence_table(m, t)
    cur = m[m.ticker == ticker].sort_values("fy_start").iloc[-1]
    fy = cur["financial_year"]
    f = flags[(flags.ticker == ticker) & (flags.financial_year == fy)] if not flags.empty else flags
    p = pers[(pers.ticker == ticker) & (pers.financial_year == fy)]
    return cur, flags, pers, assess_year(cur, f, p, t, ver)


def test_assess_conflict_strong_coverage_negative_ocf(run):
    m = metrics(run, [row("AAA", "FY2024-25", ebit="500", intr="50", ocf="-20")])
    _, _, _, a = _assess(m)
    assert any(x["kind"] == "conflict" for x in a)


def test_assess_no_flags_is_inconclusive_not_safe(run):
    m = metrics(run, [row("AAA", "FY2023-24", ebit="480", intr="50", ca="900", cl="300", rev="990", ocf="200"),
                      row("AAA", "FY2024-25", ebit="500", intr="50", ca="900", cl="300", ocf="200")])
    _, _, _, a = _assess(m)
    inc = [x for x in a if x["kind"] == "inconclusive"]
    assert inc and "not that risk is low" in inc[0]["text"]


def test_assess_convergence_two_areas(run):
    rows = [row("AAA", "FY2023-24", ebit="150", intr="50", debt="500"),
            row("AAA", "FY2024-25", ebit="60", intr="50", debt="900", ca="200", cl="400", ocf="-10")]
    m = metrics(run, rows)
    _, _, _, a = _assess(m)
    assert any(x["kind"] == "convergence" for x in a)


def test_assess_15_month_period_is_data_limitation(run):
    m = metrics(run, [row("AAA", "FY2022-23", period="15")])
    _, _, _, a = _assess(m)
    assert any(x["kind"] == "data_limitation" and "15-month" in x["text"] for x in a)


def test_assess_too_little_data_is_inconclusive(run):
    m = metrics(run, [row("AAA", "FY2024-25", ebit="", intr="", debt="", eq="", ca="", cl="", ocf="")])
    _, _, _, a = _assess(m)
    assert any(x["kind"] == "inconclusive" and "too few" in x["text"].lower() for x in a)


def test_explain_flags_has_all_required_columns(run):
    rows = [row("AAA", "FY2023-24"), row("AAA", "FY2024-25", ebit="60", intr="50")]
    m = metrics(run, rows)
    t = Thresholds()
    ex = explain_flags(evaluate_flags(m, t), m, t, None)
    assert not ex.empty
    for c in ("Indicator", "Observed", "Threshold", "Formula", "Why it matters", "Persistence", "History",
              "Peer context", "Data quality", "Follow-up"):
        assert ex[c].astype(str).str.len().gt(0).all(), c


def test_explain_flags_empty():
    assert explain_flags(pd.DataFrame(), pd.DataFrame(), Thresholds()).empty


def test_report_sections_and_basis_labels(run):
    rows = [row("AAA", "FY2023-24"), row("AAA", "FY2024-25", ebit="60", intr="50"), row("BBB", "FY2024-25")]
    m = metrics(run, rows)
    t = Thresholds()
    mm = m[m.ticker == "AAA"].sort_values("fy_start").reset_index(drop=True)
    flags = evaluate_flags(m, t)
    ex = explain_flags(flags[flags.ticker == "AAA"], m, t, None)
    cur, _, _, a = _assess(m)
    ptab = _pt(m, "consolidated", "FY2024-25", False)
    rep = build_report(ticker="AAA", name="Alpha", basis="consolidated", m=mm, fy_from="FY2023-24", fy_to="FY2024-25",
                       thresholds=t, explained=ex, assessment=a, peer=ptab, peer_med=peer_medians(ptab),
                       stress=stress_test(cur, StressInputs(revenue_decline=0.1)), ver=pd.DataFrame(),
                       disclosures=pd.DataFrame(), issues=pd.DataFrame(columns=["severity", "check_name", "detail"]),
                       is_illustrative=False)
    assert {s[:2] for s in rep["section"]} == {f"{i}." for i in range(1, 9)}
    assert set(rep["basis_of_statement"]) <= {"observed (loaded data)", "checked vs filing", "unverified",
                                              "hypothesis", "scenario (not forecast)", "limitation"}
    stress_rows = rep[rep["section"].str.startswith("5")]
    assert (stress_rows["basis_of_statement"] != "observed (loaded data)").all()


# ---------------- second-round audit: stress edge cases, rationale, threshold sensitivity ----------------
def test_stress_missing_ocf_gives_no_fcf_but_keeps_ebit_and_coverage():
    r = stress_test({**BASE, "operating_cash_flow_cr": None}, StressInputs(revenue_decline=0.1))
    assert r["available"] and "fcf" not in r["scenario"] and "ocf" not in r["scenario"]
    assert r["scenario"]["interest_coverage"] == pytest.approx(0.9 * 200 / 50)
    assert any("Free cash flow is not estimated" in n for n in r["notes"])


def test_stress_extreme_valid_inputs_do_not_crash_and_stay_finite():
    r = stress_test(BASE, StressInputs(revenue_decline=0.99, margin_decline_pp=0.10, fixed_cost_share=1.0))
    assert r["available"] and math.isfinite(r["scenario"]["ebit"]) and r["scenario"]["ebit"] < 0
    assert r["scenario"]["interest_coverage"] < 0


def test_stress_percent_and_percentage_point_inputs_are_different():
    pct = stress_test(BASE, StressInputs(revenue_decline=0.02))["scenario"]["ebit"]          # revenue -2%
    pp = stress_test(BASE, StressInputs(margin_decline_pp=0.02))["scenario"]["ebit"]         # margin -2 points
    assert pct == pytest.approx(200 * 0.98)            # EBIT scales with revenue at constant margin
    assert pp == pytest.approx(200 - 0.02 * 1000)      # exactly 2% of revenue removed


def test_stress_assumption_text_states_capex_fixed_and_unmodelled_items():
    text = " ".join(stress_test(BASE, StressInputs(revenue_decline=0.1))["assumptions"]).lower()
    for word in ("capex", "fixed", "taxes", "working capital", "refinancing", "not a cash-flow forecast"):
        assert word in text
    labels = " ".join(stress_table(stress_test(BASE, StressInputs(revenue_decline=0.1)))["Metric"])
    assert "simplified" in labels


def test_every_rule_has_threshold_rationale_that_disclaims_calibration():
    from btb.assessment import RULE_INFO
    for rid, info in RULE_INFO.items():
        text = info["rationale"].lower()
        assert " not " in f" {text} ", rid                       # each says what the threshold is NOT
        assert "proven" not in text and "empirically validated by" not in text, rid


def test_threshold_change_changes_flags_and_boundary_is_strict(run):
    from btb.flags import sensitivity_table
    rows = [row("AAA", "FY2024-25", ebit="150", intr="100", ca="400", cl="410")]
    m = metrics(run, rows)
    base = evaluate_flags(m, Thresholds(interest_coverage_min=1.5))
    assert "LOW_INTEREST_COVERAGE" not in set(base.rule_id)          # exactly 1.5 is not below 1.5
    up = evaluate_flags(m, Thresholds(interest_coverage_min=1.6))
    assert "LOW_INTEREST_COVERAGE" in set(up.rule_id)
    s = sensitivity_table(m, Thresholds())
    cr = s[(s.parameter == "current_ratio_min")].set_index("value")["flagged_company_years"]
    assert cr[1.0] == 1 and cr[0.8] == 0                                # current ratio 0.976


# ---------------- regression tests on the shipped real data ----------------
@pytest.fixture(scope="module")
def real_db(tmp_path_factory):
    from btb.pipeline import run_pipeline
    db = tmp_path_factory.mktemp("real") / "real.sqlite"
    run_pipeline(db_path=db, export_dir=None)
    return db


def _real_metrics(db):
    conn = connect(db)
    try:
        m = compute_metrics(load_fin(conn))
    finally:
        conn.close()
    return m[m.is_illustrative == 0]


def test_real_data_ambuja_fy26_ebit_correction_is_applied_and_logged(real_db):
    import csv
    m = _real_metrics(real_db)
    ebit = float(m[(m.ticker == "AMBUJACEM") & (m.financial_year == "FY2025-26")].iloc[0]["ebit_cr"])
    assert ebit == pytest.approx(2968.53)
    log = list(csv.DictReader(open(config.RAW_DIR / "corrections_log.csv", encoding="utf-8")))
    c = [r for r in log if r["ticker"] == "AMBUJACEM" and r["field"] == "ebit"]
    assert c and float(c[0]["original_value_cr"]) == 3007 and float(c[0]["revised_value_cr"]) == 2968.53
    assert c[0]["source_url"].startswith("https://") and c[0]["date_checked"]


def test_real_data_15_month_periods_excluded_from_yoy_and_peer_medians(real_db):
    m = _real_metrics(real_db)
    for t in ("AMBUJACEM", "ACC"):
        r = m[(m.ticker == t) & (m.financial_year == "FY2022-23")].iloc[0]
        assert int(r["period_months"]) == 15 and pd.isna(r["revenue_growth"])
        nxt = m[(m.ticker == t) & (m.financial_year == "FY2023-24")].iloc[0]
        assert pd.isna(nxt["revenue_growth"])                 # prior year is the 15-month period
    tab = peer_table(m, "consolidated", "FY2022-23", False)
    assert set(tab[~tab.comparable].ticker) == {"AMBUJACEM", "ACC"}
    med = peer_medians(tab).set_index("metric")
    assert med.loc["ebit_margin", "n"] == 3


def test_real_data_unverified_inputs_are_never_zero(real_db):
    m = _real_metrics(real_db)
    for t in ("AMBUJACEM", "ACC"):
        r = m[(m.ticker == t) & (m.financial_year == "FY2022-23")].iloc[0]
        assert pd.isna(r["operating_cash_flow_cr"]) and pd.isna(r["ocf_to_debt"])


def test_real_data_verification_statuses_and_dates(real_db):
    conn = connect(real_db)
    try:
        ver = pd.read_sql_query("SELECT v.*, c.ticker FROM source_verification v JOIN companies c USING (company_id)", conn)
    finally:
        conn.close()
    assert set(ver.status) <= {"verified", "approx", "discrepancy", "unverified"}
    assert ver.date_checked.notna().all() and ver.source_url.notna().all()
    disc = ver[ver.status == "discrepancy"]
    assert set(disc.ticker) == {"AMBUJACEM"} and set(disc.financial_year) == {"FY2024-25"}
    # UltraTech debt incl. leases is now matched against the filing
    ut = ver[(ver.ticker == "ULTRACEMCO") & (ver["item"] == "total_debt")]
    assert set(ut.status) == {"verified"}
    # lease-ambiguous debt rows stay unverified rather than being reported as matching
    amb = ver[(ver.ticker == "AMBUJACEM") & (ver["item"] == "total_debt")]
    assert set(amb.status) == {"unverified"}


def test_real_data_every_disclosure_is_classified_and_sourced(real_db):
    conn = connect(real_db)
    try:
        d = pd.read_sql_query("SELECT * FROM disclosures", conn)
        ext = pd.read_sql_query("SELECT * FROM external_indicators", conn)
    finally:
        conn.close()
    assert len(d) >= 9 and d.relationship.isin(["established", "possible_explanation", "unresolved", "not_assessed"]).all()
    assert d.source_url.notna().all() and d.publication_date.notna().all() and d.page_ref.notna().all()
    assert ext.empty                                           # optional file stays empty; nothing was invented


def test_disclosure_relationship_blank_is_not_assessed_and_invalid_is_safe(tmp_path, tmp_inputs):
    from btb.pipeline import run_pipeline
    from tests.conftest import write_csv
    c, f = tmp_inputs(CO[:1], [row("AAA", "FY2024-25")])
    hdr = ["ticker", "financial_year", "topic", "excerpt", "source_doc", "page_ref", "relationship"]
    d = write_csv(tmp_path / "d.csv", hdr, [["AAA", "FY2024-25", "t1", "blank", "doc", "p1", ""],
                                             ["AAA", "FY2024-25", "t2", "bad", "doc", "p2", "caused_it"],
                                             ["AAA", "FY2024-25", "t3", "ok", "doc", "p3", "unresolved"]])
    db = tmp_path / "d.sqlite"
    s = run_pipeline(db_path=db, company_files=[c], financial_files=[f], disclosure_files=[d], external_files=[],
                     verification_files=[], export_dir=None)
    conn = connect(db)
    rel = [r[0] for r in conn.execute("SELECT relationship FROM disclosures ORDER BY disclosure_id")]
    conn.close()
    assert rel == ["not_assessed", "possible_explanation", "unresolved"] and s["issues_warning"] >= 1


def test_peer_notes_disclose_debt_definition_restatement_and_case_study_scope():
    from btb.peers import COMPARABILITY_NOTES
    text = " ".join(COMPARABILITY_NOTES).lower()
    for word in ("lease", "restated", "five-company case study", "does not support general conclusions"):
        assert word in text


def test_independent_stdlib_recomputation_agrees_with_sql_and_pandas():
    """scripts/audit_recalc.py recomputes every ratio with plain Python and compares with v_ratios and btb.metrics."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("audit_recalc", config.ROOT / "scripts" / "audit_recalc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0

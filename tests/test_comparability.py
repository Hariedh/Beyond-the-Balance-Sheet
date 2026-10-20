"""Tests for the metric-level comparability statuses (Comparable / Use with caution / Not comparable / Unverified)."""
from __future__ import annotations

import pandas as pd
import pytest

from btb.comparability import METRICS, filing_check_label, metric_status
from btb.db import connect, load_fin
from btb.metrics import compute_metrics
from btb.peers import HISTORY_WINDOW, PEER_METRICS, RECENT_WINDOW, peer_medians, peer_table
from btb.verification import verification_frame


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    from btb.pipeline import run_pipeline
    db = tmp_path_factory.mktemp("cmp") / "r.sqlite"
    run_pipeline(db_path=db, export_dir=None)
    conn = connect(db)
    try:
        m = compute_metrics(load_fin(conn))
        ver = verification_frame(conn)
    finally:
        conn.close()
    return m[m.is_illustrative == 0], ver


def _row(m, t, fy):
    return m[(m.ticker == t) & (m.financial_year == fy)].iloc[0]


EMPTY = pd.DataFrame(columns=["ticker", "financial_year", "item", "status", "difference_pct"])


def test_15_month_period_treatment_per_metric(real):
    m, ver = real
    r = _row(m, "AMBUJACEM", "FY2022-23")
    assert r.period_months == 15
    st = {c: metric_status(r, c, ver)["status"] for c in METRICS}
    assert st["revenue_cr"] == "not_comparable" and st["ebit_cr"] == "not_comparable"
    assert st["ebit_margin"] == "caution" and st["interest_coverage"] == "caution"
    assert st["ocf_to_debt"] in ("caution", "not_comparable")      # period sensitive (or missing OCF)
    assert st["debt_to_equity"] != "not_comparable" and st["current_ratio"] != "not_comparable"


def test_missing_value_is_not_comparable(real):
    m, ver = real
    r = _row(m, "AMBUJACEM", "FY2022-23").copy()                  # operating cash flow blank
    assert metric_status(r, "ocf_to_debt", ver)["status"] == "not_comparable"


def test_unresolved_discrepancy_makes_input_dependent_metric_unverified(real):
    m, ver = real
    r = _row(m, "AMBUJACEM", "FY2024-25")
    assert metric_status(r, "current_ratio", ver)["status"] == "unverified"
    assert metric_status(r, "ocf_to_debt", ver)["status"] == "unverified"


def test_never_checked_year_is_not_downgraded_but_labelled(real):
    m, ver = real
    chk = {(t, y) for t, y in zip(ver.ticker, ver.financial_year)}
    unchecked = [(t, y) for t, y in zip(m.ticker, m.financial_year) if (t, y) not in chk and _row(m, t, y).period_months == 12]
    assert unchecked
    t, y = unchecked[0]
    assert metric_status(_row(m, t, y), "ebit_margin", ver)["status"] == "comparable"
    assert filing_check_label(ver, t, y) == "not checked"


def test_recent_window_is_all_12_month_for_every_company(real):
    m, _ = real
    w = m[(m.financial_year >= RECENT_WINDOW[0]) & (m.financial_year <= RECENT_WINDOW[1])]
    assert set(w.ticker) == {"ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "ACC"}
    assert (w.period_months == 12).all()
    assert (m[(m.financial_year >= HISTORY_WINDOW[0]) & (m.financial_year <= HISTORY_WINDOW[1])].period_months == 15).any()


def test_medians_exclude_period_caution_and_count_groups(real):
    m, ver = real
    pt = peer_table(m, "consolidated", "FY2022-23", False, ver)
    med = peer_medians(pt).set_index("metric")
    # the 15-month companies never enter the EBIT-margin median
    ok = pt[pt["st__ebit_margin"] == "comparable"]
    assert not {"AMBUJACEM", "ACC"} & set(ok.ticker)
    assert med.loc["ebit_margin", "n"] == len(ok)
    pt2 = peer_table(m, "consolidated", "FY2025-26", False, ver)
    med2 = peer_medians(pt2).set_index("metric")
    assert med2.loc["ebit_margin", "n_groups"] <= med2.loc["ebit_margin", "n"]
    both = pt2[pt2["st__ebit_margin"].isin(["comparable"]) & pt2.ticker.isin(["AMBUJACEM", "ACC"])]
    if len(both) == 2:
        assert med2.loc["ebit_margin", "n_groups"] == med2.loc["ebit_margin", "n"] - 1


def test_company_without_data_is_listed_not_hidden(real):
    m, ver = real
    pt = peer_table(m[m.ticker != "ACC"], "consolidated", "FY2025-26", False, ver)
    assert len(pt) >= 1
    empty = peer_table(m.iloc[0:0], "consolidated", "FY2025-26", False, EMPTY)
    assert empty.empty and "st__ebit_margin" in empty.columns


def test_original_reported_revenue_is_never_rescaled(real):
    m, ver = real
    pt = peer_table(m, "consolidated", "FY2022-23", False, ver).set_index("ticker")
    assert pt.loc["AMBUJACEM", "revenue_cr"] == pytest.approx(_row(m, "AMBUJACEM", "FY2022-23").revenue_cr)

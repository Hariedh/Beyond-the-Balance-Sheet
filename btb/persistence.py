"""Persistence analysis: is a warning isolated, new, building or persistent?

Plain-pandas logic, deliberately simple. For each company/basis and each indicator we build a
yearly observation:

    breach    the condition holds this year   (e.g. interest coverage below the threshold)
    ok        the condition was assessable and did NOT hold
    n/a       it could not be assessed (input missing, or the comparison period is not a
              directly preceding 12-month year)

A missing or non-comparable year is NEVER treated as satisfactory ("ok"): it is "n/a", and it
interrupts a run of breaches. Statuses for a year with a breach:

    persistent       breached in `sustained_years` or more directly consecutive observed years
    building         consecutive breaches, but fewer than `sustained_years` so far
    new              first breach after an observed year without a breach
    history_unknown  first breach, but the previous year is missing / not comparable / not loaded
                     (we cannot tell whether it is new or long-standing)
For a year without a breach: `recovered` (previous observed year was a breach) or `ok`.

This describes what the historical data show. It is not a statistical test and not a prediction.
"""
from __future__ import annotations

import pandas as pd

from .flags import Thresholds

INDICATORS: dict[str, str] = {
    "LOW_INTEREST_COVERAGE": "Interest coverage below threshold",
    "LOW_CURRENT_RATIO": "Current ratio below threshold",
    "NEGATIVE_OPERATING_CASH_FLOW": "Operating cash flow negative",
    "NEGATIVE_FREE_CASH_FLOW": "Free cash flow negative",
    "EBIT_MARGIN_DECLINE": "EBIT margin fell year on year",
    "REVENUE_DECLINE": "Revenue fell year on year",
    "DEBT_UP_EBIT_DOWN": "Debt rose materially while EBIT fell",
}


def debt_up_ebit_down(m: pd.DataFrame, t: Thresholds) -> pd.Series:
    """True/False/NaN: debt up by at least `debt_rise_min_pct` of prior debt while EBIT fell."""
    prev_debt = m["prev_total_debt_cr"]
    assessable = m["debt_change_cr"].notna() & m["ebit_change_cr"].notna() & (prev_debt > 0)
    rise = m["debt_change_cr"] / prev_debt.where(prev_debt > 0)
    breach = (rise >= t.debt_rise_min_pct) & (m["ebit_change_cr"] < 0)
    return breach.where(assessable)


def observations(m: pd.DataFrame, t: Thresholds) -> dict[str, pd.Series]:
    """Per-indicator Series of True (breach) / False (ok) / NaN (not assessable), aligned to m."""
    def lt(col, limit):
        return (m[col] < limit).where(m[col].notna())

    return {
        "LOW_INTEREST_COVERAGE": lt("interest_coverage", t.interest_coverage_min),
        "LOW_CURRENT_RATIO": lt("current_ratio", t.current_ratio_min),
        "NEGATIVE_OPERATING_CASH_FLOW": lt("operating_cash_flow_cr", 0),
        "NEGATIVE_FREE_CASH_FLOW": lt("free_cash_flow_cr", 0),
        "EBIT_MARGIN_DECLINE": lt("margin_change", 0),
        "REVENUE_DECLINE": lt("revenue_growth", 0),
        "DEBT_UP_EBIT_DOWN": debt_up_ebit_down(m, t),
    }


def persistence_table(m: pd.DataFrame, t: Thresholds | None = None) -> pd.DataFrame:
    """One row per company/basis/year/indicator with observation, streak and status."""
    t = t or Thresholds()
    cols = ["company_id", "ticker", "basis", "financial_year", "indicator", "observation",
            "streak", "status", "previous_observation"]
    if m.empty:
        return pd.DataFrame(columns=cols)
    obs = observations(m, t)
    rows = []
    for (cid, basis), g in m.groupby(["company_id", "basis"], sort=False):
        g = g.sort_values("fy_start")
        for name, series in obs.items():
            prev_obs, prev_start, streak = None, None, 0
            for idx, r in g.iterrows():
                v = series.loc[idx]
                adjacent = prev_start is not None and r["fy_start"] == prev_start + 1
                before = prev_obs if adjacent else None          # observation in the directly preceding year
                if pd.isna(v):
                    status, cur, streak = "not_assessable", None, 0
                elif bool(v):
                    cur = True
                    streak = streak + 1 if before is True else 1
                    if streak >= t.sustained_years:
                        status = "persistent"
                    elif streak > 1:
                        status = "building"
                    elif before is False:
                        status = "new"
                    else:
                        status = "history_unknown"
                else:
                    cur = False
                    status = "recovered" if before is True else "ok"
                    streak = 0
                rows.append({"company_id": cid, "ticker": r["ticker"], "basis": basis,
                             "financial_year": r["financial_year"], "indicator": name,
                             "observation": cur, "streak": streak, "status": status,
                             "previous_observation": before})
                prev_obs, prev_start = cur, r["fy_start"]
    return pd.DataFrame(rows, columns=cols)


def explain_status(status: str, streak: int, t: Thresholds) -> str:
    return {
        "persistent": f"persistent: breached in {streak} directly consecutive observed years (rule: {t.sustained_years} or more)",
        "building": f"building: {streak} consecutive breaches so far (persistent from {t.sustained_years})",
        "new": "new: first breach after an observed year without one",
        "history_unknown": "history unknown: previous year is missing or not comparable, so we cannot tell if this is new or long-standing",
        "recovered": "recovered: breached last year, not this year",
        "ok": "no breach",
        "not_assessable": "not assessable: input missing or comparison period not comparable (NOT treated as satisfactory)",
    }[status]

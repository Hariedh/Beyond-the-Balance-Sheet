"""Data-quality checks on the cleaned financials.

Checks never change data. They report issues so a human can verify against the
source statements. 'warning' means "look at this", not "this is wrong".
"""
from __future__ import annotations

import pandas as pd

from . import config
from .metrics import compute_metrics

FIELD_COLS = {
    "revenue": "revenue_cr",
    "ebit": "ebit_cr",
    "interest_expense": "interest_expense_cr",
    "total_debt": "total_debt_cr",
    "total_equity": "total_equity_cr",
    "current_assets": "current_assets_cr",
    "current_liabilities": "current_liabilities_cr",
    "operating_cash_flow": "operating_cash_flow_cr",
    "cash_and_equivalents": "cash_cr",
    "capex": "capex_cr",
}

# Illustrative plausibility bands used only to surface possible unit mistakes.
IMPLIED_INTEREST_RATE_BAND = (0.005, 0.40)
REVENUE_JUMP_LIMIT = 0.50


def validate_financials(fin: pd.DataFrame) -> list[dict]:
    issues: list[dict] = []

    def add(severity, check, r, detail, field=None):
        issues.append({
            "severity": severity, "check_name": check,
            "ticker": r["ticker"] if r is not None else None,
            "financial_year": r["financial_year"] if r is not None else None,
            "field": field, "detail": detail, "source_file": None,
        })

    if fin.empty:
        return issues

    m = compute_metrics(fin)

    for _, r in m.iterrows():
        # missing values
        for name, col in FIELD_COLS.items():
            if pd.isna(r[col]):
                sev = "info" if name in ("cash_and_equivalents", "capex") else "warning"
                add(sev, "missing_value", r, f"{name} is missing (kept as NULL).", name)

        if r["period_months"] != 12:
            add("info", "non_standard_period", r,
                f"Reporting period is {int(r['period_months'])} months; flows are not comparable with 12-month "
                "years, so year-on-year measures involving this year are n/a.", "period_months")

        if pd.isna(r["source"]) or not str(r["source"]).strip():
            add("warning", "missing_source", r, "No data source recorded for this observation.")

        if pd.notna(r["revenue_cr"]) and r["revenue_cr"] <= 0:
            add("error", "nonpositive_revenue", r, f"Revenue is {r['revenue_cr']:,.2f} cr.", "revenue")
        if pd.notna(r["interest_expense_cr"]) and r["interest_expense_cr"] < 0:
            add("error", "negative_interest_expense", r,
                "Interest expense is negative; check the definition (net finance income?).", "interest_expense")
        elif pd.notna(r["interest_expense_cr"]) and r["interest_expense_cr"] == 0:
            add("info", "zero_interest_expense", r, "Interest expense is zero; coverage is n/a.", "interest_expense")
        if pd.notna(r["total_equity_cr"]) and r["total_equity_cr"] <= 0:
            add("warning", "nonpositive_equity", r, "Total equity is zero or negative.", "total_equity")
        if pd.notna(r["total_debt_cr"]) and r["total_debt_cr"] < 0:
            add("error", "negative_debt", r, "Total debt is negative.", "total_debt")
        if pd.notna(r["current_liabilities_cr"]) and r["current_liabilities_cr"] <= 0:
            add("warning", "nonpositive_current_liabilities", r,
                "Current liabilities are zero or negative.", "current_liabilities")
        if pd.notna(r["capex_cr"]) and r["capex_cr"] < 0:
            add("warning", "negative_capex", r,
                "Capital expenditure is negative; enter capex as a positive cash outflow.", "capex")
        if pd.notna(r["cash_cr"]) and pd.notna(r["current_assets_cr"]) and r["cash_cr"] > r["current_assets_cr"]:
            add("warning", "cash_exceeds_current_assets", r,
                "Cash exceeds current assets; check definitions or units.", "cash_and_equivalents")

        # plausibility (possible unit / definition mistakes)
        if pd.notna(r["ebit_margin"]) and abs(r["ebit_margin"]) > 1:
            add("warning", "ebit_margin_implausible", r,
                f"EBIT margin is {r['ebit_margin'] * 100:.0f}%; check units or EBIT definition.", "ebit")
        if pd.notna(r["total_debt_cr"]) and pd.notna(r["interest_expense_cr"]) \
                and r["total_debt_cr"] > 0 and r["interest_expense_cr"] > 0:
            rate = r["interest_expense_cr"] / r["total_debt_cr"]
            lo, hi = IMPLIED_INTEREST_RATE_BAND
            if not lo <= rate <= hi:
                add("warning", "implied_interest_rate_outlier", r,
                    f"Interest / debt is {rate * 100:.1f}% (outside {lo * 100:.1f}%-{hi * 100:.0f}%); "
                    "check units, debt definition or averaging.", "interest_expense")
        if pd.notna(r["revenue_growth"]) and abs(r["revenue_growth"]) > REVENUE_JUMP_LIMIT:
            add("warning", "large_revenue_change", r,
                f"Revenue changed {r['revenue_growth'] * 100:+.0f}% year on year; check for restatement, "
                "merger, demerger, change in consolidation scope or a longer reporting period.", "revenue")

    # year gaps and mixed bases
    for (ticker, basis), g in m.groupby(["ticker", "basis"]):
        years = sorted(g["fy_start"].astype(int))
        missing = sorted(set(range(years[0], years[-1] + 1)) - set(years))
        for y in missing:
            issues.append({"severity": "warning", "check_name": "missing_financial_year", "ticker": ticker,
                           "financial_year": f"FY{y}-{(y + 1) % 100:02d}", "field": None,
                           "detail": f"{basis} data skips this year; year-on-year measures are n/a around the gap.",
                           "source_file": None})
    for ticker, g in m.groupby("ticker"):
        if g["basis"].nunique() > 1:
            issues.append({"severity": "info", "check_name": "mixed_reporting_basis", "ticker": ticker,
                           "financial_year": None, "field": None,
                           "detail": "Both standalone and consolidated rows are loaded; compare like with like.",
                           "source_file": None})
    return issues


def issues_to_frame(issues: list[dict]) -> pd.DataFrame:
    cols = ["severity", "check_name", "ticker", "financial_year", "field", "detail", "source_file"]
    return pd.DataFrame(issues, columns=cols)

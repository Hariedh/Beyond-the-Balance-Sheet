"""Financial ratio calculations (pandas implementation).

Definitions (all inputs in INR crore):
  interest_coverage = EBIT / interest expense        (interest expense must be > 0)
  debt_to_equity    = total debt / total equity      (equity must be > 0)
  current_ratio     = current assets / current liabilities (liabilities must be > 0)
  ocf_to_debt       = operating cash flow / total debt     (debt must be > 0)
  revenue_growth    = (revenue - prior revenue) / prior revenue
  ebit_margin       = EBIT / revenue                 (revenue must be > 0)

A ratio is NaN (never 0) when an input is missing or the denominator is not
strictly positive. Year-on-year figures need the immediately preceding
financial year for the same company and basis, and both periods must be
12 months long (e.g. a 15-month period after a year-end change is excluded).
"""
from __future__ import annotations

import pandas as pd

RATIO_COLUMNS = (
    "interest_coverage",
    "debt_to_equity",
    "current_ratio",
    "ocf_to_debt",
    "revenue_growth",
    "ebit_margin",
)

RATIO_LABELS = {
    "interest_coverage": "Interest coverage",
    "debt_to_equity": "Debt-to-equity",
    "current_ratio": "Current ratio",
    "ocf_to_debt": "Operating cash flow / debt",
    "revenue_growth": "Revenue growth",
    "ebit_margin": "EBIT margin",
}

RATIO_DEFINITIONS = {
    "interest_coverage": "EBIT / interest expense",
    "debt_to_equity": "Total debt / total equity",
    "current_ratio": "Current assets / current liabilities",
    "ocf_to_debt": "Operating cash flow / total debt",
    "revenue_growth": "(Revenue - prior-year revenue) / prior-year revenue",
    "ebit_margin": "EBIT / revenue",
}

PERCENT_RATIOS = {"revenue_growth", "ebit_margin"}


def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """numerator / denominator, NaN unless the denominator is strictly positive."""
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    return num / den.where(den > 0)


def compute_metrics(fin: pd.DataFrame) -> pd.DataFrame:
    """Add the six ratios plus prior-year comparison columns to cleaned financials."""
    if fin.empty:
        out = fin.copy()
        for col in (*RATIO_COLUMNS, "has_prior_year"):
            out[col] = pd.Series(dtype="float64")
        return out

    df = fin.sort_values(["company_id", "basis", "fy_start"]).reset_index(drop=True).copy()

    df["interest_coverage"] = safe_div(df["ebit_cr"], df["interest_expense_cr"])
    df["debt_to_equity"] = safe_div(df["total_debt_cr"], df["total_equity_cr"])
    df["current_ratio"] = safe_div(df["current_assets_cr"], df["current_liabilities_cr"])
    df["ocf_to_debt"] = safe_div(df["operating_cash_flow_cr"], df["total_debt_cr"])
    df["ebit_margin"] = safe_div(df["ebit_cr"], df["revenue_cr"])

    grp = df.groupby(["company_id", "basis"], sort=False)
    for col in ("fy_start", "period_months", "revenue_cr", "ebit_cr", "total_debt_cr", "ebit_margin"):
        df[f"prev_{col}"] = grp[col].shift(1)

    # Year-on-year changes need the immediately preceding FY and two 12-month periods.
    consecutive = (df["prev_fy_start"].eq(df["fy_start"] - 1)
                   & df["period_months"].eq(12) & df["prev_period_months"].eq(12))
    df["has_prior_year"] = consecutive

    df["revenue_growth"] = (
        (df["revenue_cr"] - df["prev_revenue_cr"]) / df["prev_revenue_cr"].where(df["prev_revenue_cr"] > 0)
    ).where(consecutive)
    df["ebit_change_cr"] = (df["ebit_cr"] - df["prev_ebit_cr"]).where(consecutive)
    df["debt_change_cr"] = (df["total_debt_cr"] - df["prev_total_debt_cr"]).where(consecutive)
    df["margin_change"] = (df["ebit_margin"] - df["prev_ebit_margin"]).where(consecutive)
    return df


def ratio_notes(row: pd.Series) -> str:
    """Human-readable reasons why a ratio is unavailable for this row."""
    notes = []
    pm = row.get("period_months")
    if pd.notna(pm) and pm != 12:
        notes.append(f"{int(pm)}-month reporting period: flow figures are not comparable with 12-month years")
    elif not row.get("has_prior_year", True) and pd.notna(row.get("prev_period_months")) \
            and row.get("prev_period_months") != 12:
        notes.append("prior period was not 12 months: year-on-year changes are n/a")
    ie = row.get("interest_expense_cr")
    if pd.isna(ie):
        notes.append("interest expense missing")
    elif ie == 0:
        notes.append("zero interest expense: coverage not meaningful")
    elif ie < 0:
        notes.append("negative interest expense: check definition")
    eq = row.get("total_equity_cr")
    if pd.notna(eq) and eq <= 0:
        notes.append("zero/negative equity: debt-to-equity not meaningful")
    rev = row.get("revenue_cr")
    if pd.notna(rev) and rev <= 0:
        notes.append("non-positive revenue: margin not meaningful")
    return "; ".join(notes)

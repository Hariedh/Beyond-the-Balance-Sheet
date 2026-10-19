"""Transparent rules-based warning indicators.

Each rule produces an individual flag with the threshold used and the evidence
(the actual numbers) behind it. There is deliberately NO composite score.
Thresholds are illustrative screening values, not credit-risk standards.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .fmt import fmt_cr, fmt_pct, fmt_x


@dataclass(frozen=True)
class Thresholds:
    interest_coverage_min: float = 1.5   # flag if EBIT / interest is below this
    current_ratio_min: float = 1.0       # flag if current ratio is below this
    sustained_years: int = 2             # directly consecutive observed years needed for 'persistent'
    debt_rise_min_pct: float = 0.10      # debt must rise by at least this share of prior debt to count

    def as_dict(self) -> dict:
        return asdict(self)


RULES: dict[str, tuple[str, str]] = {
    "LOW_INTEREST_COVERAGE": ("Interest coverage (EBIT / interest expense) is below the threshold", "warning"),
    "NEGATIVE_OPERATING_CASH_FLOW": ("Operating cash flow is negative", "warning"),
    "DEBT_UP_EBIT_DOWN": ("Total debt increased while EBIT decreased year on year", "warning"),
    "LOW_CURRENT_RATIO": ("Current ratio is below the threshold", "warning"),
    "SUSTAINED_EBIT_MARGIN_DECLINE": ("EBIT margin fell in each of the last N consecutive years", "warning"),
    "SUSTAINED_REVENUE_DECLINE": ("Revenue fell in each of the last N consecutive years", "warning"),
    "NEGATIVE_FREE_CASH_FLOW": ("Free cash flow (operating cash flow minus capex) is negative", "info"),
    "NONPOSITIVE_EQUITY": ("Total equity is zero or negative, so debt-to-equity is not meaningful", "info"),
}

FLAG_COLUMNS = [
    "company_id", "ticker", "basis", "financial_year", "rule_id", "rule_description",
    "severity", "threshold_used", "observed_value", "evidence", "is_illustrative",
]


def evaluate_flags(m: pd.DataFrame, t: Thresholds | None = None) -> pd.DataFrame:
    """Apply every rule to a metrics frame (see metrics.compute_metrics)."""
    t = t or Thresholds()
    if m.empty:
        return pd.DataFrame(columns=FLAG_COLUMNS)

    # Persistence (see btb/persistence.py): missing / non-comparable years are 'not assessable',
    # never 'ok', and interrupt a run of declines.
    from .persistence import persistence_table
    pers = persistence_table(m, t).set_index(["company_id", "basis", "financial_year", "indicator"])
    streaks = pers["streak"].to_dict()
    statuses = pers["status"].to_dict()

    def streak_of(r, indicator: str) -> int:
        key = (r.company_id, r.basis, r.financial_year, indicator)
        return int(streaks.get(key, 0)) if statuses.get(key) == "persistent" else 0

    rows: list[dict] = []

    def add(r, rule_id: str, threshold: str | None, observed, evidence: str) -> None:
        desc, sev = RULES[rule_id]
        rows.append({
            "company_id": r.company_id, "ticker": r.ticker, "basis": r.basis,
            "financial_year": r.financial_year, "rule_id": rule_id, "rule_description": desc,
            "severity": sev, "threshold_used": threshold,
            "observed_value": None if pd.isna(observed) else float(observed),
            "evidence": evidence, "is_illustrative": int(r.is_illustrative),
        })

    for pos, r in enumerate(m.itertuples(index=False)):
        idx = m.index[pos]

        if pd.notna(r.interest_coverage) and r.interest_coverage < t.interest_coverage_min:
            add(r, "LOW_INTEREST_COVERAGE", f"< {t.interest_coverage_min:g}x", r.interest_coverage,
                f"Interest coverage {fmt_x(r.interest_coverage)} (EBIT {fmt_cr(r.ebit_cr)} / interest "
                f"{fmt_cr(r.interest_expense_cr)}) is below {t.interest_coverage_min:g}x.")

        if pd.notna(r.operating_cash_flow_cr) and r.operating_cash_flow_cr < 0:
            add(r, "NEGATIVE_OPERATING_CASH_FLOW", "< 0", r.operating_cash_flow_cr,
                f"Operating cash flow was {fmt_cr(r.operating_cash_flow_cr)}.")

        if pd.notna(r.debt_change_cr) and pd.notna(r.ebit_change_cr) and pd.notna(r.prev_total_debt_cr) \
                and r.prev_total_debt_cr > 0 and r.ebit_change_cr < 0 \
                and r.debt_change_cr / r.prev_total_debt_cr >= t.debt_rise_min_pct:
            add(r, "DEBT_UP_EBIT_DOWN",
                f"debt rise >= {t.debt_rise_min_pct:.0%} of prior debt and EBIT change < 0", r.debt_change_cr,
                f"Total debt rose by {fmt_cr(r.debt_change_cr)} ({r.debt_change_cr / r.prev_total_debt_cr:+.0%}) to "
                f"{fmt_cr(r.total_debt_cr)} while EBIT fell by {fmt_cr(abs(r.ebit_change_cr))} to {fmt_cr(r.ebit_cr)}.")

        if pd.notna(r.free_cash_flow_cr) and r.free_cash_flow_cr < 0:
            why = ("Operating cash flow was itself negative, so this is not explained by investment alone."
                   if r.operating_cash_flow_cr < 0 else
                   "Capex exceeded operating cash flow; heavy expansion spending can cause this without distress.")
            add(r, "NEGATIVE_FREE_CASH_FLOW", "< 0", r.free_cash_flow_cr,
                f"Free cash flow was {fmt_cr(r.free_cash_flow_cr)} (operating cash flow {fmt_cr(r.operating_cash_flow_cr)} "
                f"minus capex {fmt_cr(r.capex_cr)}). {why}")

        if pd.notna(r.current_ratio) and r.current_ratio < t.current_ratio_min:
            add(r, "LOW_CURRENT_RATIO", f"< {t.current_ratio_min:g}x", r.current_ratio,
                f"Current ratio {fmt_x(r.current_ratio)} (current assets {fmt_cr(r.current_assets_cr)} / "
                f"current liabilities {fmt_cr(r.current_liabilities_cr)}) is below {t.current_ratio_min:g}x. "
                f"This can be normal for some business models, so compare with the company's own history and peers.")

        n = streak_of(r, "EBIT_MARGIN_DECLINE")
        if n:
            add(r, "SUSTAINED_EBIT_MARGIN_DECLINE", f">= {t.sustained_years} consecutive declines",
                r.ebit_margin,
                f"EBIT margin fell for {n} directly consecutive comparable years, to {fmt_pct(r.ebit_margin)} "
                f"(latest change {r.margin_change * 100:+.1f} percentage points).")

        n = streak_of(r, "REVENUE_DECLINE")
        if n:
            add(r, "SUSTAINED_REVENUE_DECLINE", f">= {t.sustained_years} consecutive declines",
                r.revenue_growth,
                f"Revenue fell for {n} directly consecutive comparable years; latest growth "
                f"{fmt_pct(r.revenue_growth)} to {fmt_cr(r.revenue_cr)}.")

        if pd.notna(r.total_equity_cr) and r.total_equity_cr <= 0:
            add(r, "NONPOSITIVE_EQUITY", "<= 0", r.total_equity_cr,
                f"Total equity was {fmt_cr(r.total_equity_cr)}; debt-to-equity is reported as n/a.")

    out = pd.DataFrame(rows, columns=FLAG_COLUMNS)
    return out.sort_values(["ticker", "basis", "financial_year", "rule_id"]).reset_index(drop=True)


# --- sensitivity analysis ----------------------------------------------------
SENSITIVITY_GRID = {
    "interest_coverage_min": (1.0, 1.5, 2.0, 3.0),
    "current_ratio_min": (0.8, 1.0, 1.2, 1.5),
    "sustained_years": (1, 2, 3),
    "debt_rise_min_pct": (0.0, 0.05, 0.10, 0.20),
}
_PARAM_RULES = {
    "interest_coverage_min": [("LOW_INTEREST_COVERAGE", "interest_coverage")],
    "current_ratio_min": [("LOW_CURRENT_RATIO", "current_ratio")],
    "sustained_years": [("SUSTAINED_EBIT_MARGIN_DECLINE", "margin_change"),
                        ("SUSTAINED_REVENUE_DECLINE", "revenue_growth")],
    "debt_rise_min_pct": [("DEBT_UP_EBIT_DOWN", "ebit_change_cr")],
}


def sensitivity_table(m: pd.DataFrame, base: Thresholds | None = None) -> pd.DataFrame:
    """How many company-years each rule flags under alternative thresholds."""
    base = base or Thresholds()
    out = []
    for param, values in SENSITIVITY_GRID.items():
        for value in values:
            t = Thresholds(**{**base.as_dict(), param: type(getattr(base, param))(value)})
            flags = evaluate_flags(m, t)
            for rule_id, evaluable_col in _PARAM_RULES[param]:
                subset = flags[flags["rule_id"] == rule_id]
                out.append({
                    "rule_id": rule_id,
                    "parameter": param,
                    "value": value,
                    "is_base_value": value == getattr(base, param),
                    "evaluable_company_years": int(m[evaluable_col].notna().sum()),
                    "flagged_company_years": len(subset),
                    "companies_affected": ", ".join(sorted(subset["ticker"].unique())) or "-",
                })
    return pd.DataFrame(out)

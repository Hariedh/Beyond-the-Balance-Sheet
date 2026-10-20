"""Per-company, per-metric comparability status.

Four statuses, in order of severity (worst wins when several apply):

  not_comparable  excluded from the relevant calculation: the value is missing, or the period length
                  makes it meaningless to compare with 12-month figures (absolute flows, growth)
  unverified      an input disagrees with the company's own filing and the difference is unresolved
  caution         the value is meaningful but affected by a period-length or definition difference
  comparable      appropriate for the selected comparison

Treatment of a non-12-month period (for example Ambuja's and ACC's 15-month FY2022-23):

  revenue, EBIT (absolute), revenue growth          not comparable
  EBIT margin, interest coverage                    caution (both are same-period flows)
  OCF / EBIT, FCF margin                            caution (same-period flows)
  OCF / debt                                        caution (a period flow over a balance-sheet stock)
  debt-to-equity, current ratio                      balance-sheet ratios at the reporting date: not affected by length

Definition caution: total debt is the aggregators' figure. Where the company's filing does not confirm that it
includes lease liabilities (or has not been checked), debt-based ratios get 'caution' of kind 'definition'.

Missing data is never treated as satisfactory: it is not_comparable. A year never compared with a filing is
NOT downgraded here (that would make most of the history 'caution'); it is reported separately as 'filing check'.
"""
from __future__ import annotations

import pandas as pd

STATUS_ORDER = ["not_comparable", "unverified", "caution", "comparable"]
STATUS_LABEL = {
    "comparable": "Comparable",
    "caution": "Use with caution",
    "not_comparable": "Not comparable",
    "unverified": "Unverified",
}
STATUS_MEANING = {
    "comparable": "appropriate for the selected comparison",
    "caution": "meaningful but affected by period or definition differences",
    "not_comparable": "excluded from the relevant calculation",
    "unverified": "an input disagrees with the company's filing (unresolved): insufficient evidence to rely on the figure",
}

# metric column -> (label, filing-verification items its inputs come from, treatment of a non-12-month period, uses debt)
METRICS: dict[str, tuple[str, list[str], str, bool]] = {
    "revenue_cr": ("Revenue (absolute)", ["revenue"], "not_comparable", False),
    "ebit_cr": ("EBIT (absolute)", ["ebit", "depreciation"], "not_comparable", False),
    "revenue_growth": ("Revenue growth", ["revenue"], "not_comparable", False),
    "ebit_margin": ("EBIT margin", ["revenue", "ebit", "depreciation"], "caution", False),
    "interest_coverage": ("Interest coverage", ["ebit", "depreciation", "interest_expense"], "caution", False),
    "debt_to_equity": ("Debt-to-equity", ["total_debt", "total_equity"], "ok", True),
    "current_ratio": ("Current ratio", ["current_assets", "current_liabilities"], "ok", False),
    "ocf_to_debt": ("OCF / debt", ["operating_cash_flow", "total_debt"], "caution", True),
    "ocf_to_ebit": ("OCF / EBIT", ["operating_cash_flow", "ebit", "depreciation"], "caution", False),
    "fcf_margin": ("FCF margin", ["operating_cash_flow", "capex", "revenue"], "caution", False),
}


def _rank(status: str) -> int:
    return STATUS_ORDER.index(status)


def metric_status(row, metric: str, ver: pd.DataFrame | None = None) -> dict:
    """Status of one metric for one company-year (`row` is a row of the metrics frame).

    Returns {"status", "reason", "kinds"} where kinds lists the causes ('period', 'definition', 'filing', 'missing').
    """
    label, items, period_rule, uses_debt = METRICS[metric]
    months = int(row["period_months"]) if pd.notna(row.get("period_months")) else 12
    status, reasons, kinds = "comparable", [], set()

    def worsen(new: str, reason: str, kind: str) -> None:
        nonlocal status
        reasons.append(reason)
        kinds.add(kind)
        if _rank(new) < _rank(status):
            status = new

    value = row.get(metric)
    if value is None or pd.isna(value):
        why = "value not available (missing input or zero/negative denominator)"
        if metric == "revenue_growth" and months == 12 and not bool(row.get("has_prior_year", False)):
            why = "the prior period is missing or is not a directly preceding 12-month year"
        worsen("not_comparable", why, "missing")
    if months != 12:
        if period_rule == "not_comparable":
            worsen("not_comparable", f"{months}-month period: not comparable with 12-month figures", "period")
        elif period_rule == "caution":
            worsen("caution", f"{months}-month period: covers a different length of time than 12-month figures", "period")

    sub = pd.DataFrame()
    if ver is not None and not ver.empty:
        sub = ver[(ver["ticker"] == row["ticker"]) & (ver["financial_year"] == row["financial_year"])]
    if not sub.empty:
        bad = sub[(sub["item"].isin(items)) & (sub["status"] == "discrepancy")]
        for r in bad.itertuples():
            pct = "" if pd.isna(r.difference_pct) else f" ({r.difference_pct:+.1f}%)"
            worsen("unverified", f"{r.item} differs from the filing{pct}, unresolved", "filing")
    if uses_debt:
        confirmed = (not sub.empty) and bool(
            ((sub["item"] == "total_debt") & (sub["status"].isin(["verified", "approx"]))).any())
        if not confirmed:
            worsen("caution", "debt definition not confirmed against the filing for this year (lease liabilities)", "definition")
    return {"status": status, "reason": "; ".join(reasons), "kinds": sorted(kinds)}


def status_table(m: pd.DataFrame, ver: pd.DataFrame | None, ticker: str | None = None, fy: str | None = None,
                 basis: str | None = None) -> pd.DataFrame:
    """Long table: ticker, basis, financial_year, metric, label, status, reason, kinds."""
    cols = ["ticker", "basis", "financial_year", "metric", "label", "status", "reason", "kinds"]
    if m is None or m.empty or "period_months" not in m.columns:
        return pd.DataFrame(columns=cols)
    sub = m
    if ticker is not None:
        sub = sub[sub["ticker"] == ticker]
    if fy is not None:
        sub = sub[sub["financial_year"] == fy]
    if basis is not None:
        sub = sub[sub["basis"] == basis]
    rows = []
    for r in sub.to_dict("records"):
        for metric, (label, *_rest) in METRICS.items():
            s = metric_status(r, metric, ver)
            rows.append({"ticker": r["ticker"], "basis": r["basis"], "financial_year": r["financial_year"],
                         "metric": metric, "label": label, **s})
    return pd.DataFrame(rows, columns=cols)


def filing_check_label(ver: pd.DataFrame | None, ticker: str, fy: str) -> str:
    """Whether any input of this company-year has been compared with a primary filing (separate from the status)."""
    if ver is None or ver.empty:
        return "not checked"
    sub = ver[(ver["ticker"] == ticker) & (ver["financial_year"] == fy)]
    if sub.empty:
        return "not checked"
    if (sub["status"] == "discrepancy").any():
        return f"checked ({len(sub)} items), unresolved difference"
    return f"checked ({len(sub)} items)"

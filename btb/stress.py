"""A simple, transparent stress test. It is a what-if on reported figures, NOT a forecast.

Inputs (all optional, default no shock)
  revenue_decline   fall in revenue, 0 to <1 (0.10 = 10%)
  margin_decline_pp fall in EBIT margin in percentage points of stressed revenue (0.02 = 2 pp)
  fixed_cost_share  share of the operating cost base treated as fixed, 0 to 1 (default 0)

Model
  C        = revenue - EBIT                      baseline operating cost base (after depreciation)
  revenue_s = revenue * (1 - d)
  cost_s   = f*C + (1-f)*C*(1-d)                 fixed part unchanged, variable part scales with revenue
  EBIT_pre = revenue_s - cost_s
  EBIT_s   = EBIT_pre - pp * revenue_s           margin shock applied once, to stressed revenue
With f = 0 every cost is variable, so a pure revenue shock leaves the EBIT margin unchanged (the
'constant margin' case). With f > 0 the margin falls with revenue (operating leverage).

Held constant: interest expense, capex and debt (no repricing, refinancing or deleveraging).
Free cash flow is estimated only when operating cash flow and capex are both known, and ONLY under
this explicit assumption: operating cash flow falls by the full shortfall in EBIT (pre-tax; no tax
shield, no working-capital change, no change in interest, other income or financing). Capex is held fixed.
Real outcomes will differ. All outputs are illustrative scenario estimates.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StressInputs:
    revenue_decline: float = 0.0
    margin_decline_pp: float = 0.0
    fixed_cost_share: float = 0.0


def _num(row, key):
    v = row.get(key) if hasattr(row, "get") else row[key]
    return None if v is None or pd.isna(v) else float(v)


def stress_test(row, s: StressInputs, coverage_threshold: float = 1.5) -> dict:
    """Baseline and scenario values for one company-year (a row of the metrics frame)."""
    out: dict = {"available": False, "notes": [], "assumptions": [], "inputs": s}
    d, pp, f = s.revenue_decline, s.margin_decline_pp, s.fixed_cost_share
    if not (0 <= d < 1) or pp < 0 or not (0 <= f <= 1):
        out["notes"].append("Invalid scenario inputs: revenue decline must be in [0, 1), margin decline >= 0, fixed share in [0, 1].")
        return out
    rev, ebit, interest = _num(row, "revenue_cr"), _num(row, "ebit_cr"), _num(row, "interest_expense_cr")
    ocf, capex = _num(row, "operating_cash_flow_cr"), _num(row, "capex_cr")
    if rev is None or rev <= 0 or ebit is None:
        out["notes"].append("Revenue (must be positive) and EBIT are required; the scenario is not available for this year.")
        return out
    months = _num(row, "period_months") or 12
    if months != 12:
        out["notes"].append(f"This is a {int(months)}-month period: amounts cover {int(months)} months, so the scenario is "
                            "not comparable with 12-month years.")

    cost = rev - ebit
    if cost < 0:
        out["notes"].append("EBIT exceeds revenue, which is implausible; check the data. Scenario not available.")
        return out
    rev_s = rev * (1 - d)
    ebit_s = rev_s - (f * cost + (1 - f) * cost * (1 - d)) - pp * rev_s

    base = {"revenue": rev, "ebit": ebit, "ebit_margin": ebit / rev, "interest": interest}
    scen = {"revenue": rev_s, "ebit": ebit_s, "ebit_margin": (ebit_s / rev_s) if rev_s > 0 else None, "interest": interest}

    def cover(e):
        return e / interest if interest is not None and interest > 0 else None
    base["interest_coverage"], scen["interest_coverage"] = cover(ebit), cover(ebit_s)
    if interest is None:
        out["notes"].append("Interest expense is missing: interest coverage is not available.")
    elif interest <= 0:
        out["notes"].append("Interest expense is zero or negative: interest coverage is not meaningful.")
    if ebit_s < 0:
        out["notes"].append("Scenario EBIT is negative: operating profit does not cover interest in this scenario.")
    if ebit < 0:
        out["notes"].append("Baseline EBIT is already negative.")

    if ocf is not None and capex is not None:
        ocf_s = ocf - (ebit - ebit_s)
        base.update(ocf=ocf, capex=capex, fcf=ocf - capex)
        scen.update(ocf=ocf_s, capex=capex, fcf=ocf_s - capex)
    else:
        out["notes"].append("Free cash flow is not estimated: operating cash flow and capex must both be loaded for this year.")

    # revenue fall that would take coverage to 1.0x under the same cost behaviour and margin shock
    breakeven = None
    if interest is not None and interest > 0:
        denom = rev * (1 - pp) - (1 - f) * cost
        if denom > 0:
            k = (interest + f * cost) / denom
            breakeven = max(0.0, 1 - k)
            if k > 1:
                out["notes"].append("With this margin shock, interest coverage is already below 1.0x at the baseline revenue.")
            elif breakeven >= 1:
                breakeven = None
        else:
            out["notes"].append("Under these assumptions EBIT cannot cover interest at any revenue level above zero.")

    out.update(available=True, baseline=base, scenario=scen, breakeven_revenue_decline=breakeven,
               below_threshold=(scen["interest_coverage"] is not None and scen["interest_coverage"] < coverage_threshold))
    out["assumptions"] = [
        ("Constant EBIT margin under a pure revenue shock (all costs variable)" if f == 0 else
         f"{f:.0%} of the cost base is fixed and {1 - f:.0%} varies with revenue (operating leverage)"),
        "Interest expense, capex and debt are held at their reported levels",
        "Capex is held FIXED at its reported level (no cut in spending in response to the shock)",
        "Operating cash flow and free cash flow are a SIMPLIFIED estimate: operating cash flow is assumed to fall by exactly the "
        "shortfall in EBIT. Taxes, working capital, changes in interest or other income, dividends, refinancing and other "
        "financing actions are NOT modelled, so this is not a cash-flow forecast",
        "Not a forecast, a probability or a credit rating: a mechanical what-if on reported figures",
    ]
    return out


def stress_table(result: dict) -> pd.DataFrame:
    """Baseline vs scenario table for display / export."""
    if not result.get("available"):
        return pd.DataFrame(columns=["Metric", "Baseline", "Scenario", "Change"])
    b, s = result["baseline"], result["scenario"]
    rows = [("Revenue (INR crore)", b["revenue"], s["revenue"], "cr"),
            ("EBIT (INR crore)", b["ebit"], s["ebit"], "cr"),
            ("EBIT margin", b["ebit_margin"], s["ebit_margin"], "pct"),
            ("Interest coverage (x)", b["interest_coverage"], s["interest_coverage"], "x")]
    if "fcf" in b:
        rows += [("Operating cash flow, simplified (INR crore)", b["ocf"], s["ocf"], "cr"),
                 ("Free cash flow, simplified (INR crore)", b["fcf"], s["fcf"], "cr")]
    return pd.DataFrame([{"Metric": n, "Baseline": x, "Scenario": y,
                          "Change": None if x is None or y is None else y - x, "kind": k} for n, x, y, k in rows])

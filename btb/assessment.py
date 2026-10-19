"""Turns flags into explained warnings and an evidence-based reading of a company-year.

Four kinds of statement are kept apart and labelled, because they mean different things:

  threshold_breach  an indicator crossed an (illustrative) threshold this year
  deterioration     a measure has moved the wrong way, and for how many consecutive years
  convergence       several independent areas (leverage, profitability, liquidity/cash) are flagged together
  conflict          two readings point in opposite directions (e.g. comfortable coverage but negative cash flow)
  data_limitation   missing, non-comparable or unverified inputs that limit what can be concluded
  inconclusive      too little assessable evidence to say anything

Thresholds are illustrative screening values. None of this is a credit rating, a default
prediction, or a statistical test.
"""
from __future__ import annotations

import pandas as pd

from .fmt import fmt_cr, fmt_pct, fmt_x
from .flags import Thresholds
from .peers import peer_context, with_peer_metrics
from .persistence import explain_status, persistence_table
from .verification import input_status, worst_status

# rule -> indicator text, formula, why it matters, follow-up, history column, peer column, inputs, kind
RULE_INFO: dict[str, dict] = {
    "LOW_INTEREST_COVERAGE": dict(
        indicator="Interest coverage", kind="threshold_breach", col="interest_coverage", fmt="x", peer="interest_coverage",
        inputs=["ebit", "interest_expense"],
        formula="EBIT / interest expense (finance costs). EBIT = operating profit after depreciation, before other income and exceptional items.",
        why="Shows how many times operating profit covers interest, i.e. the cushion if profit falls. It uses accounting profit, not cash.",
        followup="What drove EBIT and finance costs? What is the maturity and rate profile of the debt (not in this dataset)?"),
    "NEGATIVE_OPERATING_CASH_FLOW": dict(
        indicator="Operating cash flow", kind="threshold_breach", col="operating_cash_flow_cr", fmt="cr", peer=None,
        inputs=["operating_cash_flow"],
        formula="Net cash from operating activities (cash-flow statement).",
        why="A company can report profit while consuming cash (for example a working-capital build-up). Negative operating cash flow has to be funded from cash, debt or equity.",
        followup="Which working-capital items, taxes paid or one-offs explain the cash shortfall? See the cash-flow statement notes."),
    "DEBT_UP_EBIT_DOWN": dict(
        indicator="Debt up while EBIT down", kind="deterioration", col="total_debt_cr", fmt="cr", peer=None,
        inputs=["total_debt", "ebit"],
        formula="Total debt rose by at least the materiality share of prior-year debt AND EBIT fell, between two directly consecutive 12-month years.",
        why="Rising borrowing alongside falling operating profit can shrink headroom, unless the debt funds capacity that has not yet earned a return.",
        followup="What was the new debt used for (capex, acquisition, working capital) and when is it expected to contribute earnings?"),
    "LOW_CURRENT_RATIO": dict(
        indicator="Current ratio", kind="threshold_breach", col="current_ratio", fmt="x", peer="current_ratio",
        inputs=["current_assets", "current_liabilities"],
        formula="Current assets / current liabilities.",
        why="A short-term liquidity cushion. Some business models run below 1 structurally, so compare with the company's own history and peers.",
        followup="Is the low ratio structural? What undrawn facilities exist and what are the current liabilities (payables, dealer deposits, debt)?"),
    "SUSTAINED_EBIT_MARGIN_DECLINE": dict(
        indicator="EBIT margin trend", kind="deterioration", col="ebit_margin", fmt="pct", peer="ebit_margin",
        inputs=["ebit", "revenue"],
        formula="EBIT / revenue; flagged when it fell in each of N directly consecutive comparable years.",
        why="A margin that keeps falling points to cost or price pressure rather than a one-off.",
        followup="Which cost lines (energy, freight, raw materials) or price / mix changes does the management discussion cite? Is it consistent with the figures?"),
    "SUSTAINED_REVENUE_DECLINE": dict(
        indicator="Revenue trend", kind="deterioration", col="revenue_cr", fmt="cr", peer=None,
        inputs=["revenue"],
        formula="Revenue growth below zero in each of N directly consecutive comparable years.",
        why="Falling sales reduce the base that covers fixed costs and interest.",
        followup="Is the fall volume, price or a scope change (divestment, demerger)?"),
    "NEGATIVE_FREE_CASH_FLOW": dict(
        indicator="Free cash flow", kind="threshold_breach", col="free_cash_flow_cr", fmt="cr", peer="fcf_margin",
        inputs=["operating_cash_flow", "capex"],
        formula="Operating cash flow - capex (purchase of property, plant and equipment).",
        why="Cash left after investment. Negative free cash flow is common during capacity expansion and is not distress by itself; it shows reliance on cash, debt or equity.",
        followup="Was the capex growth or maintenance? How was the shortfall financed?"),
    "NONPOSITIVE_EQUITY": dict(
        indicator="Equity", kind="threshold_breach", col="total_equity_cr", fmt="cr", peer=None,
        inputs=["total_equity"],
        formula="Equity share capital + other equity (excluding non-controlling interests).",
        why="Without positive equity, debt-to-equity is not meaningful and losses have eroded owners' capital.",
        followup="What caused it (accumulated losses, buybacks, restatement)?"),
}

_FMT = {"x": fmt_x, "pct": fmt_pct, "cr": fmt_cr}
GROUPS = {
    "Leverage and coverage": {"LOW_INTEREST_COVERAGE", "DEBT_UP_EBIT_DOWN", "NONPOSITIVE_EQUITY"},
    "Profitability": {"SUSTAINED_EBIT_MARGIN_DECLINE", "SUSTAINED_REVENUE_DECLINE"},
    "Liquidity and cash flow": {"LOW_CURRENT_RATIO", "NEGATIVE_OPERATING_CASH_FLOW", "NEGATIVE_FREE_CASH_FLOW"},
}
PERSISTENCE_INDICATOR = {
    "LOW_INTEREST_COVERAGE": "LOW_INTEREST_COVERAGE", "LOW_CURRENT_RATIO": "LOW_CURRENT_RATIO",
    "NEGATIVE_OPERATING_CASH_FLOW": "NEGATIVE_OPERATING_CASH_FLOW", "NEGATIVE_FREE_CASH_FLOW": "NEGATIVE_FREE_CASH_FLOW",
    "SUSTAINED_EBIT_MARGIN_DECLINE": "EBIT_MARGIN_DECLINE", "SUSTAINED_REVENUE_DECLINE": "REVENUE_DECLINE",
    "DEBT_UP_EBIT_DOWN": "DEBT_UP_EBIT_DOWN",
}
INPUT_COLS = {"ebit": "ebit_cr", "interest_expense": "interest_expense_cr", "total_debt": "total_debt_cr",
              "total_equity": "total_equity_cr", "current_assets": "current_assets_cr",
              "current_liabilities": "current_liabilities_cr", "operating_cash_flow": "operating_cash_flow_cr",
              "capex": "capex_cr", "revenue": "revenue_cr"}


def _history(m_co: pd.DataFrame, col: str, fy_start: int, fmt_key: str, n: int = 3) -> str:
    h = m_co[m_co["fy_start"] <= fy_start].sort_values("fy_start").tail(n)
    f = _FMT[fmt_key]
    vals = [(r.financial_year, getattr(r, col)) for r in h.itertuples()]
    text = " -> ".join(f"{fy}: {f(v)}" for fy, v in vals)
    nums = [v for _, v in vals if pd.notna(v)]
    if len(nums) >= 2:
        diffs = [b - a for a, b in zip(nums, nums[1:])]
        direction = "falling" if all(x < 0 for x in diffs) else "rising" if all(x > 0 for x in diffs) else "mixed"
        text += f"  (direction over these observed years: {direction})"
    return text


def explain_flags(flags: pd.DataFrame, m_all: pd.DataFrame, t: Thresholds, ver: pd.DataFrame | None = None,
                  pers: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per fired flag with everything an analyst needs to judge it."""
    cols = ["Year", "Indicator", "Observed", "Threshold", "Formula", "Why it matters", "Persistence", "History",
            "Peer context", "Data quality", "Follow-up", "rule_id", "type"]
    if flags.empty:
        return pd.DataFrame(columns=cols)
    m_all = with_peer_metrics(m_all)
    pers = pers if pers is not None else persistence_table(m_all, t)
    pidx = pers.set_index(["ticker", "basis", "financial_year", "indicator"])
    rows = []
    for f in flags.itertuples():
        info = RULE_INFO[f.rule_id]
        co = m_all[(m_all["ticker"] == f.ticker) & (m_all["basis"] == f.basis)]
        cur = co[co["financial_year"] == f.financial_year].iloc[0]
        fmt_fn = _FMT[info["fmt"]]
        pind = PERSISTENCE_INDICATOR.get(f.rule_id)
        persist = "n/a (equity rule)"
        if pind and (f.ticker, f.basis, f.financial_year, pind) in pidx.index:
            p = pidx.loc[(f.ticker, f.basis, f.financial_year, pind)]
            persist = explain_status(p["status"], int(p["streak"]), t)
        peer = "not applicable for this indicator"
        if info["peer"]:
            peer = peer_context(m_all, f.ticker, f.basis, f.financial_year, info["peer"], bool(cur["is_illustrative"]))["text"]
        dq = []
        missing = [i for i in info["inputs"] if i in INPUT_COLS and pd.isna(cur[INPUT_COLS[i]])]
        if missing:
            dq.append("missing inputs: " + ", ".join(missing))
        if int(cur["period_months"]) != 12:
            dq.append(f"{int(cur['period_months'])}-month period")
        dq.append(input_status(ver, f.ticker, f.financial_year, info["inputs"]))
        rows.append({
            "Year": f.financial_year, "Indicator": info["indicator"], "Observed": f.evidence,
            "Threshold": f.threshold_used, "Formula": info["formula"], "Why it matters": info["why"],
            "Persistence": persist, "History": _history(co, info["col"], int(cur["fy_start"]), info["fmt"]),
            "Peer context": peer, "Data quality": "; ".join(dq), "Follow-up": info["followup"],
            "rule_id": f.rule_id, "type": info["kind"],
        })
    return pd.DataFrame(rows, columns=cols)


def assess_year(row: pd.Series, flags_year: pd.DataFrame, pers_year: pd.DataFrame, t: Thresholds,
                ver: pd.DataFrame | None = None) -> list[dict]:
    """Layered reading of one company-year. Returns [{'kind': ..., 'text': ...}, ...]."""
    out: list[dict] = []
    fired = set(flags_year["rule_id"]) if not flags_year.empty else set()

    # 1 breaches / 2 deterioration
    for rid in sorted(fired):
        info = RULE_INFO[rid]
        if rid == "NONPOSITIVE_EQUITY":
            continue
        out.append({"kind": info["kind"], "text": flags_year[flags_year.rule_id == rid].iloc[0]["evidence"]})
    for p in pers_year.itertuples():
        if p.status == "persistent" and p.indicator in ("LOW_INTEREST_COVERAGE", "LOW_CURRENT_RATIO", "NEGATIVE_OPERATING_CASH_FLOW",
                                                       "NEGATIVE_FREE_CASH_FLOW"):
            out.append({"kind": "deterioration", "text": f"{INDICATOR_TEXT(p.indicator)} has now breached in {p.streak} directly "
                                                          "consecutive observed years (historical observation, not a prediction)."})

    # 3 convergence
    groups = [g for g, rules in GROUPS.items() if fired & rules]
    if len(groups) >= 2:
        out.append({"kind": "convergence", "text": "Warnings in more than one area at the same time: " + "; ".join(groups) +
                    ". Independent areas pointing the same way is stronger than one ratio alone, but still a prompt to investigate, not a conclusion."})

    # 4 conflicts
    ic, ocf, fcf = row.get("interest_coverage"), row.get("operating_cash_flow_cr"), row.get("free_cash_flow_cr")
    if pd.notna(ic) and ic >= t.interest_coverage_min and pd.notna(ocf) and ocf < 0:
        out.append({"kind": "conflict", "text": f"Conflicting signals: interest coverage is comfortable ({fmt_x(ic)}) but operating cash flow is negative "
                                                f"({fmt_cr(ocf)}). Strong coverage does not show low overall risk when cash generation is negative."})
    elif pd.notna(ic) and ic >= t.interest_coverage_min and pd.notna(fcf) and fcf < 0:
        out.append({"kind": "conflict", "text": f"Mixed signals: interest coverage is comfortable ({fmt_x(ic)}) but free cash flow is negative "
                                                f"({fmt_cr(fcf)}) because capex exceeds operating cash flow; check how it was financed."})

    # 5 data limitations
    pm = int(row["period_months"])
    if pm != 12:
        out.append({"kind": "data_limitation", "text": f"This is a {pm}-month period: year-on-year measures are n/a and flow figures are not comparable with 12-month years."})
    na = [p.indicator for p in pers_year.itertuples() if p.status == "not_assessable"]
    if na:
        out.append({"kind": "data_limitation", "text": "Not assessable this year (missing input or non-comparable period, NOT treated as satisfactory): " +
                    ", ".join(INDICATOR_TEXT(i) for i in na) + "."})
    hu = [p.indicator for p in pers_year.itertuples() if p.status == "history_unknown"]
    if hu:
        out.append({"kind": "data_limitation", "text": "Breach with unknown history (previous year missing or not comparable): " +
                    ", ".join(INDICATOR_TEXT(i) for i in hu) + "."})
    if ver is not None and not ver.empty:
        sub = ver[(ver["ticker"] == row["ticker"]) & (ver["financial_year"] == row["financial_year"])]
        bad = sub[sub["status"] == "discrepancy"]
        if not bad.empty:
            out.append({"kind": "data_limitation", "text": "Loaded values that disagree with the company's filing (unresolved): " +
                        ", ".join(bad["item"]) + ". Treat indicators using them as provisional."})
        if sub.empty:
            out.append({"kind": "data_limitation", "text": "No input for this year has been checked against a primary filing."})
    else:
        out.append({"kind": "data_limitation", "text": "No input has been checked against a primary filing."})

    # 6 inconclusive
    assessable = sum(1 for c in ("interest_coverage", "debt_to_equity", "current_ratio", "ocf_to_debt", "ebit_margin") if pd.notna(row.get(c)))
    if assessable < 3 or (pers_year["status"] == "not_assessable").sum() >= 4:
        out.append({"kind": "inconclusive", "text": "Inconclusive: too few indicators can be assessed for this year to say whether risk is emerging."})
    elif not fired:
        out.append({"kind": "inconclusive", "text": "No rule fired. That means no illustrative threshold was crossed on the data available, not that risk is low "
                                                    "(debt maturities, liquidity facilities, contingent liabilities and many drivers are not modelled)."})
    return out


def INDICATOR_TEXT(key: str) -> str:
    from .persistence import INDICATORS
    return INDICATORS.get(key, key)

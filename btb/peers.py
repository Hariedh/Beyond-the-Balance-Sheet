"""Peer benchmarking on a comparable basis.

Rules
  * Only companies of the same kind are compared: real with real, synthetic with synthetic.
  * Same reporting basis and same financial year.
  * A period that is not 12 months is shown but excluded from peer medians. Ratios that mix a flow with
    a balance-sheet stock (operating cash flow / debt) are blanked for such periods.
  * A peer with no data for the year is listed, not silently dropped.
  * No ranking and no 'safest / riskiest' label: size, acquisitions and consolidation scope differ.
"""
from __future__ import annotations

import pandas as pd

PEER_METRICS = {
    "ebit_margin": ("EBIT margin", "profitability", "pct"),
    "interest_coverage": ("Interest coverage", "leverage / coverage", "x"),
    "debt_to_equity": ("Debt-to-equity", "leverage / coverage", "x"),
    "current_ratio": ("Current ratio", "liquidity", "x"),
    "ocf_to_ebit": ("OCF / EBIT", "cash-flow quality", "x"),
    "ocf_to_debt": ("OCF / debt", "cash-flow quality", "x"),
    "fcf_margin": ("FCF margin", "cash-flow quality", "pct"),
}
FLOW_STOCK = {"ocf_to_debt"}      # flow divided by a balance-sheet stock: not comparable across period lengths

COMPARABILITY_NOTES = (
    "Size differs a lot (UltraTech's revenue is several times that of the others), so absolute rupee amounts are not comparable; ratios are.",
    "Consolidation scope changes with acquisitions and group restructuring (for example Ambuja's and ACC's change of year-end to March and the changes in group ownership). Check each annual report's notes before reading a trend as organic.",
    "Total equity here excludes non-controlling interests while debt is consolidated. Where minorities are large the gap matters: Ambuja's filing shows non-controlling interest of about 17% of total equity at March 2026 and UltraTech's about 4% at March 2025, so debt-to-equity is somewhat higher than a like-for-like measure would show.",
    "Current ratios below 1 are structural for some business models (UltraTech has been below 1 in every year with data) and are not a distress signal on their own.",
    "Ambuja and ACC report a 15-month FY2022-23 and have no loaded history before it, so they have fewer comparable years than the other three.",
)


def with_peer_metrics(m: pd.DataFrame) -> pd.DataFrame:
    """Add derived cash-flow-quality measures (not part of the six headline ratios)."""
    out = m.copy()
    ebit = out["ebit_cr"].where(out["ebit_cr"] > 0)
    rev = out["revenue_cr"].where(out["revenue_cr"] > 0)
    out["ocf_to_ebit"] = out["operating_cash_flow_cr"] / ebit
    out["fcf_margin"] = out["free_cash_flow_cr"] / rev
    return out


def same_universe(m: pd.DataFrame, illustrative: bool) -> pd.DataFrame:
    """Rows of the same kind only: never mix synthetic demo companies with real ones."""
    return m[m["is_illustrative"] == int(bool(illustrative))]


def peer_table(m: pd.DataFrame, basis: str, fy: str, illustrative: bool) -> pd.DataFrame:
    """One row per company in the universe, with comparability status. Medians are comparable rows only."""
    if m.empty or "ebit_cr" not in m.columns:
        return pd.DataFrame(columns=["ticker", "name", "period_months", "revenue_cr", "comparable", "status", *PEER_METRICS])
    m = with_peer_metrics(same_universe(m, illustrative))
    m = m[m["basis"] == basis]
    names = m.drop_duplicates("ticker").set_index("ticker")["name"]
    rows = []
    for ticker in sorted(m["ticker"].unique()):
        r = m[(m["ticker"] == ticker) & (m["financial_year"] == fy)]
        if r.empty:
            rows.append({"ticker": ticker, "name": names[ticker], "period_months": None, "revenue_cr": None,
                         "comparable": False, "status": "no data loaded for this year",
                         **{c: None for c in PEER_METRICS}})
            continue
        r = r.iloc[0]
        ok = int(r["period_months"]) == 12
        vals = {c: (None if (not ok and c in FLOW_STOCK) or pd.isna(r[c]) else float(r[c])) for c in PEER_METRICS}
        rows.append({"ticker": ticker, "name": names[ticker], "period_months": int(r["period_months"]),
                     "revenue_cr": float(r["revenue_cr"]) if pd.notna(r["revenue_cr"]) else None,
                     "comparable": ok,
                     "status": "comparable" if ok else f"{int(r['period_months'])}-month period: excluded from peer medians",
                     **vals})
    return pd.DataFrame(rows)


def peer_medians(table: pd.DataFrame) -> pd.DataFrame:
    """Median and count per metric over comparable companies with a value."""
    comp = table[table["comparable"]]
    rows = [{"metric": c, "median": comp[c].median() if comp[c].notna().any() else None, "n": int(comp[c].notna().sum())}
            for c in PEER_METRICS]
    return pd.DataFrame(rows)


def peer_context(m: pd.DataFrame, ticker: str, basis: str, fy: str, col: str, illustrative: bool) -> dict:
    """Median of the OTHER comparable companies for one metric and year, and where this company sits."""
    t = peer_table(m, basis, fy, illustrative)
    own = t[t["ticker"] == ticker]
    others = t[(t["ticker"] != ticker) & t["comparable"] & t[col].notna()] if col in t else t.iloc[0:0]
    if own.empty or not bool(own.iloc[0]["comparable"]) or pd.isna(own.iloc[0][col]):
        return {"n": int(len(others)), "median": None, "relation": None,
                "text": "no comparable own value this year, so no peer comparison"}
    if len(others) < 2:
        return {"n": int(len(others)), "median": None, "relation": None,
                "text": f"only {len(others)} comparable peer(s) with data this year: too few for a median"}
    med = float(others[col].median())
    v = float(own.iloc[0][col])
    rel = "above" if v > med else "below" if v < med else "equal to"
    shown = f"{med * 100:.1f}%" if PEER_METRICS[col][2] == "pct" else f"{med:.2f}x"
    return {"n": int(len(others)), "median": med, "relation": rel,
            "text": f"{rel} the median of {len(others)} comparable peers ({shown})"}

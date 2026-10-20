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
    "Debt definition: total debt is the aggregators' figure, which the filings show INCLUDES lease liabilities where they could be checked (UltraTech FY2024-25 and FY2025-26, Dalmia FY2024-25 and FY2025-26, Shree FY2023-24). For ACC (reported borrowings are nil, yet loaded debt is about Rs 430 crore), Ambuja and Shree FY2025-26 the lease balance was not on the face of the statements, so inclusion is likely but NOT confirmed. Debt-to-equity and OCF / debt are therefore comparable in definition only as far as that evidence goes.",
    "Ambuja's FY2024-25 figures are the company's RESTATED comparatives (annual report, Note 68(h)) and include about Rs 964 crore of one-time income in EBITDA; they do not agree with the original FY2024-25 filing, so FY2024-25 cash-flow ratios for Ambuja are provisional.",
    "This is a five-company case study of one sector. It does not support general conclusions about other sectors, other borrowers or cement companies not in the sample.",
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


CORPORATE_GROUP = {
    "AMBUJACEM": "Ambuja / ACC group",
    "ACC": "Ambuja / ACC group",
}
GROUP_NOTE = ("Ambuja and ACC belong to the same corporate group (as noted in the project's company notes; the ownership and "
              "consolidation overlap was not verified from the filings read here). Their observations are not fully "
              "independent, so medians that include both count them as two companies but one group; read broader "
              "industry conclusions with that in mind.")
RECENT_WINDOW = ("FY2023-24", "FY2025-26")        # main peer-comparison window: standard 12-month years, best filing coverage
HISTORY_WINDOW = ("FY2020-21", "FY2022-23")       # longer-term context, with period-specific exclusions


def _usable(table_row_status: str, kinds: str, strict: bool) -> bool:
    if table_row_status == "comparable":
        return True
    return (not strict) and table_row_status == "caution" and kinds == "definition"


def peer_table(m: pd.DataFrame, basis: str, fy: str, illustrative: bool, ver: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per company in the universe with a status (and reason) for every metric.

    `comparable` stays the simple period test (12 months). Medians use the per-metric status instead.
    """
    from .comparability import METRICS, filing_check_label, metric_status
    base_cols = ["ticker", "name", "group", "period_months", "revenue_cr", "comparable", "status", "filing_check"]
    status_cols = [f"{p}{c}" for c in PEER_METRICS for p in ("st__", "why__", "kind__")]
    if m.empty or "ebit_cr" not in m.columns:
        return pd.DataFrame(columns=[*base_cols, *PEER_METRICS, *status_cols])
    m = with_peer_metrics(same_universe(m, illustrative))
    m = m[m["basis"] == basis]
    names = m.drop_duplicates("ticker").set_index("ticker")["name"]
    rows = []
    for ticker in sorted(m["ticker"].unique()):
        r = m[(m["ticker"] == ticker) & (m["financial_year"] == fy)]
        group = CORPORATE_GROUP.get(ticker, "")
        if r.empty:
            rows.append({"ticker": ticker, "name": names[ticker], "group": group, "period_months": None, "revenue_cr": None,
                         "comparable": False, "status": "no data loaded for this year", "filing_check": "not checked",
                         **{c: None for c in PEER_METRICS},
                         **{f"st__{c}": "not_comparable" for c in PEER_METRICS},
                         **{f"why__{c}": "no data loaded for this year" for c in PEER_METRICS},
                         **{f"kind__{c}": "missing" for c in PEER_METRICS}})
            continue
        r = r.iloc[0]
        months = int(r["period_months"])
        out = {"ticker": ticker, "name": names[ticker], "group": group, "period_months": months,
               "revenue_cr": float(r["revenue_cr"]) if pd.notna(r["revenue_cr"]) else None,
               "comparable": months == 12,
               "status": "comparable" if months == 12 else f"{months}-month period: see the metric statuses",
               "filing_check": filing_check_label(ver, ticker, fy)}
        for c in PEER_METRICS:
            st = metric_status(r, c, ver)
            out[c] = None if pd.isna(r[c]) else float(r[c])
            out[f"st__{c}"], out[f"why__{c}"], out[f"kind__{c}"] = st["status"], st["reason"], ",".join(st["kinds"])
        rows.append(out)
    return pd.DataFrame(rows)


def peer_medians(table: pd.DataFrame) -> pd.DataFrame:
    """Per metric: median over 'comparable' companies, and over comparable plus definition-only 'caution' companies.

    A period-length caution (e.g. a 15-month year) is never included. `n_groups` counts independent corporate groups.
    """
    rows = []
    for c in PEER_METRICS:
        out = {"metric": c}
        for tag, strict in (("", True), ("_incl_definition", False)):
            if f"st__{c}" in table.columns and not table.empty:
                mask = pd.Series([_usable(a, b, strict) for a, b in zip(table[f"st__{c}"], table[f"kind__{c}"])], index=table.index)
                ok = table[mask & table[c].notna()]
            else:
                ok = table.iloc[0:0]
            out["median" + tag] = ok[c].median() if len(ok) else None
            out["n" + tag] = int(len(ok))
            if not strict:
                out["n_groups_incl_definition"] = int(len({(g or t) for g, t in zip(ok["group"], ok["ticker"])}))
            else:
                out["n_groups"] = int(len({(g or t) for g, t in zip(ok["group"], ok["ticker"])}))
        rows.append(out)
    return pd.DataFrame(rows)


def peer_context(m: pd.DataFrame, ticker: str, basis: str, fy: str, col: str, illustrative: bool,
                 ver: pd.DataFrame | None = None) -> dict:
    """Median of the OTHER usable companies for one metric and year, and where this company sits.

    'Usable' = comparable, or caution only because the debt definition is unconfirmed (never a period-length caution).
    """
    t = peer_table(m, basis, fy, illustrative, ver)
    own = t[t["ticker"] == ticker]
    if col not in t or t.empty or f"st__{col}" not in t:
        return {"n": 0, "median": None, "relation": None, "text": "no peer comparison available"}
    usable = [_usable(a, b, False) for a, b in zip(t[f"st__{col}"], t[f"kind__{col}"])]
    others = t[(t["ticker"] != ticker) & pd.Series(usable, index=t.index) & t[col].notna()]
    if own.empty or not _usable(own.iloc[0][f"st__{col}"], own.iloc[0][f"kind__{col}"], False) or pd.isna(own.iloc[0][col]):
        return {"n": int(len(others)), "median": None, "relation": None,
                "text": "no comparable own value this year, so no peer comparison"}
    if len(others) < 2:
        return {"n": int(len(others)), "median": None, "relation": None,
                "text": f"only {len(others)} comparable peer(s) with data this year: too few for a median"}
    med = float(others[col].median())
    v = float(own.iloc[0][col])
    rel = "above" if v > med else "below" if v < med else "equal to"
    shown = f"{med * 100:.1f}%" if PEER_METRICS[col][2] == "pct" else f"{med:.2f}x"
    groups = len({(g or tk) for g, tk in zip(others["group"], others["ticker"])})
    extra = "" if groups == len(others) else f"; they come from {groups} independent corporate groups"
    return {"n": int(len(others)), "median": med, "relation": rel,
            "text": f"{rel} the median of {len(others)} comparable peers ({shown}){extra}"}


COMPARABILITY_NOTES = (*COMPARABILITY_NOTES, GROUP_NOTE,
    "Recent peer window: FY2023-24 to FY2025-26 is the main comparison window because every company has standard 12-month years there "
    "and filing checks cover most of it. FY2020-21 to FY2022-23 is longer-term context only; it contains the 15-month transition "
    "period and unchecked years, and a period-specific status is applied to each metric.",
)

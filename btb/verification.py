"""Helpers for the source-verification table (loaded value vs. primary filing)."""
from __future__ import annotations

import pandas as pd

from .db import query_df

STATUS_RANK = {"discrepancy": 0, "unverified": 1, "approx": 2, "verified": 3}


def verification_frame(conn) -> pd.DataFrame:
    return query_df(conn, "SELECT v.*, c.ticker FROM source_verification v JOIN companies c USING (company_id) "
                          "ORDER BY c.ticker, v.financial_year, v.item")


def input_status(ver: pd.DataFrame, ticker: str, fy: str, items: list[str]) -> str:
    """Plain-language verification status of the inputs behind an indicator for one company-year."""
    if ver is None or ver.empty:
        return "not checked against a primary filing"
    sub = ver[(ver["ticker"] == ticker) & (ver["financial_year"] == fy)]
    if sub.empty:
        return "not checked against a primary filing (aggregator data)"
    parts, unchecked = [], []
    for item in items:
        r = sub[sub["item"] == item]
        if r.empty:
            unchecked.append(item)
            continue
        r = r.iloc[0]
        label = {"verified": "matches filing", "approx": f"within 1% of filing ({r['difference_pct']:+.2f}%)",
                 "discrepancy": f"DISCREPANCY vs filing ({r['difference_pct']:+.1f}%)",
                 "unverified": "not like-for-like with filing"}[r["status"]]
        parts.append(f"{item}: {label}")
    if unchecked:
        parts.append("not checked: " + ", ".join(unchecked))
    return "; ".join(parts)


def worst_status(ver: pd.DataFrame, ticker: str, fy: str, items: list[str]) -> str:
    """'discrepancy' < 'unverified' < 'approx' < 'verified'; items with no row count as 'unverified'."""
    if ver is None or ver.empty:
        return "unverified"
    sub = ver[(ver["ticker"] == ticker) & (ver["financial_year"] == fy)]
    ranks = []
    for item in items:
        r = sub[sub["item"] == item]
        ranks.append(r.iloc[0]["status"] if not r.empty else "unverified")
    return min(ranks, key=lambda s: STATUS_RANK[s]) if ranks else "unverified"


def summary(ver: pd.DataFrame, ticker: str) -> dict:
    sub = ver[ver["ticker"] == ticker] if ver is not None and not ver.empty else pd.DataFrame(columns=["status"])
    counts = sub["status"].value_counts().to_dict() if not sub.empty else {}
    return {"checked": int(len(sub)), **{k: int(counts.get(k, 0)) for k in STATUS_RANK},
            "years": sorted(sub["financial_year"].unique()) if not sub.empty else []}

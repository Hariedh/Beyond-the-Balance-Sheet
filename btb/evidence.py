"""Build the structured, citable evidence packet handed to the commentary step.

Every number the commentary may use appears here with a stable ID such as
R.interest_coverage.FY2023-24 (a ratio) or F.ebit_cr.FY2023-24 (a reported
input). Flags, disclosures and external indicators get IDs too. Commentary
statements must cite these IDs, and verification checks them.
"""
from __future__ import annotations

import math

import pandas as pd

from .db import load_fin, query_df
from .flags import Thresholds, evaluate_flags
from .metrics import RATIO_COLUMNS, RATIO_DEFINITIONS, RATIO_LABELS, compute_metrics

INPUT_FIELDS = {
    "revenue_cr": "Revenue",
    "ebit_cr": "EBIT",
    "interest_expense_cr": "Interest expense",
    "total_debt_cr": "Total debt",
    "total_equity_cr": "Total equity",
    "operating_cash_flow_cr": "Operating cash flow",
}
MAX_EXTERNAL_ROWS = 40


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    # 6 decimals keeps displayed percentages identical to the dashboard (4 decimals
    # turned 8.254% into 8.25% -> "8.2%" while the dashboard showed 8.3%).
    return round(float(v), 6)


def build_packet(conn, ticker: str, basis: str, fy_from: str | None = None, fy_to: str | None = None,
                 thresholds: Thresholds | None = None) -> dict:
    thresholds = thresholds or Thresholds()
    fin = load_fin(conn)
    metrics = compute_metrics(fin)
    flags_all = evaluate_flags(metrics, thresholds)

    m = metrics[(metrics["ticker"] == ticker) & (metrics["basis"] == basis)].copy()
    if fy_from:
        m = m[m["financial_year"] >= fy_from]
    if fy_to:
        m = m[m["financial_year"] <= fy_to]
    if m.empty:
        raise ValueError(f"No data for {ticker} ({basis}) in the selected range.")
    years = list(m["financial_year"])

    figures: list[dict] = []
    for _, r in m.iterrows():
        fy = r["financial_year"]
        for col in RATIO_COLUMNS:
            v = _clean(r[col])
            if v is not None:
                figures.append({"id": f"R.{col}.{fy}", "label": RATIO_LABELS[col], "financial_year": fy,
                                "value": v, "unit": "fraction (x100 for %)" if col in ("revenue_growth", "ebit_margin") else "x",
                                "definition": RATIO_DEFINITIONS[col]})
        for col, label in INPUT_FIELDS.items():
            v = _clean(r[col])
            if v is not None:
                figures.append({"id": f"F.{col}.{fy}", "label": label, "financial_year": fy,
                                "value": v, "unit": "INR crore", "definition": "as loaded from source"})

    fl = flags_all[(flags_all["ticker"] == ticker) & (flags_all["basis"] == basis)
                   & (flags_all["financial_year"].isin(years))]
    flags = []
    for _, r in fl.iterrows():
        flags.append({
            "id": f"FLAG.{r['rule_id']}.{r['financial_year']}",
            "rule_id": r["rule_id"], "financial_year": r["financial_year"],
            "rule_description": r["rule_description"], "threshold": r["threshold_used"],
            "observed_value": _clean(r["observed_value"]), "evidence_text": r["evidence"],
        })

    company = m.iloc[0]
    cid = int(company["company_id"])
    d = query_df(conn, "SELECT * FROM disclosures WHERE company_id = ? ORDER BY financial_year, disclosure_id", (cid,))
    disclosures = [{
        "id": f"DISC.{int(r.disclosure_id)}", "financial_year": r.financial_year, "topic": r.topic,
        "excerpt": r.excerpt, "source_doc": r.source_doc, "page_ref": r.page_ref,
        "is_illustrative": bool(r.is_illustrative),
    } for r in d.itertuples() if r.financial_year is None or r.financial_year in years]

    e = query_df(conn, "SELECT * FROM external_indicators ORDER BY series_name, period LIMIT ?", (MAX_EXTERNAL_ROWS,))
    external = [{
        "id": f"EXT.{int(r.indicator_id)}", "series": r.series_name, "period": r.period,
        "value": _clean(r.value), "unit": r.unit, "source": r.source,
        "is_illustrative": bool(r.is_illustrative),
    } for r in e.itertuples()]

    iss = query_df(conn, "SELECT severity, check_name, financial_year, detail FROM validation_issues "
                         "WHERE ticker = ? AND severity IN ('error', 'warning')", (ticker,))
    data_notes = [f"[{r.severity}] {r.check_name} {r.financial_year or ''}: {r.detail}".strip()
                  for r in iss.itertuples()]

    return {
        "company": {"ticker": ticker, "name": company["name"], "industry": company["industry"]},
        "basis": basis,
        "years": years,
        "units_note": "All monetary values are in INR crore. Ratios are unit-free.",
        "is_illustrative": bool(m["is_illustrative"].any()),
        "thresholds": thresholds.as_dict(),
        "figures": figures,
        "flags": flags,
        "disclosures": disclosures,
        "external_indicators": external,
        "data_quality_notes": data_notes,
    }


def packet_ids(packet: dict) -> set[str]:
    ids = set()
    for key in ("figures", "flags", "disclosures", "external_indicators"):
        ids.update(item["id"] for item in packet.get(key, []))
    return ids

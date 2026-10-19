"""One-company analytical report, exported as a flat CSV.

Every row has a `basis_of_statement` so verified observations, hypotheses and scenario outputs
are never mixed up:

  observed (loaded data)   a figure or flag computed from the loaded data
  checked vs filing        a figure that matches the company's filing (see source_verification)
  unverified               not checked against a primary filing
  hypothesis               a possible explanation or open question, NOT established
  scenario (not forecast)  an output of the stress test
  limitation               a caveat on data, comparability or method
"""
from __future__ import annotations

import pandas as pd

from . import config
from .fmt import fmt_cr, fmt_pct, fmt_x
from .metrics import PERCENT_RATIOS, RATIO_COLUMNS, RATIO_DEFINITIONS, RATIO_LABELS
from .peers import COMPARABILITY_NOTES
from .stress import stress_table

COLUMNS = ["section", "item", "value", "basis_of_statement", "detail"]


def _fmt_stress(kind: str, v) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    return {"cr": fmt_cr, "pct": fmt_pct, "x": fmt_x}[kind](v)


def build_report(*, ticker: str, name: str, basis: str, m: pd.DataFrame, fy_from: str, fy_to: str, thresholds,
                 explained: pd.DataFrame, assessment: list[dict], peer: pd.DataFrame, peer_med: pd.DataFrame,
                 stress: dict | None, ver: pd.DataFrame, disclosures: pd.DataFrame, issues: pd.DataFrame,
                 is_illustrative: bool) -> pd.DataFrame:
    rows: list[dict] = []

    def add(section, item, value, basis_of, detail=""):
        rows.append({"section": section, "item": item, "value": value, "basis_of_statement": basis_of, "detail": detail})

    latest = m.iloc[-1]
    add("1. Company and period", "Company", f"{ticker}: {name}", "observed (loaded data)",
        "ILLUSTRATIVE SYNTHETIC DATA: not a real company" if is_illustrative else "")
    add("1. Company and period", "Reporting basis", basis, "observed (loaded data)")
    add("1. Company and period", "Financial years covered", f"{fy_from} to {fy_to}", "observed (loaded data)",
        "latest year: " + latest["financial_year"] + (f" ({int(latest['period_months'])}-month period)" if latest["period_months"] != 12 else ""))
    add("1. Company and period", "Units", "INR crore", "observed (loaded data)")

    v_sub = ver[(ver["ticker"] == ticker) & (ver["financial_year"] == latest["financial_year"])] if ver is not None and not ver.empty else pd.DataFrame()
    status = "checked vs filing" if not v_sub.empty and (v_sub["status"].isin(["verified", "approx"])).any() else "unverified"
    for c in RATIO_COLUMNS:
        v = latest[c]
        add("2. Key financial metrics", f"{RATIO_LABELS[c]} ({latest['financial_year']})",
            ("n/a" if pd.isna(v) else (fmt_pct(v) if c in PERCENT_RATIOS else fmt_x(v))), status, RATIO_DEFINITIONS[c])
    for label, col in (("Operating cash flow", "operating_cash_flow_cr"), ("Capex", "capex_cr"), ("Free cash flow", "free_cash_flow_cr")):
        add("2. Key financial metrics", f"{label} ({latest['financial_year']})", fmt_cr(latest[col]), status,
            "free cash flow = operating cash flow - capex" if col == "free_cash_flow_cr" else "")

    if explained.empty:
        add("3. Material warning signals", "Rules fired", "none", "observed (loaded data)",
            "No illustrative threshold was crossed on the data available. This does not show that risk is low.")
    for e in explained.to_dict("records"):
        add("3. Material warning signals", f"{e['Year']}: {e['Indicator']}", e["Observed"], "observed (loaded data)",
            f"threshold {e['Threshold']}; {e['Persistence']}; data quality: {e['Data quality']}")
    for a in assessment:
        basis_of = "limitation" if a["kind"] == "data_limitation" else "observed (loaded data)"
        add("3. Material warning signals", f"Reading: {a['kind']}", a["text"], basis_of)

    for r in peer.itertuples():
        add("4. Evidence and peer context", f"Peer {r.ticker} ({r.status})",
            "EBIT margin " + _fmt_stress("pct", r.ebit_margin) + "; D/E " + _fmt_stress("x", r.debt_to_equity) +
            "; coverage " + _fmt_stress("x", r.interest_coverage), "observed (loaded data)")
    for r in peer_med.itertuples():
        add("4. Evidence and peer context", f"Comparable-peer median: {r.metric}", "n/a" if pd.isna(r.median) else round(float(r.median), 4),
            "observed (loaded data)", f"n = {r.n}")
    if disclosures.empty:
        add("4. Evidence and peer context", "Company disclosures", "none loaded for this company and period", "limitation",
            "Without a documented source the tool cannot say why a metric moved.")
    for d in disclosures.itertuples():
        add("4. Evidence and peer context", f"Disclosure ({d.financial_year}): {d.topic}", d.excerpt,
            "checked vs filing" if d.relationship == "established" else "hypothesis",
            f"{d.source_doc}; {d.page_ref}; published {d.publication_date}; related metric: {d.related_metric}; "
            f"relationship: {d.relationship}")

    if stress and stress.get("available"):
        s = stress["inputs"]
        add("5. Stress test", "Scenario inputs", f"revenue -{s.revenue_decline:.0%}, EBIT margin -{s.margin_decline_pp * 100:.1f} pp, "
            f"fixed cost share {s.fixed_cost_share:.0%}", "scenario (not forecast)", f"base year {latest['financial_year']}")
        for r in stress_table(stress).itertuples():
            add("5. Stress test", r.Metric, f"{_fmt_stress(r.kind, r.Baseline)} -> {_fmt_stress(r.kind, r.Scenario)}",
                "scenario (not forecast)")
        b = stress.get("breakeven_revenue_decline")
        add("5. Stress test", "Revenue fall taking coverage to 1.0x", "n/a" if b is None else f"{b:.0%}", "scenario (not forecast)",
            "under the same cost behaviour and margin shock")
        for a in stress["assumptions"]:
            add("5. Stress test", "Assumption", a, "scenario (not forecast)")
        for n in stress["notes"]:
            add("5. Stress test", "Note", n, "limitation")
    else:
        add("5. Stress test", "Stress test", "not run or not available", "limitation",
            " ".join(stress["notes"]) if stress else "")

    for i in issues.itertuples():
        if i.severity in ("error", "warning"):
            add("6. Data quality and comparability", f"{i.check_name} {i.financial_year or ''}".strip(), i.detail, "limitation")
    for n in COMPARABILITY_NOTES:
        add("6. Data quality and comparability", "Comparability", n, "limitation")
    if ver is not None and not ver.empty:
        mine = ver[ver["ticker"] == ticker]
        add("6. Data quality and comparability", "Source verification",
            f"{int(mine['status'].isin(['verified', 'approx']).sum())} of {len(mine)} inputs checked match the company filing "
            f"({int((mine['status'] == 'discrepancy').sum())} discrepancies, {int((mine['status'] == 'unverified').sum())} not like-for-like)",
            "limitation", "Years checked: " + ", ".join(sorted(mine["financial_year"].unique())) if not mine.empty else "No years checked")

    seen = set()
    for e in explained.to_dict("records"):
        if e["rule_id"] not in seen:
            seen.add(e["rule_id"])
            add("7. Suggested follow-up", e["Indicator"], e["Follow-up"], "hypothesis", "investigation prompt, not a finding")
    if not seen:
        add("7. Suggested follow-up", "General", "Check debt maturities, liquidity facilities, contingent liabilities and the drivers "
            "of margins in the annual report; none of these are modelled here.", "hypothesis")

    for lim in config.LIMITATIONS:
        add("8. Limitations", "Limitation", lim, "limitation")
    for c in config.CANNOT_CLAIM:
        add("8. Limitations", "This project cannot claim", c, "limitation")
    add("8. Limitations", "Disclaimer", config.DISCLAIMER, "limitation")
    return pd.DataFrame(rows, columns=COLUMNS)

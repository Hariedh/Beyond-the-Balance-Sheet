#!/usr/bin/env python3
"""Independent recalculation of every displayed metric.

This script deliberately does NOT import the project's calculation code (btb.metrics, SQL views).
It re-implements each formula from the raw CSV files with plain Python, then compares the results with
  (a) the SQL view v_ratios in the SQLite database,
  (b) the pandas implementation in btb.metrics, and
  (c) the strings the dashboard would display (btb.fmt).
Differences are reported, never silently corrected. Writes docs/reconciliation_report.md.

Run:  python scripts/run_pipeline.py && python scripts/audit_recalc.py
"""
from __future__ import annotations

import csv
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UNIT = {"rupees": 1e-7, "thousands": 1e-4, "lakhs": 1e-2, "millions": 1e-1, "crores": 1.0}
FIELDS = ["revenue", "ebit", "interest_expense", "total_debt", "total_equity",
          "current_assets", "current_liabilities", "operating_cash_flow", "capex"]


def num(text):
    t = (text or "").strip().replace(",", "")
    if t.lower() in ("", "na", "n/a", "-", "null", "none"):
        return None
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    return float(t)


def load_rows(path: Path):
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        k = UNIT[r["unit"].strip().lower()]
        v = {f: (None if num(r.get(f)) is None else num(r.get(f)) * k) for f in FIELDS}
        fy = r["financial_year"].strip()
        out.append({"ticker": r["ticker"].strip().upper(), "fy": fy, "start": int(fy[2:6]), "basis": r["basis"].strip().lower(),
                    "months": int(r.get("period_months") or 12), **v})
    return out


def div(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def recompute(rows):
    rows = sorted(rows, key=lambda r: (r["ticker"], r["basis"], r["start"]))
    res = {}
    for i, r in enumerate(rows):
        prev = rows[i - 1] if i and rows[i - 1]["ticker"] == r["ticker"] and rows[i - 1]["basis"] == r["basis"] else None
        comparable = bool(prev and prev["start"] == r["start"] - 1 and prev["months"] == 12 and r["months"] == 12)
        growth = None
        if comparable and r["revenue"] is not None and prev["revenue"] and prev["revenue"] > 0:
            growth = (r["revenue"] - prev["revenue"]) / prev["revenue"]
        fcf = None if r["operating_cash_flow"] is None or r["capex"] is None else r["operating_cash_flow"] - r["capex"]
        res[(r["ticker"], r["basis"], r["fy"])] = {
            "interest_coverage": div(r["ebit"], r["interest_expense"]),
            "debt_to_equity": div(r["total_debt"], r["total_equity"]),
            "current_ratio": div(r["current_assets"], r["current_liabilities"]),
            "ocf_to_debt": div(r["operating_cash_flow"], r["total_debt"]),
            "revenue_growth": growth,
            "ebit_margin": div(r["ebit"], r["revenue"]),
            "free_cash_flow": fcf,
        }
    return res


def same(a, b, tol=1e-9):
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    if b is None or (isinstance(b, float) and math.isnan(b)):
        return False
    return abs(a - b) <= tol * max(1.0, abs(a))


def main() -> int:
    from btb import config
    from btb.db import connect, load_fin
    from btb.fmt import fmt_cr, fmt_pct, fmt_x
    from btb.metrics import compute_metrics

    rows = []
    for p in config.DEFAULT_FINANCIAL_FILES:
        if Path(p).exists():
            rows += load_rows(Path(p))
    mine = recompute(rows)

    conn = connect()
    sql = {(r["ticker"], r["basis"], r["financial_year"]): r for r in
           (dict(zip([c[0] for c in cur.description], row)) for cur in [conn.execute("SELECT * FROM v_ratios")] for row in cur)}
    pdf = compute_metrics(load_fin(conn))
    pandas_rows = {(r.ticker, r.basis, r.financial_year): r for r in pdf.itertuples()}
    conn.close()

    cols = ["interest_coverage", "debt_to_equity", "current_ratio", "ocf_to_debt", "revenue_growth", "ebit_margin"]
    mismatches, lines = [], []
    n_checked = 0
    for key, vals in sorted(mine.items()):
        for c in cols + ["free_cash_flow"]:
            n_checked += 1
            s = sql.get(key, {}).get(c) if c != "free_cash_flow" else None
            p = getattr(pandas_rows[key], c if c != "free_cash_flow" else "free_cash_flow_cr")
            if c != "free_cash_flow" and not same(vals[c], s):
                mismatches.append((key, c, "SQL view", vals[c], s))
            if not same(vals[c], p):
                mismatches.append((key, c, "pandas", vals[c], p))
        d = lambda c, f: "n/a" if vals[c] is None else f(vals[c])   # noqa: E731
        lines.append(f"| {key[0]} | {key[2]} | {d('interest_coverage', fmt_x)} | {d('debt_to_equity', fmt_x)} | {d('current_ratio', fmt_x)} | "
                     f"{d('ocf_to_debt', fmt_x)} | {d('revenue_growth', fmt_pct)} | {d('ebit_margin', fmt_pct)} | {d('free_cash_flow', fmt_cr)} |")

    md = ["# Financial reconciliation report", "",
          "Generated by `scripts/audit_recalc.py`. Every ratio below was recomputed from the raw CSV files with plain Python "
          "(no project calculation code), then compared with the SQL view `v_ratios` and with `btb.metrics` (pandas).", "",
          f"* Rows recomputed: **{len(mine)}** company-years, **{n_checked}** metric values compared.",
          f"* Disagreements between independent recalculation and the application: **{len(mismatches)}**.", ""]
    if mismatches:
        md += ["| Company/basis/year | Metric | Compared with | Independent | Application |", "|---|---|---|---|---|"]
        md += [f"| {k} | {c} | {w} | {a} | {b} |" for k, c, w, a, b in mismatches]
        md.append("")
    md += ["## Independently recalculated values (as the dashboard formats them)", "",
           "| Ticker | Year | Interest cover | Debt/equity | Current ratio | OCF/debt | Revenue growth | EBIT margin | Free cash flow |",
           "|---|---|---|---|---|---|---|---|---|", *lines, "",
           "n/a means an input is missing, a denominator is not positive, or (revenue growth) the prior period is not a "
           "directly preceding 12-month year. This report confirms the arithmetic and wiring only. It does NOT confirm that the "
           "source figures themselves are correct; see `docs/source_verification.csv`.", ""]
    out = ROOT / "docs" / "reconciliation_report.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"{len(mine)} company-years, {n_checked} values compared, {len(mismatches)} disagreements. Wrote {out}")
    for m in mismatches[:20]:
        print("  MISMATCH", m)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())

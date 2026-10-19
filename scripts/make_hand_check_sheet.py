#!/usr/bin/env python3
"""Write data/processed/hand_check_sheet.csv: a worksheet for verifying ratios by hand.

For each company, the latest year with enough data is listed with every input the tool used
and the ratio it computed. Fill `hand_value` from the annual report (and the page in
`source_page`), then set `match` to Y or N. Nothing here verifies anything by itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from btb import config  # noqa: E402
from btb.db import connect, load_fin  # noqa: E402
from btb.metrics import RATIO_COLUMNS, RATIO_DEFINITIONS, compute_metrics  # noqa: E402

INPUTS = ["revenue_cr", "ebit_cr", "interest_expense_cr", "total_debt_cr", "total_equity_cr",
          "current_assets_cr", "current_liabilities_cr", "operating_cash_flow_cr"]


def main() -> int:
    conn = connect()
    try:
        m = compute_metrics(load_fin(conn))
    finally:
        conn.close()
    m = m[(m["is_illustrative"] == 0) & (m["period_months"] == 12)]
    rows = []
    for ticker, g in m.groupby("ticker"):
        g = g.sort_values("fy_start")
        for _, r in g.tail(2).iterrows():          # latest two 12-month years per company
            for ratio in RATIO_COLUMNS:
                rows.append({"ticker": ticker, "financial_year": r["financial_year"], "ratio": ratio,
                             "definition": RATIO_DEFINITIONS[ratio],
                             "inputs_used": "; ".join(f"{c}={r[c]:,.2f}" for c in INPUTS if pd.notna(r[c])),
                             "tool_value": None if pd.isna(r[ratio]) else round(float(r[ratio]), 6),
                             "hand_value": "", "match_Y_or_N": "", "source_page": "", "checked_by": "", "notes": ""})
    out = config.PROCESSED_DIR / "hand_check_sheet.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote {out} ({len(rows)} rows to verify)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

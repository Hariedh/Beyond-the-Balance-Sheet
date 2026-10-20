#!/usr/bin/env python3
"""Build data/raw/financials_real.csv from the figures transcribed below.

WHY THIS SCRIPT EXISTS
  Every number is written down here exactly as read from its public source, so you can
  audit the transcription line by line. The script converts units, derives EBIT, runs
  cross-source consistency checks and writes the CSV the pipeline loads.

SOURCES (secondary aggregators; collected 19 Oct 2026; NOT yet hand-checked against annual reports)
  A) Screener.in, consolidated, Rs crore: sales, operating profit, other income, interest,
     depreciation, profit before tax, equity capital, reserves, borrowings, cash from operations.
  B) stockanalysis.com (S&P data), Rs million: total current assets, total current liabilities,
     total debt, operating cash flow (balance-sheet pages cover only FY2022 to FY2026).
  Spot-checks against primary filings (see PRIMARY_CHECKS) were done for UltraTech FY2021-22 and
  FY2022-23 (audited results, 28 Apr 2023) and Ambuja's 15-month period (board release, 2 May 2023).

DEFINITIONS USED (identical for every company)
  EBIT            = operating profit - depreciation        (other income and exceptional items excluded; verified
                    against filings for the years in source_verification.csv)
  interest        = finance costs as shown by Screener
  total debt      = Screener "Borrowings" (agrees with S&P total debt; appears to include leases)
  total equity    = equity capital + reserves              (owners' equity; excludes non-controlling interests)
  current assets / liabilities = S&P via stockanalysis.com (not available for FY2020-21)
  cash            = left blank (aggregator definitions are inconsistent: e.g. Ambuja ~Rs 11,530 cr per
                    its earnings call vs ~Rs 544 cr in the aggregator line)

CHECKS (the script aborts on any unexpected failure)
  1. profit-before-tax identity: operating profit + other income - depreciation - interest = reported PBT (+/- 2)
  2. Screener borrowings vs S&P total debt (+/- 0.5% or 2 cr)
  3. Screener operating cash flow vs S&P (+/- 1% or 2 cr). If they disagree, the value is left BLANK.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "financials_real.csv"
CHECKS_OUT = OUT.with_name("financials_real_crosschecks.csv")

# Screener rows: FY -> (period_months, sales, op_profit, other_income, interest, depreciation, pbt,
#                       equity_capital, reserves, borrowings, cash_from_operations)   [Rs crore]
SCREENER = {
    "ULTRACEMCO": ("https://www.screener.in/company/ULTRACEMCO/consolidated/", {
        "FY2020-21": (12, 44726, 11568, 619, 1486, 2700, None, 289, 43886, 21719, 12500),
        "FY2021-22": (12, 52599, 11514, 669, 945, 2715, None, 289, 50147, 11299, 9283),
        "FY2022-23": (12, 63240, 10620, 507, 823, 2888, None, 289, 54036, 11058, 9069),
        "FY2023-24": (12, 70908, 12979, 557, 968, 3145, None, 289, 59939, 11403, 10898),
        "FY2024-25": (12, 75955, 12547, 647, 1651, 4015, None, 295, 70412, 24102, 10673),
        "FY2025-26": (12, 88512, 17004, 439, 1872, 4644, None, 295, 76329, 23755, 15316),
    }),
    "AMBUJACEM": ("https://www.screener.in/company/AMBUJACEM/consolidated/", {
        "FY2022-23": (15, 38937, 5122, 447, 195, 1645, 3729, 397, 31301, 523, 735),
        "FY2023-24": (12, 33160, 6400, 1401, 276, 1628, 5896, 440, 41012, 699, 5646),
        "FY2024-25": (12, 35336, 5971, 2646, 216, 2297, 6104, 493, 53086, 788, 2237),
        "FY2025-26": (12, 40656, 6577, 516, 224, 3570, 3299, 494, 58853, 866, 5362),
    }),
    "SHREECEM": ("https://www.screener.in/company/SHREECEM/consolidated/", {
        "FY2020-21": (12, 13560, 4091, 426, 251, 1262, 3004, 36, 15361, 2230, 4254),
        "FY2021-22": (12, 15010, 3710, 544, 216, 1146, 2892, 36, 17424, 2129, 2668),
        "FY2022-23": (12, 17852, 2960, 459, 263, 1661, 1495, 36, 18600, 2725, 2569),
        "FY2023-24": (12, 20404, 4517, 598, 258, 1897, 2959, 36, 20667, 1656, 3347),
        "FY2024-25": (12, 19283, 3934, 589, 205, 3007, 1312, 36, 21502, 1046, 4920),
        "FY2025-26": (12, 20943, 4638, 661, 212, 2794, 2293, 36, 23231, 1868, 3794),
    }),
    "DALBHARAT": ("https://www.screener.in/company/DALBHARAT/consolidated/", {
        "FY2020-21": (12, 10110, 2770, 145, 303, 1250, 1362, 37, 12773, 3839, 3604),
        "FY2021-22": (12, 11286, 2426, 171, 202, 1235, 1160, 37, 16024, 3176, 1932),
        "FY2022-23": (12, 13552, 2328, 532, 234, 1305, 1321, 37, 15591, 3855, 2252),
        "FY2023-24": (12, 14691, 2639, 314, 386, 1498, 1069, 38, 16359, 4805, 2635),
        "FY2024-25": (12, 13980, 2407, 140, 399, 1331, 817, 38, 17336, 5702, 2117),
        "FY2025-26": (12, 14804, 3083, 195, 480, 1349, 1449, 38, 17941, 7406, 2278),
    }),
    "ACC": ("https://www.screener.in/company/ACC/consolidated/", {
        "FY2022-23": (15, 22210, 1925, 196, 77, 841, 1203, 188, 13950, 153, -1235),
        "FY2023-24": (12, 19959, 3062, 735, 155, 885, 2757, 188, 16140, 355, 2995),
        "FY2024-25": (12, 21762, 3061, 1175, 108, 1001, 3127, 188, 18367, 430, 1711),
        "FY2025-26": (12, 25962, 2958, 429, 112, 1118, 2157, 188, 20363, 429, -1364),
    }),
}

# stockanalysis.com rows: FY -> (current_assets, current_liabilities, total_debt, operating_cash_flow, revenue|None)  [Rs million]
STOCKANALYSIS = {
    "ULTRACEMCO": ("https://stockanalysis.com/quote/bom/532538/financials/balance-sheet/", {
        "FY2021-22": (174799, 201552, 112988, 92832, 525988),
        "FY2022-23": (207249, 234318, 110577, 90685, 632400),
        "FY2023-24": (231584, 269060, 114030, 108975, 709081),
        "FY2024-25": (237372, 323650, 241022, 106734, 759551),
        "FY2025-26": (252474, 338317, 237551, 153159, 885115),
    }),
    "AMBUJACEM": ("https://stockanalysis.com/quote/bom/500425/financials/balance-sheet/", {
        "FY2022-23": (192494, 115137, 5227, 5879, None),
        "FY2023-24": (239882, 121289, 6990, 56458, None),
        "FY2024-25": (194427, 138453, 7885, 22374, None),
        "FY2025-26": (137159, 130962, 8659, 53615, None),
    }),
    "SHREECEM": ("https://stockanalysis.com/quote/bom/500387/financials/balance-sheet/", {
        "FY2021-22": (84703, 46864, 21292, 26680, None),
        "FY2022-23": (89679, 67321, 27247, 25687, None),
        "FY2023-24": (122122, 61278, 16556, 33475, None),
        "FY2024-25": (121024, 57561, 10461, 49203, None),
        "FY2025-26": (151025, 69893, 18681, 37941, None),
    }),
    "DALBHARAT": ("https://stockanalysis.com/quote/bom/542216/financials/balance-sheet/", {
        "FY2021-22": (75120, 46660, 31760, 19320, None),
        "FY2022-23": (73500, 44600, 38550, 22520, None),
        "FY2023-24": (78300, 44740, 48050, 26350, None),
        "FY2024-25": (83140, 52230, 57020, 21170, None),
        "FY2025-26": (87630, 56740, 74280, 22780, None),
    }),
    "ACC": ("https://stockanalysis.com/quote/bom/500410/financials/balance-sheet/", {
        "FY2022-23": (82552, 56410, 1530, -9881, None),
        "FY2023-24": (97261, 60968, 3549, 29951, None),
        "FY2024-25": (91443, 56682, 4298, 17115, None),
        "FY2025-26": (113729, 57615, 4286, -13640, None),
    }),
}

# Spot checks against PRIMARY filings (company-audited), Rs crore as printed.
# UltraTech audited consolidated results for year ended 31 Mar 2023 (filed 28 Apr 2023).
PRIMARY_CHECKS = {
    ("ULTRACEMCO", "FY2022-23"): {"sales": 63239.98, "interest": 822.72, "depreciation": 2887.99,
                                  "current_liabilities": 23431.79},
    ("ULTRACEMCO", "FY2021-22"): {"sales": 52598.83, "interest": 944.71, "depreciation": 2714.75,
                                  "current_liabilities": 20155.19, "current_assets": 17478.94, "ocf": 9283.24},
    ("AMBUJACEM", "FY2022-23"): {"sales": 38937.0},   # board release 2 May 2023: 'Net Revenue Rs 38,937 Cr', 15 months
}
PRIMARY_NOTES = {
    ("ULTRACEMCO", "FY2022-23"): "Spot-checked to the company's audited results (28 Apr 2023): revenue, finance costs, "
                                 "depreciation and current liabilities match to rounding.",
    ("ULTRACEMCO", "FY2021-22"): "Spot-checked to the audited results (28 Apr 2023, comparative column): revenue, finance "
                                 "costs, depreciation, current assets, current liabilities and operating cash flow match to rounding.",
    ("AMBUJACEM", "FY2022-23"): "Revenue matches the company's board release of 2 May 2023.",
}

# Corrections supported by a primary filing. Applied ONLY where the filing is like-for-like with the metric
# definition; every change is written to data/raw/corrections_log.csv (original value kept).
CORRECTIONS = {
    ("AMBUJACEM", "FY2025-26", "ebit"): dict(
        revised=2968.53,
        source=("Ambuja Cements audited consolidated results FY2025-26, NSE iXBRL filing 04-May-2026 "
                "(revenue 40,655.68; total expenses 37,910.76; finance costs 223.61 => EBIT 2,968.53) and the company media "
                "release of 04-May-2026 (operating EBITDA Rs 6,539 cr = 2,968.53 + depreciation 3,570.41)"),
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_155484_04052026201158_iXBRL_WEB.html",
        reason=("Screener operating profit (6,577) is about 38 cr above the company's own operating EBITDA (6,539); "
                "the filing-derived EBIT matches the project's EBIT definition. Cause of the aggregator difference not established."),
    ),
}
CORRECTIONS_OUT = OUT.with_name("corrections_log.csv")

COMPANY_NOTES = {
    "ULTRACEMCO": "Acquisitions around FY2024-25 may affect comparability and the step-up in debt/interest: verify in the annual report.",
    "AMBUJACEM": "Year-end changed from December to March; the Dec-2020 and Dec-2021 calendar-year periods are not loaded "
                 "(not expressible as March FYs). Ownership/scope changes (Adani group, ACC, later acquisitions): verify consolidation scope.",
    "ACC": "Year-end changed from December to March; the Dec-2020 and Dec-2021 calendar-year periods are not loaded. "
           "Ownership/scope changes: verify consolidation scope.",
    "SHREECEM": "",
    "DALBHARAT": "Equity rises sharply in FY2021-22: check for restructuring or reclassification in the annual report.",
}

# Capital expenditure, stockanalysis.com cash-flow statement line "Capital Expenditures" (S&P data),
# Rs million, shown there as a negative outflow; stored here as a positive outflow.
# Page covers FY2021-22 to FY2025-26 only. NOT loaded for Ambuja/ACC FY2022-23: that 15-month period's
# cash-flow figures from the two sources disagree, so capex for it is left blank as well.
CAPEX_MN = {
    "ULTRACEMCO": {"FY2021-22": 56134, "FY2022-23": 62001, "FY2023-24": 90056, "FY2024-25": 91293, "FY2025-26": 96778},
    "AMBUJACEM": {"FY2023-24": 44825, "FY2024-25": 86871, "FY2025-26": 63443},
    "SHREECEM": {"FY2021-22": 22158, "FY2022-23": 32914, "FY2023-24": 31403, "FY2024-25": 40934, "FY2025-26": 18656},
    "DALBHARAT": {"FY2021-22": 17690, "FY2022-23": 27090, "FY2023-24": 28270, "FY2024-25": 26640, "FY2025-26": 20560},
    "ACC": {"FY2023-24": 13948, "FY2024-25": 19684, "FY2025-26": 14272},
}
CAPEX_NOTE = ("Capex = S&P 'Capital Expenditures' line (secondary source), recorded as a positive outflow. Checked against the "
              "filing's cash-flow statement only where data/raw/source_verification.csv has a capex row; otherwise unverified. "
              "Free cash flow = operating cash flow - capex.")

DEFINITIONS = (
    "EBIT = revenue - (total expenses - finance costs) = operating profit after depreciation, before other income and "
    "exceptional items (verified against filings for the checked years). Interest = finance costs (Screener). "
    "Total debt = Screener borrowings (matches S&P total debt; appears to include lease liabilities). "
    "Total equity = equity capital + reserves (owners' equity, excludes non-controlling interests). "
    "Current assets/liabilities from S&P via stockanalysis.com. Cash left blank (inconsistent aggregator definitions)."
)
SOURCE = ("Screener.in consolidated financials (P&L, borrowings, equity, cash flow) + stockanalysis.com/S&P "
          "(current assets and liabilities). Secondary sources, collected 19 Oct 2026; not yet hand-checked "
          "against annual reports unless stated in notes.")

HEADER = ["ticker", "financial_year", "basis", "unit", "period_months", "revenue", "ebit", "interest_expense",
          "total_debt", "total_equity", "current_assets", "current_liabilities", "operating_cash_flow",
          "cash_and_equivalents", "capex", "definitions_note", "source", "source_url", "notes", "is_illustrative"]


def close(a: float, b: float, rel: float, absolute: float) -> bool:
    return abs(a - b) <= max(absolute, rel * max(abs(a), abs(b)))


def fmt(x):
    return "" if x is None else (f"{x:.2f}".rstrip("0").rstrip("."))


def main() -> int:
    rows, failures, report = [], [], []
    corrections_log: list = []
    for ticker, (s_url, s_rows) in SCREENER.items():
        sa_url, sa_rows = STOCKANALYSIS[ticker]
        for fy, (months, sales, op, oi, interest, dep, pbt, eq_cap, reserves, borrow, cfo) in s_rows.items():
            notes = []
            if COMPANY_NOTES.get(ticker):
                notes.append(COMPANY_NOTES[ticker])
            sa = sa_rows.get(fy)
            ca = cl = None
            ocf = cfo

            # 1) PBT identity
            if pbt is not None:
                diff = op + oi - dep - interest - pbt
                ok = abs(diff) <= 2
                report.append((ticker, fy, "PBT identity", ok, f"diff {diff:+.0f}"))
                if not ok:
                    failures.append((ticker, fy, "PBT identity", diff))

            if sa:
                ca, cl = sa[0] / 10, sa[1] / 10
                # 2) debt
                ok = close(borrow, sa[2] / 10, 0.005, 2)
                report.append((ticker, fy, "borrowings vs S&P debt", ok, f"{borrow} vs {sa[2] / 10:.0f}"))
                if not ok:
                    failures.append((ticker, fy, "debt", (borrow, sa[2] / 10)))
                # 3) OCF
                ok = close(cfo, sa[3] / 10, 0.01, 2)
                report.append((ticker, fy, "OCF vs S&P", ok, f"{cfo} vs {sa[3] / 10:.0f}"))
                if not ok:
                    notes.append(f"Operating cash flow left blank: sources disagree (Screener {cfo:,.0f} vs S&P {sa[3] / 10:,.0f} Rs cr).")
                    ocf = None
                if sa[4] is not None:
                    ok = close(sales, sa[4] / 10, 0.002, 2)
                    report.append((ticker, fy, "revenue vs S&P", ok, f"{sales} vs {sa[4] / 10:.0f}"))
                    if not ok:
                        failures.append((ticker, fy, "revenue", (sales, sa[4] / 10)))
            else:
                notes.append("Current assets and current liabilities not available from the sources used: left blank, "
                             "so the current ratio is n/a for this year.")

            # primary-source spot checks
            prim = PRIMARY_CHECKS.get((ticker, fy))
            if prim:
                pairs = {"sales": sales, "interest": interest, "depreciation": dep,
                         "current_liabilities": cl, "current_assets": ca, "ocf": cfo}
                for k, printed in prim.items():
                    mine = pairs[k]
                    ok = mine is not None and close(mine, printed, 0.001, 1.5)
                    report.append((ticker, fy, f"PRIMARY {k}", ok, f"{mine} vs printed {printed}"))
                    if not ok:
                        failures.append((ticker, fy, f"primary {k}", (mine, printed)))
                notes.append(PRIMARY_NOTES[(ticker, fy)])
            if months != 12:
                notes.append(f"{months}-month reporting period (Jan 2022 to Mar 2023) after the year-end change; "
                             "confirmed in the company's board release of 2 May 2023. Not comparable with 12-month years.")

            capex_mn = CAPEX_MN.get(ticker, {}).get(fy)
            capex = capex_mn / 10 if capex_mn is not None else None
            if capex is not None:
                notes.append(CAPEX_NOTE)
            ebit_val = op - dep
            corr = CORRECTIONS.get((ticker, fy, "ebit"))
            if corr:
                corrections_log.append([ticker, fy, "consolidated", "ebit", ebit_val, corr["revised"], corr["source"],
                                        corr["url"], corr["reason"], "2026-10-20", "corrected: primary filing like-for-like"])
                notes.append(f"EBIT corrected from {ebit_val:,.0f} (aggregator-derived) to {corr['revised']:,.2f} using the audited filing; see corrections_log.csv.")
                ebit_val = corr["revised"]
            rows.append([ticker, fy, "consolidated", "crores", months, fmt(sales), fmt(ebit_val), fmt(interest),
                         fmt(borrow), fmt(eq_cap + reserves), fmt(ca), fmt(cl), fmt(ocf), "", fmt(capex),
                         DEFINITIONS, SOURCE, f"{s_url}; {sa_url}" if sa else s_url, " ".join(notes), 0])

    print(f"{'ticker':11s}{'year':11s}{'check':26s}{'ok':5s}detail")
    for t, fy, name, ok, detail in report:
        if not ok or "PRIMARY" in name:
            print(f"{t:11s}{fy:11s}{name:26s}{'OK' if ok else 'FAIL':5s}{detail}")
    n_ok = sum(r[3] for r in report)
    print(f"\n{n_ok}/{len(report)} automated cross-checks passed; {len(rows)} rows built.")
    if failures:
        print("\nUNEXPECTED FAILURES (nothing written):")
        for f in failures:
            print("  ", f)
        return 1

    rows.sort(key=lambda r: (r[0], r[1]))
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    print(f"Wrote {OUT}")
    with open(CORRECTIONS_OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "financial_year", "basis", "field", "original_value_cr", "revised_value_cr", "source",
                    "source_url", "reason", "date_checked", "status"])
        w.writerows(corrections_log)
    print(f"Wrote {CORRECTIONS_OUT} ({len(corrections_log)} correction(s))")
    # Machine-readable record of every automated check, shown in the dashboard's verification panel.
    with open(CHECKS_OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "financial_year", "check", "passed", "detail", "against_primary_filing"])
        for t, fy, name, ok, detail in report:
            w.writerow([t, fy, name, int(ok), detail, int(name.startswith("PRIMARY"))])
    print(f"Wrote {CHECKS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

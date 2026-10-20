#!/usr/bin/env python3
"""Build data/raw/source_verification.csv: loaded values vs. primary filings.

Every `FILING` value below was read from the company's own results filing (audited consolidated
statements) and is written down here exactly so it can be audited line by line. The script
compares each with the value in data/raw/financials_real.csv and assigns a status:

  verified     |difference| <= max(1.5 crore, 0.1% of the filing value)
  approx       difference within 1%
  discrepancy  difference above 1%  (NOT resolved here; the loaded value is NOT changed)
  unverified   the filing figure is not like-for-like (e.g. lease liabilities not located)

HOW THE FILING VALUES WERE OBTAINED (be honest about this in interviews)
  The filing text was retrieved and read with an automated page-text extraction tool, not
  inspected visually in a PDF viewer. Page numbers are given only where the extracted text
  showed them; otherwise the statement/section is named. Treat 'verified' as "matches the text
  of the filing as extracted" and re-check the PDF page before quoting a figure externally.

EBIT is not a statutory line. The filing-derived EBIT used here is
      revenue from operations - (total expenses - finance costs)
  i.e. operating profit after depreciation, BEFORE other income and BEFORE exceptional items,
  which is how the loaded EBIT is defined (Screener operating profit - depreciation).
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIN = ROOT / "data" / "raw" / "financials_real.csv"
OUT = ROOT / "data" / "raw" / "source_verification.csv"

# Depreciation actually used in the loaded EBIT (Screener) lives in the build script.
spec = importlib.util.spec_from_file_location("bld", ROOT / "scripts" / "build_real_financials.py")
bld = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bld)

CHECKED_ON = "2026-10-20"
METHOD = "filing text read via automated extraction; not visually checked in a PDF viewer"

# (ticker, FY) -> document facts
DOCS = {
    ("ULTRACEMCO", "FY2024-25"): dict(
        doc="UltraTech Cement integrated results filing (Ind-AS, consolidated, audited), NSE archives",
        date="2025-04-28 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Assets and Liabilities; Cash flow statement (year column)",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_87601_28042025202714_iXBRL_WEB.html"),
    ("DALBHARAT", "FY2024-25"): dict(
        doc="Dalmia Bharat outcome of board meeting with audited consolidated results (PDF)",
        date="2025-04-23 (from NSE filing listing)",
        where="Consolidated Statement of Results; Statement of Assets and Liabilities; Statement of Cash Flows (page numbers not shown in extracted text)",
        url="https://www.dalmiacement.com/uploads/financial-results/2024-25/quarterlyFinancialResults/outcomeofbmApril25.pdf"),
    ("ACC", "FY2024-25"): dict(
        doc="ACC integrated results filing (Ind-AS, consolidated, audited), NSE archives",
        date="2025-04-25 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Assets and Liabilities; Cash flow statement (year column)",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_86759_25042025134520_iXBRL_WEB.html"),
    ("SHREECEM", "FY2025-26"): dict(
        doc="Shree Cement integrated results filing (Ind-AS, consolidated, audited), NSE archives",
        date="2026-05-06 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Asset and Liabilities; Cash flow statement (year column)",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_155879_06052026195712_iXBRL_WEB.html"),
    ("SHREECEM", "FY2024-25"): dict(
        doc="Shree Cement stock-exchange filing: audited consolidated results for the year ended 31 March 2025 (PDF)",
        date="2025-05-14 (stated in the document)",
        where="Consolidated Statement of Audited Financial Results, p. 1",
        url="https://www.shreecement.com/uploads/investors/shareholder/March_2025.pdf"),
    ("DALBHARAT", "FY2023-24"): dict(
        doc="Dalmia Bharat outcome of board meeting April 2025 (PDF): FY2023-24 COMPARATIVE column of the audited consolidated results",
        date="2025-04-23 (from NSE filing listing); comparative column, figures as presented a year later",
        where="Consolidated Statement of Results / Assets and Liabilities / Cash Flows, comparative year column (page numbers not shown in extracted text)",
        url="https://www.dalmiacement.com/uploads/financial-results/2024-25/quarterlyFinancialResults/outcomeofbmApril25.pdf"),
    ("SHREECEM", "FY2023-24"): dict(
        doc="Shree Cement audited consolidated results year ended 31 March 2025 (PDF): FY2023-24 COMPARATIVE column",
        date="2025-05-14 (stated in the document); comparative column, figures as presented a year later",
        where="Consolidated results, balance sheet and cash flow, comparative year column (page numbers not shown in extracted text)",
        url="https://www.shreecement.com/uploads/investors/shareholder/March_2025.pdf"),
    ("ULTRACEMCO", "FY2025-26"): dict(
        doc="UltraTech Cement outcome of board meeting: audited consolidated results FY2025-26 incl. FY2024-25 comparative (PDF), NSE archives",
        date="2026-04-27 (from filing timestamp in URL)",
        where="Consolidated results p.1/5; balance sheet p.2/5; cash flow p.3/5 (page markers as extracted)",
        url="https://nsearchives.nseindia.com/corporate/ULTRACEMCO1_27042026142549_Outcome_of_BM_Results.pdf"),
    ("ACC", "FY2025-26"): dict(
        doc="ACC integrated results filing (Ind-AS, consolidated, audited), NSE archives",
        date="2026-04-30 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Assets and Liabilities; Cash flow statement (year column); amounts in lakh converted to crore",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_155102_30042026214733_iXBRL_WEB.html"),
    ("DALBHARAT", "FY2025-26"): dict(
        doc="Dalmia Bharat integrated results filing (Ind-AS, consolidated, audited), NSE archives",
        date="2026-04-28 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Assets and Liabilities; Cash flow statement (year column); amounts in lakh (rounded to hundreds) converted to crore",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_153591_28042026161720_iXBRL_WEB.html"),
    ("AMBUJACEM", "FY2025-26"): dict(
        doc="Ambuja Cements integrated results filing (Ind-AS, consolidated, audited), NSE archives",
        date="2026-05-04 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Assets and Liabilities; Cash flow statement (year column)",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_155484_04052026201158_iXBRL_WEB.html"),
    ("AMBUJACEM", "FY2024-25"): dict(
        doc="Ambuja Cements integrated results filing (Ind-AS, consolidated, audited), NSE archives (original FY2024-25 filing)",
        date="2025-04-29 (from filing timestamp in URL)",
        where="Financial Results Part I; Statement of Assets and Liabilities; Cash flow statement (year column)",
        url="https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_88271_29042025195000_iXBRL_WEB.html"),
}

# Filing values in Rs crore. total_expenses / other_income are used only to derive EBIT.
FILING = {
    ("ULTRACEMCO", "FY2024-25"): dict(revenue=75955.13, total_expenses=69063.17, finance=1650.54, dep=4014.95,
        share_cap=294.68, other_equity=70412.09, nci=3186.59, ca=23599.51, cl=32364.97, ocf=10673.43, capex=9129.33,
        borrowings=15780.77 + 7250.22, leases=868.21 + 202.98, exceptional=-97.43, other_income=744.17),
    ("ULTRACEMCO", "FY2025-26"): dict(revenue=88511.53, total_expenses=78007.47, finance=1871.71, dep=4644.46,
        share_cap=294.68, other_equity=76328.86, nci=4088.90, ca=25101.75, cl=33831.70, ocf=15315.86, capex=9677.77,
        borrowings=15018.82 + 7761.84, leases=751.72 + 222.71, exceptional=-138.55, other_income=577.51),
    ("ACC", "FY2025-26"): dict(revenue=25961.85, total_expenses=24242.04, finance=112.05, dep=1118.34,
        share_cap=187.99, other_equity=20362.55, nci=3.95, ca=11372.89, cl=5761.52, ocf=-1357.75, capex=1433.42,
        borrowings=0.0, leases=None, exceptional=27.95, other_income=401.94),
    ("DALBHARAT", "FY2023-24"): dict(revenue=14691, total_expenses=13936, finance=386, dep=1498,
        share_cap=38, other_equity=16359, ca=7830, cl=4474, ocf=2635, capex=2827, exceptional=0.0, other_income=315),
    ("SHREECEM", "FY2023-24"): dict(revenue=20403.80, total_expenses=18042.72, finance=258.34, dep=1897.32,
        share_cap=36.08, other_equity=20666.84, ca=12212.21, cl=6127.83, ocf=3347.49, capex=3140.30,
        borrowings=713.08 + 761.84, leases=141.65 + 38.98, exceptional=0.0, other_income=598.12),
    ("DALBHARAT", "FY2025-26"): dict(revenue=14804, total_expenses=13550, finance=480, dep=1349,
        share_cap=38, other_equity=17941, nci=144, ca=8763, cl=5674, ocf=2278, capex=2056,
        borrowings=6168 + 584, leases=591 + 63, exceptional=-26, other_income=222),
    ("DALBHARAT", "FY2024-25"): dict(revenue=13980, total_expenses=13303, finance=399, dep=1331,
        share_cap=38, other_equity=17336, nci=126, ca=8314, cl=5223, ocf=2117, capex=2664,
        borrowings=4605 + 653, leases=395 + 49, exceptional=-113, other_income=253),
    ("ACC", "FY2024-25"): dict(revenue=21762.31, total_expenses=19810.48, finance=108.22, dep=1001.31,
        share_cap=187.99, other_equity=18366.85, nci=3.79, ca=9137.65, cl=5668.15, ocf=1711.48, capex=1968.44,
        borrowings=0.0, leases=None, exceptional=99.73, other_income=1072.43),
    ("SHREECEM", "FY2025-26"): dict(revenue=20943.47, total_expenses=19311.29, finance=211.72, dep=2793.96,
        share_cap=36.08, other_equity=23231.45, nci=46.58, ca=15102.49, cl=6989.28, ocf=3794.07, capex=1865.59,
        borrowings=728.88 + 864.84, leases=None, exceptional=0.0, other_income=660.83),
    ("SHREECEM", "FY2024-25"): dict(revenue=19282.83, finance=204.96, dep=3006.78),
    ("AMBUJACEM", "FY2025-26"): dict(revenue=40655.68, total_expenses=37910.76, finance=223.61, dep=3570.41,
        share_cap=494.36, other_equity=58852.96, nci=12498.92, ca=13715.93, cl=13096.24, ocf=5361.53, capex=6344.33,
        borrowings=44.79 + 7.99, leases=None, exceptional=-300.54, other_income=834.34),
    ("AMBUJACEM", "FY2024-25"): dict(revenue=35044.76, finance=215.94, dep=2478.34,
        share_cap=492.62, other_equity=52950.63, ca=19710.38, cl=13845.26, ocf=3295.17, capex=8687.05),
}

NOTES = {
    ("AMBUJACEM", "FY2025-26", "ebit"): "Loaded EBIT was 3,007 (aggregator-derived); corrected to the filing-derived figure (see corrections_log.csv). Matches the company's operating EBITDA of Rs 6,539 cr less depreciation.",
    ("AMBUJACEM", "FY2024-25", "operating_cash_flow"): "UNRESOLVED. Loaded 2,237 vs ORIGINAL filing 3,295.17 (loaded is 32% below the filing, filing is 47% above loaded). Ambuja's FY2025-26 annual report marks its 2024-25 figures 'Restated, refer Note 68(h)', and the loaded revenue and EBITDA equal those restated comparatives, so the loaded series is probably the restated one. The restated cash-flow figure itself was not obtained, so this remains unresolved; treat FY2024-25 cash-flow ratios as provisional.",
    ("AMBUJACEM", "FY2024-25", "current_assets"): "UNRESOLVED. Original filing vs loaded series; see operating cash flow note (probable restatement, not confirmed).",
    ("AMBUJACEM", "FY2024-25", "depreciation"): "UNRESOLVED. Loaded depreciation 2,297 vs original filing 2,478.34; probable restatement (see operating cash flow note), restated figure not obtained.",
    ("AMBUJACEM", "FY2024-25", "revenue"): "Not like-for-like with the ORIGINAL filing: the loaded 35,336 equals the restated 2024-25 revenue in Ambuja's FY2025-26 annual report (Financial Highlights, 'Restated, refer Note 68(h)') and media release; see the restated-revenue row.",
}
NOTES[("SHREECEM", "FY2023-24", "capex")] = "Figure read from a column-aligned table that was partly garbled in the extracted text; re-check the PDF page before quoting."
NOTES[("DALBHARAT", "FY2023-24", "capex")] = "Comparative column. Debt not compared: the current-borrowings figure was unreadable in the extracted text."
STATUS_OVERRIDES = {("AMBUJACEM", "FY2024-25", "revenue"): "unverified"}
AMBUJA_RELEASE = dict(
    doc="Ambuja Cements media release for FY2025-26 results (FY2025-26 vs FY2024-25 consolidated comparatives), NSE archives",
    date="2026-05-04 (from filing timestamp in URL)",
    where="Results summary table: Revenue from Operations and Operating EBITDA, FY26 vs FY25 columns (no page number shown in extracted text)",
    url="https://nsearchives.nseindia.com/corporate/AMBUJACEM_04052026141805_ACL_Media_Release2.pdf")
DEBT_NOTE = ("Filing borrowings only: lease liabilities were not located in the extracted statements, while the loaded debt "
             "(aggregator borrowings) appears to include them. Not like-for-like, so left unverified.")


def status(app, filing):
    d = abs(app - filing)
    if d <= max(1.5, 0.001 * abs(filing)):
        return "verified"
    return "approx" if d <= 0.01 * abs(filing) else "discrepancy"


def main() -> int:
    loaded = {(r["ticker"], r["financial_year"]): r for r in csv.DictReader(open(FIN, encoding="utf-8"))}
    dep_used = {(t, fy): v[5] for t, (_u, rows) in bld.SCREENER.items() for fy, v in rows.items()}
    out = []
    for key, f in FILING.items():
        app = loaded[key]
        d = DOCS[key]

        def add(item, app_val, filing_val, st=None, note=""):
            if app_val in (None, "") or filing_val is None:
                return
            app_val, filing_val = float(app_val), float(filing_val)
            diff = app_val - filing_val
            out.append([key[0], key[1], "consolidated", item, round(app_val, 2), round(filing_val, 2), round(diff, 2),
                        round(100 * diff / filing_val, 3) if filing_val else "", st or status(app_val, filing_val),
                        METHOD, d["doc"], d["date"], d["where"], d["url"],
                        note or NOTES.get((key[0], key[1], item), "")])

        add("revenue", app["revenue"], f.get("revenue"))
        add("interest_expense", app["interest_expense"], f.get("finance"))
        add("depreciation", dep_used.get(key), f.get("dep"))
        if "total_expenses" in f:
            add("ebit", app["ebit"], f["revenue"] - f["total_expenses"] + f["finance"],
                note=NOTES.get((key[0], key[1], "ebit"), "Filing-derived EBIT = revenue - (total expenses - finance costs): before other income and exceptional items."))
        if "share_cap" in f:
            add("total_equity", app["total_equity"], f["share_cap"] + f["other_equity"],
                note="Equity share capital + other equity (excludes non-controlling interest of "
                     f"{f['nci']:,.2f} crore)." if "nci" in f else "")
        add("current_assets", app["current_assets"], f.get("ca"))
        add("current_liabilities", app["current_liabilities"], f.get("cl"))
        add("operating_cash_flow", app["operating_cash_flow"], f.get("ocf"))
        add("capex", app["capex"], f.get("capex"))
        if "borrowings" in f:
            if f.get("leases") is not None:
                add("total_debt", app["total_debt"], f["borrowings"] + f["leases"],
                    note="Borrowings + lease liabilities from the balance sheet: confirms the loaded debt includes leases.")
            else:
                add("total_debt", app["total_debt"], f["borrowings"], st="unverified", note=DEBT_NOTE)
    # Ambuja: loaded 2024-25 series vs the company's own restated comparatives (FY2025-26 media release, Rs crore)
    for fy, item, app_val, filing_val, note in (
        ("FY2024-25", "revenue_restated_comparative", float(loaded[("AMBUJACEM", "FY2024-25")]["revenue"]), 35336.0,
         "Matches the restated FY2024-25 comparative published with the FY2025-26 results; the original FY2024-25 filing shows 35,044.76."),
        ("FY2024-25", "operating_ebitda_restated_comparative",
         float(loaded[("AMBUJACEM", "FY2024-25")]["ebit"]) + dep_used[("AMBUJACEM", "FY2024-25")], 5971.0,
         "Loaded EBIT + depreciation equals the restated FY2024-25 operating EBITDA. The company states this includes one-time income of about Rs 826 cr (excise refund) and Rs 138 cr (GST incentive); EBIT and margin for this year are therefore flattered."),
        ("FY2025-26", "operating_ebitda", float(loaded[("AMBUJACEM", "FY2025-26")]["ebit"]) + dep_used[("AMBUJACEM", "FY2025-26")], 6539.0,
         "Loaded EBIT (after correction) + depreciation vs the company's operating EBITDA; the release rounds to whole crore."),
    ):
        diff = app_val - filing_val
        d = AMBUJA_RELEASE
        out.append(["AMBUJACEM", fy, "consolidated", item, round(app_val, 2), round(filing_val, 2), round(diff, 2),
                    round(100 * diff / filing_val, 3), status(app_val, filing_val), METHOD, d["doc"], d["date"], d["where"],
                    d["url"], note])
    for r in out:
        st_over = STATUS_OVERRIDES.get((r[0], r[1], r[3]))
        if st_over:
            r[8] = st_over
    for r in out:
        r.append(CHECKED_ON)
    out.sort(key=lambda r: (r[0], r[1], r[3]))
    header = ["ticker", "financial_year", "basis", "item", "app_value_cr", "filing_value_cr", "difference_cr", "difference_pct",
              "status", "method", "source_doc", "publication_date", "location", "source_url", "notes", "date_checked"]
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(out)
    counts = {}
    for r in out:
        counts[r[8]] = counts.get(r[8], 0) + 1
    print(f"Wrote {OUT} ({len(out)} comparisons): {counts}")
    for r in out:
        if r[8] in ("discrepancy", "approx", "unverified"):
            print(f"  {r[8]:11s} {r[0]:11s} {r[1]} {r[3]:20s} app {r[4]:>10} filing {r[5]:>10} diff {r[6]:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Beyond the Balance Sheet: Streamlit dashboard.

Run:  streamlit run app.py
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

try:  # optional: load ANTHROPIC_API_KEY etc. from .env
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from btb import ai_commentary as ai  # noqa: E402
from btb import config, llm  # noqa: E402
from btb.assessment import RULE_INFO, assess_year, explain_flags  # noqa: E402
from btb.db import connect, db_is_stale, load_fin, query_df  # noqa: E402
from btb.evidence import build_packet  # noqa: E402
from btb.flags import RULES, Thresholds, evaluate_flags, sensitivity_table  # noqa: E402
from btb.fmt import fmt_cr, fmt_pct, fmt_x  # noqa: E402
from btb.metrics import (PERCENT_RATIOS, RATIO_COLUMNS, RATIO_DEFINITIONS, RATIO_LABELS,  # noqa: E402
                         compute_metrics, context_notes, ratio_notes)
from btb.peers import (COMPARABILITY_NOTES, PEER_METRICS, peer_medians, peer_table,  # noqa: E402
                       same_universe, with_peer_metrics)
from btb.persistence import INDICATORS, persistence_table  # noqa: E402
from btb.pipeline import run_pipeline  # noqa: E402
from btb.report import build_report  # noqa: E402
from btb.stress import StressInputs, stress_table, stress_test  # noqa: E402
from btb.verification import summary as ver_summary  # noqa: E402
from btb.verification import verification_frame  # noqa: E402

st.set_page_config(page_title="Beyond the Balance Sheet", page_icon="\U0001F4CA", layout="wide")

TILE_LABEL = {"ocf_to_debt": "OCF / debt"}  # short label so it is not truncated in a narrow tile
LOWER_IS_WORSE = {"debt_to_equity": "inverse"}  # higher debt-to-equity is the adverse direction


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def ensure_db() -> None:
    """Build the database if it is missing, or rebuild it if the SQL or raw data are newer than it."""
    if db_is_stale():
        with st.spinner("Building database from data/raw/ ..."):
            run_pipeline()


@st.cache_data(show_spinner=False)
def load_all(db_mtime: float):
    conn = connect()
    try:
        fin = load_fin(conn)
        issues = query_df(conn, "SELECT * FROM validation_issues ORDER BY severity, ticker, financial_year")
        disc = query_df(conn, "SELECT d.*, c.ticker FROM disclosures d JOIN companies c USING (company_id) "
                              "ORDER BY c.ticker, d.financial_year")
        ext = query_df(conn, "SELECT * FROM external_indicators ORDER BY series_name, period")
        ver = verification_frame(conn)
    finally:
        conn.close()
    return fin, issues, disc, ext, ver


def fmt_ratio(col: str, v) -> str:
    return fmt_pct(v) if col in PERCENT_RATIOS else fmt_x(v)


@st.cache_data(show_spinner=False)
def load_crosschecks(mtime: float) -> pd.DataFrame:
    path = config.RAW_DIR / "financials_real_crosschecks.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def draw(ax, years, series: dict, title: str, ylabel: str, hline: tuple[float, str] | None = None, bars=None,
         annotate=None):
    """Missing values are NaN: bars are omitted and lines have gaps (never drawn as zero).
    `annotate` is an optional formatter that labels each point with its exact displayed value."""
    if bars:
        ax.bar(years, [v if pd.notna(v) else float("nan") for v in bars[1]], color="#c8d3e0", label=bars[0])
    for label, values in series.items():
        ax.plot(years, values, marker="o", linewidth=2, label=label)
        if annotate:
            for x, v in zip(years, values):
                if pd.notna(v):
                    ax.annotate(annotate(v), (x, v), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7)
    if hline:
        ax.axhline(hline[0], linestyle="--", color="#b3261e", linewidth=1)
        ax.text(0.01, hline[0], f" {hline[1]}", color="#b3261e", transform=ax.get_yaxis_transform(),
                va="bottom", fontsize=8)
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(axis="x", labelrotation=30, labelsize=8)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    if len(series) > 1 or bars:
        ax.legend(fontsize=8, frameon=False)


def show_df(data, **kwargs) -> None:
    """st.dataframe at full width on both new (width='stretch') and older (use_container_width) Streamlit."""
    try:
        st.dataframe(data, width="stretch", **kwargs)
    except TypeError:
        show_df(data, **kwargs)


def show_fig(fig) -> None:
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)



# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
ensure_db()
fin_all, issues_all, disc_all, ext_all, ver_all = load_all(config.DB_PATH.stat().st_mtime)

st.title("Beyond the Balance Sheet")
st.caption("An explainable financial-risk monitoring and stress-testing tool for Indian cement companies")
st.info(config.DISCLAIMER)

with st.expander("The question this tool answers, and how to use it", expanded=False):
    st.markdown(
        "**Which financial vulnerabilities are emerging in each company, how persistent are they, how do they compare with "
        "peers, and how sensitive are its metrics to adverse operating conditions?**\n\n"
        "Work through the sections in order:\n"
        "1. **Select** a company, reporting basis and years (sidebar), and check comparability.\n"
        "2. **Performance**: the key ratios and cash-flow figures.\n"
        "3. **Warnings**: which rules fired, why, how persistent they are, and what conflicts or is missing.\n"
        "4. **Trends and peers**: direction over time and comparison with like-for-like peers.\n"
        "5. **Stress test**: a transparent what-if (not a forecast).\n"
        "6. **Evidence and data quality**: filings, source checks and unresolved questions.\n"
        "7. **Summary and export**: a concise analyst report (CSV).\n\n"
        "No composite score is produced. A rule firing is a prompt to investigate; no rule firing does not mean low risk.")

if fin_all.empty:
    st.error("No financial data is loaded yet. Add rows to `data/raw/financials_real.csv` (or use the demo "
             "data) and run `python scripts/run_pipeline.py`.")
    st.stop()

# ---- sidebar controls -------------------------------------------------------
names = fin_all.drop_duplicates("ticker").set_index("ticker")[["name", "is_illustrative"]]
with st.sidebar:
    st.header("1. Select")
    ticker = st.selectbox(
        "Company", list(names.index),
        format_func=lambda t: f"{t}: {names.loc[t, 'name']}" + (" [illustrative]" if names.loc[t, "is_illustrative"] else ""),
    )
    bases = sorted(fin_all.loc[fin_all["ticker"] == ticker, "basis"].unique())
    basis = st.selectbox("Reporting basis", bases, index=bases.index("consolidated") if "consolidated" in bases else 0)

    all_years = sorted(fin_all.loc[(fin_all["ticker"] == ticker) & (fin_all["basis"] == basis), "financial_year"])
    if len(all_years) > 1:
        fy_from, fy_to = st.select_slider("Financial years", options=all_years, value=(all_years[0], all_years[-1]))
    else:
        fy_from = fy_to = all_years[0]
        st.caption(f"Only {fy_from} is available.")

    st.subheader("Warning thresholds")
    st.caption("Illustrative screening values, not credit-risk standards. Change them to test sensitivity.")
    defaults = Thresholds()
    t = Thresholds(
        interest_coverage_min=st.number_input("Interest coverage below (x)", 0.0, 20.0, defaults.interest_coverage_min, 0.1),
        current_ratio_min=st.number_input("Current ratio below (x)", 0.0, 5.0, defaults.current_ratio_min, 0.1),
        sustained_years=int(st.number_input("Consecutive years for 'persistent'", 1, 5, defaults.sustained_years, 1)),
        debt_rise_min_pct=st.number_input("Debt rise counted as material (% of prior debt)", 0.0, 100.0,
                                          defaults.debt_rise_min_pct * 100, 1.0) / 100,
    )

# ---- computations -----------------------------------------------------------
metrics_all = with_peer_metrics(compute_metrics(fin_all))
flags_all = evaluate_flags(metrics_all, t)
pers_all = persistence_table(metrics_all, t)
mask = (metrics_all["ticker"] == ticker) & (metrics_all["basis"] == basis) \
    & (metrics_all["financial_year"] >= fy_from) & (metrics_all["financial_year"] <= fy_to)
m = metrics_all[mask].sort_values("fy_start").reset_index(drop=True)
years = list(m["financial_year"])
flags = flags_all[(flags_all["ticker"] == ticker) & (flags_all["basis"] == basis)
                  & (flags_all["financial_year"].isin(years))]
is_illustrative = bool(m["is_illustrative"].any())
cur = m.iloc[-1]
prev = m.iloc[-2] if len(m) > 1 and bool(cur["has_prior_year"]) else None
explained = explain_flags(flags, metrics_all, t, ver_all, pers_all)
pers_company = pers_all[(pers_all["ticker"] == ticker) & (pers_all["basis"] == basis)]
assessment = assess_year(cur, flags[flags["financial_year"] == cur["financial_year"]],
                         pers_company[pers_company["financial_year"] == cur["financial_year"]], t, ver_all)

# =========================== 1. Selection and comparability ====================
st.header(f"{ticker}: {names.loc[ticker, 'name']}")
if is_illustrative:
    st.warning("ILLUSTRATIVE DATA: the figures for this company are synthetic and were created to demonstrate "
               "the software. They are not real company data and must not be quoted as such.")
st.caption(f"Basis: {basis}. All monetary values in INR crore. Years: {fy_from} to {fy_to}.")
st.markdown("### 1. Selection and comparability")
odd_periods = m[m["period_months"] != 12]
if not odd_periods.empty:
    listed = ", ".join(f"{r.financial_year} is a {int(r.period_months)}-month period" for r in odd_periods.itertuples())
    st.warning(f"Non-standard reporting period: {listed} (see data notes). Revenue, profit and cash flow for that period "
               "are not comparable with 12-month years, so year-on-year changes into and out of it are shown as n/a "
               "and rules based on them cannot fire.")
vs = ver_summary(ver_all, ticker)
if is_illustrative:
    st.caption("Source verification: not applicable to synthetic data.")
elif vs["checked"]:
    st.caption(f"Source verification: {vs['verified'] + vs['approx']} of {vs['checked']} inputs checked against the company's "
               f"own filing match ({', '.join(vs['years'])}); {vs['discrepancy']} unresolved discrepancies; "
               f"{vs['unverified']} not like-for-like. Years and inputs not listed there come from aggregators and are unverified.")
else:
    st.caption("Source verification: no input for this company has been checked against a primary filing.")
n_obs = int(m["interest_coverage"].notna().sum())
st.caption(f"{len(m)} financial years loaded in range; {int(m['has_prior_year'].sum())} with a directly comparable prior year. "
           "With so few years, persistence statements describe a short history only.")

# =========================== 2. Performance ====================================
st.markdown("### 2. Performance and key ratios")
st.caption(f"Latest year in range: **{cur['financial_year']}**" + (f", change vs {prev['financial_year']}" if prev is not None else ""))
cols = st.columns(len(RATIO_COLUMNS))
for col, name in zip(cols, RATIO_COLUMNS):
    v = cur[name]
    delta = None
    if prev is not None and pd.notna(v) and pd.notna(prev[name]):
        d = v - prev[name]
        delta = f"{d * 100:+.1f} pp" if name in PERCENT_RATIOS else f"{d:+.3f}" if abs(d) < 0.1 else f"{d:+.2f}"
    col.metric(TILE_LABEL.get(name, RATIO_LABELS[name]), fmt_ratio(name, v), delta, delta_color=LOWER_IS_WORSE.get(name, "normal"),
               help=RATIO_DEFINITIONS[name])
c1, c2, c3 = st.columns(3)
c1.metric("Operating cash flow", fmt_cr(cur["operating_cash_flow_cr"]), help="Net cash from operating activities")
c2.metric("Capex", fmt_cr(cur["capex_cr"]), help="Purchase of property, plant and equipment")
c3.metric("Free cash flow", fmt_cr(cur["free_cash_flow_cr"]), help="Operating cash flow - capex; n/a unless both are loaded")
note = ratio_notes(cur)
if note:
    st.caption(f"Notes for {cur['financial_year']}: {note}.")
cautions = context_notes(cur, t.current_ratio_min)
if cautions:
    with st.expander(f"How to read {cur['financial_year']} (cautions)", expanded=True):
        for c in cautions:
            st.markdown(f"- {c}")

with st.expander("Reported inputs (INR crore) and definitions"):
    inputs = m[["financial_year", "period_months", "revenue_cr", "ebit_cr", "interest_expense_cr", "total_debt_cr", "total_equity_cr",
                "current_assets_cr", "current_liabilities_cr", "operating_cash_flow_cr", "capex_cr", "free_cash_flow_cr",
                "cash_cr"]].copy()
    inputs.columns = ["Financial year", "Months", "Revenue", "EBIT", "Interest expense", "Total debt", "Total equity",
                      "Current assets", "Current liabilities", "Operating cash flow", "Capex", "Free cash flow", "Cash"]
    show_df(inputs.set_index("Financial year"))
    st.caption("Empty cells are missing values (NULL), not zeros. Free cash flow = operating cash flow - capex, and is "
               "empty unless both are present. Recompute any ratio from this table to verify it.")
    defs = m["definitions_note"].dropna().unique()
    if len(defs):
        st.markdown("**What each input means for this company** (from the data file)")
        st.caption(defs[0])

# =========================== 3. Warnings =======================================
st.markdown("### 3. Warning signals: why they fired, how persistent, what conflicts")
st.caption("Thresholds are illustrative. A breach, a deterioration over time, several areas flagged together, conflicting "
           "signals and missing data are different things and are labelled separately. No composite score.")
KIND_LABEL = {"threshold_breach": "Threshold breach", "deterioration": "Deterioration over time",
              "convergence": "Several areas together", "conflict": "Conflicting signals",
              "data_limitation": "Data limitation", "inconclusive": "Inconclusive"}
st.markdown(f"**Reading of {cur['financial_year']}**")
for kind in KIND_LABEL:
    items = [a for a in assessment if a["kind"] == kind]
    for a in items:
        icon = {"conflict": "↔️", "convergence": "🔗", "data_limitation": "⚠️", "inconclusive": "❔"}.get(kind, "⚑")
        st.markdown(f"{icon} **{KIND_LABEL[kind]}**: {a['text']}")

PERS_SHORT = {"persistent": "PERSISTENT", "building": "building", "new": "new", "history_unknown": "breach (history unknown)",
              "recovered": "recovered", "ok": "ok", "not_assessable": "n/a"}
st.markdown("**Persistence by indicator** (only directly consecutive, comparable years count; n/a is never treated as ok)")
pm = pers_company[pers_company["financial_year"].isin(years)].assign(s=lambda d: d["status"].map(PERS_SHORT))
if not pm.empty:
    grid = pm.pivot_table(index="indicator", columns="financial_year", values="s", aggfunc="first").reindex(columns=years)
    grid.index = [INDICATORS[i] for i in grid.index]
    show_df(grid.fillna("n/a"))
st.caption("Persistent = breached in at least the chosen number of directly consecutive observed years. This describes the "
           "historical data; it is not a statistical test or a prediction.")

if explained.empty:
    st.success("No rules fired in the selected years at the current thresholds. This is not evidence that risk is low: "
               "debt maturities, liquidity facilities, contingent liabilities and drivers are not modelled.")
else:
    st.markdown("**Each warning in detail**")
    for e in explained.to_dict("records"):
        with st.expander(f"{e['Year']}: {e['Indicator']}  ({e['Persistence'].split(':')[0]})"):
            st.markdown(f"**Observed:** {e['Observed']}")
            st.markdown(f"**Threshold:** {e['Threshold']}")
            st.markdown(f"**Formula:** {e['Formula']}")
            st.markdown(f"**Why it matters:** {e['Why it matters']}")
            st.markdown(f"**Persistence:** {e['Persistence']}")
            st.markdown(f"**History:** {e['History']}")
            st.markdown(f"**Peer context:** {e['Peer context']}")
            st.markdown(f"**Data quality:** {e['Data quality']}")
            st.markdown(f"**Suggested follow-up:** {e['Follow-up']}")

with st.expander("Threshold sensitivity (same kind of company only)"):
    st.caption("How many company-years each rule flags under alternative thresholds, for real companies only (or synthetic "
               "only if a synthetic company is selected). If conclusions change between neighbouring values, treat the flag as fragile.")
    sens = sensitivity_table(same_universe(metrics_all, is_illustrative), t)
    show_df(sens.rename(columns={"is_base_value": "current setting"}), hide_index=True)

# =========================== 4. Trends and peers ===============================
st.markdown("### 4. Trends and peer comparison")
tab1, tab2, tab3 = st.tabs(["Coverage and leverage", "Profitability", "Cash flow and liquidity"])
with tab1:
    c1, c2 = st.columns(2)
    with c1:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"Interest coverage": m["interest_coverage"]}, "Interest coverage", "x",
             hline=(t.interest_coverage_min, f"threshold {t.interest_coverage_min:g}x"), annotate=fmt_x)
        show_fig(fig)
    with c2:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"EBIT": m["ebit_cr"]}, "Total debt (bars) vs EBIT (line)", "INR crore",
             bars=("Total debt", m["total_debt_cr"]))
        show_fig(fig)
    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    draw(ax, years, {"Debt-to-equity": m["debt_to_equity"]}, "Debt-to-equity", "x", annotate=fmt_x)
    show_fig(fig)
with tab2:
    c1, c2 = st.columns(2)
    with c1:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"EBIT margin (%)": m["ebit_margin"] * 100}, "EBIT margin", "%")
        show_fig(fig)
    with c2:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"Revenue growth (%)": m["revenue_growth"] * 100}, "Revenue growth", "%")
        ax.axhline(0, color="grey", linewidth=0.8)
        show_fig(fig)
with tab3:
    c1, c2 = st.columns(2)
    with c1:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"Operating cash flow": m["operating_cash_flow_cr"],
                         "Free cash flow": m["free_cash_flow_cr"]},
             "Operating cash flow and free cash flow (after capex)", "INR crore",
             bars=("Capex", m["capex_cr"]))
        ax.axhline(0, color="grey", linewidth=0.8)
        show_fig(fig)
    with c2:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"Current ratio": m["current_ratio"]}, "Current ratio", "x",
             hline=(t.current_ratio_min, f"threshold {t.current_ratio_min:g}x"))
        show_fig(fig)
    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    draw(ax, years, {"OCF / debt": m["ocf_to_debt"]}, "Operating cash flow / total debt", "x")
    show_fig(fig)
st.caption("Gaps in a line mean the value is missing or the ratio is not defined (e.g. zero denominator, or a prior year that is not "
           "a comparable 12-month year); they are never plotted as zero. Missing bars are simply absent.")

st.markdown(f"**Peers, {basis}, {cur['financial_year']}**")
pt = peer_table(metrics_all, basis, cur["financial_year"], is_illustrative)
med = peer_medians(pt)
show = pt.copy()
for c, (_label, _grp, kind) in PEER_METRICS.items():
    show[c] = show[c].map(lambda v, kind=kind: fmt_pct(v) if kind == "pct" else fmt_x(v))
show["revenue_cr"] = show["revenue_cr"].map(fmt_cr)
show = show.drop(columns=["comparable", "name"]).rename(columns={
    "ticker": "Ticker", "period_months": "Months", "revenue_cr": "Revenue", "status": "Comparability",
    **{c: v[0] for c, v in PEER_METRICS.items()}})
show_df(show, hide_index=True)
medrow = {PEER_METRICS[r.metric][0]: (fmt_pct(r.median) if PEER_METRICS[r.metric][2] == "pct" else fmt_x(r.median)) + f" (n={r.n})"
          for r in med.itertuples()}
st.caption("Median of comparable companies only (12-month periods, same basis and year): " +
           "; ".join(f"{k}: {v}" for k, v in medrow.items()))
st.caption("Companies are not ranked or labelled safest / riskiest: one ratio cannot support that, and size, acquisitions and "
           "consolidation scope differ. A period that is not 12 months is excluded from medians; a company with no data this year is listed, not hidden.")
with st.expander("Why peers are not fully comparable"):
    for n in COMPARABILITY_NOTES:
        st.markdown(f"- {n}")

# =========================== 5. Stress test ====================================
st.markdown("### 5. Stress test (what-if, not a forecast)")
st.caption("Pick a base year and one or two operating shocks. The model is mechanical and every assumption is shown.")
twelve = m[m["period_months"] == 12]
base_options = list(twelve["financial_year"]) or list(m["financial_year"])
base_year = st.selectbox("Base year", base_options, index=len(base_options) - 1, key="stress_base")
sc1, sc2, sc3 = st.columns(3)
rev_drop = sc1.slider("Revenue falls by (%)", 0, 60, 10, 1, key="stress_rev") / 100
margin_drop = sc2.slider("EBIT margin falls by (percentage points)", 0.0, 10.0, 0.0, 0.5, key="stress_margin") / 100
fixed_share = sc3.slider("Share of operating costs that are fixed (%)", 0, 100, 0, 5, key="stress_fixed",
                         help="0% = all costs vary with revenue, so a pure revenue shock leaves the EBIT margin unchanged. "
                              "Higher values make profit fall faster than revenue (operating leverage).") / 100
stress = stress_test(m[m["financial_year"] == base_year].iloc[0], StressInputs(rev_drop, margin_drop, fixed_share),
                     t.interest_coverage_min)
if stress["available"]:
    tbl = stress_table(stress)
    disp = tbl.assign(**{k: tbl.apply(lambda r, k=k: ({"cr": fmt_cr, "pct": fmt_pct, "x": fmt_x}[r["kind"]])(r[k]), axis=1)
                         for k in ("Baseline", "Scenario", "Change")}).drop(columns=["kind"])
    show_df(disp, hide_index=True)
    be = stress["breakeven_revenue_decline"]
    st.markdown("Revenue fall that would take interest coverage to 1.0x under these assumptions: **" +
                ("not reached within a 100% fall, or not applicable" if be is None else f"{be:.0%}") + "**")
    if stress["below_threshold"]:
        st.warning(f"In this scenario interest coverage falls below the {t.interest_coverage_min:g}x screening threshold.")
    if stress["scenario"]["interest_coverage"] is not None:
        fig, ax = plt.subplots(figsize=(4.5, 2.6))
        ax.bar(["Baseline", "Scenario"], [stress["baseline"]["interest_coverage"], stress["scenario"]["interest_coverage"]],
               color=["#c8d3e0", "#7a9cc6"])
        ax.axhline(t.interest_coverage_min, linestyle="--", color="#b3261e", linewidth=1)
        ax.axhline(0, color="grey", linewidth=0.8)
        ax.set_title("Interest coverage (x)", fontsize=10, loc="left")
        ax.spines[["top", "right"]].set_visible(False)
        show_fig(fig)
for note_text in stress["notes"]:
    st.caption(f"Note: {note_text}")
if stress["available"]:
    with st.expander("Assumptions and formulas"):
        for a in stress["assumptions"]:
            st.markdown(f"- {a}")
        st.markdown("`cost base C = revenue - EBIT`; `revenue_s = revenue x (1 - d)`; "
                    "`EBIT_s = revenue_s - [f x C + (1 - f) x C x (1 - d)] - pp x revenue_s`; "
                    "`coverage_s = EBIT_s / interest`; `FCF_s = (OCF - (EBIT - EBIT_s)) - capex`.")

# =========================== 6. Evidence and data quality ======================
st.markdown("### 6. Evidence, source checks and unresolved questions")
d = disc_all[(disc_all["ticker"] == ticker) & (disc_all["financial_year"].isna() | disc_all["financial_year"].isin(years))]
if disc_all.empty and ext_all.empty:
    st.warning("No disclosures or external indicators are loaded. The tool can show WHAT changed but has no documented "
               "evidence for WHY. Any explanation is a hypothesis to investigate.")
if d.empty:
    st.write("No company disclosures are loaded for this company and period. Add short, attributed excerpts with page or "
             "section references to `data/raw/disclosures.csv` and re-run the pipeline.")
else:
    st.markdown("**Company disclosures (from primary filings)**")
    show_df(d[["financial_year", "topic", "excerpt", "related_metric", "relationship", "source_doc", "page_ref",
                    "publication_date", "source_url"]], hide_index=True)
    st.caption("'established' means the filing itself shows the link to the metric; 'possible_explanation' means a plausible "
               "link that the filing does not establish. A disclosure appearing in the same year as a ratio change does not show it caused the change.")
if ext_all.empty:
    st.caption("External indicators: none loaded (optional). Add dated, sourced series to `data/raw/external_indicators.csv` only if they materially help.")
else:
    show_df(ext_all[["series_name", "period", "value", "unit", "source", "source_url", "notes"]], hide_index=True)

st.markdown("**Source verification (loaded value vs the company's own filing)**")
mine_ver = ver_all[ver_all["ticker"] == ticker] if not ver_all.empty else ver_all
if is_illustrative:
    st.write("Not applicable to synthetic data.")
elif mine_ver.empty:
    st.write("No input for this company has been checked against a primary filing.")
else:
    vshow = mine_ver[["financial_year", "item", "app_value_cr", "filing_value_cr", "difference_cr", "difference_pct", "status",
                      "source_doc", "publication_date", "location", "notes"]]
    show_df(vshow, hide_index=True)
    st.caption("Filing values were read from the filing text by an automated extraction, not inspected in a PDF viewer; "
               "re-check the page before quoting externally. 'unverified' = not like-for-like (for example lease liabilities not located). "
               "A discrepancy is reported, not corrected.")

questions = []
if not mine_ver.empty:
    for r in mine_ver[mine_ver["status"] == "discrepancy"].itertuples():
        questions.append(f"{r.financial_year} {r.item}: loaded {r.app_value_cr:,.1f} vs filing {r.filing_value_cr:,.1f} crore "
                         f"({r.difference_pct:+.1f}%). Cause not established; resolve against the annual report before relying on it.")
checked_years = set(mine_ver["financial_year"]) if not mine_ver.empty else set()
unchecked = [y for y in years if y not in checked_years]
if not is_illustrative and unchecked:
    questions.append("Not checked against a primary filing: " + ", ".join(unchecked) + ".")
for r in m[m["period_months"] != 12].itertuples():
    questions.append(f"{r.financial_year} covers {int(r.period_months)} months: its flow figures cannot be compared with 12-month years.")
if m["current_assets_cr"].isna().any():
    questions.append("Current assets / liabilities are missing for " + ", ".join(m.loc[m["current_assets_cr"].isna(), "financial_year"]) +
                     ": the current ratio is n/a there.")
if questions:
    st.markdown("**Unresolved questions**")
    for q in questions:
        st.markdown(f"- {q}")
with st.expander("Data-quality findings for this company"):
    iss = issues_all[issues_all["ticker"] == ticker]
    iss = iss[iss["check_name"] != "blank_row_skipped"]
    if iss.empty:
        st.write("No findings.")
    else:
        show_df(iss[["severity", "check_name", "financial_year", "field", "detail"]], hide_index=True)
src = fin_all[(fin_all["ticker"] == ticker) & (fin_all["basis"] == basis) & fin_all["financial_year"].isin(years)]
with st.expander("Data sources and definitions"):
    show_df(
        src[["financial_year", "basis", "original_unit", "source", "source_url", "definitions_note", "notes"]]
        .rename(columns={"financial_year": "Year", "basis": "Basis", "original_unit": "Unit in source",
                         "source": "Source", "source_url": "URL", "definitions_note": "Definitions", "notes": "Notes"}), hide_index=True)
with st.expander("Ratio definitions"):
    st.table(pd.DataFrame({"Metric": [RATIO_LABELS[c] for c in RATIO_COLUMNS],
                           "Definition": [RATIO_DEFINITIONS[c] for c in RATIO_COLUMNS]}))
    st.caption("A ratio is shown as n/a (never 0) when an input is missing or the denominator is zero or negative.")

# =========================== 7. Summary and export =============================
st.markdown("### 7. Analyst summary and export")
report = build_report(ticker=ticker, name=names.loc[ticker, "name"], basis=basis, m=m, fy_from=fy_from, fy_to=fy_to, thresholds=t,
                      explained=explained, assessment=assessment, peer=pt, peer_med=med, stress=stress, ver=ver_all,
                      disclosures=d, issues=issues_all[issues_all["ticker"] == ticker], is_illustrative=is_illustrative)
st.caption("The report keeps statements apart by basis: observed from loaded data, checked against a filing, unverified, "
           "hypothesis, scenario (not a forecast), and limitation.")
show_df(report[report["section"].str[:1].isin(list("123"))], hide_index=True)
st.download_button("Download full analyst report (CSV)", data=report.to_csv(index=False).encode("utf-8"),
                   file_name=f"{ticker}_{basis}_{fy_to}_analyst_report.csv", mime="text/csv")
st.caption("The table above shows sections 1 to 3; the download contains all eight sections (peers, stress test, data quality, "
           "follow-ups, limitations).")

with st.expander("Optional: narrative wording (rules-only, or AI-assisted)"):
    st.caption("Not needed for the analysis above. Rules-only mode needs no AI or key. AI output can be wrong even when it "
               "passes the automatic checks, and has not been shown to improve anything.")
    mode_labels = {"Rules-only summary (no AI)": "rules_only", "AI-assisted summary": "ai"}
    mode_choice = st.radio("Mode", list(mode_labels), horizontal=True,
                           help="Both modes use only the evidence packet built from the database.")
    mode = mode_labels[mode_choice]

    provider_ready = True
    confirm_public = True
    prov_key, model_name, api_key = "", "", ""
    if mode == "ai":
        statuses = llm.all_statuses()
        keys = [s.key for s in statuses]
        prov_key = st.selectbox("Model provider", keys, index=keys.index("gemini"),
                                format_func=lambda k: llm.LABELS[k])
        sel = next(s for s in statuses if s.key == prov_key)
        provider_ready = sel.available
        if prov_key == "gemini":
            api_key = st.text_input("Gemini API key", type="password", placeholder="Paste your key (AIza...)",
                                    help="Free key from Google AI Studio (aistudio.google.com/apikey). Kept in this "
                                         "browser session only; never saved to disk or to the database.").strip()
            provider_ready = bool(api_key) or sel.available
            if not provider_ready:
                st.warning("Paste a Gemini API key to use AI-assisted mode.")
            gem_models = list(dict.fromkeys([sel.default_model, "gemini-2.5-flash", "gemini-2.5-flash-lite",
                                             "gemini-2.5-pro"]))
            pick = st.selectbox("Gemini model", gem_models + ["Other (type model ID)"])
            model_name = (st.text_input("Model ID", value=sel.default_model).strip()
                          if pick.startswith("Other") else pick)
        else:
            (st.caption if sel.available else st.warning)(sel.reason)
        if prov_key == "gemini":
            pass
        elif prov_key == "ollama" and sel.available:
            installed = llm.ollama_models()
            model_name = st.selectbox("Model", installed,
                                      index=installed.index(sel.default_model) if sel.default_model in installed else 0)
        else:
            model_name = st.text_input("Model", value=sel.default_model,
                                       help="Model IDs change; check your provider's current list.")
        if sel.is_local:
            st.caption("Local model: the evidence packet stays on your machine.")
        else:
            confirm_public = st.checkbox("I confirm this data is public (or I am authorised to send it to an external "
                                         "AI service). Free tiers of hosted services may use submitted data to improve "
                                         "their products.")
        st.caption("Small local models follow the output format less reliably; the automatic checks below will show it.")

    state_key = json.dumps([ticker, basis, fy_from, fy_to, t.as_dict(), mode, prov_key, model_name])
    if st.button("Generate commentary", disabled=(mode == "ai" and not (provider_ready and confirm_public and model_name))):
        conn = connect()
        try:
            packet = build_packet(conn, ticker, basis, fy_from, fy_to, t)
            model = None
            if mode == "ai":
                model = f"{prov_key}:{model_name}"
                with st.spinner("Asking the model ..."):
                    try:
                        commentary = ai.generate_ai_commentary(packet, provider=prov_key, model=model_name,
                                                                 api_key=api_key)
                    except Exception as exc:  # network, key, quota, or malformed JSON
                        st.error(f"AI commentary failed: {exc}")
                        commentary = None
            else:
                commentary = ai.rules_only_summary(packet)
            if commentary is not None:
                verification = ai.verify_commentary(commentary, packet)
                run_id = ai.save_run(conn, packet, commentary, verification, mode, model)
                st.session_state["commentary"] = {"key": state_key, "packet": packet, "commentary": commentary,
                                                  "verification": verification, "run_id": run_id, "mode": mode}
        finally:
            conn.close()

    res = st.session_state.get("commentary")
    if res and res["key"] == state_key:
        ver = res["verification"]
        problems_by_key = {(r["section"], r["index"]): r["problems"] for r in ver["items"]}
        if res["mode"] == "ai":
            st.caption("AI-generated text. It has not been established as correct. Automatic checks below catch some "
                       "problems (unknown IDs, unsupported numbers, unhedged causal claims) but not all.")
        st.caption(f"Run #{res['run_id']} saved for evaluation. Automatic check: {ver['statements_without_problems']} of "
                   f"{ver['statements_checked']} statements without detected problems.")
        com = res["commentary"]

        def render(section: str, title: str) -> None:
            items = com.get(section, [])
            if not items:
                return
            st.markdown(f"**{title}**")
            for i, it in enumerate(items):
                probs = problems_by_key.get((section, i), [])
                badge = "✅" if not probs else "⚠️"
                label = f" _[{it['label']}]_" if it.get("label") else ""
                ids = f"  \n`{', '.join(it['evidence_ids'])}`" if it.get("evidence_ids") else ""
                st.markdown(f"{badge} {it['statement']}{label}{ids}")
                for p in probs:
                    st.caption(f"↳ check: {p}")

        render("observed_changes", "Observed changes")
        render("implications", "Possible implications (hypotheses unless marked documented)")
        render("alternative_explanations", "Alternative explanations and uncertainties")
        if com.get("follow_up_questions"):
            st.markdown("**Follow-up questions for the analyst**")
            for q in com["follow_up_questions"]:
                st.markdown(f"- {q}")
        if com.get("caveats"):
            st.markdown("**Caveats**")
            for c in com["caveats"]:
                st.markdown(f"- {c}")
        with st.expander("Evidence packet sent to the commentary step"):
            st.json(res["packet"], expanded=False)


st.markdown("### Limitations and what this project cannot claim")
for lim in config.LIMITATIONS:
    st.markdown(f"- {lim}")
st.markdown("**This project cannot claim:**")
for c in config.CANNOT_CLAIM:
    st.markdown(f"- {c}")

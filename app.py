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
from btb.db import connect, load_fin, query_df  # noqa: E402
from btb.evidence import build_packet  # noqa: E402
from btb.flags import RULES, Thresholds, evaluate_flags, sensitivity_table  # noqa: E402
from btb.fmt import fmt_cr, fmt_pct, fmt_x  # noqa: E402
from btb.metrics import (PERCENT_RATIOS, RATIO_COLUMNS, RATIO_DEFINITIONS, RATIO_LABELS,  # noqa: E402
                         compute_metrics, ratio_notes)
from btb.pipeline import run_pipeline  # noqa: E402

st.set_page_config(page_title="Beyond the Balance Sheet", page_icon="\U0001F4CA", layout="wide")

LOWER_IS_WORSE = {"debt_to_equity": "inverse"}  # higher debt-to-equity is the adverse direction


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def ensure_db() -> None:
    if not config.DB_PATH.exists():
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
    finally:
        conn.close()
    return fin, issues, disc, ext


def fmt_ratio(col: str, v) -> str:
    return fmt_pct(v) if col in PERCENT_RATIOS else fmt_x(v)


def draw(ax, years, series: dict, title: str, ylabel: str, hline: tuple[float, str] | None = None, bars=None):
    if bars:
        ax.bar(years, [v if pd.notna(v) else 0 for v in bars[1]], color="#c8d3e0", label=bars[0])
    for label, values in series.items():
        ax.plot(years, values, marker="o", linewidth=2, label=label)
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


def show_fig(fig) -> None:
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
ensure_db()
fin_all, issues_all, disc_all, ext_all = load_all(config.DB_PATH.stat().st_mtime)

st.title("Beyond the Balance Sheet")
st.caption("Explainable screening of corporate financial risk indicators for Indian listed companies")
st.info(config.DISCLAIMER)

if fin_all.empty:
    st.error("No financial data is loaded yet. Fill in `data/raw/financials_real_TEMPLATE.csv` (or use the demo "
             "data) and run `python scripts/run_pipeline.py`.")
    st.stop()

# ---- sidebar controls -------------------------------------------------------
names = fin_all.drop_duplicates("ticker").set_index("ticker")[["name", "is_illustrative"]]
with st.sidebar:
    st.header("Controls")
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
        sustained_years=int(st.number_input("Consecutive declines for 'sustained'", 1, 5, defaults.sustained_years, 1)),
    )

# ---- computations -----------------------------------------------------------
metrics_all = compute_metrics(fin_all)
flags_all = evaluate_flags(metrics_all, t)
mask = (metrics_all["ticker"] == ticker) & (metrics_all["basis"] == basis) \
    & (metrics_all["financial_year"] >= fy_from) & (metrics_all["financial_year"] <= fy_to)
m = metrics_all[mask].sort_values("fy_start").reset_index(drop=True)
years = list(m["financial_year"])
flags = flags_all[(flags_all["ticker"] == ticker) & (flags_all["basis"] == basis)
                  & (flags_all["financial_year"].isin(years))]
is_illustrative = bool(m["is_illustrative"].any())

st.subheader(f"{ticker}: {names.loc[ticker, 'name']}")
if is_illustrative:
    st.warning("ILLUSTRATIVE DATA: the figures for this company are synthetic and were created to demonstrate "
               "the software. They are not real company data and must not be quoted as such.")
st.caption(f"Basis: {basis}. All monetary values in INR crore. Years: {fy_from} to {fy_to}.")
odd_periods = m[m["period_months"] != 12]
if not odd_periods.empty:
    listed = ", ".join(f"{r.financial_year} is a {int(r.period_months)}-month period" for r in odd_periods.itertuples())
    st.warning(f"Non-standard reporting period: {listed} (see data notes). Revenue, profit and cash flow for that period "
               "are not comparable with 12-month years, so year-on-year changes into and out of it are shown as n/a "
               "and rules based on them cannot fire.")

# ---- 3. key metrics ---------------------------------------------------------
st.markdown("### 1. Key metrics")
cur = m.iloc[-1]
prev = m.iloc[-2] if len(m) > 1 and bool(cur["has_prior_year"]) else None
st.caption(f"Latest year in range: **{cur['financial_year']}**" + (f", change vs {prev['financial_year']}" if prev is not None else ""))
cols = st.columns(len(RATIO_COLUMNS))
for col, name in zip(cols, RATIO_COLUMNS):
    v = cur[name]
    delta = None
    if prev is not None and pd.notna(v) and pd.notna(prev[name]):
        d = v - prev[name]
        delta = f"{d * 100:+.1f} pp" if name in PERCENT_RATIOS else f"{d:+.2f}"
    col.metric(RATIO_LABELS[name], fmt_ratio(name, v), delta, delta_color=LOWER_IS_WORSE.get(name, "normal"),
               help=RATIO_DEFINITIONS[name])
note = ratio_notes(cur)
if note:
    st.caption(f"Notes for {cur['financial_year']}: {note}.")

with st.expander("Reported inputs (INR crore)"):
    inputs = m[["financial_year", "period_months", "revenue_cr", "ebit_cr", "interest_expense_cr", "total_debt_cr", "total_equity_cr",
                "current_assets_cr", "current_liabilities_cr", "operating_cash_flow_cr", "cash_cr"]].copy()
    inputs.columns = ["Financial year", "Months", "Revenue", "EBIT", "Interest expense", "Total debt", "Total equity",
                      "Current assets", "Current liabilities", "Operating cash flow", "Cash"]
    st.dataframe(inputs.set_index("Financial year"), use_container_width=True)
    st.caption("Empty cells are missing values (NULL), not zeros.")

# ---- 4. trends --------------------------------------------------------------
st.markdown("### 2. Trends")
tab1, tab2, tab3 = st.tabs(["Coverage and leverage", "Profitability", "Cash flow and liquidity"])
with tab1:
    c1, c2 = st.columns(2)
    with c1:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"Interest coverage": m["interest_coverage"]}, "Interest coverage", "x",
             hline=(t.interest_coverage_min, f"threshold {t.interest_coverage_min:g}x"))
        show_fig(fig)
    with c2:
        fig, ax = plt.subplots(figsize=(5.5, 3.3))
        draw(ax, years, {"EBIT": m["ebit_cr"]}, "Total debt (bars) vs EBIT (line)", "INR crore",
             bars=("Total debt", m["total_debt_cr"]))
        show_fig(fig)
    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    draw(ax, years, {"Debt-to-equity": m["debt_to_equity"]}, "Debt-to-equity", "x")
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
        draw(ax, years, {"Operating cash flow": m["operating_cash_flow_cr"]}, "Operating cash flow", "INR crore")
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
st.caption("Gaps in a line mean the value is missing or the ratio is not defined (e.g. zero denominator); they are never plotted as zero. "
           "Bars with no data are drawn at zero height only so the axis stays aligned.")

# ---- 5. flags ---------------------------------------------------------------
st.markdown("### 3. Warning indicators")
st.caption("Each flag shows the rule, the threshold and the numbers behind it. There is no composite score: "
           "these are screening prompts for a human analyst, not a credit rating.")
if flags.empty:
    st.success("No rules fired for this company in the selected years at the current thresholds.")
else:
    matrix = flags.assign(mark="⚑").pivot_table(index="rule_id", columns="financial_year", values="mark",
                                                      aggfunc="first").reindex(columns=years).fillna("")
    matrix = matrix.reindex([r for r in RULES if r in matrix.index])
    st.dataframe(matrix, use_container_width=True)
    st.dataframe(
        flags[["financial_year", "rule_id", "severity", "threshold_used", "evidence"]]
        .rename(columns={"financial_year": "Year", "rule_id": "Rule", "severity": "Severity",
                         "threshold_used": "Threshold", "evidence": "Evidence"}),
        use_container_width=True, hide_index=True)

with st.expander("Threshold sensitivity (all loaded companies)"):
    st.caption("How many company-years each rule flags under alternative thresholds. "
               "If conclusions change a lot between neighbouring values, treat the flag as fragile.")
    sens = sensitivity_table(metrics_all, t)
    st.dataframe(sens.rename(columns={"is_base_value": "current setting"}), use_container_width=True, hide_index=True)

with st.expander("Peer comparison (same basis, latest year in range)"):
    peers = metrics_all[(metrics_all["basis"] == basis) & (metrics_all["financial_year"] == cur["financial_year"])
                        & (metrics_all["industry"] == cur["industry"])]
    if len(peers) < 2:
        st.write("No peers with data for this year and basis.")
    else:
        view = peers[["ticker", *RATIO_COLUMNS]].copy()
        for c in RATIO_COLUMNS:
            view[c] = view[c].map(lambda v, c=c: fmt_ratio(c, v))
        st.dataframe(view.rename(columns={**RATIO_LABELS, "ticker": "Ticker"}), use_container_width=True, hide_index=True)
        st.caption("Compare only like with like: check basis, definitions and restructurings first.")

# ---- 6. evidence ------------------------------------------------------------
st.markdown("### 4. Company disclosures and external indicators")
d = disc_all[(disc_all["ticker"] == ticker) & (disc_all["financial_year"].isna() | disc_all["financial_year"].isin(years))]
if d.empty:
    st.write("No company disclosures are loaded for this company and period. Add short, attributed excerpts to "
             "`data/raw/disclosures.csv` (with page references) and re-run the pipeline.")
else:
    st.dataframe(d[["financial_year", "topic", "excerpt", "source_doc", "page_ref", "source_url"]],
                 use_container_width=True, hide_index=True)
if ext_all.empty:
    st.write("No external indicators are loaded. Add dated series (fuel, freight, rates, ...) with sources to "
             "`data/raw/external_indicators.csv`.")
else:
    st.dataframe(ext_all[["series_name", "period", "value", "unit", "source", "source_url", "notes"]],
                 use_container_width=True, hide_index=True)
st.caption("Documented facts and hypotheses are kept separate. A before-and-after pattern alone does not establish causation: "
           "consider alternative explanations (price, demand, capacity, financing, accounting changes).")

# ---- 7. commentary ----------------------------------------------------------
st.markdown("### 5. Commentary")
mode_labels = {"Rules-only summary (no AI)": "rules_only", "AI-assisted summary": "ai"}
mode_choice = st.radio("Mode", list(mode_labels), horizontal=True,
                       help="Both modes use only the evidence packet built from the database.")
mode = mode_labels[mode_choice]

provider_ready = True
confirm_public = True
prov_key, model_name = "", ""
if mode == "ai":
    statuses = llm.all_statuses()
    keys = [s.key for s in statuses]
    first_ready = next((s.key for s in statuses if s.available), keys[0])
    prov_key = st.selectbox("Model provider", keys, index=keys.index(first_ready),
                            format_func=lambda k: llm.LABELS[k])
    sel = next(s for s in statuses if s.key == prov_key)
    provider_ready = sel.available
    (st.caption if sel.available else st.warning)(sel.reason)
    if prov_key == "ollama" and sel.available:
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
                    commentary = ai.generate_ai_commentary(packet, provider=prov_key, model=model_name)
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

# ---- 8. sources and limitations ---------------------------------------------
st.markdown("### 6. Data sources, reporting basis and limitations")
src = fin_all[(fin_all["ticker"] == ticker) & (fin_all["basis"] == basis) & fin_all["financial_year"].isin(years)]
st.dataframe(
    src[["financial_year", "basis", "original_unit", "source", "source_url", "definitions_note", "notes"]]
    .rename(columns={"financial_year": "Year", "basis": "Basis", "original_unit": "Unit in source",
                     "source": "Source", "source_url": "URL", "definitions_note": "Definitions", "notes": "Notes"}),
    use_container_width=True, hide_index=True)

with st.expander("Data-quality findings for this company"):
    iss = issues_all[issues_all["ticker"] == ticker]
    iss = iss[iss["check_name"] != "blank_row_skipped"]
    if iss.empty:
        st.write("No findings.")
    else:
        st.dataframe(iss[["severity", "check_name", "financial_year", "field", "detail"]],
                     use_container_width=True, hide_index=True)
with st.expander("Ratio definitions"):
    st.table(pd.DataFrame({"Metric": [RATIO_LABELS[c] for c in RATIO_COLUMNS],
                           "Definition": [RATIO_DEFINITIONS[c] for c in RATIO_COLUMNS]}))
    st.caption("A ratio is shown as n/a (never 0) when an input is missing or the denominator is zero or negative.")
st.markdown("**Limitations**")
for lim in config.LIMITATIONS:
    st.markdown(f"- {lim}")

# Beyond the Balance Sheet

An explainable screening tool for corporate financial risk indicators among Indian listed companies. It stores company financials in SQLite, calculates six transparent ratios, applies rule-based warning flags with the evidence behind each one, and presents everything in a Streamlit dashboard with optional, verified AI commentary.

> **Screening and analytical aid only.** This is not a credit rating, an investment recommendation or a validated default-prediction model.

## Status of the data (read this first)

| Dataset | Status |
|---|---|
| `data/raw/financials_real.csv` (+ `financials_real_crosschecks.csv`, the log of every automated check) | **Real data**: 5 Indian cement companies (UltraTech, Ambuja, Shree, Dalmia, ACC), consolidated, 26 company-years, FY2020-21 to FY2025-26 (capex for 21 of them). Collected from Screener.in and stockanalysis.com (secondary aggregators) on 19 Oct 2026, cross-checked automatically. 113 inputs across 12 of the 26 company-years were compared with primary filings (`source_verification.csv`, see `docs/source_verification_worksheet.md`): 97 verified, 8 approx, 3 unresolved discrepancies (all Ambuja FY2024-25, a restated year), 5 not like-for-like. 14 company-years are NOT yet checked, so the dataset is not fully verified. One value was corrected from a filing (Ambuja FY2025-26 EBIT, logged in `corrections_log.csv`). Filing text was read by automated extraction, not visually in a PDF viewer. Most other years remain unverified. |
| `data/raw/financials_demo_ILLUSTRATIVE.csv` | **Synthetic.** Three fictional companies (DEMOA/B/C) used for tests and demos. Labelled illustrative throughout the app; never mixed with real data. |

Important caveats (details in `data/raw/SOURCES.md`): Ambuja and ACC changed year-end from December to March, so FY2022-23 is a **15-month period** and their earlier calendar-year periods are not loaded; current assets/liabilities are unavailable for FY2020-21; cash is deliberately blank; EBIT = revenue - (total expenses - finance costs), i.e. before other income and exceptional items; equity excludes non-controlling interests.

## The analysis workflow (what the dashboard walks through)

1. Select a company, basis and year range (comparability notes appear at once).
2. Review performance: six ratios plus operating cash flow, capex and free cash flow.
3. Warnings: each rule shows indicator, observed value, threshold, formula, why it matters, persistence, history, peer context, data quality and follow-up. Signals are labelled breach / deterioration / convergence / conflict / data limitation / inconclusive.
4. Trends and peers (same universe, same basis and year, 12-month periods only, no ranking).
5. Stress test: revenue fall, EBIT-margin fall, optional fixed-cost share; baseline vs scenario; break-even revenue fall.
6. Evidence: primary-source disclosures, source-verification table, unresolved questions, data-quality issues.
7. Analyst summary and CSV export (observed / checked / hypothesis / scenario / limitation kept apart).

See `docs/AUDIT_FINDINGS.md` (issue table), `docs/reconciliation_report.md`, `docs/source_verification_worksheet.md`, `docs/WORKFLOW.md`, `docs/CHANGES.md`, `docs/DEMO_SCRIPT.md`, `docs/INTERVIEW_NOTES.md`.


## Definitions, rules and assumptions in brief

**Ratios** (full table in `docs/data_dictionary.md`): EBIT = revenue - (total expenses - finance costs), i.e. before other income and exceptional items; interest coverage = EBIT / interest; debt-to-equity = total debt / equity (debt includes lease liabilities where checked, equity excludes non-controlling interest); current ratio; OCF / debt; revenue growth (only between consecutive 12-month years); EBIT margin; free cash flow = operating cash flow - capex. A ratio is n/a, never zero, when an input is missing or a denominator is not positive.

**Warning rules** (seven, plus equity sign): low interest coverage, negative operating cash flow, debt up while EBIT down, low current ratio, sustained EBIT-margin decline, sustained revenue decline, negative free cash flow (informational). Every warning shows its threshold and why that threshold was chosen. All thresholds are illustrative analyst settings, not calibrated or validated credit standards; the sensitivity table shows how flags move (current-ratio flags are fragile: 2 / 5 / 6 / 9 company-years at 0.8 / 1.0 / 1.2 / 1.5). No composite score and no ranking.

**Stress test**: revenue fall (%), EBIT-margin fall (percentage points of stressed revenue), optional fixed-cost share. Interest, capex and debt are held fixed; operating cash flow is assumed to fall by exactly the EBIT shortfall. Taxes, working capital, interest changes, financing actions and dividends are not modelled. Outputs are illustrative scenario estimates, not forecasts.

**Observations, hypotheses and scenarios** are kept apart everywhere (including the CSV export): observed (loaded data), checked vs filing, unverified, hypothesis, scenario (not forecast), limitation. Explanations from filings are classified established / possible_explanation / unresolved / not_assessed; a same-period event is never shown as a cause.

**Comparability (added in the third pass)**: peer comparisons now carry a per-company, per-metric status: Comparable / Use with caution / Not comparable / Unverified (see `docs/data_dictionary.md`). Reported numbers are never rescaled. Non-12-month periods (Ambuja and ACC FY2022-23, 15 months) are shown in a separate "Special-period observations" panel; an illustrative annualised revenue (revenue x 12/months) is optional and labelled as not reported. The main peer window is FY2023-24 to FY2025-26 (all 12-month years); FY2020-21 to FY2022-23 is longer-term context. Ambuja and ACC are one corporate group, so peer counts report independent groups. No new companies were added: the dataset is still the same five.

**What has and has not been tested**: 179 automated tests pass on Streamlit 1.66 (the 171 earlier tests also passed on 1.40 and in a clean virtualenv; the 8 new comparability tests were run on 1.66 only); an independent stdlib recomputation agrees with the SQL views and pandas on 287 values; the app was exercised in headless Chromium for all five companies and the demo company (controls, tables, charts, warnings, CSV export). Not tested: live Gemini/Ollama calls, mobile layout, Streamlit 1.30, a human review of every chart. Data: 12 of 26 real company-years have inputs compared with filings; 14 do not; three Ambuja FY2024-25 differences are unresolved.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/run_pipeline.py        # builds data/btb.sqlite from real + demo data, validates, computes ratios and flags
streamlit run app.py                  # dashboard
pytest                                # 179 tests
```

Real data only: `python scripts/run_pipeline.py --real-only`. To rebuild the real CSV after editing a figure: `python scripts/build_real_financials.py`.

## How it works

```
data/raw/*.csv ──► loader ──► financials_raw (verbatim text) ──► financials (INR crore, NULL kept)
                                                                      │
                          validation ◄────────────────────────────────┤
                          ratios: SQL views (v_ratios) + pandas (btb/metrics.py), tested to agree
                                                                      │
                  rules engine (btb/flags.py) ──► flags + sensitivity table
                                                                      │
        evidence packet (btb/evidence.py, every number has an ID) ──► commentary (rules-only or AI)
                                                                      │
                                              verification of IDs, numbers, labels, causal language
                                                                      │
                                                         Streamlit dashboard (app.py)
```

### Ratios (INR crore inputs)

| Metric | Definition | n/a when |
|---|---|---|
| Interest coverage | EBIT / interest expense | interest <= 0 or missing |
| Debt-to-equity | total debt / total equity | equity <= 0 or missing |
| Current ratio | current assets / current liabilities | liabilities <= 0 or missing |
| Operating cash flow / debt | OCF / total debt | debt <= 0 or missing |
| Revenue growth | (revenue - prior revenue) / prior revenue | prior year not the immediately preceding FY |
| EBIT margin | EBIT / revenue | revenue <= 0 or missing |

A ratio is **never** silently set to zero. Missing stays NULL, and the app shows "n/a". Small values keep three decimals (a 0.016x debt-to-equity is not shown as 0.02x), and the coverage and leverage charts label each point with the displayed value.

**Cash-flow context (not a seventh ratio).** Optional `capex` (entered as a positive outflow) gives **free cash flow = operating cash flow - capex**, NaN unless both are present. Interest coverage uses accounting EBIT, so the dashboard adds a "How to read this year" box: for example, a comfortable coverage ratio next to negative operating cash flow is not read as low credit risk; low current ratios, very low debt-to-equity and reported revenue growth each carry a note about what they do not show.

**Not modelled:** debt maturities and repayment schedules, cash and liquid investments, guarantees and contingent liabilities, and any split of revenue growth into volume, price and acquisitions.

### Warning rules (default thresholds are illustrative, adjustable in the sidebar)

`LOW_INTEREST_COVERAGE` (< 1.5x), `NEGATIVE_OPERATING_CASH_FLOW`, `DEBT_UP_EBIT_DOWN`, `LOW_CURRENT_RATIO` (< 1.0x), `SUSTAINED_EBIT_MARGIN_DECLINE` and `SUSTAINED_REVENUE_DECLINE` (2 consecutive declines), plus informational `NEGATIVE_FREE_CASH_FLOW` (heavy expansion capex can cause it) and `NONPOSITIVE_EQUITY`. Every flag records the threshold and the numbers. There is deliberately **no composite score**. A sensitivity table shows how flag counts change under alternative thresholds. Note that a current ratio below 1 can be normal for some business models, so interpret it within the industry.

### AI commentary (optional)

* **Rules-only mode** (default) produces deterministic text from the evidence packet. No AI, no key.
* **AI mode** supports four providers, chosen in the dashboard (details and env vars in `.env.example`):

  | Provider | Cost / privacy |
  |---|---|
  | **Google Gemini API** (`GEMINI_API_KEY`) | Free tier available via Google AI Studio; limits and included models are shown in your account. Hosted service: free tiers may use submitted data to improve products, so send only public data. |
  | **Ollama** (local open-source models: Llama, Qwen, Mistral, ...) | Free, runs on your machine, nothing leaves it. Install Ollama and `ollama pull llama3.1:8b`. Small models follow the JSON format less reliably (the code retries once and the checks show problems). |
  | **OpenAI-compatible endpoint** (`LLM_BASE_URL`, `LLM_MODEL`) | Groq, OpenRouter, LM Studio, vLLM, llama.cpp server, etc. |
  | **Anthropic Claude** (`ANTHROPIC_API_KEY`) | Paid API. |

* Whatever the provider, the model gets only the evidence packet, is told not to compute numbers or use outside knowledge, and must cite evidence IDs. Hosted providers require you to tick a "data is public" confirmation. API keys are read from the environment and sent in headers, never in URLs, logs or error messages.
* After generation, **automatic checks** flag unknown IDs, numbers not found in the cited evidence, causal language in observations, unhedged hypotheses, "documented" claims that do not cite an `established` disclosure (or an external indicator), and predictive wording. These catch some problems, not all, so a human still reviews.
* Every run is stored in `ai_runs` (with the `provider:model` used) and manual-review columns for the evaluation in `docs/evaluation_guide.md`: compare providers and compare against rules-only. **Do not claim the AI improves anything until you have measured it.**
* The provider code is tested against a local HTTP server (request shapes, auth headers, error mapping, retries). **It has not been run against live Gemini or Ollama services** in this build, so try each once with your own key or install.

## Project layout

```
app.py                     Streamlit dashboard
btb/                       config, db, loader, metrics, flags, persistence, assessment, peers, stress, verification, report, validation, evidence, ai_commentary, uihelpers, pipeline
sql/schema.sql             tables with CHECK constraints and foreign keys
sql/views.sql              v_fin and v_ratios (window functions, NULL-safe CASE guards)
sql/analysis_queries.sql   10 named example queries (JOIN, GROUP BY, window, NULL handling)
scripts/run_pipeline.py    CLI to rebuild the database
scripts/make_hand_check_sheet.py  worksheet (data/processed/hand_check_sheet.csv) for verifying ratios against annual reports
scripts/build_real_financials.py  every transcribed real figure, derivations, cross-checks, corrections -> financials_real.csv, corrections_log.csv
scripts/build_source_verification.py  filing values (crore) -> source_verification.csv
scripts/make_verification_worksheet.py  -> docs/source_verification_worksheet.md
scripts/audit_recalc.py    independent stdlib recomputation -> docs/reconciliation_report.md
data/raw/                  inputs + SOURCES.md; data/processed/ holds exported CSVs
docs/                      AUDIT_FINDINGS, reconciliation_report, source_verification_worksheet, WORKFLOW, CHANGES, DEMO_SCRIPT, INTERVIEW_NOTES, data_dictionary, evaluation_guide, report_template
tests/                     179 tests (pytest)
```

SQLite notes: foreign keys are enforced because every connection runs `PRAGMA foreign_keys = ON`; `CHECK` constraints enforce the financial-year format, basis and unit lists.

## Adding real data

1. Read `data/raw/SOURCES.md`. `financials_real.csv` is pre-filled; add rows or correct values there (one row per company, year and basis; blank cells stay NULL) or edit `scripts/build_real_financials.py` and re-run it.
2. Record `definitions_note` and `source` for every row, and keep definitions consistent across companies (especially EBIT, finance costs and whether lease liabilities are in debt).
3. `python scripts/run_pipeline.py --real-only`, then read `data/processed/validation_issues.csv`. Resolve warnings about units, gaps, restatements and large revenue jumps (mergers, changes in reporting period).
4. Hand-check at least one ratio per company against the source statements: run `python scripts/make_hand_check_sheet.py` and fill in `hand_value`, `source_page` and `match_Y_or_N` from the annual report.
5. Optionally add short attributed excerpts to `disclosures.csv` (5 are loaded already) and dated series to `external_indicators.csv`. Excerpts are capped at 600 characters, so paraphrase where you can.

Confirm access before relying on any source (for example, CMIE Prowess DX availability through GIPE is unconfirmed), and re-verify the candidate sample for comparability and restructurings before treating it as final.

## What this project cannot claim

* It does not predict which companies will default, or estimate a probability of default.
* It does not show that any external event caused a company's numbers to change.
* It does not produce validated credit-risk classifications or ratings.
* Five cement companies do not generalise to all Indian listed companies.

## Limitations

* A small purposive sample cannot represent all Indian firms.
* Annual statements are historical; ratios depend on accounting policy and business model.
* Thresholds are illustrative and not empirically validated.
* Screening does not prove distress or predict default.
* External events overlap with other factors; before-and-after patterns do not establish causation.
* AI output can be wrong or unsupported even when it passes automatic checks.
* Not a substitute for professional credit analysis.

## CV wording

Use only what you have actually completed and verified (see section 15 of the project brief). Do not claim predictive accuracy, default prediction, time savings or AI performance unless you have measured them.

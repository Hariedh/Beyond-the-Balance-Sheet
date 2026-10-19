# Beyond the Balance Sheet

An explainable screening tool for corporate financial risk indicators among Indian listed companies. It stores company financials in SQLite, calculates six transparent ratios, applies rule-based warning flags with the evidence behind each one, and presents everything in a Streamlit dashboard with optional, verified AI commentary.

> **Screening and analytical aid only.** This is not a credit rating, an investment recommendation or a validated default-prediction model.

## Status of the data (read this first)

| Dataset | Status |
|---|---|
| `data/raw/financials_real.csv` | **Real data**: 5 Indian cement companies (UltraTech, Ambuja, Shree, Dalmia, ACC), consolidated, 26 company-years, FY2020-21 to FY2025-26. Collected from Screener.in and stockanalysis.com (secondary aggregators) on 19 Oct 2026, cross-checked automatically and spot-checked against two primary filings. **Not yet hand-checked against annual reports.** |
| `data/raw/financials_demo_ILLUSTRATIVE.csv` | **Synthetic.** Three fictional companies (DEMOA/B/C) used for tests and demos. Labelled illustrative throughout the app; never mixed with real data. |

Important caveats (details in `data/raw/SOURCES.md`): Ambuja and ACC changed year-end from December to March, so FY2022-23 is a **15-month period** and their earlier calendar-year periods are not loaded; current assets/liabilities are unavailable for FY2020-21; cash is deliberately blank; EBIT = operating profit - depreciation; equity excludes non-controlling interests.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/run_pipeline.py        # builds data/btb.sqlite from real + demo data, validates, computes ratios and flags
streamlit run app.py                  # dashboard
pytest                                # 96 tests
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

A ratio is **never** silently set to zero. Missing stays NULL, and the app shows "n/a".

### Warning rules (default thresholds are illustrative, adjustable in the sidebar)

`LOW_INTEREST_COVERAGE` (< 1.5x), `NEGATIVE_OPERATING_CASH_FLOW`, `DEBT_UP_EBIT_DOWN`, `LOW_CURRENT_RATIO` (< 1.0x), `SUSTAINED_EBIT_MARGIN_DECLINE` and `SUSTAINED_REVENUE_DECLINE` (2 consecutive declines), plus an informational `NONPOSITIVE_EQUITY`. Every flag records the threshold and the numbers. There is deliberately **no composite score**. A sensitivity table shows how flag counts change under alternative thresholds. Note that a current ratio below 1 can be normal for some business models, so interpret it within the industry.

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
* After generation, **automatic checks** flag unknown IDs, numbers not found in the cited evidence, causal language in observations, unhedged hypotheses, "documented" claims without a disclosure or external indicator, and predictive wording. These catch some problems, not all, so a human still reviews.
* Every run is stored in `ai_runs` (with the `provider:model` used) and manual-review columns for the evaluation in `docs/evaluation_guide.md`: compare providers and compare against rules-only. **Do not claim the AI improves anything until you have measured it.**
* The provider code is tested against a local HTTP server (request shapes, auth headers, error mapping, retries). **It has not been run against live Gemini or Ollama services** in this build, so try each once with your own key or install.

## Project layout

```
app.py                     Streamlit dashboard
btb/                       config, db, loader, metrics, flags, validation, evidence, ai_commentary, pipeline
sql/schema.sql             tables with CHECK constraints and foreign keys
sql/views.sql              v_fin and v_ratios (window functions, NULL-safe CASE guards)
sql/analysis_queries.sql   10 named example queries (JOIN, GROUP BY, window, NULL handling)
scripts/run_pipeline.py    CLI to rebuild the database
scripts/build_real_financials.py  every transcribed real figure, derivations, cross-checks -> financials_real.csv
data/raw/                  inputs + SOURCES.md; data/processed/ holds exported CSVs
docs/                      data_dictionary.md, evaluation_guide.md, report_template.md
tests/                     96 tests (pytest)
```

SQLite notes: foreign keys are enforced because every connection runs `PRAGMA foreign_keys = ON`; `CHECK` constraints enforce the financial-year format, basis and unit lists.

## Adding real data

1. Read `data/raw/SOURCES.md`. `financials_real.csv` is pre-filled; add rows or correct values there (one row per company, year and basis; blank cells stay NULL) or edit `scripts/build_real_financials.py` and re-run it.
2. Record `definitions_note` and `source` for every row, and keep definitions consistent across companies (especially EBIT, finance costs and whether lease liabilities are in debt).
3. `python scripts/run_pipeline.py --real-only`, then read `data/processed/validation_issues.csv`. Resolve warnings about units, gaps, restatements and large revenue jumps (mergers, changes in reporting period).
4. Hand-check at least one ratio per company against the source statements.
5. Optionally add short attributed excerpts to `disclosures.csv` and dated series to `external_indicators.csv`. Excerpts are capped at 600 characters, so paraphrase where you can.

Confirm access before relying on any source (for example, CMIE Prowess DX availability through GIPE is unconfirmed), and re-verify the candidate sample for comparability and restructurings before treating it as final.

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

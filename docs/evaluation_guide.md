# Evaluation guide

The aim is to find out, with evidence, whether the AI commentary adds anything beyond the rules-only summary. Until you have done this, make no claims about AI accuracy or usefulness.

## 1. Verify the calculations (do this first)

1. Pick at least one company-year per company. Open the source statements.
2. Recompute each ratio by hand from the source figures and compare with `v_ratios` / the dashboard.
3. Record the check, for example in a table: company, year, ratio, hand value, tool value, match (Y/N), notes.
4. `pytest` already checks that the SQL views and the pandas code agree and that unit conversion is correct. It cannot check that your **source data entry** is correct. That is your hand-check.

## 2. Generate comparable commentary

For a fixed set of company-years or ranges (for example 5 companies x 1 range):

1. Run **Rules-only** and **AI-assisted** in the dashboard with the same thresholds. Each run is saved to `ai_runs`.
2. The automatic check count (`auto_problem_count`) is a floor on problems, not a measure of correctness.

## 3. Manual review of each AI run

The `model` column records `provider:model` (for example `gemini:gemini-3.5-flash-lite` or `ollama:llama3.1:8b`), so you can compare providers as well as AI vs rules-only.

Read the stored output against the evidence packet and fill in, per run:

| Column in `ai_runs` | How to score |
|---|---|
| `manual_factual_errors` | Count statements whose numbers or direction contradict the packet. |
| `manual_unsupported_claims` | Count statements that go beyond the cited evidence (invented causes, outside facts, undocumented "documented" labels). |
| `manual_usefulness_1to5` | Does it add specific, correct, useful information beyond restating the ratios? 1 = just restates, 5 = clearly helpful follow-up focus. |
| `manual_notes` | Examples of good and bad statements. |

```sql
UPDATE ai_runs SET manual_factual_errors = 0, manual_unsupported_claims = 1,
                   manual_usefulness_1to5 = 3, manual_notes = '...' WHERE run_id = 7;
```

## 4. Compare

```sql
SELECT mode, COALESCE(model, 'rules-only') AS model, COUNT(*) AS runs,
       AVG(auto_problem_count)         AS avg_auto_problems,
       AVG(manual_factual_errors)      AS avg_factual_errors,
       AVG(manual_unsupported_claims)  AS avg_unsupported,
       AVG(manual_usefulness_1to5)     AS avg_usefulness
FROM ai_runs WHERE manual_usefulness_1to5 IS NOT NULL
GROUP BY mode, model;
```

Report the sample size honestly. A handful of runs gives anecdotes, not statistics. Describe what you did and found, including failures.

## 5. What you can and cannot say

You may say: "I checked N AI-generated summaries against the underlying figures and found X factual errors and Y unsupported claims."
Do not say, unless you measured it: that the AI improves accuracy, efficiency or predictive power, or saves time.

## 6. Real-world event analysis checklist (per hypothesis)

1. Which metric changed, and in which year?
2. Is there company-specific evidence (annual report passage, with page reference) in `disclosures.csv`?
3. Is there a dated external series in `external_indicators.csv`?
4. Which parts are documented fact and which are hypothesis?
5. What alternative explanations fit equally well (price, volume, capacity, financing, accounting changes)?
6. Never assert causation from a before-and-after comparison alone.

# Beyond the Balance Sheet: short report (template)

*Replace every bracketed prompt with your own findings from the real data. Delete this line. Do not report results from the illustrative demo data as findings.*

## 1. Research question

Choose one (see the project brief):
* Can financial ratios combined with documented corporate disclosures and economic indicators provide more informative early-warning analysis than financial ratios alone?
* How do selected external shocks relate to changes in financial performance and risk indicators among Indian cement companies? (Only if enough dated, reliable evidence is collected.)

## 2. Sample and data

* Sector and why: [capital intensity, energy and freight exposure, infrastructure demand; or your reason for a different sector].
* Companies and why included or excluded: [list; mention restructurings, mergers, comparability checks].
* Period: [FY..-.. to FY..-..]. Basis: [standalone / consolidated] and why.
* Sources and access: [Prowess DX / annual reports / NSE-BSE filings]. Definitions of EBIT, finance costs, debt: [state them].
* Purposive sample: results do not represent all Indian companies.

## 3. Methodology

* Pipeline: raw CSV -> SQLite (raw preserved) -> cleaned INR-crore table -> validation -> ratios (SQL view and pandas, tested to agree) -> rules.
* Ratios: see README. Edge cases: [how zero, negative and missing values were handled].
* Rules and thresholds: [list, with the rationale for each threshold and the sensitivity results].
* Commentary: [rules-only and/or AI; model; the evidence-packet approach; automatic checks; manual review].

## 4. Results

* Data validation: [issues found and how each was resolved].
* Ratio trends: [what the data show, per company; cite figures and sources].
* Flags: [which rules fired, for whom, and how sensitive they are to thresholds].
* Event analysis: [for each hypothesis: metric, timing, documented company evidence, external data, alternative explanations, and an explicit statement of what is fact vs hypothesis].
* Commentary evaluation: [N runs reviewed; factual errors; unsupported claims; usefulness; honest comparison with rules-only].

## 5. Limitations

[Adapt the list in the README: small purposive sample, historical data, accounting differences, subjective thresholds, no default prediction, causation not established, AI can be wrong, not a credit rating.]

## 6. Future work

[Examples: more companies and sectors, quarterly data, empirically calibrating thresholds against a defined distress event, peer-relative flags, a validated retrieval step for annual-report passages.]

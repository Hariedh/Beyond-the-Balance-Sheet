# Audit findings

Status key: **confirmed** (reproduced in the code or data), **suspected** (plausible, evidence incomplete), **unverified** (could not be checked from available sources). "Fixed" means changed in code; data discrepancies are reported and the loaded values were deliberately NOT altered.

## Verification of the project summary's claims
| Claim | Result |
|---|---|
| 26 real company-years, 80 of 82 automated cross-checks passed | Confirmed from `financials_real.csv` and `financials_real_crosschecks.csv` (the script prints 80/82). |
| Two unresolved FY2022-23 OCF disputes (ACC, Ambuja); 15-month FY2022-23 for both | Confirmed. OCF left blank for those two; 15-month period excluded from YoY and peer medians. |
| Empty `disclosures.csv` and `external_indicators.csv` | Confirmed at start. Disclosures now hold 5 primary-source entries; external indicators remain empty (optional). |
| 109 passing tests | Confirmed at start; now 146. |
| Six ratios, seven rules, SQL views, rules-only mode | Confirmed. |

## Issue table
| # | Type | Status | Issue | Action |
|---|---|---|---|---|
| B1 | Bug (logic) | confirmed | Sustained rules treated missing or non-comparable years as satisfactory / as a gap-free streak. | Fixed: `btb/persistence.py`, statuses persistent / building / new / history_unknown / recovered / ok / not_assessable. |
| B2 | Bug (logic) | confirmed | DEBT_UP_EBIT_DOWN fired on trivial debt increases and on any period length. | Fixed: needs >=10% debt rise, positive prior debt, 12-month periods; SQL query changed to match (parity test). |
| B3 | Bug (display) | confirmed | Ratios near zero (D/E 0.011x for ACC/Ambuja) shown as 0.01x / 0.02x, hiding magnitude. | Fixed: adaptive precision in `fmt_x`. |
| B4 | Bug (display) | confirmed | Negative rupee amounts printed as "₹-1,364 cr". | Fixed: "-₹1,364 cr". |
| B5 | Bug (UX) | confirmed | Evidence text repeated itself ("Threshold breach: Free cash flow: Free cash flow was..."); a metric tile was truncated. | Fixed. |
| B6 | Bug (robustness) | confirmed | `peer_table` raised KeyError on an empty metrics frame. | Fixed with a test. |
| B7 | Operational | confirmed | A stale `btb.sqlite` caused "no such table" after the schema changed. | Fixed: `db_is_stale()` auto-rebuild. |
| B8 | Bug (deprecation) | confirmed | Streamlit `use_container_width` deprecated. | Fixed: `show_df` helper. |
| D1 | Data | confirmed | Ambuja FY2024-25 operating cash flow loaded 2,237 cr vs filing 3,295.17 cr (-32%). | Reported (validation warning). Cause NOT established. Values not altered. |
| D2 | Data | confirmed | Ambuja FY2024-25 current assets (-1.4%) and depreciation (-7.3%) differ from the filing. | Reported, unresolved. |
| D3 | Data | confirmed | Ambuja FY2025-26 EBIT 3,007 vs filing-derived 2,968.53 (+1.3%). | Reported, unresolved. |
| D4 | Data | confirmed | Total debt not comparable with filing borrowings (leases): ACC FY25, Ambuja FY26, Shree FY26, UltraTech FY25 (Dalmia FY25 matched). | Marked unverified; leases appear to be included in the loaded figure (confirmed for Dalmia FY25 only). |
| D5 | Data | confirmed | ACC and Ambuja FY2022-23 is a 15-month period; earlier calendar-year periods not loaded. | Flagged everywhere; excluded from YoY and peer medians. |
| D6 | Data | confirmed | Two FY2022-23 OCF values disputed between sources (ACC, Ambuja). | Left blank, never treated as zero. |
| D7 | Data | confirmed | Only some FY2024-25 / FY2025-26 inputs were checked against filings (61 comparisons); all other years rest on aggregators. | Disclosed in README and app; extend the CSV to widen coverage. |
| D8 | Data | confirmed | Capex comes from an aggregator line for 21 of 26 company-years; verified against the filing's cash-flow statement for 6 company-years (all matched): ACC FY25, Ambuja FY25 and FY26, Dalmia FY25, Shree FY26, UltraTech FY25. | Labelled unverified elsewhere. |
| D9 | Data | confirmed | Cash left blank (aggregator definitions inconsistent). | Documented; no cash-based ratio. |
| D10 | Data | suspected | Aggregator figures may be restated vs the original filing for Ambuja FY2025 (consolidation scope after acquisitions). | Unverified; compare with FY2025-26 comparatives. |
| M1 | Method | confirmed | EBIT suspected to include exceptional items. Result: it excludes other income and exceptional items (checked against UltraTech, Ambuja, Dalmia, Shree, ACC filings). | Definition documented; exceptional items disclosed separately. |
| M2 | Method | confirmed | D/E numerator is consolidated debt while equity excludes non-controlling interest (Ambuja FY26: NCI ~17% of equity). | Documented limitation + disclosure. |
| M3 | Method | confirmed | Thresholds (e.g. coverage 1.5x, current ratio 1.0x) are illustrative, not a credit standard; current ratio < 1 is structural for some firms (UltraTech). | Caveats shown with each warning; sensitivity grid. |
| M4 | Method | confirmed | Sample is tiny (5 companies; only 4 years for Ambuja/ACC): no statistical inference is possible. | Stated in limitations; no model or score added. |
| M5 | Method | confirmed | Strong interest coverage can coexist with negative FCF (ACC, Ambuja FY25) and does not indicate low risk. | "Conflict" signal and inconclusive wording added. |
| M6 | Method | confirmed | Stress model is mechanical: interest, capex and debt fixed; OCF falls by the full EBIT shortfall (no tax shield or working-capital change). | Assumptions shown beside every result. |
| M7 | Method | unverified | Lease liabilities are included in debt for most companies. | Confirmed for Dalmia FY25 only. |
| E1 | Enhancement | done | Persistence, layered assessment, stress test, peer view, disclosures, verification table, CSV report, 7-step workflow. | See `docs/CHANGES.md`. |
| E2 | Enhancement | optional | External indicators (fuel, freight). | Not added: no consistent source obtained. |
| E3 | Enhancement | optional | Verify FY2020-21 to FY2023-24 and the remaining inputs against annual reports. | Not done. |
| E4 | Enhancement | optional | Resolve the Ambuja discrepancies via FY2025-26 annual-report comparatives. | Not done. |

## Not tested / not claimed
* Live Gemini or Ollama calls were not tested (only the rules-only path and offline AI-validation tests).
* Filing values were read by automated text extraction, not viewed in a PDF viewer; page numbers appear only where the text showed them.
* Browser testing: Chromium via Playwright against the running app (see `docs/CHANGES.md` for what was covered).

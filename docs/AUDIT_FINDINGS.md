# Audit findings

Round 2 (final audit) is recorded in the section **Round 2: resolution of discrepancies and final status** at the end. Where a round-1 row below disagrees with it, the round-2 section is current.

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


## Round 2: resolution of discrepancies and final status

Final status vocabulary: Fixed and verified / Fixed but not fully verified / Unresolved - evidence unavailable / Not tested.

| # | Issue | Evidence found | Action | Final status |
|---|---|---|---|---|
| R1 | `show_df()` fell back to calling itself (infinite recursion on `TypeError`) | Reproduced by reading `app.py`: the `except TypeError` branch called `show_df(data, **kwargs)` | Replaced by `btb/uihelpers.show_df` (signature check, different fallback call, no duplicated kwargs); 5 tests incl. fake old/new Streamlit signatures | Fixed and verified for the installed Streamlit 1.66 and by simulated old signatures. Real Streamlit 1.30 run: see Remaining risks |
| R2 | Ambuja FY2025-26 EBIT 3,007 vs filing-derived 2,968.53 (+1.3%) | Audited filing (revenue 40,655.68; expenses 37,910.76; finance 223.61) and the company media release (operating EBITDA 6,539 = 2,968.53 + depreciation 3,570.41). Screener's operating profit (6,577) is about 38 cr above the company's own EBITDA | Corrected to 2,968.53 in `build_real_financials.py`; original kept in `data/raw/corrections_log.csv` with source, reason and date | Fixed and verified (against filing text read by automated extraction). Cause of the aggregator difference not established |
| R3 | Ambuja FY2024-25 revenue (loaded 35,336 vs original filing 35,044.76) | Ambuja's FY2025-26 annual report marks its 2024-25 figures "Restated, refer Note 68(h)"; the restated revenue shown is 35,336, and the media release gives the same 35,336 | No data change: the loaded value equals the company's restated comparative. Original-filing row marked not like-for-like; restated row added and verified | Fixed and verified for revenue and EBITDA (35,336; 5,971) |
| R4 | Ambuja FY2024-25 operating cash flow (-32%), current assets (-1.4%), depreciation (-7.3%) | Same restatement is the probable cause (loaded revenue and EBITDA equal restated figures) but Note 68(h) and the restated statements could not be read (the annual-report extraction stopped before the financial statements; downloads from the shell are blocked) | Not changed. Kept as `discrepancy`; shown in data-quality warnings, Unresolved questions and the report; ratios using them labelled provisional | Unresolved - evidence unavailable |
| R5 | Ambuja FY2024-25 EBIT includes one-time income | Company media release: FY25 EBITDA includes about Rs 826 cr excise refund and Rs 138 cr GST incentive; normalised EBITDA Rs 5,006 cr (14.6%) vs 5,971 reported | Added as an `established` disclosure; peer notes mention it. No adjustment made to loaded EBIT | Fixed and verified (disclosure); EBIT itself deliberately unadjusted |
| R6 | Debt definition / leases | UltraTech FY25 and FY26: borrowings + lease liabilities equal the loaded debt (24,102.18 and 23,755.09). Dalmia FY25, FY26 and Shree FY24 also match with leases included. ACC reports nil borrowings in both years while loaded debt is about Rs 430 cr; Ambuja FY26 (loaded 866 vs borrowings 52.78) and Shree FY26 (1,868 vs 1,593.72) have no lease line on the face of the statements | Definition kept as the aggregators' total debt, now confirmed to include leases for UltraTech, Dalmia and Shree in the years checked; the rest marked not like-for-like; peer notes disclose this | Fixed but not fully verified: inclusion of leases is confirmed for 3 of 5 companies and is implied, not shown, for ACC, Ambuja and Shree FY26 |
| R7 | Verification coverage | 12 of 26 real company-years now have at least one input compared with a filing (was 7); 113 comparisons: 97 verified, 8 approx, 3 discrepancy, 5 not like-for-like | Worksheet lists every company-year including "not yet checked" | Fixed but not fully verified: 14 company-years (FY2020-21 to FY2023-24 for most companies) remain NOT yet checked |
| R8 | ACC and Ambuja FY2022-23 operating cash flow left blank | Sources disagreed and the FY2022-23 filings were not obtained | Left blank; OCF/debt and FCF are n/a; persistence treats them as not assessable | Unresolved - evidence unavailable |
| R9 | 15-month FY2022-23 | Confirmed in the board release (2 May 2023) | Excluded from YoY, peer medians and OCF/debt peer ratio; tested on the shipped data | Fixed and verified |
| R10 | Stress-test wording | Stress FCF assumed OCF falls by the EBIT shortfall with fixed capex but did not say taxes, working capital, interest changes, financing were unmodelled | Assumption text, table labels ("simplified"), UI caption and docs now say so; slider units tested (percent vs percentage points) | Fixed and verified |
| R11 | Warning thresholds had no stated rationale | Thresholds were presented without saying how they were chosen | `Why this threshold` shown with every warning; each rationale states it is illustrative / a sign boundary and not calibrated. Sensitivity run on real data (below) | Fixed and verified |
| R12 | Causal wording (`points to cost or price pressure`, `can reflect expansion`) | Read in `assessment.py` and `metrics.py` | Reworded as hypotheses that need disclosure evidence | Fixed and verified |
| R13 | Disclosure relationship only had two values; a blank was left NULL | | Four classes: established / possible_explanation / unresolved / not_assessed (blank = not_assessed); schema CHECK, loader, report and UI updated | Fixed and verified |
| R14 | AI "documented" label accepted any DISC citation | Validator only checked the prefix | Now requires an `established` disclosure; prompt states the packet has no scenario results; limitation caption shown for rules-only and AI output | Fixed and verified (offline tests). Live Gemini/Ollama never called: Not tested |
| R15 | `external_indicators.csv` empty | Confirmed | Left empty; the UI says so and works | Not tested beyond the empty-file path (nothing invented) |
| R17 | App crashed in the commentary section on older Streamlit (nested expander rejected: 'Expanders may not be nested') | Found by running the app tests under Streamlit 1.40 | Replaced the inner expander with a checkbox | Fixed and verified on 1.40 and 1.66 |
| R18 | Charts: auto-scaled axis made a 0.015x debt-to-equity look like a collapse; 15-month period plotted like a normal year; stress table showed '-0.0%' for a margin change | Seen in the browser | Zero baseline when nothing is negative; non-12-month years labelled on every axis; margin changes shown in points | Fixed and verified by eye in the browser (Ambuja) |
| R16 | UltraTech FY2024-25 PBT: FY2025-26 filing's comparative column shows 7,528.13 whereas the disclosure arithmetic from the FY2024-25 filing gives 7,538.70 | Possible small restatement or extraction error | Not investigated; disclosure keeps the figures it states (exceptional items 97.43 only) | Unresolved - evidence unavailable (no loaded metric uses PBT) |

### Threshold sensitivity on the real data (26 company-years, run 2026-10-20)
* Interest coverage: no company-year is flagged at 1.0x, 1.5x or 2.0x; two (both Dalmia) at 3.0x. Not fragile in the 1.0x-2.0x range, but absence of a flag is not evidence of low risk.
* Current ratio: 2 flagged at 0.8x, 5 at 1.0x, 6 at 1.2x, 9 at 1.5x. Fragile: modest changes alter the result materially, and the flags are mainly UltraTech's structurally low ratio.
* Debt up while EBIT down: 7 / 7 / 6 / 4 company-years at 0% / 5% / 10% / 20% materiality.
* Sustained EBIT-margin decline: 13 company-years at N=1, 5 at N=2, 0 at N=3. Sustained revenue decline: 2 at N=1, 0 at N=2 and 3.

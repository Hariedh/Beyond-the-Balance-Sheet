"""Central configuration: paths, units, field lists and the limitations text."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SQL_DIR = ROOT / "sql"
DB_PATH = Path(os.environ.get("BTB_DB_PATH", DATA_DIR / "btb.sqlite"))

# --- units ------------------------------------------------------------------
# Multiply a value in the given unit by this factor to get INR crore.
#   1 crore = 10,000,000 rupees; 1 lakh = 100,000 rupees; 1 million = 1,000,000 rupees
UNIT_TO_CRORE: dict[str, float] = {
    "rupees": 1e-7,
    "thousands": 1e-4,
    "lakhs": 1e-2,
    "millions": 1e-1,
    "crores": 1.0,
}
UNIT_ALIASES: dict[str, str] = {
    "rupee": "rupees", "inr": "rupees", "rs": "rupees",
    "thousand": "thousands", "000": "thousands", "k": "thousands",
    "lakh": "lakhs", "lac": "lakhs", "lacs": "lakhs",
    "million": "millions", "mn": "millions",
    "crore": "crores", "cr": "crores",
}
BASES = ("standalone", "consolidated")

# --- fields -----------------------------------------------------------------
NUMERIC_FIELDS = (
    "revenue",
    "ebit",
    "interest_expense",
    "total_debt",
    "total_equity",
    "current_assets",
    "current_liabilities",
    "operating_cash_flow",
    "cash_and_equivalents",
)
# Needed for the six ratios; cash is optional.
CORE_FIELDS = NUMERIC_FIELDS[:-1]
# Optional numeric inputs: the CSV column may be absent. Capital expenditure is entered as a
# POSITIVE number (cash outflow); free cash flow = operating cash flow - capex.
OPTIONAL_NUMERIC_FIELDS = ("capex",)
ALL_NUMERIC_FIELDS = (*NUMERIC_FIELDS, *OPTIONAL_NUMERIC_FIELDS)

FINANCIAL_CSV_REQUIRED = ("ticker", "financial_year", "basis", "unit", *NUMERIC_FIELDS)
FINANCIAL_CSV_OPTIONAL = ("capex", "period_months", "definitions_note", "source", "source_url", "notes", "is_illustrative")

# --- default inputs for the pipeline ---------------------------------------
DEFAULT_COMPANY_FILES = (
    RAW_DIR / "companies_candidates.csv",
    RAW_DIR / "companies_demo_ILLUSTRATIVE.csv",
)
DEFAULT_FINANCIAL_FILES = (
    RAW_DIR / "financials_real.csv",
    RAW_DIR / "financials_demo_ILLUSTRATIVE.csv",
)
DEFAULT_DISCLOSURE_FILES = (RAW_DIR / "disclosures.csv",)
DEFAULT_EXTERNAL_FILES = (RAW_DIR / "external_indicators.csv",)
DEFAULT_VERIFICATION_FILES = (RAW_DIR / "source_verification.csv",)

# --- text shown in the app and README ---------------------------------------
DISCLAIMER = (
    "Screening and analytical aid only. This is not a credit rating, an investment "
    "recommendation or a validated default-prediction model."
)

LIMITATIONS = (
    "A small purposive sample cannot represent all Indian firms.",
    "Annual statements are historical and may not reflect current conditions.",
    "Ratios differ by business model and accounting policy; definitions must be harmonised before comparison.",
    "Warning thresholds are illustrative and subjective unless empirically validated.",
    "Financial-ratio screening does not prove distress or predict default.",
    "External and geopolitical events overlap with many other factors; a before-and-after comparison cannot establish causation.",
    "AI commentary can misread data or give plausible but unsupported explanations; every statement must be checked against the cited evidence.",
    "This project is not a substitute for professional credit analysis.",
    "A dashboard can create a false sense of certainty; always read the sources, reporting basis and data-quality notes.",
    "Interest coverage uses accounting EBIT, not cash; it can look comfortable while operating or free cash flow is negative.",
    "Debt is the aggregator's borrowings figure. Debt maturities, guarantees, contingent liabilities and cash are not modelled.",
    "Reported revenue growth mixes price, volume, acquisitions and changes in consolidation scope; the tool does not separate them.",
)

# What this project must not claim (shown in the app and the README).
CANNOT_CLAIM = (
    "It does not predict which companies will default.",
    "It does not estimate a probability of default.",
    "It does not establish that any external event caused a change in a company's finances.",
    "It does not produce validated credit-risk classifications or ratings.",
    "Its findings from five cement companies do not generalise to all Indian listed companies.",
)

#!/usr/bin/env python3
"""Build the SQLite database from CSVs, validate, compute ratios and flags.

Examples
  python scripts/run_pipeline.py                      # default inputs (data/raw/)
  python scripts/run_pipeline.py --real-only          # only your real data
  python scripts/run_pipeline.py --demo-only          # only the illustrative demo data
  python scripts/run_pipeline.py --db /tmp/test.sqlite
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from btb import config  # noqa: E402
from btb.flags import Thresholds  # noqa: E402
from btb.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=config.DB_PATH, help="SQLite file to (re)build")
    p.add_argument("--companies", type=Path, nargs="+", help="company CSV file(s)")
    p.add_argument("--financials", type=Path, nargs="+", help="financials CSV file(s)")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--demo-only", action="store_true", help="load only the illustrative demo data")
    grp.add_argument("--real-only", action="store_true", help="load only the real-data files")
    p.add_argument("--coverage-min", type=float, default=Thresholds().interest_coverage_min)
    p.add_argument("--current-ratio-min", type=float, default=Thresholds().current_ratio_min)
    p.add_argument("--sustained-years", type=int, default=Thresholds().sustained_years)
    args = p.parse_args()

    companies = args.companies or list(config.DEFAULT_COMPANY_FILES)
    financials = args.financials or list(config.DEFAULT_FINANCIAL_FILES)
    if args.demo_only:
        companies = [f for f in companies if "ILLUSTRATIVE" in f.name]
        financials = [f for f in financials if "ILLUSTRATIVE" in f.name]
    elif args.real_only:
        companies = [f for f in companies if "ILLUSTRATIVE" not in f.name]
        financials = [f for f in financials if "ILLUSTRATIVE" not in f.name]

    summary = run_pipeline(
        db_path=args.db, company_files=companies, financial_files=financials,
        thresholds=Thresholds(args.coverage_min, args.current_ratio_min, args.sustained_years),
    )

    print(f"Database: {args.db}")
    for key, value in summary.items():
        print(f"  {key:32s} {value}")
    if summary["illustrative_rows_loaded"]:
        print("\nNOTE: illustrative (synthetic) rows are loaded. They are labelled in the app and "
              "must not be treated as real company data.")
    if summary["issues_error"]:
        print(f"\n{summary['issues_error']} data error(s) logged; see data/processed/validation_issues.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

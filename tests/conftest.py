from __future__ import annotations

import csv
from pathlib import Path

import pytest

from btb import config
from btb.pipeline import run_pipeline

HEADER = ["ticker", "financial_year", "basis", "unit", *config.NUMERIC_FIELDS,
          "definitions_note", "source", "source_url", "notes", "is_illustrative", "period_months"]
COMPANY_HEADER = ["ticker", "name", "industry", "exchange", "notes", "is_illustrative"]


def write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def fin_row(ticker, fy, unit="crores", basis="consolidated", rev="", ebit="", intr="", debt="", eq="",
            ca="", cl="", ocf="", cash="", src="test source", illustrative=0, period=""):
    return [ticker, fy, basis, unit, rev, ebit, intr, debt, eq, ca, cl, ocf, cash, "test defs", src, "", "",
            illustrative, period]


@pytest.fixture
def tmp_inputs(tmp_path):
    """Helper that writes company + financial CSVs into tmp_path and returns paths."""
    def make(companies, fin_rows):
        c = write_csv(tmp_path / "companies.csv", COMPANY_HEADER, companies)
        f = write_csv(tmp_path / "fin.csv", HEADER, fin_rows)
        return c, f
    return make


@pytest.fixture
def run(tmp_path, tmp_inputs):
    """Run the full pipeline on custom rows; returns (db_path, summary)."""
    def _run(companies, fin_rows, thresholds=None):
        c, f = tmp_inputs(companies, fin_rows)
        db = tmp_path / "t.sqlite"
        summary = run_pipeline(db_path=db, company_files=[c], financial_files=[f], disclosure_files=[],
                               external_files=[], export_dir=None, thresholds=thresholds)
        return db, summary
    return _run


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    """Pipeline run on the shipped demo data."""
    db = tmp_path_factory.mktemp("demo") / "demo.sqlite"
    run_pipeline(db_path=db, export_dir=None)
    return db

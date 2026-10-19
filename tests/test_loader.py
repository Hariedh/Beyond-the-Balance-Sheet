from __future__ import annotations

import pytest

from btb import loader
from btb.db import connect, query_df

from conftest import fin_row

CO = [["T1", "Test One", "Cement", "NSE", "", 0]]


@pytest.mark.parametrize("unit,factor", [("rupees", 1e-7), ("thousands", 1e-4), ("lakhs", 1e-2),
                                         ("millions", 1e-1), ("crores", 1.0)])
def test_unit_conversion_factors(unit, factor):
    assert loader.to_crore(1_000_000.0, unit) == pytest.approx(1_000_000.0 * factor)


def test_known_conversions():
    assert loader.to_crore(10_000_000, "rupees") == pytest.approx(1.0)       # 1 crore = 1e7 rupees
    assert loader.to_crore(100, "lakhs") == pytest.approx(1.0)               # 100 lakh = 1 crore
    assert loader.to_crore(10, "millions") == pytest.approx(1.0)             # 10 million = 1 crore
    assert loader.to_crore(None, "crores") is None


@pytest.mark.parametrize("text,expected", [
    ("1,234.5", (1234.5, True)), ("(1,234.5)", (-1234.5, True)), ("-50", (-50.0, True)),
    ("", (None, True)), ("NA", (None, True)), ("n/a", (None, True)), ("-", (None, True)),
    ("abc", (None, False)), ("12x", (None, False)), ("nan", (None, True)),
])
def test_parse_number(text, expected):
    assert loader.parse_number(text) == expected


def test_zero_is_kept_as_zero_not_missing():
    assert loader.parse_number("0") == (0.0, True)


@pytest.mark.parametrize("text,ok", [("FY2020-21", True), ("fy2020-21", True), ("FY1999-00", True),
                                     ("FY2020-22", False), ("2020-21", False), ("FY20-21", False), ("", False)])
def test_financial_year_validation(text, ok):
    assert (loader.normalise_fy(text) is not None) is ok


def test_unit_aliases_and_invalid():
    assert loader.normalise_unit("Crore") == "crores"
    assert loader.normalise_unit("lakh") == "lakhs"
    assert loader.normalise_unit("dollars") is None


def test_pipeline_converts_units_and_preserves_raw(run):
    db, _ = run(CO, [fin_row("T1", "FY2020-21", unit="lakhs", rev="300,000", ebit="45000", intr="9000",
                             debt="100000", eq="180000", ca="90000", cl="80000", ocf="40000", cash="")])
    conn = connect(db)
    f = query_df(conn, "SELECT * FROM financials")
    raw = query_df(conn, "SELECT * FROM financials_raw")
    assert f.loc[0, "revenue_cr"] == pytest.approx(3000.0)
    assert f.loc[0, "total_debt_cr"] == pytest.approx(1000.0)
    assert f.loc[0, "original_unit"] == "lakhs"
    assert raw.loc[0, "revenue"] == "300,000"          # raw text preserved verbatim
    assert f["cash_cr"].isna().all()                    # missing stays NULL, not 0


def test_bad_rows_rejected_and_logged(run):
    rows = [
        fin_row("T1", "FY2020-21", rev="100", ebit="10"),
        fin_row("T1", "FY2020-21", rev="100", ebit="10"),          # duplicate
        fin_row("T1", "2021-22", rev="100", ebit="10"),            # bad FY
        fin_row("T1", "FY2022-23", unit="dollars", rev="100"),     # bad unit
        fin_row("T1", "FY2023-24", basis="group", rev="100"),      # bad basis
        fin_row("NOPE", "FY2020-21", rev="100"),                   # unknown ticker
    ]
    db, summary = run(CO, rows)
    assert summary["financial_rows_loaded"] == 1
    assert summary["financial_rows_rejected"] == 5
    conn = connect(db)
    checks = set(query_df(conn, "SELECT check_name FROM validation_issues WHERE severity = 'error'")["check_name"])
    assert {"duplicate_company_year", "invalid_financial_year", "invalid_unit", "invalid_basis",
            "unknown_ticker"} <= checks
    assert query_df(conn, "SELECT COUNT(*) AS n FROM financials_raw").loc[0, "n"] == 6   # raw keeps everything


def test_period_months_default_and_validation(run):
    db, summary = run(CO, [
        fin_row("T1", "FY2020-21", rev="100"),                       # blank -> 12
        fin_row("T1", "FY2021-22", rev="100", period="15"),
        fin_row("T1", "FY2022-23", rev="100", period="abc"),         # rejected
        fin_row("T1", "FY2023-24", rev="100", period="0"),           # rejected
    ])
    conn = connect(db)
    got = dict(query_df(conn, "SELECT financial_year, period_months FROM financials").values)
    assert got == {"FY2020-21": 12, "FY2021-22": 15}
    assert summary["financial_rows_rejected"] == 2
    checks = set(query_df(conn, "SELECT check_name FROM validation_issues WHERE severity = 'error'")["check_name"])
    assert "invalid_period_months" in checks
    info = set(query_df(conn, "SELECT check_name FROM validation_issues WHERE severity = 'info'")["check_name"])
    assert "non_standard_period" in info


def test_unparseable_number_becomes_null_and_is_logged(run):
    db, _ = run(CO, [fin_row("T1", "FY2020-21", rev="100", ebit="ten", intr="5")])
    conn = connect(db)
    f = query_df(conn, "SELECT ebit_cr FROM financials")
    assert f["ebit_cr"].isna().all()
    issues = query_df(conn, "SELECT * FROM validation_issues WHERE check_name = 'unparseable_number'")
    assert len(issues) == 1 and issues.loc[0, "field"] == "ebit"


def test_blank_template_rows_are_skipped(run):
    db, summary = run(CO, [fin_row("T1", "FY2020-21"), fin_row("T1", "FY2021-22", rev="100")])
    assert summary["financial_rows_blank_skipped"] == 1
    assert summary["financial_rows_loaded"] == 1


def test_database_constraints_enforced(tmp_path):
    from btb.db import init_db
    conn = connect(tmp_path / "c.sqlite")
    init_db(conn)
    conn.execute("INSERT INTO companies (ticker, name, industry) VALUES ('X','X','C')")
    with pytest.raises(Exception):   # bad FY pattern
        conn.execute("INSERT INTO financials (company_id, financial_year, basis, original_unit) "
                     "VALUES (1, 'FY2020-22', 'consolidated', 'crores')")
    with pytest.raises(Exception):   # bad basis
        conn.execute("INSERT INTO financials (company_id, financial_year, basis, original_unit) "
                     "VALUES (1, 'FY2020-21', 'group', 'crores')")
    with pytest.raises(Exception):   # foreign key to missing company (needs PRAGMA foreign_keys = ON)
        conn.execute("INSERT INTO financials (company_id, financial_year, basis, original_unit) "
                     "VALUES (99, 'FY2020-21', 'consolidated', 'crores')")

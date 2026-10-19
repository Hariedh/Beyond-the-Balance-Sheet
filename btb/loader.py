"""CSV loaders: raw preservation, unit conversion and row-level validation.

Principles
  * Every financial CSV row is stored verbatim (as text) in financials_raw.
  * Missing values stay NULL. Unparseable values become NULL *and* are logged;
    nothing is ever converted to zero.
  * Rows that cannot be trusted structurally (unknown ticker, bad financial
    year, basis or unit, duplicate key) are rejected and logged.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

from . import config

FY_RE = re.compile(r"^FY(\d{4})-(\d{2})$")
MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-", "--", "—", "–"}
MAX_EXCERPT_CHARS = 600


@dataclass
class LoadReport:
    rows_read: int = 0
    rows_loaded: int = 0
    rows_blank_skipped: int = 0
    rows_rejected: int = 0
    issues: list[dict] = field(default_factory=list)

    def add_issue(self, severity: str, check_name: str, detail: str, *, ticker=None,
                  financial_year=None, field_name=None, source_file=None) -> None:
        self.issues.append({
            "severity": severity, "check_name": check_name, "ticker": ticker,
            "financial_year": financial_year, "field": field_name,
            "detail": detail, "source_file": source_file,
        })

    def merge(self, other: "LoadReport") -> None:
        self.rows_read += other.rows_read
        self.rows_loaded += other.rows_loaded
        self.rows_blank_skipped += other.rows_blank_skipped
        self.rows_rejected += other.rows_rejected
        self.issues.extend(other.issues)


# --- parsing helpers ---------------------------------------------------------
def parse_number(text: str | None) -> tuple[float | None, bool]:
    """Parse a numeric string. Returns (value, ok).

    ok=True with value=None means 'legitimately missing'.
    ok=False means the text was present but not a number.
    Accepts thousands separators and accounting negatives such as (1,234.5).
    """
    if text is None:
        return None, True
    s = str(text).strip()
    if s.lower() in MISSING_TOKENS:
        return None, True
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    try:
        value = float(s)
    except ValueError:
        return None, False
    if value != value or value in (float("inf"), float("-inf")):
        return None, False
    return (-value if negative else value), True


def normalise_fy(text: str | None) -> str | None:
    """Return a valid 'FY2020-21' string or None."""
    if text is None:
        return None
    s = str(text).strip().upper().replace("–", "-").replace("—", "-")
    m = FY_RE.match(s)
    if not m:
        return None
    if (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        return None
    return s


def normalise_unit(text: str | None) -> str | None:
    if text is None:
        return None
    s = str(text).strip().lower()
    s = config.UNIT_ALIASES.get(s, s)
    return s if s in config.UNIT_TO_CRORE else None


def normalise_basis(text: str | None) -> str | None:
    if text is None:
        return None
    s = str(text).strip().lower()
    return s if s in config.BASES else None


def to_crore(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return round(value * config.UNIT_TO_CRORE[unit], 6)


def _read_csv(path: Path, required: Iterable[str], report: LoadReport) -> pd.DataFrame | None:
    if not path.exists():
        report.add_issue("warning", "file_not_found", f"{path} does not exist; skipped.",
                         source_file=path.name)
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing required column(s): {', '.join(missing)}")
    return df


def _flag01(text: str | None) -> int:
    return 1 if str(text or "").strip().lower() in {"1", "true", "yes", "y"} else 0


# --- companies ---------------------------------------------------------------
def load_companies(conn: sqlite3.Connection, paths: Iterable[Path]) -> LoadReport:
    report = LoadReport()
    for path in map(Path, paths):
        df = _read_csv(path, ("ticker", "name", "industry"), report)
        if df is None:
            continue
        for i, row in df.iterrows():
            report.rows_read += 1
            ticker = row["ticker"].strip().upper()
            if not ticker or not row["name"].strip() or not row["industry"].strip():
                report.rows_rejected += 1
                report.add_issue("error", "company_incomplete",
                                 f"Row {i + 2}: ticker, name and industry are required.",
                                 ticker=ticker or None, source_file=path.name)
                continue
            try:
                conn.execute(
                    "INSERT INTO companies (ticker, name, industry, exchange, notes, is_illustrative) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (ticker, row["name"].strip(), row["industry"].strip(),
                     row.get("exchange", "").strip() or None,
                     row.get("notes", "").strip() or None,
                     _flag01(row.get("is_illustrative"))),
                )
                report.rows_loaded += 1
            except sqlite3.IntegrityError:
                report.rows_rejected += 1
                report.add_issue("error", "duplicate_company", f"Ticker {ticker} already loaded.",
                                 ticker=ticker, source_file=path.name)
    conn.commit()
    return report


# --- financials --------------------------------------------------------------
def load_financials(conn: sqlite3.Connection, paths: Iterable[Path]) -> LoadReport:
    report = LoadReport()
    tickers = {r["ticker"]: r["company_id"] for r in conn.execute("SELECT ticker, company_id FROM companies")}
    seen: set[tuple[int, str, str]] = set()

    for path in map(Path, paths):
        df = _read_csv(path, config.FINANCIAL_CSV_REQUIRED, report)
        if df is None:
            continue
        for col in config.FINANCIAL_CSV_OPTIONAL:
            if col not in df.columns:
                df[col] = ""

        for i, row in df.iterrows():
            src_row = i + 2  # header is line 1
            report.rows_read += 1

            # 1) preserve the raw row verbatim
            cur = conn.execute(
                "INSERT INTO financials_raw (source_file, source_row, ticker, financial_year, basis, unit, "
                "period_months, revenue, ebit, interest_expense, total_debt, total_equity, current_assets, "
                "current_liabilities, operating_cash_flow, cash_and_equivalents, capex, definitions_note, "
                "source, source_url, notes, is_illustrative) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (path.name, src_row, row["ticker"], row["financial_year"], row["basis"], row["unit"],
                 row["period_months"],
                 *[row[f] for f in config.ALL_NUMERIC_FIELDS],
                 row["definitions_note"], row["source"], row["source_url"], row["notes"],
                 row["is_illustrative"]),
            )
            raw_id = cur.lastrowid

            ticker = row["ticker"].strip().upper()
            fy_text = row["financial_year"].strip()

            # 2) structural checks -> reject
            numeric_raw = {f: row[f] for f in config.ALL_NUMERIC_FIELDS}
            all_blank = all(str(v).strip().lower() in MISSING_TOKENS for v in numeric_raw.values())
            if all_blank:
                report.rows_blank_skipped += 1
                report.add_issue("info", "blank_row_skipped",
                                 f"Row {src_row} has no numeric values (template row); not loaded.",
                                 ticker=ticker or None, financial_year=fy_text or None,
                                 source_file=path.name)
                continue

            company_id = tickers.get(ticker)
            fy = normalise_fy(fy_text)
            basis = normalise_basis(row["basis"])
            unit = normalise_unit(row["unit"])
            problems = []
            if company_id is None:
                problems.append(("unknown_ticker", f"Ticker '{ticker}' is not in the companies table."))
            if fy is None:
                problems.append(("invalid_financial_year",
                                 f"'{fy_text}' is not a valid financial year (expected e.g. FY2020-21)."))
            if basis is None:
                problems.append(("invalid_basis", f"Basis '{row['basis']}' must be standalone or consolidated."))
            if unit is None:
                problems.append(("invalid_unit",
                                 f"Unit '{row['unit']}' must be one of {', '.join(config.UNIT_TO_CRORE)}."))
            period_text = row["period_months"].strip()
            period_months = 12
            if period_text:
                pm, pm_ok = parse_number(period_text)
                if not pm_ok or pm is None or int(pm) != pm or not 1 <= int(pm) <= 24:
                    problems.append(("invalid_period_months",
                                     f"period_months '{period_text}' must be a whole number between 1 and 24."))
                else:
                    period_months = int(pm)
            if problems:
                report.rows_rejected += 1
                for check, detail in problems:
                    report.add_issue("error", check, f"Row {src_row} rejected: {detail}",
                                     ticker=ticker or None, financial_year=fy_text or None,
                                     source_file=path.name)
                continue

            key = (company_id, fy, basis)
            if key in seen:
                report.rows_rejected += 1
                report.add_issue("error", "duplicate_company_year",
                                 f"Row {src_row} rejected: {ticker} {fy} ({basis}) already loaded.",
                                 ticker=ticker, financial_year=fy, source_file=path.name)
                continue
            seen.add(key)

            # 3) parse numbers; keep NULL on failure and log it
            values: dict[str, float | None] = {}
            for fname, text in numeric_raw.items():
                value, ok = parse_number(text)
                if not ok:
                    report.add_issue("error", "unparseable_number",
                                     f"Row {src_row}: '{text}' is not a number; stored as NULL.",
                                     ticker=ticker, financial_year=fy, field_name=fname,
                                     source_file=path.name)
                values[fname] = to_crore(value, unit)

            conn.execute(
                "INSERT INTO financials (company_id, financial_year, basis, revenue_cr, ebit_cr, "
                "interest_expense_cr, total_debt_cr, total_equity_cr, current_assets_cr, "
                "current_liabilities_cr, operating_cash_flow_cr, cash_cr, capex_cr, original_unit, period_months, "
                "definitions_note, source, source_url, notes, is_illustrative, raw_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (company_id, fy, basis, values["revenue"], values["ebit"], values["interest_expense"],
                 values["total_debt"], values["total_equity"], values["current_assets"],
                 values["current_liabilities"], values["operating_cash_flow"],
                 values["cash_and_equivalents"], values["capex"], unit, period_months,
                 row["definitions_note"].strip() or None, row["source"].strip() or None,
                 row["source_url"].strip() or None, row["notes"].strip() or None,
                 _flag01(row["is_illustrative"]), raw_id),
            )
            report.rows_loaded += 1
    conn.commit()
    return report


# --- disclosures and external indicators ------------------------------------
def load_disclosures(conn: sqlite3.Connection, paths: Iterable[Path]) -> LoadReport:
    report = LoadReport()
    tickers = {r["ticker"]: r["company_id"] for r in conn.execute("SELECT ticker, company_id FROM companies")}
    for path in map(Path, paths):
        df = _read_csv(path, ("ticker", "excerpt", "source_doc"), report)
        if df is None:
            continue
        for i, row in df.iterrows():
            if not any(str(v).strip() for v in row.values):
                continue
            report.rows_read += 1
            ticker = row["ticker"].strip().upper()
            excerpt = row["excerpt"].strip()
            if ticker not in tickers or not excerpt or not row["source_doc"].strip():
                report.rows_rejected += 1
                report.add_issue("error", "disclosure_rejected",
                                 f"Row {i + 2}: needs a known ticker, an excerpt and a source_doc.",
                                 ticker=ticker or None, source_file=path.name)
                continue
            if len(excerpt) > MAX_EXCERPT_CHARS:
                excerpt = excerpt[:MAX_EXCERPT_CHARS].rstrip() + "..."
                report.add_issue("warning", "excerpt_truncated",
                                 f"Row {i + 2}: excerpt truncated to {MAX_EXCERPT_CHARS} characters. "
                                 "Keep excerpts short and paraphrase where possible.",
                                 ticker=ticker, source_file=path.name)
            fy = normalise_fy(row.get("financial_year", "")) if row.get("financial_year", "").strip() else None
            relationship = row.get("relationship", "").strip().lower() or None
            if relationship not in (None, "established", "possible_explanation"):
                report.add_issue("warning", "invalid_relationship",
                                 f"Row {i + 2}: relationship '{relationship}' is not 'established' or "
                                 "'possible_explanation'; stored as possible_explanation (the safer reading).",
                                 ticker=ticker, source_file=path.name)
                relationship = "possible_explanation"
            conn.execute(
                "INSERT INTO disclosures (company_id, financial_year, topic, excerpt, source_doc, page_ref, "
                "source_url, publication_date, related_metric, relationship, is_illustrative) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (tickers[ticker], fy, row.get("topic", "").strip() or None, excerpt,
                 row["source_doc"].strip(), row.get("page_ref", "").strip() or None,
                 row.get("source_url", "").strip() or None,
                 row.get("publication_date", "").strip() or None,
                 row.get("related_metric", "").strip() or None, relationship,
                 _flag01(row.get("is_illustrative"))),
            )
            report.rows_loaded += 1
    conn.commit()
    return report


def load_external(conn: sqlite3.Connection, paths: Iterable[Path]) -> LoadReport:
    report = LoadReport()
    for path in map(Path, paths):
        df = _read_csv(path, ("series_name", "period", "value", "source"), report)
        if df is None:
            continue
        for i, row in df.iterrows():
            if not any(str(v).strip() for v in row.values):
                continue
            report.rows_read += 1
            value, ok = parse_number(row["value"])
            if (not ok) or value is None or not row["series_name"].strip() \
                    or not row["period"].strip() or not row["source"].strip():
                report.rows_rejected += 1
                report.add_issue("error", "external_rejected",
                                 f"Row {i + 2}: needs series_name, period, a numeric value and a source.",
                                 source_file=path.name)
                continue
            conn.execute(
                "INSERT INTO external_indicators (series_name, period, value, unit, source, source_url, "
                "notes, is_illustrative) VALUES (?,?,?,?,?,?,?,?)",
                (row["series_name"].strip(), row["period"].strip(), value,
                 row.get("unit", "").strip() or None, row["source"].strip(),
                 row.get("source_url", "").strip() or None, row.get("notes", "").strip() or None,
                 _flag01(row.get("is_illustrative"))),
            )
            report.rows_loaded += 1
    conn.commit()
    return report


# --- source verification ------------------------------------------------------
VERIFICATION_STATUSES = ("verified", "approx", "discrepancy", "unverified")


def load_source_verification(conn: sqlite3.Connection, paths: Iterable[Path]) -> LoadReport:
    """Load loaded-value-vs-filing comparisons. A discrepancy is surfaced as a data-quality warning."""
    report = LoadReport()
    tickers = {r["ticker"]: r["company_id"] for r in conn.execute("SELECT ticker, company_id FROM companies")}
    for path in map(Path, paths):
        df = _read_csv(path, ("ticker", "financial_year", "item", "status", "source_doc"), report)
        if df is None:
            continue
        for i, row in df.iterrows():
            if not any(str(v).strip() for v in row.values):
                continue
            report.rows_read += 1
            ticker = row["ticker"].strip().upper()
            fy = normalise_fy(row["financial_year"])
            status = row["status"].strip().lower()
            if ticker not in tickers or fy is None or status not in VERIFICATION_STATUSES or not row["item"].strip():
                report.rows_rejected += 1
                report.add_issue("error", "verification_rejected",
                                 f"Row {i + 2}: needs a known ticker, a valid financial year, an item and a status "
                                 f"in {VERIFICATION_STATUSES}.", ticker=ticker or None, source_file=path.name)
                continue
            vals = [parse_number(row.get(c, ""))[0] for c in ("app_value_cr", "filing_value_cr", "difference_cr", "difference_pct")]
            conn.execute(
                "INSERT INTO source_verification (company_id, financial_year, basis, item, app_value_cr, "
                "filing_value_cr, difference_cr, difference_pct, status, method, source_doc, publication_date, "
                "location, source_url, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tickers[ticker], fy, (normalise_basis(row.get("basis", "")) or "consolidated"), row["item"].strip(),
                 *vals, status, row.get("method", "").strip() or None, row["source_doc"].strip(),
                 row.get("publication_date", "").strip() or None, row.get("location", "").strip() or None,
                 row.get("source_url", "").strip() or None, row.get("notes", "").strip() or None))
            report.rows_loaded += 1
            if status == "discrepancy":
                report.add_issue("warning", "source_discrepancy",
                                 f"{row['item']}: loaded {vals[0]} vs filing {vals[1]} (difference {vals[3]}%). "
                                 "Unresolved; the loaded value was not changed.",
                                 ticker=ticker, financial_year=fy, field_name=row["item"].strip(), source_file=path.name)
    conn.commit()
    return report

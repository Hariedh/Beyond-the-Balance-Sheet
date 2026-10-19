"""End-to-end pipeline: CSV -> SQLite -> validation -> metrics -> flags -> exports."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from . import config
from .db import connect, init_db, load_fin
from .flags import Thresholds, evaluate_flags
from .loader import LoadReport, load_companies, load_disclosures, load_external, load_financials
from .metrics import compute_metrics, ratio_notes
from .validation import issues_to_frame, validate_financials


def store_issues(conn, issues: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO validation_issues (severity, check_name, ticker, financial_year, field, detail, source_file) "
        "VALUES (:severity, :check_name, :ticker, :financial_year, :field, :detail, :source_file)",
        issues,
    )
    conn.commit()


def store_flags(conn, flags: pd.DataFrame) -> None:
    if flags.empty:
        return
    conn.executemany(
        "INSERT INTO flags (company_id, basis, financial_year, rule_id, rule_description, severity, "
        "threshold_used, observed_value, evidence, is_illustrative) "
        "VALUES (:company_id, :basis, :financial_year, :rule_id, :rule_description, :severity, "
        ":threshold_used, :observed_value, :evidence, :is_illustrative)",
        flags.astype(object).where(flags.notna(), None).to_dict("records"),
    )
    conn.commit()


def run_pipeline(
    db_path: str | Path | None = None,
    company_files: Iterable[Path] = config.DEFAULT_COMPANY_FILES,
    financial_files: Iterable[Path] = config.DEFAULT_FINANCIAL_FILES,
    disclosure_files: Iterable[Path] = config.DEFAULT_DISCLOSURE_FILES,
    external_files: Iterable[Path] = config.DEFAULT_EXTERNAL_FILES,
    export_dir: Path | None = config.PROCESSED_DIR,
    thresholds: Thresholds | None = None,
) -> dict:
    thresholds = thresholds or Thresholds()
    conn = connect(db_path)
    try:
        init_db(conn)

        report = LoadReport()
        companies_report = load_companies(conn, company_files)
        fin_report = load_financials(conn, financial_files)
        disc_report = load_disclosures(conn, disclosure_files)
        ext_report = load_external(conn, external_files)
        for r in (companies_report, fin_report, disc_report, ext_report):
            report.merge(r)

        fin = load_fin(conn)
        issues = report.issues + validate_financials(fin)
        store_issues(conn, issues)

        metrics = compute_metrics(fin)
        flags = evaluate_flags(metrics, thresholds)
        store_flags(conn, flags)

        if export_dir is not None and not metrics.empty:
            export_dir = Path(export_dir)
            export_dir.mkdir(parents=True, exist_ok=True)
            metrics["ratio_notes"] = metrics.apply(ratio_notes, axis=1)
            fin.to_csv(export_dir / "financials_clean.csv", index=False)
            metrics.to_csv(export_dir / "ratios.csv", index=False)
            flags.to_csv(export_dir / "flags.csv", index=False)
            issues_to_frame(issues).to_csv(export_dir / "validation_issues.csv", index=False)

        return {
            "companies_loaded": companies_report.rows_loaded,
            "financial_rows_read": fin_report.rows_read,
            "financial_rows_loaded": fin_report.rows_loaded,
            "financial_rows_blank_skipped": fin_report.rows_blank_skipped,
            "financial_rows_rejected": fin_report.rows_rejected,
            "disclosures_loaded": disc_report.rows_loaded,
            "external_indicators_loaded": ext_report.rows_loaded,
            "flags": len(flags),
            "issues_error": sum(i["severity"] == "error" for i in issues),
            "issues_warning": sum(i["severity"] == "warning" for i in issues),
            "issues_info": sum(i["severity"] == "info" for i in issues),
            "illustrative_rows_loaded": int(fin["is_illustrative"].sum()) if not fin.empty else 0,
        }
    finally:
        conn.close()

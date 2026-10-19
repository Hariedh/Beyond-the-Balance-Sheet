"""SQLite helpers. Every connection enables foreign-key enforcement."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

import pandas as pd

from . import config


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = str(db_path if db_path is not None else config.DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """(Re)create all data tables and views. ai_runs is preserved."""
    conn.executescript((config.SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript((config.SQL_DIR / "views.sql").read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()


def query_df(conn: sqlite3.Connection, sql: str, params: Sequence | None = None) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params or ())


def load_fin(conn: sqlite3.Connection) -> pd.DataFrame:
    """Cleaned financials joined with company metadata (INR crore)."""
    return query_df(conn, "SELECT * FROM v_fin ORDER BY ticker, basis, fy_start")


def split_sql_queries(text: str) -> dict[str, str]:
    """Split analysis_queries.sql into {name: sql} using '-- name:' markers."""
    queries: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("-- name:"):
            current = line.split(":", 1)[1].strip()
            queries[current] = []
        elif current is not None:
            queries[current].append(line)
    return {k: "\n".join(v).strip() for k, v in queries.items()}

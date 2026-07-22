"""DuckDB warehouse access layer shared by pipeline tasks."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from nba_duckdb.config import load_env_file
from nba_duckdb.sql.schema import schema_sql_text

logger = logging.getLogger("nba_duckdb.db")

DEFAULT_DUCKDB_PATH = "data/warehouse/nba.duckdb"
DEFAULT_DATABASE_URL = DEFAULT_DUCKDB_PATH
LOCK_RETRY_ATTEMPTS = 30
LOCK_RETRY_DELAY_SECONDS = 2.0
LIGHTWEIGHT_MIGRATIONS = (
    (
        "ops",
        "pipeline_runs",
        "ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS degraded_count INTEGER DEFAULT 0",
    ),
    (
        "ops",
        "pipeline_runs",
        "ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS deferred_count INTEGER DEFAULT 0",
    ),
    (
        "ops",
        "task_runs",
        "ALTER TABLE ops.task_runs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP",
    ),
    (
        "ops",
        "task_runs",
        "ALTER TABLE ops.task_runs ADD COLUMN IF NOT EXISTS worker_pid INTEGER",
    ),
    (
        "ops",
        "task_runs",
        "ALTER TABLE ops.task_runs ADD COLUMN IF NOT EXISTS progress_json JSON",
    ),
    (
        "bronze",
        "play_by_play",
        "ALTER TABLE bronze.play_by_play ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'unknown'",
    ),
    (
        "bronze",
        "boxscores",
        "ALTER TABLE bronze.boxscores ADD COLUMN IF NOT EXISTS traditional_source TEXT DEFAULT 'unknown'",
    ),
    (
        "bronze",
        "boxscores",
        "ALTER TABLE bronze.boxscores ADD COLUMN IF NOT EXISTS advanced_source TEXT DEFAULT 'unknown'",
    ),
    (
        "bronze",
        "schedule",
        "ALTER TABLE bronze.schedule ADD COLUMN IF NOT EXISTS league_id TEXT DEFAULT '00'",
    ),
    (
        "bronze",
        "schedule",
        "ALTER TABLE bronze.schedule ALTER COLUMN league_id SET NOT NULL",
    ),
    (
        "bronze",
        "schedule",
        "ALTER TABLE bronze.schedule ADD COLUMN IF NOT EXISTS competition TEXT DEFAULT 'nba'",
    ),
    (
        "bronze",
        "schedule",
        "ALTER TABLE bronze.schedule ALTER COLUMN competition SET NOT NULL",
    ),
)


class DuckDBLockTimeoutError(RuntimeError):
    """Raised when the warehouse remains locked beyond the bounded retry window."""


def get_database_url() -> str:
    load_env_file()
    return (
        os.environ.get("NBA_DUCKDB_DATABASE_URL")
        or os.environ.get("NBA_DUCKDB_PATH")
        or DEFAULT_DUCKDB_PATH
    )


def _database_path() -> Path:
    raw = get_database_url()
    if raw.startswith("duckdb:///"):
        raw = raw.removeprefix("duckdb:///")
    elif raw.startswith("duckdb://"):
        raw = raw.removeprefix("duckdb://")
    return Path(raw)


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _coerce_value(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value)
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _decode_row(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {
        column: _decode_value(value)
        for column, value in zip(columns, row, strict=False)
    }


def _coerce_params(params: Iterable[Any] | None) -> list[Any]:
    return [_coerce_value(value) for value in params or []]


def _expand_list_param(value: Any) -> tuple[str, list[Any]]:
    values = list(value) if isinstance(value, list | tuple | set) else [value]
    if not values:
        return "NULL", []
    return ", ".join("?" for _ in values), [_coerce_value(item) for item in values]


def _translate_sql(sql_text: str, params: Iterable[Any] | None = None) -> tuple[str, list[Any]]:
    """Translate the internal DB-API convenience surface used by pipeline tasks."""
    param_values = list(params or [])
    output_params: list[Any] = []
    param_index = 0

    sql_text = re.sub(
        r"to_date\(([^,]+),\s*'MM/DD/YYYY HH24:MI:SS'\)",
        r"strptime(\1, '%m/%d/%Y %H:%M:%S')",
        sql_text,
        flags=re.IGNORECASE,
    )

    def replace_any(_: re.Match[str]) -> str:
        nonlocal param_index
        if param_index >= len(param_values):
            raise ValueError("Not enough parameters supplied for ANY(%s)")
        placeholders, expanded = _expand_list_param(param_values[param_index])
        param_index += 1
        output_params.extend(expanded)
        return f"IN ({placeholders})"

    sql_text = re.sub(r"=\s*ANY\(\s*%s\s*\)", replace_any, sql_text, flags=re.IGNORECASE)

    def replace_placeholder(_: re.Match[str]) -> str:
        nonlocal param_index
        if param_index >= len(param_values):
            raise ValueError("Not enough parameters supplied for %s placeholder")
        output_params.append(_coerce_value(param_values[param_index]))
        param_index += 1
        return "?"

    sql_text = re.sub(r"%s", replace_placeholder, sql_text)
    if param_index < len(param_values):
        output_params.extend(_coerce_params(param_values[param_index:]))
    return sql_text, output_params


class DuckCursor(AbstractContextManager["DuckCursor"]):
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self._conn = conn
        self._result: duckdb.DuckDBPyConnection | None = None
        self.description: Sequence[Any] | None = None
        self.rowcount = -1

    def __enter__(self) -> DuckCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql_text: str, params: Iterable[Any] | None = None) -> DuckCursor:
        translated_sql, translated_params = _translate_sql(sql_text, params)
        self._result = self._conn.execute(translated_sql, translated_params)
        self.description = self._result.description
        self.rowcount = -1
        return self

    def executemany(self, sql_text: str, rows: Iterable[Iterable[Any]]) -> DuckCursor:
        translated_sql, translated_params = _translate_sql(sql_text, [])
        if translated_params:
            raise ValueError("executemany does not support pre-bound translated parameters")
        prepared_rows = [tuple(_coerce_value(value) for value in row) for row in rows]
        self._result = self._conn.executemany(translated_sql, prepared_rows)
        self.description = self._result.description
        self.rowcount = len(prepared_rows)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        if self._result is None or self.description is None:
            return None
        row = self._result.fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self.description]
        return _decode_row(columns, row)

    def fetchall(self) -> list[dict[str, Any]]:
        if self._result is None or self.description is None:
            return []
        columns = [column[0] for column in self.description]
        return [_decode_row(columns, row) for row in self._result.fetchall()]


def _is_lock_error(exc: Exception) -> bool:
    message = str(exc)
    return "Could not set lock on file" in message or "Conflicting lock" in message


class DuckConnection(AbstractContextManager["DuckConnection"]):
    def __init__(self, path: Path, *, read_only: bool = False):
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(LOCK_RETRY_ATTEMPTS):
            try:
                self._conn = duckdb.connect(str(path), read_only=read_only)
                break
            except duckdb.IOException as exc:
                last_error = exc
                if not _is_lock_error(exc) or attempt == LOCK_RETRY_ATTEMPTS - 1:
                    if _is_lock_error(exc):
                        mode = "read-only" if read_only else "write"
                        raise DuckDBLockTimeoutError(
                            f"DuckDB warehouse is locked by another process after "
                            f"{LOCK_RETRY_ATTEMPTS * LOCK_RETRY_DELAY_SECONDS:.0f}s "
                            f"while opening in {mode} mode. Try again when the active "
                            "pipeline phase releases the warehouse lock."
                        ) from exc
                    raise
                time.sleep(LOCK_RETRY_DELAY_SECONDS)
        else:
            assert last_error is not None
            raise last_error

    def __enter__(self) -> DuckConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def cursor(self) -> DuckCursor:
        return DuckCursor(self._conn)

    def execute(self, sql_text: str, params: Iterable[Any] | None = None) -> DuckCursor:
        return self.cursor().execute(sql_text, params)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def get_conn(*, read_only: bool = False) -> DuckConnection:
    return DuckConnection(_database_path(), read_only=read_only)


def init_schema() -> None:
    execute_sql_text(schema_sql_text())
    _apply_lightweight_migrations()


def table_exists(schema: str, table: str, *, read_only: bool = False) -> bool:
    rows = execute_sql(
        """
        SELECT COUNT(*) AS row_count
        FROM information_schema.tables
        WHERE table_schema = ?
          AND table_name = ?
        """,
        [schema, table],
        read_only=read_only,
    )
    return bool(rows and int(rows[0]["row_count"] or 0))


def _apply_lightweight_migrations() -> None:
    """Apply additive ops-schema changes for existing local DuckDB files."""
    for schema, table, sql_text in LIGHTWEIGHT_MIGRATIONS:
        if not table_exists(schema, table):
            continue
        execute_sql(sql_text)


def execute_sql_file(filepath: str | Path) -> None:
    execute_sql_text(Path(filepath).read_text())
    logger.info("Executed SQL file: %s", filepath)


def execute_sql_text(sql_text: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()


def execute_sql(
    sql_text: str,
    params: Iterable[Any] | None = None,
    *,
    read_only: bool = False,
) -> list[dict[str, Any]]:
    with get_conn(read_only=read_only) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text, params)
            if cur.description:
                return cur.fetchall()
        if not read_only:
            conn.commit()
    return []


def execute(
    sql_text: str,
    params: Iterable[Any] | None = None,
    *,
    read_only: bool = False,
) -> list[dict[str, Any]]:
    return execute_sql(sql_text, params, read_only=read_only)


def read_table(
    schema: str,
    table: str,
    where: str = "",
    params: list[Any] | None = None,
) -> pl.DataFrame:
    query = f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)}"
    if where:
        query += f" WHERE {where}"
    rows = execute_sql(query, params)
    return pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()


def fetch_all(schema: str, table: str) -> list[dict[str, Any]]:
    return execute_sql(f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)}")


def _insert_sql(schema: str, table: str, columns: list[str]) -> str:
    column_list = ", ".join(_quote_ident(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO {_quote_ident(schema)}.{_quote_ident(table)} ({column_list}) VALUES ({placeholders})"


def _prepare_rows(rows: list[Mapping[str, Any]], columns: list[str]) -> list[tuple[Any, ...]]:
    return [tuple(_coerce_value(row.get(column)) for column in columns) for row in rows]


def insert_rows(
    schema: str,
    table: str,
    rows: list[Mapping[str, Any]],
    batch_size: int = 1000,
) -> int:
    if not rows:
        logger.info("No rows to insert into %s.%s", schema, table)
        return 0

    columns = list(rows[0].keys())
    prepared = _prepare_rows(rows, columns)
    query = _insert_sql(schema, table, columns)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for index in range(0, len(prepared), batch_size):
                cur.executemany(query, prepared[index : index + batch_size])
        conn.commit()
    logger.info("Inserted %d rows into %s.%s", len(rows), schema, table)
    return len(rows)


def truncate_and_insert(
    schema: str,
    table: str,
    rows: list[Mapping[str, Any]],
    batch_size: int = 1000,
) -> int:
    if not rows:
        logger.info("No rows to insert into %s.%s", schema, table)
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_quote_ident(schema)}.{_quote_ident(table)}")
            columns = list(rows[0].keys())
            prepared = _prepare_rows(rows, columns)
            query = _insert_sql(schema, table, columns)
            for index in range(0, len(prepared), batch_size):
                cur.executemany(query, prepared[index : index + batch_size])
        conn.commit()
    logger.info("Refreshed %s.%s with %d rows", schema, table, len(rows))
    return len(rows)


def delete_where(
    schema: str,
    table: str,
    where: str,
    params: list[Any] | None = None,
) -> int:
    query = f"DELETE FROM {_quote_ident(schema)}.{_quote_ident(table)} WHERE {where}"
    execute_sql(query, params)
    return 0


def upsert_rows(
    schema: str,
    table: str,
    rows: list[Mapping[str, Any]],
    conflict_cols: list[str] | None = None,
    conflict_columns: list[str] | None = None,
) -> int:
    if not rows:
        return 0

    conflicts = conflict_cols or conflict_columns
    if not conflicts:
        raise ValueError("upsert_rows requires conflict_cols or conflict_columns")

    columns = list(rows[0].keys())
    insert_query = _insert_sql(schema, table, columns)
    prepared = _prepare_rows(rows, columns)
    table_name = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN TRANSACTION")
                predicates = " AND ".join(f"{_quote_ident(column)} = ?" for column in conflicts)
                for row in rows:
                    cur.execute(
                        f"DELETE FROM {table_name} WHERE {predicates}",
                        [row.get(column) for column in conflicts],
                    )
                cur.executemany(insert_query, prepared)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    logger.info("Upserted %d rows into %s.%s", len(rows), schema, table)
    return len(rows)


def replace_rows_for_keys(
    schema: str,
    table: str,
    key_column: str,
    key_values: Iterable[Any],
    rows: list[Mapping[str, Any]],
) -> int:
    scoped_keys = list(dict.fromkeys(key_values))
    if not scoped_keys:
        return 0

    placeholders = ", ".join("?" for _ in scoped_keys)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                f"WHERE {_quote_ident(key_column)} IN ({placeholders})",
                scoped_keys,
            )
            if rows:
                columns = list(rows[0].keys())
                cur.executemany(_insert_sql(schema, table, columns), _prepare_rows(rows, columns))
        conn.commit()
    return len(rows)


def count_rows(schema: str, table: str) -> int:
    row = execute_sql(
        f"SELECT COUNT(*) AS row_count FROM {_quote_ident(schema)}.{_quote_ident(table)}"
    )[0]
    return int(row["row_count"])


def table_row_count(schema: str, table: str) -> int:
    return count_rows(schema, table)

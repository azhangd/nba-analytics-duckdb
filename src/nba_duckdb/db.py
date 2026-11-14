"""DuckDB warehouse access layer shared by pipeline tasks."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from nba_duckdb.config import load_env_file
from nba_duckdb.exceptions import PipelineStateNotInitializedError
from nba_duckdb.sql.schema import schema_sql_text

logger = logging.getLogger("nba_duckdb.db")

DEFAULT_DUCKDB_PATH = "data/warehouse/nba.duckdb"
LOCK_RETRY_ATTEMPTS = 30
LOCK_RETRY_DELAY_SECONDS = 2.0


class DuckDBLockTimeoutError(RuntimeError):
    """Raised when the warehouse remains locked beyond the bounded retry window."""


def database_path() -> Path:
    load_env_file()
    return Path(os.environ.get("NBA_DUCKDB_PATH") or DEFAULT_DUCKDB_PATH)


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


def _query_params(params: Iterable[Any] | None) -> list[Any]:
    """Bind dicts as JSON text; lists stay lists so `col = ANY(?)` works."""
    return [json.dumps(value) if isinstance(value, dict) else value for value in params or []]


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
        self._result = self._conn.execute(sql_text, _query_params(params))
        self.description = self._result.description
        self.rowcount = -1
        return self

    def executemany(self, sql_text: str, rows: Iterable[Iterable[Any]]) -> DuckCursor:
        prepared_rows = [tuple(_coerce_value(value) for value in row) for row in rows]
        self._result = self._conn.executemany(sql_text, prepared_rows)
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
        if read_only and not path.exists():
            raise PipelineStateNotInitializedError(
                f"Warehouse {path} not found; run `nba-duckdb init` first"
            )
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
    return DuckConnection(database_path(), read_only=read_only)


def init_schema() -> None:
    execute_sql_text(schema_sql_text())


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
            try:
                cur.execute(sql_text, params)
            except duckdb.CatalogException as exc:
                if read_only:
                    raise PipelineStateNotInitializedError(
                        f"{exc.args[0].splitlines()[0]}; run `nba-duckdb init` first"
                    ) from exc
                raise
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
    conflict_cols: list[str],
) -> int:
    if not rows:
        return 0

    conflicts = conflict_cols

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


def count_rows(schema: str, table: str) -> int:
    row = execute_sql(
        f"SELECT COUNT(*) AS row_count FROM {_quote_ident(schema)}.{_quote_ident(table)}"
    )[0]
    return int(row["row_count"])



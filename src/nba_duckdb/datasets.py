"""Declarative dataset metadata and atomic DuckDB materialization helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from nba_duckdb import db

logger = logging.getLogger("nba_duckdb.datasets")


@dataclass(frozen=True)
class NotNullExpectation:
    """Require one or more columns to be populated in every output row."""

    columns: tuple[str, ...]
    name: str = "not_null"


@dataclass(frozen=True)
class RowCountExpectation:
    """Require a minimum number of rows before materializing a dataset."""

    min_count: int
    name: str = "row_count_min"


Expectation = NotNullExpectation | RowCountExpectation


@dataclass(frozen=True)
class DatasetSpec:
    """Metadata for a DuckDB table produced by a pipeline task."""

    schema: str
    table: str
    default_scope_col: str | None = None
    delete_scope_when_empty: bool = False
    expectations: tuple[Expectation, ...] = field(default_factory=tuple)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.table}"


def _unique(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value is not None))


def _scope_values_from_rows(rows: list[Mapping[str, Any]], scope_col: str | None) -> list[Any]:
    if not scope_col:
        return []
    return _unique(row.get(scope_col) for row in rows)


def _normalize_scope_filters(
    scope_filters: Mapping[str, Iterable[Any]] | None,
) -> dict[str, list[Any]]:
    if not scope_filters:
        return {}
    normalized = {column: _unique(values) for column, values in scope_filters.items()}
    empty_columns = [column for column, values in normalized.items() if not values]
    if empty_columns:
        columns = ", ".join(empty_columns)
        raise ValueError(f"Scope filters must include at least one value for: {columns}")
    return normalized


def _validate_expectations(spec: DatasetSpec, rows: list[Mapping[str, Any]]) -> None:
    for expectation in spec.expectations:
        if isinstance(expectation, RowCountExpectation):
            if len(rows) < expectation.min_count:
                raise ValueError(
                    f"Expectation {expectation.name!r} failed for {spec.qualified_name}: "
                    f"expected at least {expectation.min_count} rows, got {len(rows)}"
                )
        elif isinstance(expectation, NotNullExpectation):
            missing = [
                column
                for column in expectation.columns
                if any(row.get(column) is None for row in rows)
            ]
            if missing:
                columns = ", ".join(missing)
                raise ValueError(
                    f"Expectation {expectation.name!r} failed for {spec.qualified_name}: "
                    f"null values found in {columns}"
                )
        else:
            raise TypeError(f"Unsupported expectation: {expectation!r}")


def _validate_rows_within_explicit_scope(
    rows: list[Mapping[str, Any]],
    *,
    scope_col: str | None,
    scope_values: list[Any],
    scope_values_explicit: bool,
    scope_filters: Mapping[str, list[Any]],
) -> None:
    if not rows:
        return

    if scope_values_explicit:
        if not scope_col:
            raise ValueError("Explicit scope_values require a scope_col or dataset default_scope_col")
        allowed = set(scope_values)
        if not allowed:
            raise ValueError("Explicit scope_values cannot be empty when inserting rows")
        invalid = [
            row.get(scope_col)
            for row in rows
            if row.get(scope_col) is None or row.get(scope_col) not in allowed
        ]
        if invalid:
            sample = ", ".join(repr(value) for value in invalid[:5])
            raise ValueError(
                f"Rows for scoped materialization must stay within {scope_col} scope; "
                f"found out-of-scope values: {sample}"
            )

    for column, values in scope_filters.items():
        allowed = set(values)
        invalid = [
            row.get(column)
            for row in rows
            if row.get(column) is None or row.get(column) not in allowed
        ]
        if invalid:
            sample = ", ".join(repr(value) for value in invalid[:5])
            raise ValueError(
                f"Rows for scoped materialization must stay within {column} scope; "
                f"found out-of-scope values: {sample}"
            )


def materialize(
    spec: DatasetSpec,
    rows: Iterable[Mapping[str, Any]],
    *,
    scope_col: str | None = None,
    scope_values: Iterable[Any] | None = None,
    scope_filters: Mapping[str, Iterable[Any]] | None = None,
    full_refresh: bool = False,
    batch_size: int = 1000,
) -> int:
    """Atomically replace a table, or one scoped slice of a table, with rows.

    When callers pass explicit ``scope_values`` or ``scope_filters``, every
    inserted row must have non-null scope values inside that declared delete
    scope. This keeps a scoped refresh from deleting one slice and accidentally
    inserting rows for another slice in the same transaction.
    """

    materialized_rows = [dict(row) for row in rows]
    target_scope_filters = _normalize_scope_filters(scope_filters)
    target_scope_col = scope_col if scope_col is not None else spec.default_scope_col
    scope_values_explicit = scope_values is not None
    target_scope_values = (
        _unique(scope_values)
        if scope_values_explicit
        else _scope_values_from_rows(materialized_rows, target_scope_col)
    )

    if not materialized_rows and not spec.delete_scope_when_empty:
        logger.info("No rows to materialize into %s", spec.qualified_name)
        return 0

    _validate_expectations(spec, materialized_rows)
    _validate_rows_within_explicit_scope(
        materialized_rows,
        scope_col=target_scope_col,
        scope_values=target_scope_values,
        scope_values_explicit=scope_values_explicit,
        scope_filters=target_scope_filters,
    )

    table_name = f"{db._quote_ident(spec.schema)}.{db._quote_ident(spec.table)}"
    with db.get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN TRANSACTION")
                if full_refresh:
                    cur.execute(f"DELETE FROM {table_name}")
                elif target_scope_filters:
                    clauses = []
                    params = []
                    for column, values in target_scope_filters.items():
                        placeholders = ", ".join("?" for _ in values)
                        clauses.append(f"{db._quote_ident(column)} IN ({placeholders})")
                        params.extend(values)
                    cur.execute(
                        f"DELETE FROM {table_name} WHERE {' AND '.join(clauses)}",
                        params,
                    )
                elif not target_scope_col:
                    cur.execute(f"DELETE FROM {table_name}")
                elif target_scope_values:
                    placeholders = ", ".join("?" for _ in target_scope_values)
                    cur.execute(
                        f"DELETE FROM {table_name} "
                        f"WHERE {db._quote_ident(target_scope_col)} IN ({placeholders})",
                        target_scope_values,
                    )

                if materialized_rows:
                    columns = list(materialized_rows[0].keys())
                    prepared = db._prepare_rows(materialized_rows, columns)
                    insert_sql = db._insert_sql(spec.schema, spec.table, columns)
                    for index in range(0, len(prepared), batch_size):
                        cur.executemany(insert_sql, prepared[index : index + batch_size])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    logger.info("Materialized %d rows into %s", len(materialized_rows), spec.qualified_name)
    return len(materialized_rows)


def materialize_derived(
    spec: DatasetSpec,
    rows: Iterable[Mapping[str, Any]],
    *,
    full_refresh: bool = False,
    scope_col: str | None = None,
    scope_values: Iterable[Any] | None = None,
    scope_filters: Mapping[str, Iterable[Any]] | None = None,
    delete_scope_when_empty: bool = True,
    batch_size: int = 1000,
) -> int:
    """Materialize deterministic silver/gold outputs with consistent semantics.

    Derived datasets should be exact functions of their upstream inputs. For
    scoped reruns, an empty output usually means the old scoped rows are no
    longer valid, so this helper clears the explicit scope by default. For full
    refreshes, callers always replace the complete target table.
    """

    effective_spec = (
        replace(spec, delete_scope_when_empty=True)
        if delete_scope_when_empty and not spec.delete_scope_when_empty
        else spec
    )
    if full_refresh:
        return materialize(
            effective_spec,
            rows,
            full_refresh=True,
            batch_size=batch_size,
        )
    if scope_filters is not None:
        return materialize(
            effective_spec,
            rows,
            scope_filters=scope_filters,
            batch_size=batch_size,
        )
    if scope_values is not None:
        return materialize(
            effective_spec,
            rows,
            scope_col=scope_col,
            scope_values=scope_values,
            batch_size=batch_size,
        )
    return materialize(effective_spec, rows, full_refresh=True, batch_size=batch_size)

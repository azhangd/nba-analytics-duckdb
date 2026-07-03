"""Helpers shared by dbt Python models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import polars as pl


def relation_to_polars(relation: Any) -> pl.DataFrame:
    """Convert a dbt-duckdb relation to Polars."""
    return relation.pl()


def relation_to_dicts(relation: Any) -> list[dict[str, Any]]:
    return relation_to_polars(relation).to_dicts()


def frame_from_rows(
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[str],
) -> pl.DataFrame:
    """Return a stable-column Polars frame for dbt Python model materialization."""
    normalized = [{column: row.get(column) for column in columns} for row in rows]
    if not normalized:
        return pl.DataFrame({column: [] for column in columns})
    return pl.DataFrame(normalized).select(list(columns))


def optional_polars(relation: Any | None) -> pl.DataFrame:
    if relation is None:
        return pl.DataFrame()
    return relation_to_polars(relation)

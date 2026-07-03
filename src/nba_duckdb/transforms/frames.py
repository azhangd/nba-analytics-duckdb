"""Small dataframe helpers for explicit transformation contracts."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl


def require_columns(frame: pl.DataFrame, columns: Sequence[str], *, context: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{context} is missing required columns: {joined}")


def select_columns(frame: pl.DataFrame, columns: Sequence[str], *, context: str) -> pl.DataFrame:
    require_columns(frame, columns, context=context)
    return frame.select(list(columns))

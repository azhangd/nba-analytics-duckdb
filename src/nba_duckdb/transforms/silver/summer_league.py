"""Shared competition scoping for Summer League dbt facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from nba_duckdb.competitions import SUMMER_LEAGUE_SLUGS

SUMMER_SCOPE_COLUMNS = ("season", "league_id", "competition")


def summer_game_scope(
    schedule_rows: list[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    return {
        str(row["game_id"]): {
            "season": str(row.get("season") or ""),
            "league_id": str(row.get("league_id") or ""),
            "competition": str(row.get("competition") or ""),
        }
        for row in schedule_rows
        if row.get("game_id") and row.get("competition") in SUMMER_LEAGUE_SLUGS
    }


def build_scoped_fact_rows(
    schedule_rows: list[Mapping[str, Any]],
    bronze_rows: list[Mapping[str, Any]],
    builder: Callable[[list[Mapping[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    scope = summer_game_scope(schedule_rows)
    scoped_bronze = [
        row for row in bronze_rows if str(row.get("game_id") or "") in scope
    ]
    output = []
    for row in builder(scoped_bronze):
        game_id = str(row.get("game_id") or "")
        if game_id in scope:
            output.append({**row, **scope[game_id]})
    return output


def scoped_columns(fact_columns: Sequence[str]) -> tuple[str, ...]:
    return (
        "game_id",
        *SUMMER_SCOPE_COLUMNS,
        *(column for column in fact_columns if column not in {"game_id", "season"}),
    )

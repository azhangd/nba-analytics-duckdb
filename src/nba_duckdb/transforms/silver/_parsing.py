"""Shared parsing helpers for silver transforms."""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from nba_duckdb.analytics.lineup_tracker import _add_name_variants


def load_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def result_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for result_set in raw.get("resultSets", []):
        headers = [str(header).lower() for header in result_set.get("headers", [])]
        for raw_row in result_set.get("rowSet", []):
            rows.append(dict(zip(headers, raw_row, strict=False)))
    return rows


def parse_minutes(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        parts = str(value).split(":")
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
        return float(value)
    except (TypeError, ValueError):
        return None


def build_roster_name_map(boxscores_df: pl.DataFrame) -> dict[int, dict[str, int | None]]:
    roster_name_map: dict[int, dict[str, int | None]] = {}
    for row in boxscores_df.iter_rows(named=True):
        team_id = row.get("team_id")
        player_id = row.get("player_id")
        player_name = str(row.get("player_name") or "").strip()
        if not team_id or not player_id or not player_name:
            continue
        _add_name_variants(roster_name_map.setdefault(int(team_id), {}), player_name, int(player_id))
    return roster_name_map

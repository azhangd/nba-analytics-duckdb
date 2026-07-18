"""Shared game-scope boundaries for normalized facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def filter_rows_to_games(
    fact_rows: list[Mapping[str, Any]],
    game_rows: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Keep bronze facts owned by the supplied normalized game relation."""

    game_ids = {
        str(row["game_id"])
        for row in game_rows
        if row.get("game_id") is not None
    }
    return [
        row
        for row in fact_rows
        if row.get("game_id") is not None and str(row["game_id"]) in game_ids
    ]

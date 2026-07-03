"""Pure transforms for gold.game_flow_snapshots."""

from __future__ import annotations

import polars as pl

from nba_duckdb.analytics.game_flow import compute_game_flow
from nba_duckdb.transforms.frames import select_columns

GAME_FLOW_SNAPSHOTS = (
    "game_id",
    "period",
    "clock_seconds_remaining",
    "game_seconds_elapsed",
    "home_score",
    "away_score",
    "margin",
    "home_win_prob",
)

OUTPUT_COLUMNS = list(GAME_FLOW_SNAPSHOTS)


def build_game_flow_rows(pbp: pl.DataFrame, games: pl.DataFrame) -> tuple[list[dict], list[str]]:
    season_by_game = {
        str(row.get("game_id")): str(row.get("season") or "")
        for row in games.iter_rows(named=True)
        if row.get("game_id")
    } if not games.is_empty() else {}
    target_game_ids = [str(game_id) for game_id in pbp["game_id"].unique().to_list()]
    frames = []
    for game_id in target_game_ids:
        flow = compute_game_flow(
            pbp.filter(pl.col("game_id") == game_id),
            game_id,
            season=season_by_game.get(game_id),
        )
        if not flow.is_empty():
            frames.append(flow)
    if not frames:
        return [], target_game_ids
    result = select_columns(pl.concat(frames), OUTPUT_COLUMNS, context="gold.game_flow_snapshots")
    return result.to_dicts(), target_game_ids

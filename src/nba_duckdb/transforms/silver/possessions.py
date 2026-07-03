"""Pure transforms for silver possession rows."""

from __future__ import annotations

import polars as pl

from nba_duckdb.analytics.possession_parser import parse_possessions

FCT_POSSESSIONS = (
    "game_id",
    "possession_number",
    "period",
    "offense_team_id",
    "start_clock_seconds",
    "end_clock_seconds",
    "duration_seconds",
    "start_type",
    "end_type",
    "possession_context",
    "is_garbage_time",
    "score_margin",
    "points_scored",
    "event_count",
    "events",
)

OUTPUT_COLUMNS = list(FCT_POSSESSIONS)


def build_fct_possession_rows(
    pbp_df: pl.DataFrame,
    *,
    home_team_by_game: dict[str, int | None],
) -> tuple[list[dict], list[str]]:
    game_ids = [str(game_id) for game_id in pbp_df["game_id"].unique().to_list()]
    frames = []
    for game_id in game_ids:
        possessions = parse_possessions(
            pbp_df.filter(pl.col("game_id") == game_id),
            game_id,
            home_team_id=home_team_by_game.get(game_id),
        )
        if not possessions.is_empty():
            frames.append(possessions)
    if not frames:
        return [], game_ids
    rows = [
        {column: row.get(column) for column in OUTPUT_COLUMNS}
        for row in pl.concat(frames).iter_rows(named=True)
    ]
    return rows, game_ids

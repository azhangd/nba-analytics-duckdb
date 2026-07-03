"""Pure transforms for heuristic shot quality outputs."""

from __future__ import annotations

import polars as pl

from nba_duckdb.analytics.shot_quality_model import aggregate_shot_quality, compute_shot_quality
from nba_duckdb.transforms.frames import select_columns

PLAYER_ZONE_SEASON_SHOT_QUALITY = (
    "season",
    "player_id",
    "player_name",
    "team_id",
    "shot_zone_basic",
    "attempts",
    "makes",
    "actual_fg_pct",
    "expected_fg_pct_heuristic",
    "quality_delta_heuristic",
)

OUTPUT_COLUMNS = list(PLAYER_ZONE_SEASON_SHOT_QUALITY)


def canonical_player_names(shots_df: pl.DataFrame) -> pl.DataFrame:
    if shots_df.is_empty() or "player_name" not in shots_df.columns:
        return pl.DataFrame()
    return (
        shots_df
        .select(["season", "team_id", "player_id", "player_name"])
        .drop_nulls(["season", "team_id", "player_id", "player_name"])
        .group_by(["season", "team_id", "player_id"])
        .agg(pl.col("player_name").sort().last().alias("player_name"))
    )


def build_shot_quality_rows(fct_shots: pl.DataFrame) -> list[dict]:
    shots_with_quality = compute_shot_quality(fct_shots)
    aggregated = aggregate_shot_quality(
        shots_with_quality,
        group_by=["season", "player_id", "team_id", "shot_zone_basic"],
    )
    if aggregated.is_empty():
        return []
    player_names = canonical_player_names(fct_shots)
    if not player_names.is_empty():
        aggregated = aggregated.join(
            player_names,
            on=["season", "team_id", "player_id"],
            how="left",
        )
    return select_columns(aggregated, OUTPUT_COLUMNS, context="gold.player_zone_season_shot_quality").to_dicts()

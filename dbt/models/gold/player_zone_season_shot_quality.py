import polars as pl

from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.player_zone_season_shot_quality import (
    PLAYER_ZONE_SEASON_SHOT_QUALITY,
    build_shot_quality_rows,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    games = relation_to_polars(dbt.ref("fct_games"))
    regular_season = games.filter(pl.col("game_type") == "regular_season").select("game_id")
    shot_df = relation_to_polars(dbt.ref("fct_shots")).join(regular_season, on="game_id", how="semi")
    rows = build_shot_quality_rows(shot_df) if not shot_df.is_empty() else []
    return frame_from_rows(rows, PLAYER_ZONE_SEASON_SHOT_QUALITY)

from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.player_zone_season_shot_quality import (
    PLAYER_ZONE_SEASON_SHOT_QUALITY,
    build_shot_quality_rows,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    shots = dbt.ref("fct_shots")
    shot_df = relation_to_polars(shots)
    rows = build_shot_quality_rows(shot_df) if not shot_df.is_empty() else []
    return frame_from_rows(rows, PLAYER_ZONE_SEASON_SHOT_QUALITY)

from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.player_season_archetypes import (
    PLAYER_SEASON_ARCHETYPES,
    build_player_season_archetype_rows,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    season_stats = dbt.ref("player_season_stats")
    return frame_from_rows(
        build_player_season_archetype_rows(relation_to_polars(season_stats)),
        PLAYER_SEASON_ARCHETYPES,
    )

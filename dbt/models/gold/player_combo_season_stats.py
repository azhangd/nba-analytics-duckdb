from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.player_combo_season_stats import (
    PLAYER_COMBO_SEASON_STATS,
    build_player_combo_season_stat_rows,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    lineups = dbt.ref("fct_lineups")
    dim_players = dbt.ref("dim_players")
    games = dbt.ref("fct_games")
    boxscores = dbt.ref("fct_boxscores")
    return frame_from_rows(
        build_player_combo_season_stat_rows(
            relation_to_polars(lineups),
            relation_to_polars(dim_players),
            relation_to_polars(games),
            relation_to_polars(boxscores),
        ),
        PLAYER_COMBO_SEASON_STATS,
    )

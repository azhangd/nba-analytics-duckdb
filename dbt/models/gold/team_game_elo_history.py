from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.team_season_elo import (
    TEAM_GAME_ELO_HISTORY,
    build_team_elo_rows,
    seasons_in_games,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    games = dbt.ref("fct_games")
    teams = dbt.ref("dim_teams")
    game_df = relation_to_polars(games)
    _rows, history_rows = build_team_elo_rows(game_df, relation_to_polars(teams), target_seasons=seasons_in_games(game_df))
    return frame_from_rows(history_rows, TEAM_GAME_ELO_HISTORY)

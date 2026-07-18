from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.boxscores import FCT_BOXSCORES, build_fct_boxscore_rows
from nba_duckdb.transforms.silver.scope import filter_rows_to_games


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    boxscores = relation_to_dicts(dbt.source("bronze", "boxscores"))
    games = relation_to_dicts(dbt.ref("fct_games"))
    dbt.ref("dim_players")
    rows = build_fct_boxscore_rows(filter_rows_to_games(boxscores, games))
    return frame_from_rows(rows, FCT_BOXSCORES)

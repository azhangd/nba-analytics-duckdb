from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.boxscores import FCT_BOXSCORES, build_fct_boxscore_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    boxscores = dbt.source("bronze", "boxscores")
    dbt.ref("fct_games")
    dbt.ref("dim_players")
    return frame_from_rows(build_fct_boxscore_rows(relation_to_dicts(boxscores)), FCT_BOXSCORES)

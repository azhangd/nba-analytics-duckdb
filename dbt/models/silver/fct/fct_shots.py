from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.scope import filter_rows_to_games
from nba_duckdb.transforms.silver.shots import FCT_SHOTS, build_fct_shot_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    shot_charts = relation_to_dicts(dbt.source("bronze", "shot_charts"))
    games = relation_to_dicts(dbt.ref("fct_games"))
    rows = build_fct_shot_rows(filter_rows_to_games(shot_charts, games))
    return frame_from_rows(rows, FCT_SHOTS)

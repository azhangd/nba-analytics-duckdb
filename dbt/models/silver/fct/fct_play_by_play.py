from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.play_by_play import FCT_PLAY_BY_PLAY, build_fct_play_by_play_rows
from nba_duckdb.transforms.silver.scope import filter_rows_to_games


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    play_by_play = relation_to_dicts(dbt.source("bronze", "play_by_play"))
    games = relation_to_dicts(dbt.ref("fct_games"))
    rows = build_fct_play_by_play_rows(filter_rows_to_games(play_by_play, games))
    return frame_from_rows(rows, FCT_PLAY_BY_PLAY)

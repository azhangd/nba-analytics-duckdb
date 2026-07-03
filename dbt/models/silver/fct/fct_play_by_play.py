from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.play_by_play import FCT_PLAY_BY_PLAY, build_fct_play_by_play_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    play_by_play = dbt.source("bronze", "play_by_play")
    dbt.ref("fct_games")
    return frame_from_rows(build_fct_play_by_play_rows(relation_to_dicts(play_by_play)), FCT_PLAY_BY_PLAY)

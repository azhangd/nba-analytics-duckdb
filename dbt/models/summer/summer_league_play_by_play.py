from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.play_by_play import (
    FCT_PLAY_BY_PLAY,
    build_fct_play_by_play_rows,
)
from nba_duckdb.transforms.silver.summer_league import build_scoped_fact_rows, scoped_columns


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["summer_league"])
    schedule = relation_to_dicts(dbt.source("bronze", "schedule"))
    play_by_play = relation_to_dicts(dbt.source("bronze", "play_by_play"))
    rows = build_scoped_fact_rows(schedule, play_by_play, build_fct_play_by_play_rows)
    return frame_from_rows(rows, scoped_columns(FCT_PLAY_BY_PLAY))

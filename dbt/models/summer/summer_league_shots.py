from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.shots import FCT_SHOTS, build_fct_shot_rows
from nba_duckdb.transforms.silver.summer_league import build_scoped_fact_rows, scoped_columns


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["summer_league"])
    schedule = relation_to_dicts(dbt.source("bronze", "schedule"))
    shots = relation_to_dicts(dbt.source("bronze", "shot_charts"))
    rows = build_scoped_fact_rows(schedule, shots, build_fct_shot_rows)
    return frame_from_rows(rows, scoped_columns(FCT_SHOTS))

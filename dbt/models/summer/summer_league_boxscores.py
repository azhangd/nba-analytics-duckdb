from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.boxscores import FCT_BOXSCORES, build_fct_boxscore_rows
from nba_duckdb.transforms.silver.summer_league import build_scoped_fact_rows, scoped_columns


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["summer_league"])
    schedule = relation_to_dicts(dbt.source("bronze", "schedule"))
    boxscores = relation_to_dicts(dbt.source("bronze", "boxscores"))
    rows = build_scoped_fact_rows(schedule, boxscores, build_fct_boxscore_rows)
    return frame_from_rows(rows, scoped_columns(FCT_BOXSCORES))

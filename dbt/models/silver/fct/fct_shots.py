from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.shots import FCT_SHOTS, build_fct_shot_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    shot_charts = dbt.source("bronze", "shot_charts")
    return frame_from_rows(build_fct_shot_rows(relation_to_dicts(shot_charts)), FCT_SHOTS)

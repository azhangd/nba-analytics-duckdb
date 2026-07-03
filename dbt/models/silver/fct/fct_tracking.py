from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.enrichment import FCT_TRACKING, build_fct_tracking_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    tracking = dbt.source("bronze", "tracking_stats")
    return frame_from_rows(build_fct_tracking_rows(relation_to_dicts(tracking)), FCT_TRACKING)

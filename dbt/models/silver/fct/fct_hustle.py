from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.enrichment import FCT_HUSTLE, build_fct_hustle_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    hustle = dbt.source("bronze", "hustle")
    return frame_from_rows(build_fct_hustle_rows(relation_to_dicts(hustle)), FCT_HUSTLE)

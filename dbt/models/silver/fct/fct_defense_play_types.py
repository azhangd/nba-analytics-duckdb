from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.enrichment import (
    FCT_DEFENSE_PLAY_TYPES,
    build_fct_defense_play_type_rows,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    defense = dbt.source("bronze", "defense")
    return frame_from_rows(build_fct_defense_play_type_rows(relation_to_dicts(defense)), FCT_DEFENSE_PLAY_TYPES)

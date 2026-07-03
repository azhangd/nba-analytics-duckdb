from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts
from nba_duckdb.transforms.silver.game_detail import FCT_GAME_DETAIL, build_fct_game_detail_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    game_detail = dbt.source("bronze", "game_detail")
    return frame_from_rows(build_fct_game_detail_rows(relation_to_dicts(game_detail)), FCT_GAME_DETAIL)

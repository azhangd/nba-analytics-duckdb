from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.silver.injuries import DIM_INJURIES, build_dim_injury_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    injuries = dbt.source("bronze", "injuries")
    teams = dbt.ref("dim_teams")
    players = dbt.ref("dim_players")
    rows = build_dim_injury_rows(relation_to_polars(injuries), relation_to_polars(teams), relation_to_polars(players))
    return frame_from_rows(rows, DIM_INJURIES)

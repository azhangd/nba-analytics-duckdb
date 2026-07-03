from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts, relation_to_polars
from nba_duckdb.transforms.silver.players import DIM_PLAYERS, build_dim_player_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    rosters = dbt.source("bronze", "rosters")
    boxscores = dbt.source("bronze", "boxscores")
    schedule = dbt.source("bronze", "schedule")
    boxscore_df = relation_to_polars(boxscores)
    schedule_df = relation_to_polars(schedule).select(["game_id", "season"])
    boxscore_rows = [] if boxscore_df.is_empty() else boxscore_df.join(schedule_df, on="game_id", how="left").to_dicts()
    rows = build_dim_player_rows(relation_to_dicts(rosters), boxscore_rows)
    return frame_from_rows(rows, DIM_PLAYERS)

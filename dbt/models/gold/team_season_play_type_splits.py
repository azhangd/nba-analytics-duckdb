from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.team_season_play_type_stats import (
    TEAM_SEASON_PLAY_TYPE_SPLITS,
    build_situational_play_type_rows,
)


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    possessions = dbt.ref("fct_possessions")
    play_by_play = dbt.ref("fct_play_by_play")
    games = dbt.ref("fct_games")
    possession_df = relation_to_polars(possessions)
    rows = build_situational_play_type_rows(possession_df, relation_to_polars(play_by_play), relation_to_polars(games)) if not possession_df.is_empty() else []
    rows = [row for row in rows if row.get("offense_team_id") is not None]
    return frame_from_rows(rows, TEAM_SEASON_PLAY_TYPE_SPLITS)

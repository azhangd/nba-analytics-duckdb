from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.gold.game_flow_snapshots import GAME_FLOW_SNAPSHOTS, build_game_flow_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    play_by_play = dbt.ref("fct_play_by_play")
    games = dbt.ref("fct_games")
    pbp = relation_to_polars(play_by_play)
    rows, _game_ids = build_game_flow_rows(pbp, relation_to_polars(games)) if not pbp.is_empty() else ([], [])
    return frame_from_rows(rows, GAME_FLOW_SNAPSHOTS)

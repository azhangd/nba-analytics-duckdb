from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts, relation_to_polars
from nba_duckdb.transforms.silver._parsing import build_roster_name_map
from nba_duckdb.transforms.silver.play_by_play import FCT_PLAY_BY_PLAY, build_fct_play_by_play_rows
from nba_duckdb.transforms.silver.scope import filter_rows_to_games


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    play_by_play = relation_to_dicts(dbt.source("bronze", "play_by_play"))
    games = relation_to_dicts(dbt.ref("fct_games"))
    boxscores = relation_to_polars(dbt.ref("fct_boxscores"))
    roster_name_maps = {
        str(game_id): build_roster_name_map(game_boxscores)
        for (game_id,), game_boxscores in boxscores.group_by("game_id")
    }
    rows = build_fct_play_by_play_rows(filter_rows_to_games(play_by_play, games), roster_name_maps)
    return frame_from_rows(rows, FCT_PLAY_BY_PLAY)

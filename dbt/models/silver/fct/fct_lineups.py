from nba_duckdb.dbt_support import frame_from_rows, relation_to_dicts, relation_to_polars
from nba_duckdb.transforms.silver.lineups import FCT_LINEUPS, build_fct_lineup_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    play_by_play = dbt.ref("fct_play_by_play")
    games = dbt.ref("fct_games")
    boxscores = dbt.ref("fct_boxscores")
    game_detail = dbt.source("bronze", "game_detail")
    rows = build_fct_lineup_rows(
        relation_to_polars(play_by_play),
        relation_to_polars(games),
        relation_to_polars(boxscores),
        relation_to_dicts(game_detail),
    )
    return frame_from_rows(rows, FCT_LINEUPS)

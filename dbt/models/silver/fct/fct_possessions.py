from nba_duckdb.dbt_support import frame_from_rows, relation_to_polars
from nba_duckdb.transforms.silver.possessions import FCT_POSSESSIONS, build_fct_possession_rows


def model(dbt, session):
    dbt.config(materialized="table", schema="silver", tags=["silver"])
    play_by_play = dbt.ref("fct_play_by_play")
    games = dbt.ref("fct_games")
    pbp = relation_to_polars(play_by_play)
    games_df = relation_to_polars(games)
    home_by_game = {str(row["game_id"]): int(row["home_team_id"]) if row.get("home_team_id") else None for row in games_df.iter_rows(named=True)}
    rows, _game_ids = build_fct_possession_rows(pbp, home_team_by_game=home_by_game) if not pbp.is_empty() else ([], [])
    return frame_from_rows(rows, FCT_POSSESSIONS)

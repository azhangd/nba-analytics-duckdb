from nba_duckdb.dbt_support import relation_to_polars
from nba_duckdb.transforms.gold.player_season_stats import build_player_season_stats_frame


def model(dbt, session):
    dbt.config(materialized="table", schema="gold", tags=["gold"])
    base = dbt.ref("player_season_stats_base")
    player_games = dbt.ref("player_game_stats")
    team_games = dbt.ref("team_game_stats")
    games = dbt.ref("fct_games")
    four_factors = dbt.ref("team_season_four_factors")
    return build_player_season_stats_frame(
        base=relation_to_polars(base),
        player_games=relation_to_polars(player_games),
        team_games=relation_to_polars(team_games),
        games=relation_to_polars(games),
        four_factors=relation_to_polars(four_factors),
    )

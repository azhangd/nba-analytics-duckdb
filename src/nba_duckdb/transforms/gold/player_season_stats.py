"""Pure transforms for final player season stats."""

from __future__ import annotations

import polars as pl

from nba_duckdb.transforms.gold.adjusted_stats import build_adjusted_stats
from nba_duckdb.transforms.gold.bpm_vorp import build_bpm_vorp


def build_player_season_stats_frame(
    *,
    base: pl.DataFrame,
    player_games: pl.DataFrame,
    games: pl.DataFrame,
    four_factors: pl.DataFrame,
    team_games: pl.DataFrame,
) -> pl.DataFrame:
    adjusted, _league_avg_def_rtg = build_adjusted_stats(
        player_games=player_games,
        team_ratings=four_factors,
        fct_games=games,
    )
    bpm_vorp = build_bpm_vorp(player_games=player_games, team_games=team_games)
    return base.join(bpm_vorp, on=["player_id", "season"], how="left").join(
        adjusted, on=["player_id", "season"], how="left"
    )

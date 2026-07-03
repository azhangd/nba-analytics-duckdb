"""Pure transforms for final player season stats."""

from __future__ import annotations

import polars as pl

from nba_duckdb.transforms.gold.adjusted_stats import build_adjusted_stats
from nba_duckdb.transforms.gold.bpm_vorp import build_bpm_vorp


def overlay_columns(base: pl.DataFrame, updates: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    available = tuple(column for column in columns if column in updates.columns)
    if updates.is_empty() or not available:
        return base
    renamed = updates.rename({column: f"{column}__computed" for column in available})
    result = base.join(renamed, on=["player_id", "season"], how="left")
    result = result.with_columns([
        pl.coalesce([pl.col(f"{column}__computed"), pl.col(column)]).alias(column)
        for column in available
    ])
    return result.drop([f"{column}__computed" for column in available])


def build_player_season_stats_frame(
    *,
    base: pl.DataFrame,
    player_games: pl.DataFrame,
    team_games: pl.DataFrame,
    games: pl.DataFrame,
    four_factors: pl.DataFrame,
) -> pl.DataFrame:
    if base.is_empty():
        return base
    adjusted, _league_avg_def_rtg = build_adjusted_stats(
        player_games=player_games,
        team_log=team_games,
        fct_games=games,
    )
    bpm_vorp, _league_avg_pace = build_bpm_vorp(
        player_games=player_games,
        fct_games=games,
        season_stats=base,
        four_factors=four_factors,
    )
    result = overlay_columns(base, adjusted, ("adj_ppg", "adj_ts_pct", "adj_net_rtg"))
    result = overlay_columns(result, bpm_vorp, ("obpm", "dbpm", "bpm_approx", "vorp_approx"))
    return result.select(base.columns)

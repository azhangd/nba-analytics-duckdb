"""Pure transforms for opponent-adjusted player season stats."""

from __future__ import annotations

import polars as pl

_LEAGUE_AVG_DEF_RTG = 112.0


def empty_adjusted_stats() -> pl.DataFrame:
    return pl.DataFrame({
        "player_id": pl.Series([], dtype=pl.Int64),
        "season": pl.Series([], dtype=pl.Utf8),
        "adj_ppg": pl.Series([], dtype=pl.Float64),
        "adj_ts_pct": pl.Series([], dtype=pl.Float64),
        "adj_net_rtg": pl.Series([], dtype=pl.Float64),
    })


def build_adjusted_stats(
    *,
    player_games: pl.DataFrame,
    team_log: pl.DataFrame,
    fct_games: pl.DataFrame,
) -> tuple[pl.DataFrame, float]:
    if player_games.is_empty() or team_log.is_empty() or fct_games.is_empty():
        return empty_adjusted_stats(), _LEAGUE_AVG_DEF_RTG

    valid_rtg = team_log.filter(pl.col("def_rtg").is_not_null() & (pl.col("def_rtg") > 80))
    league_avg = valid_rtg["def_rtg"].mean() if not valid_rtg.is_empty() else _LEAGUE_AVG_DEF_RTG

    games_slim = fct_games.select(["game_id", "home_team_id", "away_team_id", "season"])
    team_def_rtg = (
        team_log
        .filter(pl.col("def_rtg").is_not_null())
        .group_by("team_id")
        .agg(pl.col("def_rtg").mean().alias("season_def_rtg"))
    )

    pgs = player_games.join(games_slim, on="game_id", how="left")
    pgs = pgs.with_columns(
        pl.when(pl.col("team_id") == pl.col("home_team_id"))
        .then(pl.col("away_team_id"))
        .otherwise(pl.col("home_team_id"))
        .alias("opp_team_id")
    )
    pgs = pgs.join(
        team_def_rtg.rename({"team_id": "opp_team_id", "season_def_rtg": "opp_def_rtg"}),
        on="opp_team_id",
        how="left",
    )
    pgs = pgs.with_columns(pl.col("opp_def_rtg").fill_null(league_avg))
    pgs = pgs.with_columns([
        (pl.col("pts") * (league_avg / pl.col("opp_def_rtg"))).alias("adj_pts"),
        pl.when(pl.col("fga").is_not_null() & (pl.col("fga") > 0))
        .then(pl.col("ts_pct") * (league_avg / pl.col("opp_def_rtg")))
        .otherwise(None)
        .alias("adj_ts_pct_raw"),
    ])

    adjusted = (
        pgs.filter(pl.col("minutes").is_not_null() & (pl.col("minutes") > 0))
        .group_by(["player_id", "season"])
        .agg([
            pl.col("adj_pts").mean().alias("adj_ppg"),
            pl.col("adj_ts_pct_raw").drop_nulls().mean().alias("adj_ts_pct"),
            pl.col("net_rating").mean().alias("adj_net_rtg"),
        ])
        .with_columns([
            pl.col("adj_ppg").cast(pl.Float64, strict=False).round(1),
            pl.col("adj_ts_pct").cast(pl.Float64, strict=False).round(3),
            pl.col("adj_net_rtg").cast(pl.Float64, strict=False).round(1),
            pl.col("season").fill_null("2025-26"),
        ])
    )
    return adjusted, float(league_avg)

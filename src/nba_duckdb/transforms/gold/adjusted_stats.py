"""Pure transforms for opponent-adjusted player season stats."""

from __future__ import annotations

import polars as pl


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
    team_ratings: pl.DataFrame,
    fct_games: pl.DataFrame,
) -> pl.DataFrame:
    """`team_ratings` has one row per team-season with its season `def_rtg`.

    Points and TS% are scaled by the season's league average defensive rating
    (the mean of that season's team def_rtg) over the opponent's def_rtg.
    """
    if player_games.is_empty() or team_ratings.is_empty() or fct_games.is_empty():
        return empty_adjusted_stats()

    ratings = team_ratings.select(["team_id", "season", "def_rtg"])
    league_avg = ratings.group_by("season").agg(pl.col("def_rtg").mean().alias("league_avg_def_rtg"))
    games_slim = fct_games.select(["game_id", "home_team_id", "away_team_id", "season"])

    played = player_games.filter(pl.col("minutes").is_not_null() & (pl.col("minutes") > 0))
    pgs = played.join(games_slim, on="game_id", how="left")
    pgs = pgs.with_columns(
        pl.when(pl.col("team_id") == pl.col("home_team_id"))
        .then(pl.col("away_team_id"))
        .otherwise(pl.col("home_team_id"))
        .alias("opp_team_id")
    )
    pgs = pgs.join(
        ratings.rename({"team_id": "opp_team_id", "def_rtg": "opp_def_rtg"}),
        on=["opp_team_id", "season"],
        how="left",
    ).join(league_avg, on="season", how="left")
    missing = pgs.filter(pl.col("opp_def_rtg").is_null())
    if not missing.is_empty():
        first = missing.row(0, named=True)
        raise ValueError(
            f"{missing.height} player games have no opponent defensive rating; first: game {first['game_id']}, "
            f"team {first['team_id']}, opponent {first['opp_team_id']}, season {first['season']}"
        )
    scale = pl.col("league_avg_def_rtg") / pl.col("opp_def_rtg")
    pgs = pgs.with_columns([
        (pl.col("pts") * scale).alias("adj_pts"),
        pl.when(pl.col("fga").is_not_null() & (pl.col("fga") > 0))
        .then(pl.col("ts_pct") * scale)
        .otherwise(None)
        .alias("adj_ts_pct_raw"),
    ])

    adjusted = (
        pgs.with_columns((pl.col("fga") + 0.44 * pl.col("fta")).alias("tsa"))
        .group_by(["player_id", "season"])
        .agg([
            pl.col("adj_pts").mean().alias("adj_ppg"),
            # Weighted like pooled rates: TS% by shooting attempts, net rating by minutes.
            (pl.col("adj_ts_pct_raw") * pl.col("tsa")).sum().alias("ts_weighted"),
            pl.col("tsa").filter(pl.col("adj_ts_pct_raw").is_not_null()).sum().alias("ts_weight"),
            (pl.col("net_rating") * pl.col("minutes")).sum().alias("net_weighted"),
            pl.col("minutes").filter(pl.col("net_rating").is_not_null()).sum().alias("net_weight"),
        ])
        .with_columns([
            pl.when(pl.col("ts_weight") > 0).then(pl.col("ts_weighted") / pl.col("ts_weight")).alias("adj_ts_pct"),
            pl.when(pl.col("net_weight") > 0).then(pl.col("net_weighted") / pl.col("net_weight")).alias("adj_net_rtg"),
        ])
        .drop(["ts_weighted", "ts_weight", "net_weighted", "net_weight"])
        .with_columns([
            pl.col("adj_ppg").cast(pl.Float64, strict=False).round(1),
            pl.col("adj_ts_pct").cast(pl.Float64, strict=False).round(3),
            pl.col("adj_net_rtg").cast(pl.Float64, strict=False).round(1),
        ])
    )
    return adjusted

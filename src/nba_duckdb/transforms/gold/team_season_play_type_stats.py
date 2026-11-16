"""Pure transforms for rule-based play-type outputs."""

from __future__ import annotations

import polars as pl

from nba_duckdb.analytics.play_type_classifier import classify_possessions
from nba_duckdb.transforms.frames import select_columns

TEAM_SEASON_PLAY_TYPE_STATS = (
    "offense_team_id",
    "season",
    "play_type",
    "possessions",
    "total_points",
    "ppp",
    "frequency_pct",
)
TEAM_SEASON_PLAY_TYPE_SPLITS = (
    "offense_team_id",
    "season",
    "play_type",
    "split_type",
    "split_value",
    "possessions",
    "total_points",
    "ppp",
    "frequency_pct",
)

PLAY_TYPE_COLUMNS = list(TEAM_SEASON_PLAY_TYPE_STATS)
SITUATIONAL_COLUMNS = list(TEAM_SEASON_PLAY_TYPE_SPLITS)
def margin_bucket(margin: int) -> str:
    """Score margin for the offense: tied, close (1-5), comfortable (6-14), big (15+)."""
    if margin == 0:
        return "tied"
    size = abs(margin)
    side = "up" if margin > 0 else "down"
    if size <= 5:
        return f"{side}_close"
    if size <= 14:
        return f"{side}_comfortable"
    return f"{side}_big"


def games_with_season(games: pl.DataFrame) -> pl.DataFrame:
    """Regular-season games and their season; joined inner so other games drop out."""
    return (
        games.filter(pl.col("game_type") == "regular_season")
        .select(["game_id", "season"])
        .unique(subset=["game_id"])
    )


def build_play_type_rows(possessions: pl.DataFrame, pbp: pl.DataFrame, games: pl.DataFrame) -> list[dict]:
    classified = classify_possessions(possessions, pbp)
    if classified.is_empty() or "play_type" not in classified.columns:
        return []
    summary = (
        classified
        .join(games_with_season(games), on="game_id", how="inner")
        .filter(pl.col("play_type") != "")
        .group_by(["offense_team_id", "season", "play_type"])
        .agg(
            pl.len().alias("possessions"),
            pl.col("points_scored").sum().alias("total_points"),
            pl.col("points_scored").mean().round(3).alias("ppp"),
        )
        .with_columns(
            (
                pl.col("possessions").cast(pl.Float64)
                / pl.col("possessions").sum().over(["offense_team_id", "season"])
                * 100
            ).round(1).alias("frequency_pct")
        )
        .sort(["season", "offense_team_id", "possessions"], descending=[False, False, True])
    )
    return select_columns(summary, PLAY_TYPE_COLUMNS, context="gold.team_season_play_type_stats").to_dicts()


def build_situational_play_type_rows(
    possessions: pl.DataFrame,
    pbp: pl.DataFrame,
    games: pl.DataFrame,
) -> list[dict]:
    classified = classify_possessions(possessions, pbp)
    if classified.is_empty() or "play_type" not in classified.columns:
        return []
    classified = (
        classified
        .filter(pl.col("play_type") != "")
        .join(games_with_season(games), on="game_id", how="inner")
        .with_columns(
            pl.when(pl.col("play_type") == "Transition")
            .then(pl.lit("transition"))
            .otherwise(pl.lit("half_court"))
            .alias("possession_context"),
            pl.col("score_margin")
            .fill_null(0)
            .map_elements(lambda value: margin_bucket(int(value)), return_dtype=pl.Utf8)
            .alias("margin_bucket"),
            (
                (pl.col("period") >= 4)
                & (pl.col("start_clock_seconds") <= 300.0)
                & (pl.col("score_margin").abs() <= 5)
            ).alias("is_clutch"),
        )
    )
    by_period = (
        classified
        .group_by(["offense_team_id", "season", "play_type", "period"])
        .agg(
            pl.len().alias("possessions"),
            pl.col("points_scored").sum().alias("total_points"),
            pl.col("points_scored").mean().round(3).alias("ppp"),
        )
        .with_columns(pl.lit("period").alias("split_type"), pl.col("period").cast(pl.Utf8).alias("split_value"))
    )
    by_margin = (
        classified
        .group_by(["offense_team_id", "season", "play_type", "margin_bucket"])
        .agg(
            pl.len().alias("possessions"),
            pl.col("points_scored").sum().alias("total_points"),
            pl.col("points_scored").mean().round(3).alias("ppp"),
        )
        .with_columns(pl.lit("margin").alias("split_type"), pl.col("margin_bucket").alias("split_value"))
        .drop("margin_bucket")
    )
    by_context = (
        classified
        .group_by(["offense_team_id", "season", "play_type", "possession_context"])
        .agg(
            pl.len().alias("possessions"),
            pl.col("points_scored").sum().alias("total_points"),
            pl.col("points_scored").mean().round(3).alias("ppp"),
        )
        .with_columns(pl.lit("context").alias("split_type"), pl.col("possession_context").alias("split_value"))
        .drop("possession_context")
    )
    by_clutch = (
        classified
        .group_by(["offense_team_id", "season", "play_type", "is_clutch"])
        .agg(
            pl.len().alias("possessions"),
            pl.col("points_scored").sum().alias("total_points"),
            pl.col("points_scored").mean().round(3).alias("ppp"),
        )
        .with_columns(
            pl.lit("clutch").alias("split_type"),
            pl.when(pl.col("is_clutch")).then(pl.lit("clutch")).otherwise(pl.lit("non_clutch")).alias("split_value"),
        )
        .drop("is_clutch")
    )
    combined = pl.concat([
        by_period.select(SITUATIONAL_COLUMNS[:-1]),
        by_margin.select(SITUATIONAL_COLUMNS[:-1]),
        by_context.select(SITUATIONAL_COLUMNS[:-1]),
        by_clutch.select(SITUATIONAL_COLUMNS[:-1]),
    ])
    combined = (
        combined
        .with_columns(
            (
                pl.col("possessions").cast(pl.Float64)
                / pl.col("possessions").sum().over(["offense_team_id", "season", "split_type", "split_value"])
                * 100
            ).round(1).alias("frequency_pct")
        )
        .sort(
            ["season", "offense_team_id", "split_type", "split_value", "possessions"],
            descending=[False, False, False, False, True],
        )
    )
    return select_columns(combined, SITUATIONAL_COLUMNS, context="gold.team_season_play_type_splits").to_dicts()

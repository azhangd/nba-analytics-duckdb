"""Pure transform for gold.player_season_archetypes."""

from __future__ import annotations

import polars as pl

from nba_duckdb.modeling.player_archetype import classify_archetypes

PLAYER_SEASON_ARCHETYPES = (
    "player_id",
    "season",
    "player_name",
    "team_id",
    "primary_archetype",
    "secondary_archetype",
    "archetype_confidence",
    "prob_primary_creator",
    "prob_secondary_creator",
    "prob_stretch_shooter",
    "prob_slasher",
    "prob_post_scorer",
    "prob_3_and_d_wing",
    "prob_athletic_big",
    "prob_role_player",
    "creation_per_36",
    "gravity_score",
)

_FLOAT_INPUT_COLUMNS = (
    "mpg",
    "ppg",
    "apg",
    "rpg",
    "spg",
    "bpg",
    "topg",
    "avg_usg_pct",
    "fg3_pct",
    "fg_pct",
    "avg_ts_pct",
)


def _normalize_classifier_inputs(season_stats: pl.DataFrame) -> pl.DataFrame:
    expressions = [
        pl.col(column).cast(pl.Float64, strict=False).alias(column)
        for column in _FLOAT_INPUT_COLUMNS
        if column in season_stats.columns
    ]
    if "player_id" in season_stats.columns:
        expressions.append(pl.col("player_id").cast(pl.Int64, strict=False).alias("player_id"))
    if "team_id" in season_stats.columns:
        expressions.append(pl.col("team_id").cast(pl.Int64, strict=False).alias("team_id"))
    return season_stats.with_columns(expressions) if expressions else season_stats


def _creation_rows(season_stats: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for player in season_stats.iter_rows(named=True):
        mpg = player.get("mpg", 0) or 0
        if mpg < 5:
            continue
        scale = 36.0 / mpg if mpg > 0 else 0
        apg = (player.get("apg", 0) or 0) * scale
        ppg = (player.get("ppg", 0) or 0) * scale
        topg = (player.get("topg", 0) or 0) * scale
        usg = (player.get("avg_usg_pct", 0) or 0) * 100
        creation = round(apg * 0.50 + ppg * 0.15 + topg * 0.20 + (usg - 20) * 0.05, 1)
        rows.append({
            "player_id": player["player_id"],
            "creation_per_36": max(0, creation),
        })
    if not rows:
        return pl.DataFrame({"player_id": [], "creation_per_36": []})
    return pl.DataFrame(rows)


def build_player_season_archetype_rows(season_stats: pl.DataFrame) -> list[dict[str, object]]:
    if season_stats.is_empty():
        return []

    season_stats = _normalize_classifier_inputs(season_stats)

    if "season" not in season_stats.columns:
        season_stats = season_stats.with_columns(pl.lit("").alias("season"))

    outputs: list[pl.DataFrame] = []
    seasons = [
        str(season)
        for season in season_stats["season"].drop_nulls().unique().to_list()
        if str(season).strip()
    ]
    for season_value in sorted(seasons):
        scoped = season_stats.filter(pl.col("season") == season_value)
        if scoped.is_empty():
            continue
        archetypes = classify_archetypes(scoped)
        if archetypes.is_empty():
            continue
        result = archetypes.join(_creation_rows(scoped), on="player_id", how="left").with_columns(
            pl.lit(season_value).alias("season")
        )
        available = [column for column in PLAYER_SEASON_ARCHETYPES if column in result.columns]
        outputs.append(result.select(available))

    if not outputs:
        return []
    return pl.concat(outputs, how="diagonal_relaxed").to_dicts()

"""Pure transforms for BPM/VORP-style approximations."""

from __future__ import annotations

import polars as pl

_OBPM_PTS = 0.123
_OBPM_NET_REB = 0.179
_OBPM_AST = 0.267
_OBPM_TOV = -0.194
_OBPM_FGA = -0.186
_OBPM_3PA = 0.172

_DBPM_STL = 0.200
_DBPM_BLK = 0.178
_DBPM_PF = -0.029
_DBPM_DRB = 0.124
_DBPM_AST = 0.046
_DBPM_OPP3PA_CONST = -0.48

_LEAGUE_AVG_PACE = 98.0
_AVG_USG = 0.20


def empty_bpm_vorp() -> pl.DataFrame:
    return pl.DataFrame({
        "player_id": pl.Series([], dtype=pl.Int64),
        "season": pl.Series([], dtype=pl.Utf8),
        "obpm": pl.Series([], dtype=pl.Float64),
        "dbpm": pl.Series([], dtype=pl.Float64),
        "bpm_approx": pl.Series([], dtype=pl.Float64),
        "vorp_approx": pl.Series([], dtype=pl.Float64),
    })


def build_bpm_vorp(
    *,
    player_games: pl.DataFrame,
    fct_games: pl.DataFrame,
    season_stats: pl.DataFrame,
    four_factors: pl.DataFrame,
) -> tuple[pl.DataFrame, float]:
    if player_games.is_empty() or fct_games.is_empty() or season_stats.is_empty():
        return empty_bpm_vorp(), _LEAGUE_AVG_PACE

    if not four_factors.is_empty() and "pace" in four_factors.columns:
        valid_pace = four_factors.filter(pl.col("pace").is_not_null() & (pl.col("pace") > 0))
        league_avg_pace = float(valid_pace["pace"].mean()) if not valid_pace.is_empty() else _LEAGUE_AVG_PACE
        team_pace_columns = ["team_id", "pace"]
        if "season" in four_factors.columns:
            team_pace_columns.insert(1, "season")
        team_pace = four_factors.select(team_pace_columns).unique(
            subset=[column for column in team_pace_columns if column != "pace"],
            keep="last",
        )
    else:
        league_avg_pace = _LEAGUE_AVG_PACE
        team_pace = pl.DataFrame({"team_id": pl.Series([], dtype=pl.Int64), "pace": pl.Series([], dtype=pl.Float64)})

    games_slim = fct_games.select(["game_id", "season"])
    pgs = player_games.join(games_slim, on="game_id", how="left")
    pgs = pgs.with_columns(pl.col("season").fill_null("2025-26"))
    pgs = pgs.filter(pl.col("minutes").is_not_null() & (pl.col("minutes") > 0))

    if not team_pace.is_empty():
        pace_join_keys = ["team_id", "season"] if "season" in team_pace.columns else ["team_id"]
        pgs = pgs.join(
            team_pace.rename({"pace": "team_pace"}),
            on=pace_join_keys,
            how="left",
        )
        pgs = pgs.with_columns(pl.col("team_pace").fill_null(league_avg_pace))
    else:
        pgs = pgs.with_columns(pl.lit(league_avg_pace).alias("team_pace"))

    agg = (
        pgs.group_by(["player_id", "season"])
        .agg([
            pl.col("minutes").mean().alias("mpg"),
            pl.col("pts").mean().alias("ppg"),
            pl.col("reb").mean().alias("rpg"),
            pl.col("oreb").mean().alias("orpg"),
            pl.col("dreb").mean().alias("drpg"),
            pl.col("ast").mean().alias("apg"),
            pl.col("stl").mean().alias("spg"),
            pl.col("blk").mean().alias("bpg"),
            pl.col("tov").mean().alias("topg"),
            pl.col("fga").mean().alias("fga_pg"),
            pl.col("fg3a").mean().alias("fg3a_pg"),
            pl.col("pf").mean().alias("pfpg"),
            pl.col("game_id").count().alias("gp"),
            pl.col("team_pace").mean().alias("team_pace"),
        ])
        .with_columns(pl.col("season").fill_null("2025-26"))
        .filter(pl.col("mpg") > 0)
    )

    usg = (
        season_stats.select(["player_id", "season", "avg_usg_pct"])
        .filter(pl.col("avg_usg_pct").is_not_null())
        .group_by(["player_id", "season"])
        .agg(pl.col("avg_usg_pct").mean())
    )
    agg = agg.join(usg, on=["player_id", "season"], how="left")
    agg = agg.with_columns(pl.col("avg_usg_pct").fill_null(_AVG_USG))

    scale = 4800.0 / (pl.col("mpg") * pl.col("team_pace"))
    agg = agg.with_columns([
        (pl.col("ppg") * scale).alias("pts100"),
        (pl.col("rpg") * scale).alias("reb100"),
        (pl.col("orpg") * scale).alias("oreb100"),
        (pl.col("drpg") * scale).alias("dreb100"),
        (pl.col("apg") * scale).alias("ast100"),
        (pl.col("spg") * scale).alias("stl100"),
        (pl.col("bpg") * scale).alias("blk100"),
        (pl.col("topg") * scale).alias("tov100"),
        (pl.col("fga_pg") * scale).alias("fga100"),
        (pl.col("fg3a_pg") * scale).alias("fg3a100"),
        (pl.col("pfpg") * scale).alias("pf100"),
    ])
    agg = agg.with_columns((2.5 * (pl.col("avg_usg_pct") - _AVG_USG)).alias("role_adj"))
    agg = agg.with_columns(
        (
            _OBPM_PTS * pl.col("pts100")
            + _OBPM_NET_REB * (pl.col("reb100") - 0.26 * pl.col("oreb100"))
            + _OBPM_AST * pl.col("ast100")
            + _OBPM_TOV * pl.col("tov100")
            + _OBPM_FGA * pl.col("fga100")
            + _OBPM_3PA * pl.col("fg3a100")
            + pl.col("role_adj")
        ).round(1).alias("obpm")
    )
    agg = agg.with_columns(
        (
            _DBPM_STL * pl.col("stl100")
            + _DBPM_BLK * pl.col("blk100")
            + _DBPM_PF * pl.col("pf100")
            + _DBPM_DRB * pl.col("dreb100")
            + _DBPM_AST * pl.col("ast100")
            + _DBPM_OPP3PA_CONST
            + pl.col("role_adj") * 0.5
        ).round(1).alias("dbpm")
    )
    agg = agg.with_columns([
        (pl.col("obpm") + pl.col("dbpm")).round(1).alias("bpm_approx"),
        (
            (pl.col("obpm") + pl.col("dbpm") + 2.0)
            * (pl.col("gp") / 82.0)
            * (pl.col("mpg") / 48.0)
        ).round(2).alias("vorp_approx"),
    ])
    return agg.select(["player_id", "season", "obpm", "dbpm", "bpm_approx", "vorp_approx"]), float(league_avg_pace)

"""Shared helpers for working with season-scoped pipeline datasets."""

from __future__ import annotations

import polars as pl

from nba_duckdb.competitions import NBA, normalize_competition_slugs
from nba_duckdb.db import read_table
from nba_duckdb.defaults import get_default_season, sort_seasons


def normalize_requested_seasons(seasons: list[str] | tuple[str, ...] | None) -> list[str]:
    return sort_seasons(
        [
            str(season).strip()
            for season in (seasons or [])
            if str(season).strip()
        ]
    )


def requested_or_default_seasons(
    *,
    season: str | None = None,
    seasons: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    requested = normalize_requested_seasons(seasons)
    if requested:
        return requested
    if season and str(season).strip():
        return sort_seasons([str(season).strip()])
    return [get_default_season()]


def available_seasons(*, regular_season_only: bool = False) -> list[str]:
    games = read_table("silver", "fct_games")
    if games.is_empty() or "season" not in games.columns:
        return [get_default_season()]

    if regular_season_only and "game_type" in games.columns:
        games = games.filter(
            pl.col("game_type").is_in(["regular_season", "Regular Season"])
            | pl.col("game_type").is_null()
        )

    seasons = [
        str(season)
        for season in games["season"].drop_nulls().unique().to_list()
        if str(season).strip()
    ]
    ordered = normalize_requested_seasons(seasons)
    return ordered or [get_default_season()]


def seasons_for_game_ids(game_ids: list[str], *, regular_season_only: bool = False) -> list[str]:
    if not game_ids:
        return []

    games = read_table("silver", "fct_games", "game_id = ANY(%s)", [[str(game_id) for game_id in game_ids]])
    if games.is_empty() or "season" not in games.columns:
        return []

    if regular_season_only and "game_type" in games.columns:
        games = games.filter(
            pl.col("game_type").is_in(["regular_season", "Regular Season"])
            | pl.col("game_type").is_null()
        )

    seasons = [
        str(season)
        for season in games["season"].drop_nulls().unique().to_list()
        if str(season).strip()
    ]
    return sort_seasons(seasons)


def resolved_target_seasons(
    *,
    season: str | None = None,
    seasons: list[str] | tuple[str, ...] | None = None,
    game_ids: list[str] | None = None,
    regular_season_only: bool = False,
) -> list[str]:
    requested = normalize_requested_seasons(seasons)
    if requested:
        return requested

    if season:
        return sort_seasons([season])

    derived = seasons_for_game_ids(game_ids or [], regular_season_only=regular_season_only)
    if derived:
        return derived

    return available_seasons(regular_season_only=regular_season_only)


def filter_frame_to_competitions(
    frame: pl.DataFrame,
    competitions: list[str] | tuple[str, ...] | None,
) -> pl.DataFrame:
    """Filter a schedule-derived frame to explicit competition scope."""

    requested = normalize_competition_slugs(competitions, default=())
    if frame.is_empty() or not requested:
        return frame
    if "competition" not in frame.columns:
        return frame if requested == [NBA.slug] else frame.head(0)
    return frame.filter(pl.col("competition").is_in(requested))

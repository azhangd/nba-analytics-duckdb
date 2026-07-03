"""Shared helpers for working with season-scoped pipeline datasets."""

from __future__ import annotations

import polars as pl

from nba_duckdb.db import read_table
from nba_duckdb.defaults import get_default_season, latest_season, sort_seasons


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


def latest_available_season(*, regular_season_only: bool = False) -> str:
    return latest_season(available_seasons(regular_season_only=regular_season_only)) or get_default_season()


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


def game_ids_for_seasons(seasons: list[str], *, regular_season_only: bool = False) -> list[str]:
    ordered = normalize_requested_seasons(seasons)
    if not ordered:
        return []

    games = read_table("silver", "fct_games", "season = ANY(%s)", [ordered])
    if games.is_empty():
        return []

    if regular_season_only and "game_type" in games.columns:
        games = games.filter(
            pl.col("game_type").is_in(["regular_season", "Regular Season"])
            | pl.col("game_type").is_null()
        )

    return sorted(
        {
            str(game_id)
            for game_id in games["game_id"].drop_nulls().to_list()
            if str(game_id).strip()
        }
    )


def schedule_game_ids_for_seasons(
    seasons: list[str],
    *,
    completed_only: bool = False,
) -> list[str]:
    ordered = normalize_requested_seasons(seasons)
    if not ordered:
        return []

    where = "season = ANY(%s)"
    params: list = [ordered]
    if completed_only:
        where += " AND game_status = 3"

    games = read_table("bronze", "schedule", where, params)
    if games.is_empty() or "game_id" not in games.columns:
        return []

    return sorted(
        {
            str(game_id)
            for game_id in games["game_id"].drop_nulls().to_list()
            if str(game_id).strip()
        }
    )


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


def filter_frame_to_seasons(
    frame: pl.DataFrame,
    seasons: list[str],
    *,
    season_col: str = "season",
) -> pl.DataFrame:
    if frame.is_empty() or season_col not in frame.columns or not seasons:
        return frame
    return frame.filter(pl.col(season_col).is_in(seasons))

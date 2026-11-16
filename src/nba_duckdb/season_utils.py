"""Shared helpers for working with season-scoped pipeline datasets."""

from __future__ import annotations

from datetime import date

import polars as pl

from nba_duckdb.competitions import NBA, normalize_competition_slugs
from nba_duckdb.db import read_table
from nba_duckdb.defaults import get_default_season, get_team_ids, sort_seasons


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

    games = read_table("silver", "fct_games", "game_id = ANY(?)", [[str(game_id) for game_id in game_ids]])
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


class GamesNotInScopeError(ValueError):
    """Requested game ids that aren't finished games in the run's seasons and filters."""


def completed_games_in_scope(scope: dict) -> pl.DataFrame:
    """Finished games (bronze.schedule rows) for a per-game ingest task.

    Applies the run's seasons, competitions, team ids (NBA_DUCKDB_TEAM_IDS), game
    ids and inclusive start/end dates (YYYY-MM-DD). A requested game id that isn't
    a finished game in that scope raises instead of being skipped.
    """
    seasons = requested_or_default_seasons(season=scope.get("season"), seasons=scope.get("seasons"))
    schedule = read_table("bronze", "schedule", "game_status = 3")
    if not schedule.is_empty():
        schedule = schedule.filter(pl.col("season").is_in(seasons))
        schedule = filter_frame_to_competitions(schedule, scope.get("competitions"))
    if not schedule.is_empty() and (team_ids := get_team_ids()) is not None:
        schedule = schedule.filter(
            pl.col("home_team_id").is_in(team_ids) | pl.col("away_team_id").is_in(team_ids)
        )
    if not schedule.is_empty() and (scope.get("start_date") or scope.get("end_date")):
        played_on = pl.col("game_date").str.strptime(pl.Date, "%m/%d/%Y %H:%M:%S")
        if scope.get("start_date"):
            schedule = schedule.filter(played_on >= date.fromisoformat(str(scope["start_date"])))
        if scope.get("end_date"):
            schedule = schedule.filter(played_on <= date.fromisoformat(str(scope["end_date"])))

    requested = [str(game_id) for game_id in scope.get("game_ids") or []]
    if requested:
        schedule = schedule.filter(pl.col("game_id").is_in(requested)) if not schedule.is_empty() else schedule
        found = set(schedule["game_id"].to_list()) if not schedule.is_empty() else set()
        missing = [game_id for game_id in requested if game_id not in found]
        if missing:
            raise GamesNotInScopeError(
                f"Not finished games in seasons {', '.join(seasons)} with this run's filters: "
                f"{', '.join(missing[:10])}"
            )
    return schedule.unique(subset=["game_id"]) if not schedule.is_empty() else schedule

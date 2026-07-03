"""Shared checked-in defaults for the pipeline."""

from __future__ import annotations

import os


def season_sort_key(season: str) -> tuple[int, int]:
    """Return a sortable key for NBA season labels like ``2025-26``."""
    value = str(season or "").strip()
    if not value:
        return (0, 0)

    if "-" not in value:
        try:
            numeric = int(value)
        except ValueError:
            return (0, 0)
        return (numeric, numeric)

    start_raw, end_raw = value.split("-", 1)
    try:
        start_year = int(start_raw)
    except ValueError:
        start_year = 0

    try:
        end_year = int(end_raw) if len(end_raw) == 4 else int(f"{start_raw[:2]}{end_raw}")
    except ValueError:
        end_year = start_year

    return (start_year, end_year)


def sort_seasons(seasons: list[str]) -> list[str]:
    """Sort season labels oldest to newest."""
    unique = {str(season).strip() for season in seasons if str(season).strip()}
    return sorted(unique, key=season_sort_key)


def latest_season(seasons: list[str]) -> str | None:
    """Return the latest season label from a list."""
    ordered = sort_seasons(seasons)
    return ordered[-1] if ordered else None


def get_default_season() -> str:
    return os.environ.get("NBA_DUCKDB_DEFAULT_SEASON", "2025-26")


def get_seasons() -> list[str]:
    """Return the list of seasons to ingest.

    Reads NBA_DUCKDB_SEASONS env var (comma-separated, e.g. "2023-24,2024-25,2025-26").
    Falls back to NBA_DUCKDB_DEFAULT_SEASON when NBA_DUCKDB_SEASONS is unset.
    """
    seasons_raw = os.environ.get("NBA_DUCKDB_SEASONS", "").strip()
    if seasons_raw:
        return sort_seasons([s.strip() for s in seasons_raw.split(",") if s.strip()])
    return [get_default_season()]


ALL_TEAM_IDS = ",".join(str(team_id) for team_id in [
    1610612737, 1610612738, 1610612739, 1610612740, 1610612741,
    1610612742, 1610612743, 1610612744, 1610612745, 1610612746,
    1610612747, 1610612748, 1610612749, 1610612750, 1610612751,
    1610612752, 1610612753, 1610612754, 1610612755, 1610612756,
    1610612757, 1610612758, 1610612759, 1610612760, 1610612761,
    1610612762, 1610612763, 1610612764, 1610612765, 1610612766,
])

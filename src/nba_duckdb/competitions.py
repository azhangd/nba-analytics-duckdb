"""Canonical competition metadata for NBA-operated data feeds."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Competition:
    """One independently scheduled competition exposed by the NBA stats feeds."""

    slug: str
    league_id: str
    display_name: str
    game_type: str
    season_type: str = "Regular Season"


NBA = Competition(
    slug="nba",
    league_id="00",
    display_name="NBA",
    game_type="nba",
)
SUMMER_LEAGUE_CALIFORNIA = Competition(
    slug="summer_league_california",
    league_id="13",
    display_name="California Classic Summer League",
    game_type="summer_league",
)
SUMMER_LEAGUE_VEGAS = Competition(
    slug="summer_league_vegas",
    league_id="15",
    display_name="NBA Summer League (Las Vegas)",
    game_type="summer_league",
)
SUMMER_LEAGUE_SALT_LAKE_CITY = Competition(
    slug="summer_league_salt_lake_city",
    league_id="16",
    display_name="Salt Lake City Summer League",
    game_type="summer_league",
)

SUMMER_LEAGUE_COMPETITIONS = (
    SUMMER_LEAGUE_CALIFORNIA,
    SUMMER_LEAGUE_VEGAS,
    SUMMER_LEAGUE_SALT_LAKE_CITY,
)
COMPETITIONS = {
    competition.slug: competition
    for competition in (NBA, *SUMMER_LEAGUE_COMPETITIONS)
}
COMPETITIONS_BY_LEAGUE_ID = {
    competition.league_id: competition
    for competition in COMPETITIONS.values()
}
SUMMER_LEAGUE_SLUGS = tuple(
    competition.slug for competition in SUMMER_LEAGUE_COMPETITIONS
)


def competition_named(slug: str) -> Competition:
    normalized = str(slug).strip().lower().replace("-", "_")
    try:
        return COMPETITIONS[normalized]
    except KeyError as exc:
        choices = ", ".join(sorted(COMPETITIONS))
        raise ValueError(f"Unknown competition {slug!r}. Choose one of: {choices}") from exc


def normalize_competition_slugs(
    values: Iterable[str] | None,
    *,
    default: Iterable[str] = (NBA.slug,),
) -> list[str]:
    requested = list(values or default)
    normalized: list[str] = []
    for value in requested:
        slug = competition_named(value).slug
        if slug not in normalized:
            normalized.append(slug)
    return normalized


def competitions_for_slugs(
    values: Iterable[str] | None,
    *,
    default: Iterable[str] = (NBA.slug,),
) -> list[Competition]:
    return [
        competition_named(slug)
        for slug in normalize_competition_slugs(values, default=default)
    ]


def competition_for_league_id(league_id: str | int | None) -> Competition:
    return COMPETITIONS_BY_LEAGUE_ID.get(str(league_id or NBA.league_id), NBA)

"""Pure transforms for lineup stints."""

from __future__ import annotations

import logging

import polars as pl

from nba_duckdb.analytics.lineup_tracker import _PERIOD_MARKERS, _period_length, track_lineups
from nba_duckdb.analytics.rotation_lineups import (
    build_lineup_stints_from_rotation,
    has_rotation_data,
)
from nba_duckdb.transforms.silver._parsing import build_roster_name_map, load_json

logger = logging.getLogger(__name__)

# How far short of the full game a team's rotation-built lineups may fall before the rotation is
# treated as broken. On 2025-26, good rotations covered every game to within 3 seconds, and the
# broken ones (players missing, or up to 13 "on court" at once) fell short by more than 2 minutes.
ROTATION_SHORTFALL_SECONDS = 60.0

FCT_LINEUPS = (
    "game_id",
    "stint_number",
    "period",
    "team_id",
    "player_ids_str",
    "player_count",
    "start_clock_seconds",
    "end_clock_seconds",
    "duration_seconds",
    "points_for",
    "points_against",
)


def build_fct_lineup_rows(
    pbp_df: pl.DataFrame,
    games_df: pl.DataFrame,
    boxscores_df: pl.DataFrame,
    detail_rows: list[dict],
) -> list[dict]:
    if pbp_df.is_empty():
        return []
    game_meta = {
        str(row["game_id"]): {
            "home_team_id": int(row["home_team_id"]),
            "away_team_id": int(row["away_team_id"]),
        }
        for row in games_df.iter_rows(named=True)
        if row.get("game_id") and row.get("home_team_id") and row.get("away_team_id")
    }
    detail_map = {
        str(row["game_id"]): load_json(row.get("detail_json"))
        for row in detail_rows
        if row.get("game_id")
    }
    frames = []
    for game_id in [str(value) for value in pbp_df["game_id"].unique().to_list()]:
        game_pbp = pbp_df.filter(pl.col("game_id") == game_id)
        game_boxscores = boxscores_df.filter(pl.col("game_id") == game_id) if "game_id" in boxscores_df.columns else pl.DataFrame()
        game_info = game_meta.get(game_id)
        if not game_info:
            continue
        detail = detail_map.get(game_id, {})
        rotation_payload = detail.get("rotation", {})
        stints = pl.DataFrame()
        if has_rotation_data(rotation_payload):
            stints = build_lineup_stints_from_rotation(
                game_id=game_id,
                rotation_payload=rotation_payload,
                pbp_df=game_pbp,
                home_team_id=game_info["home_team_id"],
                away_team_id=game_info["away_team_id"],
            )
            if not _covers_game(stints, game_pbp, (game_info["home_team_id"], game_info["away_team_id"])):
                logger.warning(
                    "Rotation data for %s doesn't keep five players per team on court for the whole game; "
                    "building lineups from substitutions instead",
                    game_id,
                )
                stints = pl.DataFrame()
        if stints.is_empty():
            stints = _stints_from_substitutions(game_id, game_pbp, game_boxscores, game_info["home_team_id"])
        if not stints.is_empty():
            frames.append(stints.select(list(FCT_LINEUPS)))
    if not frames:
        return []
    return pl.concat(frames).to_dicts()


def _covers_game(stints: pl.DataFrame, game_pbp: pl.DataFrame, team_ids: tuple[int, int]) -> bool:
    """Whether each team's stints add up to the full game, give or take ROTATION_SHORTFALL_SECONDS."""
    if stints.is_empty():
        return False
    # Count the periods that were played: the All-Star tournament plays one 12-minute period, and a
    # period holding only a "Game End" marker after a game decided in regulation wasn't played.
    played = game_pbp.filter(~pl.col("action_type").str.to_lowercase().is_in(list(_PERIOD_MARKERS)))
    game_seconds = sum(_period_length(int(period)) for period in played["period"].unique().to_list())
    covered = dict(stints.group_by("team_id").agg(pl.col("duration_seconds").sum()).rows())
    return all(covered.get(team_id, 0.0) >= game_seconds - ROTATION_SHORTFALL_SECONDS for team_id in team_ids)


def _stints_from_substitutions(
    game_id: str, game_pbp: pl.DataFrame, game_boxscores: pl.DataFrame, home_team_id: int
) -> pl.DataFrame:
    starters_by_team: dict[int, set[int]] = {}
    if not game_boxscores.is_empty() and {"started", "minutes"}.issubset(game_boxscores.columns):
        starter_rows = game_boxscores.filter(pl.col("started") & (pl.col("minutes") > 0))
        for row in starter_rows.iter_rows(named=True):
            if row.get("team_id") and row.get("player_id"):
                starters_by_team.setdefault(int(row["team_id"]), set()).add(int(row["player_id"]))
    return track_lineups(
        game_pbp,
        game_id,
        home_team_id=home_team_id,
        starters_by_team=starters_by_team,
        roster_name_map=build_roster_name_map(game_boxscores),
    )

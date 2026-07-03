"""Pure transforms for lineup stints."""

from __future__ import annotations

import polars as pl

from nba_duckdb.analytics.lineup_tracker import track_lineups
from nba_duckdb.analytics.rotation_lineups import (
    build_lineup_stints_from_rotation,
    has_rotation_data,
)
from nba_duckdb.transforms.silver._parsing import build_roster_name_map, load_json

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
        detail = detail_map.get(game_id, {})
        rotation_payload = detail.get("rotation", {})
        if has_rotation_data(rotation_payload):
            game_info = game_meta.get(game_id)
            if not game_info:
                continue
            stints = build_lineup_stints_from_rotation(
                game_id=game_id,
                rotation_payload=rotation_payload,
                pbp_df=game_pbp,
                home_team_id=game_info["home_team_id"],
                away_team_id=game_info["away_team_id"],
            )
        else:
            starters_by_team: dict[int, set[int]] = {}
            roster_name_map = build_roster_name_map(game_boxscores)
            if not game_boxscores.is_empty() and {"started", "minutes"}.issubset(game_boxscores.columns):
                starter_rows = game_boxscores.filter(pl.col("started") & (pl.col("minutes") > 0))
                for row in starter_rows.iter_rows(named=True):
                    if row.get("team_id") and row.get("player_id"):
                        starters_by_team.setdefault(int(row["team_id"]), set()).add(int(row["player_id"]))
            stints = track_lineups(
                game_pbp,
                game_id,
                starters_by_team=starters_by_team,
                roster_name_map=roster_name_map,
            )
        if not stints.is_empty():
            frames.append(stints.select(list(FCT_LINEUPS)))
    if not frames:
        return []
    return pl.concat(frames).to_dicts()

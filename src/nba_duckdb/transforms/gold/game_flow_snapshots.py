"""Pure transforms for gold.game_flow_snapshots."""

from __future__ import annotations

import json

import polars as pl

from nba_duckdb.analytics.game_flow import compute_game_flow
from nba_duckdb.transforms.frames import select_columns

GAME_FLOW_SNAPSHOTS = (
    "game_id",
    "period",
    "clock_seconds_remaining",
    "game_seconds_elapsed",
    "home_score",
    "away_score",
    "margin",
    "home_win_prob",
)

OUTPUT_COLUMNS = list(GAME_FLOW_SNAPSHOTS)


def build_game_flow_rows(
    pbp: pl.DataFrame,
    games: pl.DataFrame,
    elo_history: pl.DataFrame | None = None,
    model_artifacts: pl.DataFrame | None = None,
) -> tuple[list[dict], list[str]]:
    game_metadata = {
        str(row.get("game_id")): {
            "season": str(row.get("season") or ""),
            "home_team_id": int(row["home_team_id"]) if row.get("home_team_id") else None,
            "away_team_id": int(row["away_team_id"]) if row.get("away_team_id") else None,
        }
        for row in games.iter_rows(named=True)
        if row.get("game_id")
    } if not games.is_empty() else {}
    pregame_elo_by_game: dict[str, float] = {}
    if elo_history is not None and not elo_history.is_empty():
        for row in elo_history.iter_rows(named=True):
            game_id = str(row.get("game_id") or "")
            metadata = game_metadata.get(game_id, {})
            team_id = row.get("team_id")
            elo_before = row.get("elo_before")
            opp_elo_before = row.get("opp_elo_before")
            if (
                game_id
                and team_id == metadata.get("home_team_id")
                and elo_before is not None
                and opp_elo_before is not None
            ):
                pregame_elo_by_game[game_id] = (
                    float(elo_before) - float(opp_elo_before)
                ) / 100.0

    coefficients_by_season: dict[str, dict] = {}
    if model_artifacts is not None and not model_artifacts.is_empty():
        for row in model_artifacts.iter_rows(named=True):
            if row.get("model_name") != "win_probability":
                continue
            metadata = row.get("metadata_json")
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            coefficients = metadata.get("coefficients") if isinstance(metadata, dict) else None
            season = str(row.get("season") or "")
            if season and coefficients:
                coefficients_by_season[season] = coefficients

    target_game_ids = [str(game_id) for game_id in pbp["game_id"].unique().to_list()]
    frames = []
    for game_id in target_game_ids:
        metadata = game_metadata.get(game_id, {})
        season = str(metadata.get("season") or "")
        flow = compute_game_flow(
            pbp.filter(pl.col("game_id") == game_id),
            game_id,
            season=season,
            home_team_id=metadata.get("home_team_id"),
            away_team_id=metadata.get("away_team_id"),
            pregame_elo_diff=pregame_elo_by_game.get(game_id, 0.0),
            coefficients=coefficients_by_season.get(season),
        )
        if not flow.is_empty():
            frames.append(flow)
    if not frames:
        return [], target_game_ids
    result = select_columns(pl.concat(frames), OUTPUT_COLUMNS, context="gold.game_flow_snapshots")
    return result.to_dicts(), target_game_ids

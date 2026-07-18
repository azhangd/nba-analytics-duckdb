"""Fail-closed coverage checks for the Summer League ingestion graph."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import polars as pl

from nba_duckdb.competitions import SUMMER_LEAGUE_SLUGS, normalize_competition_slugs
from nba_duckdb.db import read_table
from nba_duckdb.season_utils import requested_or_default_seasons


def _json_document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _game_ids(frame: pl.DataFrame) -> set[str]:
    if frame.is_empty() or "game_id" not in frame.columns:
        return set()
    return {
        str(game_id)
        for game_id in frame["game_id"].drop_nulls().to_list()
        if str(game_id).strip()
    }


def _valid_payload_game_ids(
    frame: pl.DataFrame,
    payload_column: str,
    validator: Callable[[dict[str, Any]], bool],
) -> set[str]:
    if frame.is_empty() or payload_column not in frame.columns:
        return set()
    return {
        str(row["game_id"])
        for row in frame.iter_rows(named=True)
        if validator(_json_document(row.get(payload_column)))
    }


def _assert_coverage(label: str, expected: set[str], actual: set[str]) -> None:
    missing = sorted(expected - actual)
    if missing:
        examples = ", ".join(missing[:10])
        raise RuntimeError(
            f"Summer League quality gate: {label} missing {len(missing)} "
            f"completed game(s): {examples}"
        )


def run(**kwargs) -> dict[str, Any]:
    seasons = requested_or_default_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
    )
    competitions = normalize_competition_slugs(
        kwargs.get("competitions"),
        default=SUMMER_LEAGUE_SLUGS,
    )
    invalid = sorted(set(competitions) - set(SUMMER_LEAGUE_SLUGS))
    if invalid:
        raise ValueError(
            "Summer League quality gate received non-Summer competition(s): "
            + ", ".join(invalid)
        )

    schedule = read_table("bronze", "schedule")
    if schedule.is_empty():
        raise RuntimeError("Summer League quality gate: bronze.schedule is empty")
    schedule = schedule.filter(
        pl.col("season").is_in(seasons)
        & pl.col("competition").is_in(competitions)
    )
    requested_game_ids = {
        str(game_id) for game_id in (kwargs.get("game_ids") or [])
    }
    if requested_game_ids:
        schedule = schedule.filter(pl.col("game_id").is_in(requested_game_ids))
    if schedule.is_empty():
        raise RuntimeError(
            "Summer League quality gate: no schedule rows match the requested scope"
        )

    competition_counts = {
        str(row["competition"]): int(row["len"])
        for row in schedule.group_by("competition").len().iter_rows(named=True)
    }
    if not requested_game_ids:
        missing_competitions = [
            competition
            for competition in competitions
            if competition_counts.get(competition, 0) == 0
        ]
        if missing_competitions:
            raise RuntimeError(
                "Summer League quality gate: schedule missing competition(s): "
                + ", ".join(missing_competitions)
            )

    schedule_ids = _game_ids(schedule)
    completed_ids = _game_ids(schedule.filter(pl.col("game_status") == 3))

    silver_games = read_table("silver", "summer_league_games")
    _assert_coverage(
        "silver.summer_league_games",
        schedule_ids,
        _game_ids(silver_games),
    )

    if completed_ids:
        bronze_boxscores = read_table("bronze", "boxscores")
        bronze_pbp = read_table("bronze", "play_by_play")
        bronze_shots = read_table("bronze", "shot_charts")
        _assert_coverage(
            "bronze.boxscores",
            completed_ids,
            _valid_payload_game_ids(
                bronze_boxscores,
                "traditional_json",
                lambda doc: bool(doc.get("boxScoreTraditional") or doc.get("game")),
            ),
        )
        _assert_coverage(
            "bronze.play_by_play",
            completed_ids,
            _valid_payload_game_ids(
                bronze_pbp,
                "pbp_json",
                lambda doc: bool(doc.get("game", {}).get("actions")),
            ),
        )
        _assert_coverage(
            "bronze.shot_charts",
            completed_ids,
            _valid_payload_game_ids(
                bronze_shots,
                "shot_chart_json",
                lambda doc: any(
                    result_set.get("name") == "Shot_Chart_Detail"
                    and bool(result_set.get("rowSet"))
                    for result_set in doc.get("resultSets", [])
                ),
            ),
        )
        _assert_coverage(
            "silver.summer_league_boxscores",
            completed_ids,
            _game_ids(read_table("silver", "summer_league_boxscores")),
        )
        _assert_coverage(
            "silver.summer_league_play_by_play",
            completed_ids,
            _game_ids(read_table("silver", "summer_league_play_by_play")),
        )
        _assert_coverage(
            "silver.summer_league_shots",
            completed_ids,
            _game_ids(read_table("silver", "summer_league_shots")),
        )

    return {
        "status": "success",
        "seasons": seasons,
        "competitions": competitions,
        "competition_counts": competition_counts,
        "schedule_games": len(schedule_ids),
        "completed_games": len(completed_ids),
    }


TASK_DEF = {
    "layer": "quality",
    "task_type": "quality",
    "inputs": (
        "bronze.schedule",
        "bronze.boxscores",
        "bronze.play_by_play",
        "bronze.shot_charts",
        "silver.summer_league_games",
        "silver.summer_league_boxscores",
        "silver.summer_league_play_by_play",
        "silver.summer_league_shots",
    ),
    "optional_inputs": (),
    "outputs": (),
    "mutates": (),
    "graphs": ("summer_league",),
    "modes": ("live",),
    "required": True,
    "quality_outputs": (),
    "regular_season_only": False,
    "live_order": 200,
}

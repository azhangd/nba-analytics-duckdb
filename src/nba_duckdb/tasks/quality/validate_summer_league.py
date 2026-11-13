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
    """Parse a stored payload; a missing payload is an empty document."""
    if value is None:
        return {}
    return value if isinstance(value, dict) else json.loads(value)


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


def _schedule_score(document: dict[str, Any], side: str) -> int | None:
    team = document.get(f"{side}Team", document.get(f"{side.title()}Team", {}))
    if not isinstance(team, dict):
        return None
    value = team.get("score", team.get("Score"))
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _boxscore_teams(document: dict[str, Any]) -> list[dict[str, Any]]:
    root = document.get("boxScoreTraditional", document.get("game", document))
    if not isinstance(root, dict):
        return []
    teams = [root.get("homeTeam"), root.get("awayTeam")]
    return [team for team in teams if isinstance(team, dict)]


def _team_stat(team: dict[str, Any], name: str) -> int | None:
    statistics = team.get("statistics")
    if not isinstance(statistics, dict):
        return None
    value = statistics.get(name)
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _free_throw_actions(document: dict[str, Any]) -> list[dict[str, Any]]:
    game = document.get("game")
    actions = game.get("actions") if isinstance(game, dict) else None
    if not isinstance(actions, list):
        return []
    return [
        action
        for action in actions
        if isinstance(action, dict)
        and str(action.get("actionType") or "").strip().lower()
        in {"free throw", "freethrow"}
    ]


def _is_made_free_throw(action: dict[str, Any]) -> bool:
    description = str(action.get("description") or "").lstrip().upper()
    return not (description == "MISS" or description.startswith("MISS "))


def _semantic_reconciliation(
    schedule: pl.DataFrame,
    boxscores: pl.DataFrame,
    play_by_play: pl.DataFrame,
    completed_ids: set[str],
) -> dict[str, Any]:
    schedule_by_game = {
        str(row["game_id"]): _json_document(row.get("raw_json"))
        for row in schedule.iter_rows(named=True)
        if str(row.get("game_id") or "") in completed_ids
    }
    box_by_game = {
        str(row["game_id"]): _json_document(row.get("traditional_json"))
        for row in boxscores.iter_rows(named=True)
        if str(row.get("game_id") or "") in completed_ids
    }
    pbp_by_game = {
        str(row["game_id"]): _json_document(row.get("pbp_json"))
        for row in play_by_play.iter_rows(named=True)
        if str(row.get("game_id") or "") in completed_ids
    }

    mismatches: list[dict[str, Any]] = []
    for game_id in sorted(completed_ids):
        teams = _boxscore_teams(box_by_game.get(game_id, {}))
        box_fta = [_team_stat(team, "freeThrowsAttempted") for team in teams]
        box_ftm = [_team_stat(team, "freeThrowsMade") for team in teams]
        box_points = [_team_stat(team, "points") for team in teams]
        actions = _free_throw_actions(pbp_by_game.get(game_id, {}))
        pbp_totals = {
            "attempted": len(actions),
            "made": sum(_is_made_free_throw(action) for action in actions),
        }
        box_totals = {
            "attempted": sum(value for value in box_fta if value is not None),
            "made": sum(value for value in box_ftm if value is not None),
        }
        if len(teams) != 2 or any(value is None for value in (*box_fta, *box_ftm)):
            mismatches.append({"game_id": game_id, "check": "boxscore_ft_fields"})
        elif pbp_totals != box_totals:
            mismatches.append(
                {
                    "game_id": game_id,
                    "check": "pbp_vs_boxscore_free_throws",
                    "play_by_play": pbp_totals,
                    "boxscore": box_totals,
                }
            )

        schedule_document = schedule_by_game.get(game_id, {})
        schedule_points = [
            _schedule_score(schedule_document, "home"),
            _schedule_score(schedule_document, "away"),
        ]
        if (
            len(teams) != 2
            or any(value is None for value in (*box_points, *schedule_points))
        ):
            mismatches.append({"game_id": game_id, "check": "final_score_fields"})
        elif box_points != schedule_points:
            mismatches.append(
                {
                    "game_id": game_id,
                    "check": "schedule_vs_boxscore_final_score",
                    "schedule": schedule_points,
                    "boxscore": box_points,
                }
            )

    if mismatches:
        raise RuntimeError(
            "Summer League semantic reconciliation failed for "
            f"{len({row['game_id'] for row in mismatches})} game(s): "
            f"{json.dumps(mismatches[:10], sort_keys=True)}"
        )
    return {
        "games_checked": len(completed_ids),
        "free_throw_mismatches": 0,
        "final_score_mismatches": 0,
    }


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

    semantic_reconciliation = {
        "games_checked": 0,
        "free_throw_mismatches": 0,
        "final_score_mismatches": 0,
    }
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
        semantic_reconciliation = _semantic_reconciliation(
            schedule,
            bronze_boxscores,
            bronze_pbp,
            completed_ids,
        )

    return {
        "status": "success",
        "seasons": seasons,
        "competitions": competitions,
        "competition_counts": competition_counts,
        "schedule_games": len(schedule_ids),
        "completed_games": len(completed_ids),
        "semantic_reconciliation": semantic_reconciliation,
    }


TASK_DEF = {
    "layer": "quality",
    "inputs": ("bronze.schedule", "bronze.boxscores", "bronze.play_by_play", "bronze.shot_charts", "silver.summer_league_games", "silver.summer_league_boxscores", "silver.summer_league_play_by_play", "silver.summer_league_shots"),
    "outputs": (),
    "graphs": ("summer_league",),
    "modes": ("live",),
    "regular_season_only": False,
    "live_order": 200,
}

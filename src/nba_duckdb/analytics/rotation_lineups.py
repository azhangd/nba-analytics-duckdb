"""Build lineup stints from NBA Stats GameRotation payloads."""

from __future__ import annotations

import bisect
from collections import defaultdict
from typing import Any

import polars as pl


def _period_length(period: int) -> float:
    return 720.0 if period <= 4 else 300.0


def _period_start_elapsed(period: int) -> float:
    if period <= 4:
        return float((period - 1) * 720)
    return 2880.0 + float((period - 5) * 300)


def _period_for_elapsed(elapsed_seconds: float) -> int:
    if elapsed_seconds < 2880.0:
        return int(elapsed_seconds // 720.0) + 1
    return 5 + int((elapsed_seconds - 2880.0) // 300.0)


def _elapsed_from_pbp_row(row: dict[str, Any]) -> float:
    period = int(row.get("period", 0) or 0)
    if period <= 0:
        return 0.0
    clock = float(row.get("clock_seconds_remaining", 0.0) or 0.0)
    return _period_start_elapsed(period) + (_period_length(period) - clock)


def _score_timeline(pbp_df: pl.DataFrame) -> tuple[list[float], list[tuple[int, int]]]:
    timeline_times = [0.0]
    timeline_scores = [(0, 0)]

    rows = (
        pbp_df.sort(["period", "clock_seconds_remaining", "action_number"], descending=[False, True, False])
        .iter_rows(named=True)
    )
    for row in rows:
        raw_home = row.get("score_home") or ""
        raw_away = row.get("score_away") or ""
        if not raw_home or not raw_away:
            continue
        try:
            score = (int(str(raw_home).strip()), int(str(raw_away).strip()))
        except (TypeError, ValueError):
            continue

        elapsed = _elapsed_from_pbp_row(row)
        if timeline_times and abs(timeline_times[-1] - elapsed) < 1e-6:
            timeline_scores[-1] = score
        else:
            timeline_times.append(elapsed)
            timeline_scores.append(score)

    return timeline_times, timeline_scores


def _score_at(
    timeline_times: list[float],
    timeline_scores: list[tuple[int, int]],
    elapsed_seconds: float,
) -> tuple[int, int]:
    idx = bisect.bisect_right(timeline_times, elapsed_seconds) - 1
    if idx < 0:
        return (0, 0)
    return timeline_scores[idx]


def _parse_result_set(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    for result_set in payload.get("resultSets", []):
        if result_set.get("name") != name:
            continue
        headers = result_set.get("headers", [])
        return [dict(zip(headers, row, strict=False)) for row in result_set.get("rowSet", [])]
    return []


def has_rotation_data(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    return bool(_parse_result_set(payload, "HomeTeam") or _parse_result_set(payload, "AwayTeam"))


def _rotation_intervals(payload: dict[str, Any]) -> dict[int, list[dict[str, float | int]]]:
    intervals_by_team: dict[int, list[dict[str, float | int]]] = defaultdict(list)
    for result_name in ("HomeTeam", "AwayTeam"):
        for row in _parse_result_set(payload, result_name):
            team_id = int(row.get("TEAM_ID", 0) or 0)
            player_id = int(row.get("PERSON_ID", 0) or 0)
            start = float(row.get("IN_TIME_REAL", 0) or 0.0) / 10.0
            end = float(row.get("OUT_TIME_REAL", 0) or 0.0) / 10.0
            if not team_id or not player_id or end <= start:
                continue
            intervals_by_team[team_id].append(
                {
                    "player_id": player_id,
                    "start_elapsed": start,
                    "end_elapsed": end,
                }
            )
    return intervals_by_team


def _boundary_points(intervals: list[dict[str, float | int]]) -> list[float]:
    if not intervals:
        return []
    max_elapsed = max(float(interval["end_elapsed"]) for interval in intervals)
    boundaries = {0.0, max_elapsed}
    for interval in intervals:
        boundaries.add(float(interval["start_elapsed"]))
        boundaries.add(float(interval["end_elapsed"]))

    boundary = 720.0
    while boundary < max_elapsed:
        boundaries.add(boundary)
        boundary += 720.0

    overtime_boundary = 2880.0
    while overtime_boundary < max_elapsed:
        boundaries.add(overtime_boundary)
        overtime_boundary += 300.0

    return sorted(boundaries)


def build_lineup_stints_from_rotation(
    *,
    game_id: str,
    rotation_payload: dict[str, Any],
    pbp_df: pl.DataFrame,
    home_team_id: int,
    away_team_id: int,
) -> pl.DataFrame:
    """Reconstruct lineup stints from official rotation intervals."""
    intervals_by_team = _rotation_intervals(rotation_payload)
    if not intervals_by_team:
        return pl.DataFrame()

    timeline_times, timeline_scores = _score_timeline(pbp_df)
    stints: list[dict[str, Any]] = []
    stint_number = 0

    for team_id, intervals in intervals_by_team.items():
        previous_key: tuple[int, str] | None = None
        previous_stint: dict[str, Any] | None = None
        boundaries = _boundary_points(intervals)

        for start_elapsed, end_elapsed in zip(boundaries, boundaries[1:]):
            if end_elapsed <= start_elapsed:
                continue

            midpoint = (start_elapsed + end_elapsed) / 2.0
            active_players = sorted(
                int(interval["player_id"])
                for interval in intervals
                if float(interval["start_elapsed"]) <= midpoint < float(interval["end_elapsed"])
            )
            if len(active_players) != 5:
                continue

            period = _period_for_elapsed(start_elapsed + 1e-6)
            period_start = _period_start_elapsed(period)
            period_length = _period_length(period)
            start_clock = round(max(period_length - (start_elapsed - period_start), 0.0), 1)
            end_clock = round(max(period_length - (end_elapsed - period_start), 0.0), 1)

            start_home, start_away = _score_at(timeline_times, timeline_scores, start_elapsed)
            end_home, end_away = _score_at(timeline_times, timeline_scores, end_elapsed)
            if team_id == home_team_id:
                points_for = end_home - start_home
                points_against = end_away - start_away
            elif team_id == away_team_id:
                points_for = end_away - start_away
                points_against = end_home - start_home
            else:
                continue

            player_ids_str = ",".join(str(player_id) for player_id in active_players)
            key = (period, player_ids_str)
            if previous_key == key and previous_stint is not None and abs(previous_stint["end_clock_seconds"] - start_clock) < 1e-6:
                previous_stint["end_clock_seconds"] = end_clock
                previous_stint["duration_seconds"] = round(
                    float(previous_stint["duration_seconds"]) + (end_elapsed - start_elapsed),
                    1,
                )
                previous_stint["points_for"] += points_for
                previous_stint["points_against"] += points_against
                continue

            stint_number += 1
            previous_stint = {
                "game_id": game_id,
                "stint_number": stint_number,
                "period": period,
                "team_id": team_id,
                "player_ids_str": player_ids_str,
                "player_count": 5,
                "start_clock_seconds": start_clock,
                "end_clock_seconds": end_clock,
                "duration_seconds": round(end_elapsed - start_elapsed, 1),
                "points_for": int(points_for),
                "points_against": int(points_against),
            }
            stints.append(previous_stint)
            previous_key = key

    if not stints:
        return pl.DataFrame()
    return pl.DataFrame(stints)

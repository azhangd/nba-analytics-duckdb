"""Tests for reconstructing lineup stints from official rotation intervals."""

import polars as pl

from nba_duckdb.analytics.rotation_lineups import build_lineup_stints_from_rotation


def _rotation_payload(home_rows: list[list], away_rows: list[list] | None = None) -> dict:
    headers = [
        "GAME_ID",
        "TEAM_ID",
        "TEAM_CITY",
        "TEAM_NAME",
        "PERSON_ID",
        "PLAYER_FIRST",
        "PLAYER_LAST",
        "IN_TIME_REAL",
        "OUT_TIME_REAL",
        "PLAYER_PTS",
        "PT_DIFF",
        "USG_PCT",
    ]
    return {
        "resultSets": [
            {"name": "HomeTeam", "headers": headers, "rowSet": home_rows},
            {"name": "AwayTeam", "headers": headers, "rowSet": away_rows or []},
        ]
    }


def _pbp(events: list[dict]) -> pl.DataFrame:
    defaults = {
        "game_id": "0022500463",
        "action_number": 0,
        "period": 1,
        "clock_seconds_remaining": 720.0,
        "score_home": "",
        "score_away": "",
    }
    rows = [{**defaults, "action_number": idx, **event} for idx, event in enumerate(events)]
    if rows:
        return pl.DataFrame(rows)
    return pl.DataFrame(
        schema={
            "game_id": pl.String,
            "action_number": pl.Int64,
            "period": pl.Int64,
            "clock_seconds_remaining": pl.Float64,
            "score_home": pl.String,
            "score_away": pl.String,
        }
    )


def test_build_lineups_from_rotation_uses_scoreboard_deltas():
    payload = _rotation_payload(
        home_rows=[
            ["0022500463", 1, "", "", 101, "", "", 0.0, 1200.0, 0, 0, 0],
            ["0022500463", 1, "", "", 102, "", "", 0.0, 2400.0, 0, 0, 0],
            ["0022500463", 1, "", "", 103, "", "", 0.0, 2400.0, 0, 0, 0],
            ["0022500463", 1, "", "", 104, "", "", 0.0, 2400.0, 0, 0, 0],
            ["0022500463", 1, "", "", 105, "", "", 0.0, 2400.0, 0, 0, 0],
            ["0022500463", 1, "", "", 201, "", "", 1200.0, 2400.0, 0, 0, 0],
        ]
    )
    pbp = _pbp(
        [
            {"period": 1, "clock_seconds_remaining": 660.0, "score_home": "2", "score_away": "0"},
            {"period": 1, "clock_seconds_remaining": 540.0, "score_home": "4", "score_away": "1"},
        ]
    )

    stints = build_lineup_stints_from_rotation(
        game_id="0022500463",
        rotation_payload=payload,
        pbp_df=pbp,
        home_team_id=1,
        away_team_id=2,
    )

    assert len(stints) == 2
    first = stints.row(0, named=True)
    second = stints.row(1, named=True)

    assert first["player_ids_str"] == "101,102,103,104,105"
    assert first["start_clock_seconds"] == 720.0
    assert first["end_clock_seconds"] == 600.0
    assert first["duration_seconds"] == 120.0
    assert first["points_for"] == 2
    assert first["points_against"] == 0

    assert second["player_ids_str"] == "102,103,104,105,201"
    assert second["start_clock_seconds"] == 600.0
    assert second["end_clock_seconds"] == 480.0
    assert second["duration_seconds"] == 120.0
    assert second["points_for"] == 2
    assert second["points_against"] == 1


def test_build_lineups_from_rotation_splits_cross_period_intervals():
    payload = _rotation_payload(
        home_rows=[
            ["0022500463", 1, "", "", 101, "", "", 6000.0, 7800.0, 0, 0, 0],
            ["0022500463", 1, "", "", 102, "", "", 6000.0, 7800.0, 0, 0, 0],
            ["0022500463", 1, "", "", 103, "", "", 6000.0, 7800.0, 0, 0, 0],
            ["0022500463", 1, "", "", 104, "", "", 6000.0, 7800.0, 0, 0, 0],
            ["0022500463", 1, "", "", 105, "", "", 6000.0, 7800.0, 0, 0, 0],
        ]
    )

    stints = build_lineup_stints_from_rotation(
        game_id="0022500463",
        rotation_payload=payload,
        pbp_df=_pbp([]),
        home_team_id=1,
        away_team_id=2,
    )

    assert len(stints) == 2
    first = stints.row(0, named=True)
    second = stints.row(1, named=True)

    assert first["period"] == 1
    assert first["start_clock_seconds"] == 120.0
    assert first["end_clock_seconds"] == 0.0
    assert first["duration_seconds"] == 120.0

    assert second["period"] == 2
    assert second["start_clock_seconds"] == 720.0
    assert second["end_clock_seconds"] == 660.0
    assert second["duration_seconds"] == 60.0

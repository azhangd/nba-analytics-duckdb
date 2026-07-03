"""Tests for lineup tracking and stint reconstruction."""

import polars as pl

from nba_duckdb.analytics.lineup_tracker import track_lineups


def _make_pbp(events: list[dict]) -> pl.DataFrame:
    defaults = {
        "game_id": "0022500463",
        "action_number": 0,
        "period": 1,
        "clock": "PT12M00.00S",
        "clock_seconds_remaining": 720.0,
        "team_id": None,
        "player_id": None,
        "player_name": "",
        "action_type": "",
        "description": "",
        "score_home": "0",
        "score_away": "0",
    }
    rows = []
    for index, event in enumerate(events):
        rows.append({**defaults, "action_number": index, **event})
    return pl.DataFrame(rows)


def test_seeded_starters_cover_opening_stint_and_batch_substitutions():
    pbp = _make_pbp([
        {"period": 1, "clock_seconds_remaining": 720.0, "action_type": "Jump Ball",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "Jump Ball"},
        {"period": 1, "clock_seconds_remaining": 700.0, "action_type": "Made Shot",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "Made Shot",
         "score_home": "2", "score_away": "0"},
        {"period": 1, "clock_seconds_remaining": 338.0, "action_type": "Substitution",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "SUB out: A Starter"},
        {"period": 1, "clock_seconds_remaining": 338.0, "action_type": "Substitution",
         "team_id": 1, "player_id": 102, "player_name": "B Starter", "description": "SUB out: B Starter"},
        {"period": 1, "clock_seconds_remaining": 338.0, "action_type": "Substitution",
         "team_id": 1, "player_id": 201, "player_name": "Bench One", "description": "SUB in: Bench One"},
        {"period": 1, "clock_seconds_remaining": 338.0, "action_type": "Substitution",
         "team_id": 1, "player_id": 202, "player_name": "Bench Two", "description": "SUB in: Bench Two"},
        {"period": 2, "clock_seconds_remaining": 720.0, "action_type": "period",
         "description": "Start of 2nd Quarter", "score_home": "10", "score_away": "8"},
    ])

    stints = track_lineups(
        pbp,
        "0022500463",
        starters_by_team={1: {101, 102, 103, 104, 105}},
    )

    assert len(stints) == 2
    first = stints.row(0, named=True)
    second = stints.row(1, named=True)

    assert first["start_clock_seconds"] == 720.0
    assert first["end_clock_seconds"] == 338.0
    assert first["duration_seconds"] == 382.0
    assert second["start_clock_seconds"] == 338.0
    assert second["end_clock_seconds"] == 0.0
    assert second["duration_seconds"] == 338.0


def test_legacy_substitution_rows_use_roster_name_map_for_incoming_players():
    pbp = _make_pbp([
        {"period": 1, "clock_seconds_remaining": 720.0, "action_type": "period",
         "description": "Start of 1st Quarter"},
        {"period": 1, "clock_seconds_remaining": 700.0, "action_type": "Made Shot",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "Made Shot",
         "score_home": "2", "score_away": "0"},
        {"period": 1, "clock_seconds_remaining": 338.0, "action_type": "Substitution",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "SUB: Bench One FOR Starter"},
        {"period": 2, "clock_seconds_remaining": 720.0, "action_type": "period",
         "description": "Start of 2nd Quarter", "score_home": "10", "score_away": "8"},
    ])

    stints = track_lineups(
        pbp,
        "0022500463",
        starters_by_team={1: {101, 102, 103, 104, 105}},
        roster_name_map={1: {"bench one": 201}},
    )

    assert len(stints) == 2
    second = stints.row(1, named=True)
    assert second["player_ids_str"] == "102,103,104,105,201"


def test_period_start_carries_forward_previous_lineup_until_changed():
    pbp = _make_pbp([
        {"period": 1, "clock_seconds_remaining": 720.0, "action_type": "period",
         "description": "Start of 1st Quarter"},
        {"period": 1, "clock_seconds_remaining": 715.0, "action_type": "Jump Ball",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "Jump Ball"},
        {"period": 2, "clock_seconds_remaining": 720.0, "action_type": "period",
         "description": "Start of 2nd Quarter", "score_home": "20", "score_away": "18"},
        {"period": 2, "clock_seconds_remaining": 708.0, "action_type": "Rebound",
         "team_id": 1, "player_id": 101, "player_name": "A Starter", "description": "Rebound"},
    ])

    stints = track_lineups(
        pbp,
        "0022500463",
        starters_by_team={1: {101, 102, 103, 104, 105}},
    )

    period_two = stints.filter(pl.col("period") == 2)
    assert len(period_two) == 1
    row = period_two.row(0, named=True)
    assert row["start_clock_seconds"] == 720.0
    assert row["end_clock_seconds"] == 0.0
    assert row["duration_seconds"] == 720.0


def test_first_detected_lineup_backfills_when_no_prior_lineup_is_known():
    pbp = _make_pbp([
        {"period": 2, "clock_seconds_remaining": 720.0, "action_type": "period",
         "description": "Start of 2nd Quarter", "score_home": "20", "score_away": "18"},
        {"period": 2, "clock_seconds_remaining": 708.0, "action_type": "Rebound",
         "team_id": 1, "player_id": 201, "player_name": "Bench A", "description": "Rebound"},
        {"period": 2, "clock_seconds_remaining": 704.0, "action_type": "Missed Shot",
         "team_id": 1, "player_id": 202, "player_name": "Bench B", "description": "Missed Shot"},
        {"period": 2, "clock_seconds_remaining": 699.0, "action_type": "Rebound",
         "team_id": 1, "player_id": 203, "player_name": "Bench C", "description": "Rebound"},
        {"period": 2, "clock_seconds_remaining": 695.0, "action_type": "Turnover",
         "team_id": 1, "player_id": 204, "player_name": "Bench D", "description": "Turnover"},
        {"period": 2, "clock_seconds_remaining": 690.0, "action_type": "Made Shot",
         "team_id": 1, "player_id": 205, "player_name": "Bench E", "description": "Made Shot",
         "score_home": "22", "score_away": "18"},
    ])

    stints = track_lineups(pbp, "0022500463")

    period_two = stints.filter(pl.col("period") == 2)
    assert len(period_two) == 1
    row = period_two.row(0, named=True)
    assert row["start_clock_seconds"] == 720.0
    assert row["end_clock_seconds"] == 0.0
    assert row["duration_seconds"] == 720.0

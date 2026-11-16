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
        rows.append({**defaults, "action_number": index, "action_id": index, **event})
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
        home_team_id=1,
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
        home_team_id=1,
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
        home_team_id=1,
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

    stints = track_lineups(pbp, "0022500463", home_team_id=1)

    period_two = stints.filter(pl.col("period") == 2)
    assert len(period_two) == 1
    row = period_two.row(0, named=True)
    assert row["start_clock_seconds"] == 720.0
    assert row["end_clock_seconds"] == 0.0
    assert row["duration_seconds"] == 720.0


def test_points_are_credited_to_the_home_team_even_when_the_away_team_acts_first():
    home, away = 1, 2
    home_players = {101, 102, 103, 104, 105}
    away_players = {201, 202, 203, 204, 205}
    pbp = _make_pbp([
        {"action_type": "period", "description": "Period Start", "clock_seconds_remaining": 720.0},
        {"action_type": "2pt", "team_id": away, "player_id": 201, "clock_seconds_remaining": 700.0,
         "score_away": "2"},
        {"action_type": "3pt", "team_id": home, "player_id": 101, "clock_seconds_remaining": 680.0,
         "score_home": "3", "score_away": "2"},
    ])

    stints = track_lineups(
        pbp,
        "0022500463",
        home_team_id=home,
        starters_by_team={home: home_players, away: away_players},
    )

    by_team = {row["team_id"]: row for row in stints.iter_rows(named=True)}
    assert (by_team[home]["points_for"], by_team[home]["points_against"]) == (3, 2)
    assert (by_team[away]["points_for"], by_team[away]["points_against"]) == (2, 3)


def test_substitutions_before_the_period_start_row_do_not_create_phantom_stints():
    # The live feed lists between-period substitutions ahead of "Period Start".
    starters = {101, 102, 103, 104, 105}
    pbp = _make_pbp([
        {"period": 1, "action_type": "period", "description": "Period Start", "clock_seconds_remaining": 720.0},
        {"period": 1, "action_type": "2pt", "team_id": 1, "player_id": 101, "clock_seconds_remaining": 30.0},
        {"period": 2, "action_type": "substitution", "team_id": 1, "player_id": 105,
         "description": "SUB out: P. Five", "clock_seconds_remaining": 720.0},
        {"period": 2, "action_type": "substitution", "team_id": 1, "player_id": 106,
         "description": "SUB in: P. Six", "clock_seconds_remaining": 720.0},
        {"period": 2, "action_type": "period", "description": "Period Start", "clock_seconds_remaining": 720.0},
        {"period": 2, "action_type": "2pt", "team_id": 1, "player_id": 106, "clock_seconds_remaining": 600.0},
    ])

    stints = track_lineups(pbp, "0022500463", home_team_id=1, starters_by_team={1: starters})

    seconds = dict(stints.group_by("period").agg(pl.col("duration_seconds").sum()).iter_rows())
    assert seconds == {1: 720.0, 2: 720.0}


def _sub(period, clock, player_id, direction):
    return {"period": period, "clock_seconds_remaining": clock, "action_type": "substitution", "team_id": 1,
            "player_id": player_id, "description": f"SUB {direction}: P{player_id}"}


def _play(period, clock, player_id, action_type="2pt", sub_type=""):
    return {"period": period, "clock_seconds_remaining": clock, "action_type": action_type, "sub_type": sub_type,
            "team_id": 1, "player_id": player_id}


def _lineups(stints, period):
    rows = stints.filter(pl.col("period") == period).sort("start_clock_seconds", descending=True)
    return [(row["start_clock_seconds"], row["end_clock_seconds"], row["player_ids_str"]) for row in rows.iter_rows(named=True)]


def test_period_starts_with_the_players_who_play_when_the_feed_skips_break_substitutions():
    # stats_v3 has no rows for substitutions made between periods: 104 and 106 sat down at the
    # break and 107 and 108 came on. They show up by playing, or by being taken out.
    pbp = _make_pbp([
        _play(1, 700.0, 101),
        _sub(1, 300.0, 105, "out"),
        _sub(1, 300.0, 106, "in"),
        _play(2, 700.0, 107),
        _play(2, 680.0, 102, "3pt"),
        _play(2, 650.0, 101, "rebound"),
        _play(2, 620.0, 103, "turnover"),
        _sub(2, 500.0, 108, "out"),
        _sub(2, 500.0, 105, "in"),
    ])

    stints = track_lineups(pbp, "0022500463", home_team_id=1, starters_by_team={1: {101, 102, 103, 104, 105}})

    assert _lineups(stints, 2) == [
        (720.0, 500.0, "101,102,103,107,108"),
        (500.0, 0.0, "101,102,103,105,107"),
    ]


def test_a_bench_technical_does_not_put_the_player_on_the_floor():
    pbp = _make_pbp([
        _play(1, 600.0, 109, "foul", "technical"),
        _sub(1, 500.0, 101, "out"),
        _sub(1, 500.0, 106, "in"),
    ])

    stints = track_lineups(pbp, "0022500463", home_team_id=1, starters_by_team={1: {101, 102, 103, 104, 105}})

    assert _lineups(stints, 1) == [(720.0, 500.0, "101,102,103,104,105"), (500.0, 0.0, "102,103,104,105,106")]


def test_a_substitution_that_does_not_fit_the_lineup_stops_the_period_with_a_warning(caplog):
    # 110 is taken out but was never on the floor, so who is on after 400 isn't known.
    pbp = _make_pbp([
        _play(1, 600.0, 101),
        _sub(1, 400.0, 110, "out"),
        _sub(1, 400.0, 106, "in"),
    ])

    stints = track_lineups(pbp, "0022500463", home_team_id=1, starters_by_team={1: {101, 102, 103, 104, 105}})

    assert _lineups(stints, 1) == [(720.0, 400.0, "101,102,103,104,105")]
    assert "period 1 of game 0022500463" in caplog.text

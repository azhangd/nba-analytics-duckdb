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
    rows = [{**defaults, "action_number": idx, "action_id": idx, **event} for idx, event in enumerate(events)]
    if rows:
        return pl.DataFrame(rows)
    return pl.DataFrame(
        schema={
            "game_id": pl.String,
            "action_number": pl.Int64,
            "action_id": pl.Int64,
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


def _one_period_game(home_rotation_rows: list[list]) -> tuple:
    """A 12-minute, one-period game: home 101-105 (+106 off the bench), away 201-205."""
    import json

    game_id = "0022500463"
    away_rows = [[game_id, 2, "", "", pid, "", "", 0.0, 7200.0, 0, 0, 0] for pid in range(201, 206)]
    detail_rows = [{"game_id": game_id, "detail_json": json.dumps({"rotation": _rotation_payload(home_rotation_rows, away_rows)})}]
    pbp = _pbp(
        [
            {"action_type": "2pt", "team_id": 1, "player_id": 101, "player_name": "P101", "description": "",
             "clock_seconds_remaining": 600.0, "score_home": "2", "score_away": "0"},
            {"action_type": "2pt", "team_id": 2, "player_id": 201, "player_name": "P201", "description": "",
             "clock_seconds_remaining": 300.0, "score_home": "2", "score_away": "2"},
            {"action_type": "period", "team_id": None, "player_id": None, "player_name": "", "description": "End",
             "clock_seconds_remaining": 0.0, "score_home": "2", "score_away": "2"},
        ]
    )
    games = pl.DataFrame([{"game_id": game_id, "home_team_id": 1, "away_team_id": 2}])
    boxscores = pl.DataFrame(
        [
            {"game_id": game_id, "team_id": team, "player_id": pid, "player_name": f"P{pid}", "started": True, "minutes": 12.0}
            for team, pids in ((1, range(101, 106)), (2, range(201, 206)))
            for pid in pids
        ]
    )
    return pbp, games, boxscores, detail_rows


def test_broken_rotation_falls_back_to_substitutions():
    from nba_duckdb.transforms.silver.lineups import build_fct_lineup_rows

    # The home rotation only ever has four players on court, like the NBA's broken rotations.
    home = [["0022500463", 1, "", "", pid, "", "", 0.0, 7200.0, 0, 0, 0] for pid in range(101, 105)]
    rows = pl.DataFrame(build_fct_lineup_rows(*_one_period_game(home)))

    minutes = dict(rows.group_by("team_id").agg(pl.col("duration_seconds").sum() / 60).rows())
    assert minutes == {1: 12.0, 2: 12.0}
    assert set(rows.filter(pl.col("team_id") == 1)["player_ids_str"]) == {"101,102,103,104,105"}


def test_complete_rotation_is_still_used():
    from nba_duckdb.transforms.silver.lineups import build_fct_lineup_rows

    # 106 replaces 105 after two minutes; only the rotation knows, the play-by-play has no substitution.
    home = [["0022500463", 1, "", "", pid, "", "", 0.0, 7200.0, 0, 0, 0] for pid in range(101, 105)]
    home += [["0022500463", 1, "", "", 105, "", "", 0.0, 1200.0, 0, 0, 0], ["0022500463", 1, "", "", 106, "", "", 1200.0, 7200.0, 0, 0, 0]]
    rows = pl.DataFrame(build_fct_lineup_rows(*_one_period_game(home)))

    assert set(rows.filter(pl.col("team_id") == 1)["player_ids_str"]) == {"101,102,103,104,105", "101,102,103,104,106"}

import polars as pl

from nba_duckdb.analytics.possession_parser import parse_possessions

HOME_TEAM_ID = 1610612737
AWAY_TEAM_ID = 1610612738


def _make_pbp(events: list[dict]) -> pl.DataFrame:
    defaults = {
        "game_id": "0022500001",
        "action_number": 0,
        "period": 1,
        "clock": "PT12M00.00S",
        "clock_seconds_remaining": 720.0,
        "team_id": None,
        "player_id": None,
        "player_name": "",
        "action_type": "",
        "sub_type": "",
        "description": "",
        "score_home": "0",
        "score_away": "0",
        "shot_result": "",
        "is_field_goal": False,
        "pbp_source": "live_cdn",
        "loc_x": None,
        "loc_y": None,
    }
    return pl.DataFrame([{**defaults, "action_number": i, **event} for i, event in enumerate(events)])


def test_live_defensive_rebound_ends_possession():
    pbp = _make_pbp([
        {
            "action_type": "2pt",
            "sub_type": "jump shot",
            "shot_result": "Missed",
            "is_field_goal": True,
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 700.0,
        },
        {
            "action_type": "rebound",
            "sub_type": "defensive",
            "description": "Defensive rebound",
            "team_id": AWAY_TEAM_ID,
            "clock_seconds_remaining": 698.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    first = result.row(0, named=True)
    assert first["end_type"] == "defensive_rebound"
    assert first["offense_team_id"] == HOME_TEAM_ID


def test_live_offensive_rebound_continues_until_made_field_goal():
    pbp = _make_pbp([
        {
            "action_type": "3pt",
            "shot_result": "Missed",
            "is_field_goal": True,
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 700.0,
        },
        {
            "action_type": "rebound",
            "sub_type": "offensive",
            "description": "Offensive rebound",
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 698.0,
        },
        {
            "action_type": "2pt",
            "shot_result": "Made",
            "is_field_goal": True,
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 690.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    assert len(result) == 1
    first = result.row(0, named=True)
    assert first["end_type"] == "made_2"
    assert first["points_scored"] == 2
    assert first["event_count"] == 1


def test_live_made_final_free_throw_ends_possession():
    pbp = _make_pbp([
        {
            "action_type": "freethrow",
            "sub_type": "2 of 2",
            "shot_result": "Made",
            "description": "Free Throw 2 of 2",
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 650.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    first = result.row(0, named=True)
    assert first["end_type"] == "free_throw"
    assert first["points_scored"] == 1


def test_live_missed_final_free_throw_waits_for_rebound():
    pbp = _make_pbp([
        {
            "action_type": "freethrow",
            "sub_type": "2 of 2",
            "shot_result": "Missed",
            "description": "Free Throw 2 of 2",
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 650.0,
        },
        {
            "action_type": "rebound",
            "sub_type": "defensive",
            "description": "Defensive rebound",
            "team_id": AWAY_TEAM_ID,
            "clock_seconds_remaining": 648.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    first = result.row(0, named=True)
    assert first["end_type"] == "defensive_rebound"
    assert first["points_scored"] == 0


def test_live_turnover_ends_possession():
    pbp = _make_pbp([
        {
            "action_type": "turnover",
            "description": "Bad pass turnover",
            "team_id": HOME_TEAM_ID,
            "clock_seconds_remaining": 700.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    first = result.row(0, named=True)
    assert first["end_type"] == "turnover"
    assert first["points_scored"] == 0


def test_live_period_end_ends_possession():
    pbp = _make_pbp([
        {
            "action_type": "period",
            "sub_type": "end",
            "description": "End Period",
            "clock_seconds_remaining": 0.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    first = result.row(0, named=True)
    assert first["end_type"] == "end_period"


def test_score_margin_is_signed_from_offense_perspective():
    pbp = _make_pbp([
        {
            "action_type": "turnover",
            "team_id": AWAY_TEAM_ID,
            "score_home": "10",
            "score_away": "8",
            "clock_seconds_remaining": 700.0,
        },
    ])

    result = parse_possessions(pbp, "0022500001", home_team_id=HOME_TEAM_ID)

    first = result.row(0, named=True)
    assert first["score_margin"] == -2


def test_empty_pbp_returns_empty():
    result = parse_possessions(pl.DataFrame(), "0022500001")

    assert result.is_empty()

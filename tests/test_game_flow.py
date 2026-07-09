"""Contract tests for game-flow win-probability snapshots."""

import json

import polars as pl

from nba_duckdb.analytics.game_flow import compute_game_flow
from nba_duckdb.transforms.gold.game_flow_snapshots import build_game_flow_rows

COEFFICIENTS = {
    "intercept": 0.0,
    "features": {
        "margin": 0.0,
        "time_norm": 0.0,
        "time_sq": 0.0,
        "margin_time": 0.0,
        "possession_flag": 1.0,
        "elo_diff": 1.0,
    },
}


def test_compute_game_flow_uses_the_same_possession_and_elo_features_as_training():
    events = pl.DataFrame([
        {
            "game_id": "002A",
            "period": 1,
            "clock_seconds_remaining": 700.0,
            "score_home": 0,
            "score_away": 2,
            "action_type": "turnover",
            "team_id": 2,
        }
    ])

    result = compute_game_flow(
        events,
        "002A",
        season="2025-26",
        home_team_id=1,
        away_team_id=2,
        pregame_elo_diff=1.0,
        coefficients=COEFFICIENTS,
    )

    assert result["home_win_prob"].to_list() == [0.881]


def test_build_game_flow_rows_wires_pregame_features_and_trained_model_by_season():
    events = pl.DataFrame([
        {
            "game_id": "002A",
            "period": 1,
            "clock_seconds_remaining": 700.0,
            "score_home": 0,
            "score_away": 2,
            "action_type": "turnover",
            "team_id": 2,
        }
    ])
    games = pl.DataFrame([
        {
            "game_id": "002A",
            "season": "2025-26",
            "home_team_id": 1,
            "away_team_id": 2,
        }
    ])
    elo_history = pl.DataFrame([
        {
            "game_id": "002A",
            "team_id": 1,
            "elo_before": 1550.0,
            "opp_elo_before": 1450.0,
            "is_home": True,
        }
    ])
    model_artifacts = pl.DataFrame([
        {
            "model_name": "win_probability",
            "season": "2025-26",
            "metadata_json": json.dumps({"coefficients": COEFFICIENTS}),
        }
    ])

    rows, game_ids = build_game_flow_rows(events, games, elo_history, model_artifacts)

    assert game_ids == ["002A"]
    assert rows[0]["home_win_prob"] == 0.881

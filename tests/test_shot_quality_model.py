"""Tests for the shot quality model."""

import polars as pl

from nba_duckdb.analytics.shot_quality_model import compute_shot_quality


def test_dunk_has_high_expected_fg():
    """Dunks should have very high expected FG%."""
    shots = pl.DataFrame([{
        "shot_zone_basic": "Restricted Area",
        "action_type": "Dunk",
        "shot_made": True,
        "player_id": 1, "player_name": "Test", "team_id": 1,
        "loc_x": 0, "loc_y": 10, "shot_type": "2PT",
        "shot_distance_ft": 1, "period": 1, "game_id": "001", "game_date": "", "season": "",
    }])
    result = compute_shot_quality(shots)
    assert result["expected_fg_pct_heuristic"][0] > 0.9


def test_three_pointer_has_lower_expected_fg():
    """Three pointers should have lower expected FG%."""
    shots = pl.DataFrame([{
        "shot_zone_basic": "Above the Break 3",
        "action_type": "Jump Shot",
        "shot_made": False,
        "player_id": 1, "player_name": "Test", "team_id": 1,
        "loc_x": 0, "loc_y": 250, "shot_type": "3PT",
        "shot_distance_ft": 24, "period": 1, "game_id": "001", "game_date": "", "season": "",
    }])
    result = compute_shot_quality(shots)
    assert result["expected_fg_pct_heuristic"][0] < 0.40


def test_empty_has_quality_columns():
    """Empty input should still return the quality columns."""
    result = compute_shot_quality(pl.DataFrame())
    assert "expected_fg_pct_heuristic" in result.columns
    assert "quality_delta_heuristic" in result.columns

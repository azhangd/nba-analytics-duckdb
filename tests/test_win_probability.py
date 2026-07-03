"""Tests for win probability model."""


import numpy as np
import polars as pl
import pytest

pytest.importorskip("sklearn")

from nba_duckdb.modeling.win_probability import (
    build_training_data,
    evaluate_model,
    predict_from_coefficients,
    probit_baseline,
    train_model,
)


def _make_pbp(n_games=20, events_per_game=50):
    """Build synthetic PBP data with scores evolving over time."""
    rows = []
    for g in range(n_games):
        gid = f"002{g:05d}"
        home_final = 100 + int(np.random.randn() * 15)
        away_final = 100 + int(np.random.randn() * 15)
        for e in range(events_per_game):
            frac = e / events_per_game
            rows.append({
                "game_id": gid,
                "period": min(int(frac * 4) + 1, 4),
                "clock_seconds_remaining": 720 * (1 - (frac * 4) % 1),
                "score_home": int(home_final * frac),
                "score_away": int(away_final * frac),
                "action_type": "Jump Shot Made" if e % 3 == 0 else "Rebound",
            })
    return pl.DataFrame(rows)


def _make_games(n_games=20):
    """Build synthetic games with outcomes."""
    rows = []
    for g in range(n_games):
        hs = 100 + int(np.random.randn() * 15)
        aws = 100 + int(np.random.randn() * 15)
        rows.append({
            "game_id": f"002{g:05d}",
            "game_date": f"2025-{(g // 28) + 10:02d}-{(g % 28) + 1:02d}",
            "home_team_id": 1610612737,
            "away_team_id": 1610612738,
            "home_score": hs,
            "away_score": aws,
            "game_status": 3,
        })
    return pl.DataFrame(rows)


def test_probit_baseline_game_over():
    """Home team ahead at buzzer should have ~100% win probability."""
    assert probit_baseline(10, 0) == 1.0
    assert probit_baseline(-5, 0) == 0.0
    assert probit_baseline(0, 0) == 0.5


def test_probit_baseline_large_lead():
    """Large lead with little time should be near 1.0."""
    prob = probit_baseline(20, 60)
    assert prob > 0.95


def test_probit_baseline_tied_game():
    """Tied game at halftime should be near 0.5 (slight home advantage)."""
    prob = probit_baseline(0, 1440)
    assert 0.45 < prob < 0.65


def test_probit_baseline_symmetry():
    """Opposite margins should sum to ~1.0."""
    p_plus = probit_baseline(5, 600)
    p_minus = probit_baseline(-5, 600)
    assert abs(p_plus + p_minus - 1.0) < 0.1


def test_build_training_data_produces_rows():
    """Should produce training rows from PBP + games."""
    np.random.seed(42)
    pbp = _make_pbp(n_games=10)
    games = _make_games(n_games=10)
    data = build_training_data(pbp, games, None)

    assert not data.is_empty()
    assert "margin" in data.columns
    assert "seconds_remaining" in data.columns
    assert "home_wins" in data.columns
    assert "elo_diff" in data.columns

    # Labels should be 0 or 1
    labels = data["home_wins"].unique().to_list()
    assert set(labels).issubset({0, 1})


def test_build_training_data_empty_input():
    """Should handle empty PBP gracefully."""
    empty_pbp = pl.DataFrame(schema={
        "game_id": pl.Utf8, "period": pl.Int64,
        "clock_seconds_remaining": pl.Float64,
        "score_home": pl.Int64, "score_away": pl.Int64,
        "action_type": pl.Utf8,
    })
    games = _make_games(n_games=5)
    data = build_training_data(empty_pbp, games, None)
    assert data.is_empty()


def test_train_and_evaluate():
    """Full train→evaluate pipeline should produce valid metrics."""
    np.random.seed(42)
    pbp = _make_pbp(n_games=30)
    games = _make_games(n_games=30)
    data = build_training_data(pbp, games, None)

    assert len(data) > 50, f"Need enough training data, got {len(data)}"

    split = int(len(data) * 0.7)
    train_df = data[:split]
    test_df = data[split:]

    model, coefficients = train_model(train_df)

    assert "intercept" in coefficients
    assert "features" in coefficients
    assert "margin" in coefficients["features"]

    metrics = evaluate_model(model, test_df)

    assert 0 < metrics["brier_score"] < 1
    assert 0 < metrics["log_loss"] < 10
    assert metrics["n_test_samples"] == len(test_df)


def test_predict_from_coefficients_bounds():
    """Predictions should always be in [0, 1]."""
    coefficients = {
        "intercept": 0.0,
        "features": {
            "margin": 0.5,
            "time_norm": 0.1,
            "time_sq": 0.05,
            "margin_time": 0.2,
            "possession_flag": 0.1,
            "elo_diff": 0.3,
        },
    }

    # Test various scenarios
    scenarios = [
        (30, 60, 0, 0),       # huge lead, 1 min left
        (-30, 60, 0, 0),      # huge deficit
        (0, 2880, 0, 0),      # tipoff, tied
        (0, 0, 0, 0),         # game over, tied
        (5, 300, 1, 2.0),     # up 5, 5 min, home ball, big Elo edge
        (-10, 1440, -1, -3),  # down 10, halftime, away ball, weak team
    ]

    for margin, secs, poss, elo in scenarios:
        prob = predict_from_coefficients(coefficients, margin, secs, poss, elo)
        assert 0 <= prob <= 1, f"Out of bounds: {prob} for ({margin}, {secs}, {poss}, {elo})"


def test_predict_from_coefficients_game_over():
    """Game over predictions should be deterministic."""
    coefficients = {
        "intercept": 0.0,
        "features": {"margin": 1, "time_norm": 0, "time_sq": 0,
                      "margin_time": 0, "possession_flag": 0, "elo_diff": 0},
    }
    assert predict_from_coefficients(coefficients, 5, 0) == 1.0
    assert predict_from_coefficients(coefficients, -5, 0) == 0.0
    assert predict_from_coefficients(coefficients, 0, 0) == 0.5

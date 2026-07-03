"""Tests for RAPM (Regularized Adjusted Plus-Minus)."""

import numpy as np
import polars as pl
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("scipy")

from nba_duckdb.modeling.rapm import (
    blend_with_prior,
    bootstrap_ci,
    build_design_matrix,
    fit_rapm,
)


def _make_lineups(n_games=10, stints_per_game=8):
    """Build synthetic lineup stint data.

    Each game has two teams with 5 players each.
    Stints alternate teams within each (game_id, stint_number, period).
    """
    rows = []
    for g in range(n_games):
        gid = f"002{g:05d}"
        # Two teams: players 1-5 and 6-10
        team_a = 100
        team_b = 200
        players_a = [1, 2, 3, 4, 5]
        players_b = [6, 7, 8, 9, 10]

        for s in range(stints_per_game):
            period = (s // 2) + 1
            duration = 60 + np.random.randint(-20, 20)
            # Team A scores more when player 1 is on court (the "star")
            pts_a = int(np.random.poisson(3) + (1 if 1 in players_a else 0))
            pts_b = int(np.random.poisson(2))

            rows.append({
                "game_id": gid,
                "stint_number": s,
                "period": period,
                "team_id": team_a,
                "player_ids_str": ",".join(str(p) for p in players_a),
                "player_count": 5,
                "start_clock_seconds": 720 - s * 90,
                "end_clock_seconds": 720 - (s + 1) * 90,
                "duration_seconds": float(duration),
                "points_for": pts_a,
                "points_against": pts_b,
            })
            rows.append({
                "game_id": gid,
                "stint_number": s,
                "period": period,
                "team_id": team_b,
                "player_ids_str": ",".join(str(p) for p in players_b),
                "player_count": 5,
                "start_clock_seconds": 720 - s * 90,
                "end_clock_seconds": 720 - (s + 1) * 90,
                "duration_seconds": float(duration),
                "points_for": pts_b,
                "points_against": pts_a,
            })

    return pl.DataFrame(rows)


def _make_games(n_games=10):
    """Synthetic games with home/away teams."""
    return pl.DataFrame([
        {
            "game_id": f"002{g:05d}",
            "home_team_id": 100,
            "away_team_id": 200,
            "home_score": 100,
            "away_score": 95,
        }
        for g in range(n_games)
    ])


def test_build_design_matrix_shape():
    """Design matrix should have correct dimensions."""
    np.random.seed(42)
    lineups = _make_lineups(n_games=5, stints_per_game=6)
    games = _make_games(n_games=5)
    pace = {100: 100.0, 200: 100.0}

    X, y, weights, player_ids, game_ids = build_design_matrix(lineups, games, pace)

    assert X.shape[1] == 10  # 10 unique players (5 per team)
    assert X.shape[0] > 0    # should have stint rows
    assert len(y) == X.shape[0]
    assert len(weights) == X.shape[0]
    assert len(player_ids) == 10
    assert len(game_ids) == X.shape[0]


def test_build_design_matrix_values():
    """Each row should have +1 for offense, -1 for defense players."""
    np.random.seed(42)
    lineups = _make_lineups(n_games=2, stints_per_game=4)
    games = _make_games(n_games=2)
    pace = {100: 100.0, 200: 100.0}

    X, y, weights, player_ids, game_ids = build_design_matrix(lineups, games, pace)

    # Convert first row to dense and check
    row = X[0].toarray().flatten()
    pos_count = (row == 1.0).sum()
    neg_count = (row == -1.0).sum()
    zero_count = (row == 0.0).sum()

    assert pos_count == 5, f"Expected 5 offense players, got {pos_count}"
    assert neg_count == 5, f"Expected 5 defense players, got {neg_count}"
    assert zero_count == 0, f"Expected 0 zeros (all 10 players on court), got {zero_count}"


def test_fit_rapm_returns_coefficients():
    """Ridge fit should return one coefficient per player."""
    np.random.seed(42)
    lineups = _make_lineups(n_games=15, stints_per_game=10)
    games = _make_games(n_games=15)
    pace = {100: 100.0, 200: 100.0}

    X, y, weights, player_ids, game_ids = build_design_matrix(lineups, games, pace)
    coefficients, best_lambda, cv_mse = fit_rapm(X, y, weights, game_ids, n_folds=3)

    assert len(coefficients) == len(player_ids)
    assert best_lambda > 0
    assert cv_mse >= 0


def test_bootstrap_ci_shape():
    """Bootstrap should return lower/upper bounds for each player."""
    np.random.seed(42)
    lineups = _make_lineups(n_games=10, stints_per_game=8)
    games = _make_games(n_games=10)
    pace = {100: 100.0, 200: 100.0}

    X, y, weights, player_ids, game_ids = build_design_matrix(lineups, games, pace)
    lower, upper = bootstrap_ci(X, y, weights, game_ids, lam=100.0, n_boot=10)

    assert lower.shape == (len(player_ids),)
    assert upper.shape == (len(player_ids),)
    # Upper should be >= lower for all players
    assert np.all(upper >= lower)


def test_blend_with_prior_full_trust():
    """Players with enough minutes should get pure RAPM (no prior blend)."""
    rapm = np.array([5.0, -3.0, 1.0])
    minutes = np.array([1000.0, 800.0, 600.0])
    prior = np.array([0.0, 0.0, 0.0])

    blended = blend_with_prior(rapm, minutes, prior, min_trust_minutes=500.0)

    np.testing.assert_array_almost_equal(blended, rapm)


def test_blend_with_prior_zero_minutes():
    """Players with zero minutes should get pure prior."""
    rapm = np.array([5.0, -3.0])
    minutes = np.array([0.0, 0.0])
    prior = np.array([2.0, -1.0])

    blended = blend_with_prior(rapm, minutes, prior, min_trust_minutes=500.0)

    np.testing.assert_array_almost_equal(blended, prior)


def test_blend_with_prior_partial():
    """Players with partial minutes should get a blend."""
    rapm = np.array([10.0])
    minutes = np.array([250.0])  # half of 500
    prior = np.array([0.0])

    blended = blend_with_prior(rapm, minutes, prior, min_trust_minutes=500.0)

    assert blended[0] == 5.0  # 0.5 * 10 + 0.5 * 0 = 5


def test_empty_lineups_raises():
    """Empty lineups should raise ValueError."""
    lineups = pl.DataFrame(schema={
        "game_id": pl.Utf8, "stint_number": pl.Int64, "period": pl.Int64,
        "team_id": pl.Int64, "player_ids_str": pl.Utf8,
        "duration_seconds": pl.Float64, "points_for": pl.Int64, "points_against": pl.Int64,
    })
    games = _make_games(n_games=1)

    try:
        build_design_matrix(lineups, games, {})
    except ValueError:
        pass
    else:
        raise AssertionError("Should have raised ValueError")

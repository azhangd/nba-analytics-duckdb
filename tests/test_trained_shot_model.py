"""Contract tests for trained shot-model evaluation and artifacts."""

import numpy as np
import polars as pl
import pytest

pytest.importorskip("joblib")
pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from nba_duckdb.modeling.trained_shot_model import build_features, chronological_game_split


def test_chronological_game_split_keeps_every_game_in_exactly_one_partition():
    game_ids = np.array(["g3", "g1", "g4", "g2", "g3", "g1", "g4", "g2"])
    game_dates = np.array([
        "2026-01-03",
        "2026-01-01",
        "2026-01-04",
        "2026-01-02",
        "2026-01-03",
        "2026-01-01",
        "2026-01-04",
        "2026-01-02",
    ])

    train_idx, test_idx = chronological_game_split(game_ids, game_dates, train_fraction=0.5)

    train_games = set(game_ids[train_idx])
    test_games = set(game_ids[test_idx])
    assert train_games == {"g1", "g2"}
    assert test_games == {"g3", "g4"}
    assert train_games.isdisjoint(test_games)
    assert sorted(np.concatenate([train_idx, test_idx]).tolist()) == list(range(len(game_ids)))


def test_shot_features_exclude_same_season_aggregate_priors():
    shots = pl.DataFrame([
        {
            "shot_made": True,
            "loc_x": 0,
            "loc_y": 10,
            "shot_distance_ft": 1,
            "period": 1,
            "minutes_remaining": 11,
            "seconds_remaining": 30,
            "shot_type": "2PT Field Goal",
            "action_type": "Dunk Shot",
            "shot_context": "other",
            "shot_zone_basic": "Restricted Area",
            "player_id": 1,
            "season": "2025-26",
        }
    ])

    _X, _y, feature_names = build_features(shots)

    assert not any(name.startswith("prior_") for name in feature_names)

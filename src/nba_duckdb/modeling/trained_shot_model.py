"""Trained shot difficulty model.

XGBoost binary classifier trained on shot-level data with spatial,
temporal, action, and player-prior features. Predicts P(make) per shot.

Replaces hardcoded zone-based expected FG% with data-driven estimates.
"""

import json
import logging
import math
import os
from datetime import datetime

import joblib
import numpy as np
import polars as pl
import xgboost as xgb
from sklearn.calibration import calibration_curve
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from nba_duckdb.modeling.artifact_paths import artifact_dir

logger = logging.getLogger("nba_duckdb.modeling.trained_shot_model")
SHOT_MODEL_N_JOBS = int(os.environ.get("SHOT_MODEL_N_JOBS", "1"))

# Top action types (rest → "Other")
TOP_ACTION_TYPES = [
    "Jump Shot", "Layup Shot", "Driving Layup Shot", "Pullup Jump Shot",
    "Floating Jump Shot", "Step Back Jump Shot", "Turnaround Jump Shot",
    "Fadeaway Jump Shot", "Running Layup Shot", "Hook Shot",
    "Driving Finger Roll Layup Shot", "Cutting Layup Shot",
    "Alley Oop Layup Shot", "Dunk Shot", "Driving Dunk Shot",
    "Tip Shot", "Running Jump Shot", "Turnaround Fadeaway Shot",
    "Putback Layup Shot", "Pullup Bank Shot", "Driving Hook Shot",
    "Running Finger Roll Layup Shot", "Cutting Dunk Shot",
    "Alley Oop Dunk Shot", "Running Dunk Shot", "Putback Dunk Shot",
    "Turnaround Hook Shot", "Running Pull-Up Jump Shot",
    "Driving Floating Jump Shot", "Driving Bank Hook Shot",
]

SHOT_CONTEXTS = ["pull_up", "catch_and_shoot", "off_dribble", "other"]

ARTIFACT_DIR = artifact_dir("shot_model")


def artifact_dir_for_season(
    season: str | None = None,
    *,
    artifact_dir: str | None = None,
) -> str:
    """Resolve on-disk artifact directory, namespaced by season when provided."""
    if artifact_dir:
        return artifact_dir
    season_value = str(season or "").strip()
    if season_value:
        return os.path.join(ARTIFACT_DIR, season_value)
    return ARTIFACT_DIR


def build_features(
    shots_df: pl.DataFrame,
    tracking_df: pl.DataFrame | None = None,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build feature matrix from shot-level data.

    Returns (X, y, feature_names).
    """
    feature_rows = []
    targets = []
    feature_names = None

    # Build tracking prior lookup: {(player_id, season): {metric: value}}
    tracking_lookup: dict[tuple, dict] = {}
    if tracking_df is not None and not tracking_df.is_empty():
        for row in tracking_df.iter_rows(named=True):
            pid = row.get("player_id")
            season = row.get("season")
            cat = row.get("category", "")
            stats = row.get("stats")
            if not pid or not stats:
                continue
            key = (pid, season)
            if key not in tracking_lookup:
                tracking_lookup[key] = {}
            if isinstance(stats, str):
                try:
                    stats = json.loads(stats)
                except Exception:
                    continue
            if isinstance(stats, dict):
                for k, v in stats.items():
                    tracking_lookup[key][f"{cat}_{k}"] = v

    # Action type encoding
    action_to_idx = {a: i for i, a in enumerate(TOP_ACTION_TYPES)}
    n_action_types = len(TOP_ACTION_TYPES) + 1  # +1 for "Other"

    for row in shots_df.iter_rows(named=True):
        shot_made = row.get("shot_made")
        if shot_made is None:
            continue

        loc_x = float(row.get("loc_x", 0) or 0)
        loc_y = float(row.get("loc_y", 0) or 0)
        dist = float(row.get("shot_distance_ft", 0) or 0)

        # Spatial features
        loc_r = math.sqrt(loc_x ** 2 + loc_y ** 2)
        loc_angle = math.atan2(loc_x, max(loc_y, 1))  # avoid div by 0

        # Temporal features
        period = int(row.get("period", 1) or 1)
        mins_rem = float(row.get("minutes_remaining", 0) or 0)
        secs_rem = float(row.get("seconds_remaining", 0) or 0)
        game_clock = mins_rem * 60 + secs_rem
        is_end_of_quarter = 1 if game_clock < 5 else 0
        is_clutch = 1 if (period >= 4 and game_clock < 300) else 0

        # Shot type
        shot_type = 1 if row.get("shot_type") == "3PT Field Goal" else 0

        # Action type (one-hot)
        action = row.get("action_type", "")
        action_idx = action_to_idx.get(action, len(TOP_ACTION_TYPES))

        # Shot context (one-hot)
        context = str(row.get("shot_context", "other") or "other").lower()
        context_vec = [1 if c == context else 0 for c in SHOT_CONTEXTS]

        # Zone (simplified to category)
        zone = str(row.get("shot_zone_basic", "") or "")
        zone_features = [
            1 if zone == "Restricted Area" else 0,
            1 if zone == "In The Paint (Non-RA)" else 0,
            1 if zone == "Mid-Range" else 0,
            1 if "3" in zone or "Above" in zone else 0,
        ]

        # Player tracking priors
        pid = row.get("player_id")
        season = row.get("season")
        priors = tracking_lookup.get((pid, season), {})
        catch_shoot_fg = float(priors.get("CatchShoot_fg_pct", 0) or 0)
        pullup_fg = float(priors.get("PullUpShot_fg_pct", 0) or 0)
        drive_freq = float(priors.get("Drives_drives", 0) or 0)

        features = [
            loc_x / 250.0,  # normalize to [-1, 1]
            loc_y / 470.0,
            dist / 35.0,   # normalize
            loc_r / 500.0,
            loc_angle / math.pi,
            float(period) / 5.0,
            game_clock / 720.0,
            float(is_end_of_quarter),
            float(is_clutch),
            float(shot_type),
            float(action_idx) / float(n_action_types),
            *context_vec,
            *zone_features,
            catch_shoot_fg,
            pullup_fg,
            drive_freq / 20.0,  # normalize
        ]

        feature_rows.append(features)
        targets.append(1 if shot_made else 0)

    if not feature_rows:
        return np.array([]), np.array([]), []

    feature_names = [
        "loc_x_norm", "loc_y_norm", "dist_norm", "loc_r_norm", "loc_angle_norm",
        "period_norm", "game_clock_norm", "is_end_of_quarter", "is_clutch",
        "shot_type_3pt", "action_type_enc",
        "ctx_pull_up", "ctx_catch_and_shoot", "ctx_off_dribble", "ctx_other",
        "zone_restricted", "zone_paint", "zone_midrange", "zone_three",
        "prior_catch_shoot_fg", "prior_pullup_fg", "prior_drive_freq",
    ]

    return np.array(feature_rows, dtype=np.float32), np.array(targets, dtype=np.int32), feature_names


def train_shot_model(
    X: np.ndarray,
    y: np.ndarray,
    game_ids: np.ndarray,
    n_folds: int = 3,
) -> tuple[xgb.XGBClassifier, dict]:
    """Train XGBoost shot model with grouped cross-validation.

    Returns (model, metadata).
    """
    # Hyperparameter grid (simplified for speed)
    param_grid = [
        {"max_depth": 6, "n_estimators": 300, "learning_rate": 0.05, "min_child_weight": 10},
        {"max_depth": 4, "n_estimators": 400, "learning_rate": 0.1, "min_child_weight": 5},
        {"max_depth": 8, "n_estimators": 200, "learning_rate": 0.05, "min_child_weight": 10},
    ]

    gkf = GroupKFold(n_splits=min(n_folds, len(np.unique(game_ids))))

    best_model = None
    best_auc = 0.0
    best_params = None

    for params in param_grid:
        fold_aucs = []
        for train_idx, test_idx in gkf.split(X, y, groups=game_ids):
            model = xgb.XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                tree_method="hist",
                random_state=42,
                verbosity=0,
                n_jobs=SHOT_MODEL_N_JOBS,
                **params,
            )
            model.fit(X[train_idx], y[train_idx])
            preds = model.predict_proba(X[test_idx])[:, 1]
            auc = roc_auc_score(y[test_idx], preds)
            fold_aucs.append(auc)

        avg_auc = np.mean(fold_aucs)
        logger.info("Params %s → AUC=%.4f", params, avg_auc)

        if avg_auc > best_auc:
            best_auc = avg_auc
            best_params = params

    # Refit on all data with best params
    best_model = xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=42,
        verbosity=0,
        n_jobs=SHOT_MODEL_N_JOBS,
        **best_params,
    )
    best_model.fit(X, y)

    metadata = {
        "best_params": best_params,
        "cv_auc": round(best_auc, 4),
        "n_samples": len(y),
        "positive_rate": round(float(y.mean()), 4),
    }

    return best_model, metadata


def evaluate_shot_model(
    model: xgb.XGBClassifier,
    X_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: list[str],
    baseline_preds: np.ndarray | None = None,
) -> dict:
    """Evaluate model on test set."""
    y_pred = model.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, y_pred)
    ll = log_loss(y_test, y_pred)

    # Calibration
    prob_true, prob_pred = calibration_curve(y_test, y_pred, n_bins=10, strategy="uniform")

    # Feature importance
    importances = model.feature_importances_
    fi = sorted(
        zip(feature_names, importances.tolist()),
        key=lambda x: x[1],
        reverse=True,
    )[:15]

    metrics = {
        "auc_roc": round(float(auc), 4),
        "log_loss": round(float(ll), 6),
        "calibration": {
            "predicted": [round(float(p), 4) for p in prob_pred],
            "actual": [round(float(p), 4) for p in prob_true],
        },
        "feature_importance": fi,
    }

    # Baseline comparison
    if baseline_preds is not None:
        baseline_auc = roc_auc_score(y_test, baseline_preds)
        baseline_ll = log_loss(y_test, np.clip(baseline_preds, 1e-7, 1 - 1e-7))
        metrics["baseline_auc"] = round(float(baseline_auc), 4)
        metrics["baseline_log_loss"] = round(float(baseline_ll), 6)
        metrics["auc_improvement"] = round(float(auc - baseline_auc), 4)

    logger.info("Shot model: AUC=%.4f, LogLoss=%.6f", auc, ll)
    if "baseline_auc" in metrics:
        logger.info("  Baseline AUC=%.4f, improvement=+%.4f",
                     metrics["baseline_auc"], metrics["auc_improvement"])

    return metrics


def save_model(
    model: xgb.XGBClassifier,
    metadata: dict,
    *,
    season: str | None = None,
    artifact_dir: str | None = None,
) -> str:
    """Save model artifact. Returns model version string."""
    target_artifact_dir = artifact_dir_for_season(season, artifact_dir=artifact_dir)
    os.makedirs(target_artifact_dir, exist_ok=True)
    version = datetime.now().strftime("%Y-%m-%d")
    model_path = os.path.join(target_artifact_dir, f"model_{version}.joblib")
    meta_path = os.path.join(target_artifact_dir, f"metadata_{version}.json")
    latest_path = os.path.join(target_artifact_dir, "latest.txt")

    joblib.dump(model, model_path)
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    with open(latest_path, "w") as f:
        f.write(version)

    logger.info("Saved shot model: %s", model_path)
    return version


def load_latest_model(
    *,
    season: str | None = None,
    artifact_dir: str | None = None,
) -> tuple[xgb.XGBClassifier | None, str | None]:
    """Load the latest model artifact."""
    target_artifact_dir = artifact_dir_for_season(season, artifact_dir=artifact_dir)
    latest_path = os.path.join(target_artifact_dir, "latest.txt")
    if not os.path.exists(latest_path):
        return None, None

    with open(latest_path) as f:
        version = f.read().strip()

    model_path = os.path.join(target_artifact_dir, f"model_{version}.joblib")
    if not os.path.exists(model_path):
        return None, None

    return joblib.load(model_path), version

"""Gold: Compute trained shot quality using XGBoost model."""

import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import polars as pl

from nba_duckdb.db import delete_where, insert_rows, read_table, upsert_rows
from nba_duckdb.modeling.trained_shot_model import (
    artifact_dir_for_season,
    build_features,
    evaluate_shot_model,
    load_latest_model,
    save_model,
    train_shot_model,
)
from nba_duckdb.season_utils import resolved_target_seasons

logger = logging.getLogger("nba_duckdb.tasks.gold.player_zone_season_shot_quality_trained")

RETRAIN_DAYS = int(os.environ.get("SHOT_MODEL_RETRAIN_DAYS", "7"))
MAX_TRAIN_SAMPLES = int(os.environ.get("SHOT_MODEL_MAX_TRAIN_SAMPLES", "75000"))
TRAIN_SAMPLE_SEED = int(os.environ.get("SHOT_MODEL_RANDOM_SEED", "42"))


def _model_is_stale(season: str) -> bool:
    """Check if model needs retraining."""
    latest_path = os.path.join(artifact_dir_for_season(season), "latest.txt")
    if not os.path.exists(latest_path):
        return True

    with open(latest_path) as f:
        version = f.read().strip()
    try:
        model_date = datetime.strptime(version, "%Y-%m-%d")
        age_days = (datetime.now() - model_date).days
        return age_days >= RETRAIN_DAYS
    except ValueError:
        return True


def _cap_training_sample(
    X,
    y,
    game_ids,
    *,
    max_samples: int = MAX_TRAIN_SAMPLES,
    seed: int = TRAIN_SAMPLE_SEED,
):
    """Cap training size by sampling whole games when possible."""
    if max_samples <= 0 or len(X) <= max_samples:
        return X, y, game_ids

    game_ids = np.asarray(game_ids)
    rng = np.random.default_rng(seed)
    selected_indices: list[int] = []
    total = 0

    for game_id in rng.permutation(np.unique(game_ids)):
        game_idx = np.flatnonzero(game_ids == game_id)
        if total and total + len(game_idx) > max_samples:
            continue
        selected_indices.extend(game_idx.tolist())
        total += len(game_idx)
        if total >= max_samples:
            break

    if not selected_indices:
        selected_indices = rng.choice(len(X), size=max_samples, replace=False).tolist()

    sample_idx = np.array(sorted(selected_indices[:max_samples]), dtype=int)
    return X[sample_idx], y[sample_idx], game_ids[sample_idx]


def run(**kwargs):
    target_seasons = resolved_target_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
        game_ids=[str(game_id) for game_id in kwargs.get("game_ids", []) or []],
        regular_season_only=True,
    )

    # 1. Read data
    shots = read_table("silver", "fct_shots")
    tracking = read_table("silver", "fct_tracking")

    if shots.is_empty():
        logger.warning("No shot data — cannot compute trained shot quality")
        return {"status": "skipped", "seasons": target_seasons}

    results: list[dict[str, object]] = []
    versions_by_season: dict[str, str | None] = {}

    for season_value in target_seasons:
        scoped_shots = (
            shots.filter(pl.col("season") == season_value)
            if "season" in shots.columns
            else shots
        )
        if scoped_shots.is_empty():
            continue

        # Keep the historical contract aligned with regular-season-only enrichments.
        scoped_shots = scoped_shots.filter(pl.col("game_id").cast(pl.Utf8).str.starts_with("002"))
        if scoped_shots.is_empty():
            continue

        scoped_tracking = (
            tracking.filter(pl.col("season") == season_value)
            if not tracking.is_empty() and "season" in tracking.columns
            else tracking
        )

        # 2. Build features
        X, y, feature_names = build_features(scoped_shots, scoped_tracking)
        if len(X) == 0:
            logger.warning("No shot-quality features built for %s", season_value)
            continue

        logger.info(
            "Shot quality features for %s: %d samples, %d features",
            season_value,
            X.shape[0],
            X.shape[1],
        )

        # 3. Get game_ids for CV
        game_ids = scoped_shots.filter(pl.col("shot_made").is_not_null())["game_id"].to_numpy()
        if len(game_ids) > len(X):
            game_ids = game_ids[:len(X)]
        if len(np.unique(game_ids)) < 2:
            logger.info(
                "Skipping trained shot model for %s: at least two games are required for cross-validation",
                season_value,
            )
            continue

        # 4. Check if model needs training
        model, version = load_latest_model(season=season_value)
        if model is None or _model_is_stale(season_value):
            logger.info("Training new shot model for %s", season_value)

            train_X, train_y, train_game_ids = _cap_training_sample(X, y, game_ids)
            if len(train_X) < len(X):
                logger.info(
                    "Capped shot model training set for %s to %d/%d shots across %d games",
                    season_value,
                    len(train_X),
                    len(X),
                    len(np.unique(train_game_ids)),
                )

            # Split: first 70% of sampled shots for train, rest for test
            n_train = min(max(int(len(train_X) * 0.7), 1), max(len(train_X) - 1, 1))
            X_train, X_test = train_X[:n_train], train_X[n_train:]
            y_train, y_test = train_y[:n_train], train_y[n_train:]
            gids_train = train_game_ids[:n_train]

            model, meta = train_shot_model(X_train, y_train, gids_train)

            eval_metrics = (
                evaluate_shot_model(model, X_test, y_test, feature_names)
                if len(X_test) > 0
                else {
                    "auc_roc": None,
                    "log_loss": None,
                    "calibration": {"predicted": [], "actual": []},
                    "feature_importance": [],
                }
            )
            meta["evaluation"] = eval_metrics
            meta["train_sample_size"] = int(len(train_X))
            meta["train_sample_games"] = int(len(np.unique(train_game_ids)))

            version = save_model(model, meta, season=season_value)

            artifact = {
                "model_name": "player_zone_season_shot_quality",
                "season": season_value,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "metadata_json": json.dumps(meta),
            }
            upsert_rows("gold", "model_artifacts", [artifact], conflict_cols=["model_name", "season"])

            logger.info("Shot model trained for %s: AUC=%.4f", season_value, eval_metrics["auc_roc"])
        else:
            logger.info("Using existing shot model version %s for %s", version, season_value)

        versions_by_season[season_value] = version

        # 5. Run inference on all scoped shots
        y_pred = model.predict_proba(X)[:, 1]

        # 6. Build per-shot results and aggregate to player × zone
        shot_rows = scoped_shots.filter(pl.col("shot_made").is_not_null())
        if len(shot_rows) > len(y_pred):
            shot_rows = shot_rows.head(len(y_pred))

        player_ids = shot_rows["player_id"].to_list()
        player_names = shot_rows["player_name"].to_list()
        team_ids = shot_rows["team_id"].to_list()
        zones = shot_rows["shot_zone_basic"].to_list()
        made = y[:len(y_pred)]

        agg: dict[tuple, dict] = {}
        for i in range(len(y_pred)):
            pid = player_ids[i] if i < len(player_ids) else None
            pname = player_names[i] if i < len(player_names) else None
            tid = team_ids[i] if i < len(team_ids) else None
            zone = zones[i] if i < len(zones) else None

            key = (pid, zone)
            if key not in agg:
                agg[key] = {
                    "player_id": pid,
                    "player_name": pname,
                    "team_id": tid,
                    "shot_zone_basic": zone,
                    "attempts": 0,
                    "makes": 0,
                    "expected_sum": 0.0,
                }
            agg[key]["attempts"] += 1
            agg[key]["makes"] += int(made[i])
            agg[key]["expected_sum"] += float(y_pred[i])

        for entry in agg.values():
            attempts = entry["attempts"]
            if attempts == 0:
                continue
            actual_fg = entry["makes"] / attempts
            expected_fg = entry["expected_sum"] / attempts

            results.append({
                "season": season_value,
                "player_id": entry["player_id"],
                "player_name": entry["player_name"],
                "team_id": entry["team_id"],
                "shot_zone_basic": entry["shot_zone_basic"],
                "attempts": attempts,
                "makes": entry["makes"],
                "actual_fg_pct": round(actual_fg, 4),
                "expected_fg_pct_baseline": None,
                "expected_fg_pct_trained": round(expected_fg, 4),
                "quality_delta_trained": round(actual_fg - expected_fg, 4),
                "model_version": version,
            })

    if not results:
        return {"status": "skipped", "rows_written": 0, "seasons": target_seasons}

    delete_where("gold", "player_zone_season_shot_quality_trained", "season = ANY(%s)", [target_seasons])
    count = insert_rows("gold", "player_zone_season_shot_quality_trained", results)
    logger.info("Wrote %d shot quality rows across %d seasons", count, len(target_seasons))

    return {
        "status": "success",
        "rows_written": count,
        "seasons": target_seasons,
        "model_versions": versions_by_season,
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'gold',
 'task_type': 'gold',
 'inputs': ('silver.fct_shots', 'silver.fct_tracking'),
 'optional_inputs': (),
 'outputs': ('gold.player_zone_season_shot_quality_trained',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live', 'fixture'),
 'required': True,
 'quality_outputs': ('gold.player_zone_season_shot_quality_trained',),
 'regular_season_only': True,
 'live_order': 590,
 'fixture_order': 470}

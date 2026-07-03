"""Trained win probability model.

Logistic regression trained on play-by-play data with features:
  margin, seconds_remaining, time², margin×time interaction,
  possession flag, Elo differential.

Replaces the fixed-parameter probit model with a data-driven approach.
At inference time, uses stored coefficients (no sklearn dependency needed).
"""

import logging
import math
from typing import Any

import polars as pl

logger = logging.getLogger("nba_duckdb.modeling.win_probability")


def build_training_data(
    pbp_df: pl.DataFrame,
    games_df: pl.DataFrame,
    elo_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build features + labels from play-by-play data.

    Returns DataFrame with columns: margin, seconds_remaining, time_sq,
    margin_time, possession_flag, elo_diff, home_wins, game_id, game_date.
    """
    # Get game outcomes: who won
    outcomes = games_df.select([
        pl.col("game_id"),
        pl.col("game_date"),
        pl.col("home_team_id"),
        pl.col("away_team_id"),
        pl.col("home_score"),
        pl.col("away_score"),
    ]).filter(
        (pl.col("home_score").is_not_null()) & (pl.col("away_score").is_not_null())
    ).with_columns(
        (pl.col("home_score") > pl.col("away_score")).cast(pl.Int8).alias("home_wins"),
    )

    # Build Elo lookup
    elo_lookup: dict[int, float] = {}
    if elo_df is not None and not elo_df.is_empty():
        for row in elo_df.iter_rows(named=True):
            tid = row.get("team_id")
            elo = row.get("elo") or row.get("current_elo") or row.get("elo_rating")
            if tid and elo:
                elo_lookup[tid] = float(elo)

    # Process PBP events
    rows = []
    outcome_map = {}
    for r in outcomes.iter_rows(named=True):
        outcome_map[r["game_id"]] = r

    for row in pbp_df.iter_rows(named=True):
        gid = row.get("game_id")
        outcome = outcome_map.get(gid)
        if outcome is None:
            continue

        period = row.get("period", 1) or 1
        clock = row.get("clock_seconds_remaining", 0.0) or 0.0

        # Parse scores
        try:
            home = int(row.get("score_home", 0) or 0)
            away = int(row.get("score_away", 0) or 0)
        except (ValueError, TypeError):
            continue

        if home == 0 and away == 0:
            continue

        # Seconds remaining in regulation
        if period <= 4:
            seconds_remaining = (4 - period) * 720 + clock
        else:
            seconds_remaining = clock

        margin = home - away

        # Infer possession from action type
        action = str(row.get("action_type", "") or "").lower()
        poss_flag = 0.0
        if "turnover" in action:
            poss_flag = -1.0  # opponent gets ball
        elif "made" in action or "free throw" in action:
            poss_flag = -1.0  # opponent gets ball after make
        elif "rebound" in action:
            if "defensive" in action or "def" in action.split():
                poss_flag = 1.0  # home gets ball on defensive rebound
            else:
                poss_flag = 1.0  # offensive rebound, same team keeps ball

        # Elo diff
        home_tid = outcome.get("home_team_id")
        away_tid = outcome.get("away_team_id")
        home_elo = elo_lookup.get(home_tid, 1500.0) if home_tid else 1500.0
        away_elo = elo_lookup.get(away_tid, 1500.0) if away_tid else 1500.0
        elo_diff = (home_elo - away_elo) / 100.0

        # Normalize time for numerical stability
        time_norm = seconds_remaining / 2880.0  # fraction of regulation

        rows.append({
            "game_id": gid,
            "game_date": outcome.get("game_date", ""),
            "margin": float(margin),
            "seconds_remaining": seconds_remaining,
            "time_norm": time_norm,
            "time_sq": time_norm ** 2,
            "margin_time": float(margin) * time_norm,
            "possession_flag": poss_flag,
            "elo_diff": elo_diff,
            "home_wins": outcome["home_wins"],
        })

    if not rows:
        return pl.DataFrame()

    df = pl.DataFrame(rows)

    # Sample: keep ~10% of events to reduce correlation within games
    # Prefer events at different time points (every ~30 seconds of game time)
    df = df.sort(["game_id", "seconds_remaining"], descending=[False, True])
    df = df.with_row_index("idx")
    df = df.filter(pl.col("idx") % 5 == 0).drop("idx")

    return df


def train_model(
    train_df: pl.DataFrame,
) -> tuple[Any, dict]:
    """Train logistic regression on features.

    Returns (fitted model, metadata dict with coefficients).
    """
    from sklearn.linear_model import LogisticRegression

    feature_cols = ["margin", "time_norm", "time_sq", "margin_time", "possession_flag", "elo_diff"]
    X = train_df.select(feature_cols).to_numpy()
    y = train_df["home_wins"].to_numpy()

    model = LogisticRegression(
        max_iter=1000,
        solver="lbfgs",
        C=1.0,
    )
    model.fit(X, y)

    coefficients = {
        "intercept": float(model.intercept_[0]),
        "features": {name: float(coef) for name, coef in zip(feature_cols, model.coef_[0])},
    }

    logger.info(
        "Win prob model trained: intercept=%.4f, margin=%.4f, time=%.4f, elo=%.4f",
        coefficients["intercept"],
        coefficients["features"]["margin"],
        coefficients["features"]["time_norm"],
        coefficients["features"]["elo_diff"],
    )

    return model, coefficients


def evaluate_model(
    model: Any,
    test_df: pl.DataFrame,
    feature_cols: list[str] | None = None,
) -> dict:
    """Evaluate model on test set. Returns metrics dict."""
    import numpy as np
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import brier_score_loss, log_loss

    if feature_cols is None:
        feature_cols = ["margin", "time_norm", "time_sq", "margin_time", "possession_flag", "elo_diff"]

    X_test = test_df.select(feature_cols).to_numpy()
    y_test = test_df["home_wins"].to_numpy()

    y_pred = model.predict_proba(X_test)[:, 1]

    brier = brier_score_loss(y_test, y_pred)
    logloss = log_loss(y_test, y_pred)

    # Calibration curve
    prob_true, prob_pred = calibration_curve(y_test, y_pred, n_bins=10, strategy="uniform")

    # Baseline comparison: probit model
    baseline_preds = []
    for row in test_df.iter_rows(named=True):
        bp = probit_baseline(row["margin"], row["seconds_remaining"])
        baseline_preds.append(bp)
    baseline_preds = np.array(baseline_preds)
    baseline_brier = brier_score_loss(y_test, baseline_preds)
    baseline_logloss = log_loss(y_test, np.clip(baseline_preds, 1e-7, 1 - 1e-7))

    improvement_pct = (1 - brier / baseline_brier) * 100

    metrics = {
        "brier_score": round(float(brier), 6),
        "log_loss": round(float(logloss), 6),
        "baseline_brier_score": round(float(baseline_brier), 6),
        "baseline_log_loss": round(float(baseline_logloss), 6),
        "brier_improvement_pct": round(float(improvement_pct), 2),
        "calibration_bins": {
            "predicted": [round(float(p), 4) for p in prob_pred],
            "actual": [round(float(p), 4) for p in prob_true],
        },
        "n_test_samples": len(y_test),
    }

    logger.info(
        "Win prob evaluation: Brier=%.6f (baseline=%.6f, improvement=%.1f%%), "
        "LogLoss=%.6f (baseline=%.6f)",
        brier, baseline_brier, improvement_pct, logloss, baseline_logloss,
    )

    return metrics


def probit_baseline(margin: float, seconds_remaining: float) -> float:
    """The current fixed-parameter probit model for comparison."""
    if seconds_remaining <= 0:
        return 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5

    minutes_left = seconds_remaining / 60.0
    time_fraction = min(minutes_left / 48.0, 1.0)
    adj_margin = margin + 3.0 * time_fraction

    std = 4.2 * math.sqrt(minutes_left)
    if std < 0.01:
        return 1.0 if adj_margin > 0 else 0.0

    z = adj_margin / std
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def predict_from_coefficients(
    coefficients: dict,
    margin: float,
    seconds_remaining: float,
    possession_flag: float = 0.0,
    elo_diff: float = 0.0,
) -> float:
    """Pure-math inference using stored coefficients. No sklearn needed.

    This is what game_flow.py calls at runtime.
    """
    if seconds_remaining <= 0:
        return 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5

    time_norm = seconds_remaining / 2880.0
    time_sq = time_norm ** 2
    margin_time = margin * time_norm

    b = coefficients["features"]
    z = (
        coefficients["intercept"]
        + b["margin"] * margin
        + b["time_norm"] * time_norm
        + b["time_sq"] * time_sq
        + b["margin_time"] * margin_time
        + b["possession_flag"] * possession_flag
        + b["elo_diff"] * elo_diff
    )

    return 1.0 / (1.0 + math.exp(-z))

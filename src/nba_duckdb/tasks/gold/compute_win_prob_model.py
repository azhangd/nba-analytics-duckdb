"""Gold: Train win probability model and store coefficients."""

import json
import logging
from datetime import datetime, timezone

import polars as pl

from nba_duckdb.db import read_table, upsert_rows
from nba_duckdb.modeling.win_probability import build_training_data, evaluate_model, train_model
from nba_duckdb.season_utils import resolved_target_seasons

logger = logging.getLogger("nba_duckdb.tasks.gold.win_prob_model")


def run(**kwargs):
    target_seasons = resolved_target_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
        game_ids=[str(game_id) for game_id in kwargs.get("game_ids", []) or []],
        regular_season_only=True,
    )

    # 1. Read data
    pbp = read_table("silver", "fct_play_by_play")
    games = read_table("silver", "fct_games")
    elo_history = read_table("gold", "team_game_elo_history")

    if pbp.is_empty() or games.is_empty():
        logger.warning("No PBP or games data — cannot train win probability model")
        return {"status": "skipped", "seasons": target_seasons}

    # Filter to regular season completed games
    status_col = "game_status" if "game_status" in games.columns else "status"
    completed_games = games.filter(
        pl.col(status_col).cast(pl.Utf8).is_in(["3", "Final"]) | pl.col(status_col).is_null()
    )
    if "game_type" in completed_games.columns:
        completed_games = completed_games.filter(
            pl.col("game_type").is_in(["regular_season", "Regular Season"])
            | pl.col("game_type").is_null()
        )

    summaries: list[dict[str, object]] = []
    for season_value in target_seasons:
        season_games = (
            completed_games.filter(pl.col("season") == season_value)
            if "season" in completed_games.columns
            else completed_games
        )
        if season_games.is_empty():
            continue

        game_ids = set(season_games["game_id"].to_list())
        pbp_filtered = pbp.filter(pl.col("game_id").is_in(game_ids))
        elo_history_scoped = (
            elo_history.filter(pl.col("season") == season_value)
            if not elo_history.is_empty() and "season" in elo_history.columns
            else elo_history
        )

        logger.info(
            "Building win-prob training data for %s from %d games, %d PBP events",
            season_value,
            len(game_ids),
            len(pbp_filtered),
        )

        # 2. Build training data
        data = build_training_data(pbp_filtered, season_games, elo_history_scoped)
        if data.is_empty():
            logger.warning("No win-prob training data built for %s", season_value)
            continue

        logger.info(
            "Training data for %s: %d samples from %d games",
            season_value,
            len(data),
            data["game_id"].n_unique(),
        )

        # 3. Split by game date (first 70% train, last 30% test)
        game_dates = data.select("game_id", "game_date").unique().sort("game_date")
        n_games = len(game_dates)
        if n_games < 2:
            logger.warning("Skipping win-prob model for %s: not enough games (%d)", season_value, n_games)
            continue

        split_idx = max(1, int(n_games * 0.7))
        if split_idx >= n_games:
            split_idx = n_games - 1
        train_game_ids = set(game_dates[:split_idx]["game_id"].to_list())
        test_game_ids = set(game_dates[split_idx:]["game_id"].to_list())

        train_df = data.filter(pl.col("game_id").is_in(train_game_ids))
        test_df = data.filter(pl.col("game_id").is_in(test_game_ids))
        if train_df.is_empty() or test_df.is_empty():
            logger.warning("Skipping win-prob model for %s: empty train/test split", season_value)
            continue

        logger.info(
            "Win-prob split for %s: train=%d samples (%d games), test=%d samples (%d games)",
            season_value,
            len(train_df),
            len(train_game_ids),
            len(test_df),
            len(test_game_ids),
        )

        # 4. Train
        model, coefficients = train_model(train_df)

        # 5. Evaluate
        metrics = evaluate_model(model, test_df)

        # 6. Store in model_artifacts
        artifact = {
            "model_name": "win_probability",
            "season": season_value,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "metadata_json": json.dumps({
                "coefficients": coefficients,
                "metrics": metrics,
                "train_samples": len(train_df),
                "test_samples": len(test_df),
                "train_games": len(train_game_ids),
                "test_games": len(test_game_ids),
            }),
        }

        upsert_rows("gold", "model_artifacts", [artifact], conflict_cols=["model_name", "season"])
        summaries.append(
            {
                "season": season_value,
                "brier_score": metrics["brier_score"],
                "baseline_brier": metrics["baseline_brier_score"],
                "improvement_pct": metrics["brier_improvement_pct"],
            }
        )
        logger.info(
            "Win probability model for %s stored. Brier=%.6f (%.1f%% better than baseline)",
            season_value,
            metrics["brier_score"],
            metrics["brier_improvement_pct"],
        )

    if not summaries:
        return {"status": "skipped", "seasons": target_seasons}

    return {
        "status": "trained",
        "seasons": target_seasons,
        "summaries": summaries,
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'gold',
 'task_type': 'gold',
 'inputs': ('silver.fct_play_by_play', 'silver.fct_games', 'gold.team_game_elo_history'),
 'optional_inputs': (),
 'outputs': ('gold.model_artifacts',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live', 'fixture'),
 'required': True,
 'quality_outputs': ('gold.model_artifacts',),
 'regular_season_only': True,
 'live_order': 560,
 'fixture_order': 440}

"""Gold: Compute RAPM (Regularized Adjusted Plus-Minus) for all players."""

import json
import logging
from datetime import datetime, timezone

import numpy as np
import polars as pl

from nba_duckdb.db import (
    delete_where,
    insert_rows,
    read_table,
    truncate_and_insert,
    upsert_rows,
)
from nba_duckdb.modeling.rapm import (
    bootstrap_ci,
    build_design_matrix,
    fit_rapm,
)
from nba_duckdb.season_utils import resolved_target_seasons

logger = logging.getLogger("nba_duckdb.tasks.gold.rapm")


def run(**kwargs):
    target_seasons = resolved_target_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
        game_ids=[str(game_id) for game_id in kwargs.get("game_ids", []) or []],
        regular_season_only=True,
    )

    # 1. Read required data
    lineups = read_table("silver", "fct_lineups")
    games = read_table("silver", "fct_games")
    four_factors = read_table("gold", "team_season_four_factors")
    season_stats_table = read_table("gold", "player_season_stats")
    dim_players = read_table("silver", "dim_players")

    if lineups.is_empty() or games.is_empty():
        logger.warning("No lineups or games data — cannot compute RAPM")
        return {"status": "skipped"}

    # Filter to regular season games
    if "game_type" in games.columns:
        games = games.filter(
            pl.col("game_type").is_in(["regular_season", "Regular Season"])
            | pl.col("game_type").is_null()
        )

    logger.info("RAPM input: %d lineups, %d games", len(lineups), len(games))

    name_lookup: dict[int, str] = {}
    if not dim_players.is_empty():
        for row in dim_players.iter_rows(named=True):
            pid = row.get("player_id")
            name = row.get("player_name") or row.get("full_name")
            if pid and name:
                name_lookup[int(pid)] = str(name)

    results: list[dict[str, object]] = []
    status_rows: list[dict[str, object]] = []
    for season_value in target_seasons:
        season_games = games.filter(pl.col("season") == season_value) if "season" in games.columns else games
        if season_games.is_empty():
            continue

        season_game_ids = [str(game_id) for game_id in season_games["game_id"].drop_nulls().to_list()]
        season_lineups = lineups.filter(pl.col("game_id").is_in(season_game_ids))
        season_four_factors = (
            four_factors.filter(pl.col("season") == season_value)
            if not four_factors.is_empty() and "season" in four_factors.columns
            else four_factors
        )
        season_stats = (
            season_stats_table.filter(pl.col("season") == season_value)
            if not season_stats_table.is_empty() and "season" in season_stats_table.columns
            else season_stats_table
        )
        if season_lineups.is_empty():
            continue

        pace_lookup: dict[int, float] = {}
        if not season_four_factors.is_empty() and "pace" in season_four_factors.columns:
            for row in season_four_factors.iter_rows(named=True):
                tid = row.get("team_id")
                pace = row.get("pace")
                if tid and pace:
                    pace_lookup[int(tid)] = float(pace)

        try:
            X, y, weights, player_ids, rapm_game_ids = build_design_matrix(
                season_lineups, season_games, pace_lookup
            )
        except ValueError as e:
            logger.warning("Could not build RAPM matrix for %s: %s", season_value, e)
            continue

        if len(np.unique(rapm_game_ids)) < 2:
            logger.info(
                "Skipping RAPM for %s: at least two games are required for cross-validation",
                season_value,
            )
            continue

        coefficients, best_lambda, cv_mse = fit_rapm(X, y, weights, rapm_game_ids)
        n_boot = 100
        ci_lower, ci_upper = bootstrap_ci(X, y, weights, rapm_game_ids, best_lambda, n_boot=n_boot)

        player_minutes: dict[int, float] = {}
        player_stints: dict[int, int] = {}
        player_teams: dict[int, int] = {}
        for row in season_lineups.iter_rows(named=True):
            pid_str = row.get("player_ids_str", "")
            dur = row.get("duration_seconds", 0) or 0
            team_id = row.get("team_id")
            for pid_s in str(pid_str).split(","):
                try:
                    pid = int(pid_s.strip())
                except ValueError:
                    continue
                player_minutes[pid] = player_minutes.get(pid, 0.0) + dur / 60.0
                player_stints[pid] = player_stints.get(pid, 0) + 1
                if team_id:
                    player_teams[pid] = int(team_id)

        bpm_prior: dict[int, float] = {}
        if not season_stats.is_empty() and "bpm_approx" in season_stats.columns:
            for row in season_stats.iter_rows(named=True):
                pid = row.get("player_id")
                bpm_approx = row.get("bpm_approx")
                if pid and bpm_approx is not None:
                    bpm_prior[int(pid)] = float(bpm_approx)

        season_results: list[dict[str, object]] = []
        for idx, pid in enumerate(player_ids):
            rapm_val = float(coefficients[idx])
            minutes = player_minutes.get(pid, 0.0)
            prior_val = bpm_prior.get(pid, 0.0)
            alpha = min(1.0, minutes / 500.0)
            blended = alpha * rapm_val + (1 - alpha) * prior_val

            season_results.append({
                "player_id": pid,
                "player_name": name_lookup.get(pid, f"Player {pid}"),
                "season": season_value,
                "team_id": player_teams.get(pid),
                "minutes_played": round(minutes, 1),
                "possessions": None,
                "stints": player_stints.get(pid, 0),
                "orapm": None,
                "drapm": None,
                "rapm": round(rapm_val, 2),
                "orapm_prior": None,
                "drapm_prior": round(prior_val, 2),
                "rapm_blended": round(blended, 2),
                "rapm_ci_lower": round(float(ci_lower[idx]), 2),
                "rapm_ci_upper": round(float(ci_upper[idx]), 2),
                "ridge_lambda": best_lambda,
            })

        if not season_results:
            continue

        sorted_results = sorted(season_results, key=lambda r: r["rapm"], reverse=True)
        top5 = [(r["player_name"], r["rapm"]) for r in sorted_results[:5]]
        bot5 = [(r["player_name"], r["rapm"]) for r in sorted_results[-5:]]

        artifact = {
            "model_name": "rapm",
            "season": season_value,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "metadata_json": json.dumps({
                "best_lambda": best_lambda,
                "cv_mse": round(cv_mse, 4),
                "n_stints": X.shape[0],
                "n_players": X.shape[1],
                "n_bootstrap": n_boot,
                "top_5": top5,
                "bottom_5": bot5,
            }),
        }
        upsert_rows("gold", "model_artifacts", [artifact], conflict_cols=["model_name", "season"])

        both = [
            (r["rapm"], bpm_prior.get(r["player_id"], 0.0))
            for r in season_results
            if r["player_id"] in bpm_prior and r["minutes_played"] > 200
        ]
        corr = None
        if len(both) > 10:
            rapm_arr = np.array([b[0] for b in both])
            bpm_arr = np.array([b[1] for b in both])
            corr = np.corrcoef(rapm_arr, bpm_arr)[0, 1]

        logger.info("Top 5 RAPM for %s: %s", season_value, top5)
        logger.info("Bottom 5 RAPM for %s: %s", season_value, bot5)
        results.extend(season_results)
        status_rows.append(
            {
                "season": season_value,
                "n_players": len(season_results),
                "best_lambda": best_lambda,
                "cv_mse": round(cv_mse, 4),
                "bpm_correlation": round(corr, 3) if corr is not None else None,
            }
        )

    if not results:
        return {"status": "skipped", "rows_written": 0, "seasons": target_seasons}

    count = truncate_and_insert("gold", "player_season_rapm", results) if not target_seasons else 0
    if target_seasons:
        delete_where("gold", "player_season_rapm", "season = ANY(%s)", [target_seasons])
        count = insert_rows("gold", "player_season_rapm", results)
    logger.info("Wrote %d player RAPM values", count)

    latest = status_rows[-1] if status_rows else {}
    return {
        "status": "trained",
        "rows_written": count,
        "seasons": target_seasons,
        "n_players": latest.get("n_players", 0),
        "best_lambda": latest.get("best_lambda"),
        "cv_mse": latest.get("cv_mse"),
        "bpm_correlation": latest.get("bpm_correlation"),
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'gold',
 'task_type': 'gold',
 'inputs': ('silver.fct_lineups',
            'silver.fct_games',
            'gold.team_season_four_factors',
            'gold.player_season_stats'),
 'optional_inputs': (),
 'outputs': ('gold.player_season_rapm',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live', 'fixture'),
 'required': True,
 'quality_outputs': ('gold.player_season_rapm',),
 'regular_season_only': True,
 'live_order': 550,
 'fixture_order': 430}

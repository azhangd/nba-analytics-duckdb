"""Game flow analysis.

Tracks score margin over time, detects scoring runs,
and computes win probability estimates.

Uses a trained logistic regression model if available (stored in
gold.model_artifacts), falling back to the probit baseline otherwise.
"""

import json
import logging

import polars as pl

from nba_duckdb.modeling.win_probability import (
    infer_home_possession_flag,
    predict_from_coefficients,
    probit_baseline,
)

logger = logging.getLogger("nba_duckdb.analytics.game_flow")

# Lazily loaded trained coefficients keyed by season.
_coefficients_by_season: dict[str, dict | None] = {}
_fallback_coefficients: dict | None = None
_fallback_loaded = False


def _load_trained_coefficients(season: str | None = None) -> dict | None:
    """Load trained win probability coefficients from gold.model_artifacts."""
    global _fallback_coefficients, _fallback_loaded

    season_value = str(season or "").strip()
    if season_value in _coefficients_by_season:
        return _coefficients_by_season[season_value]

    try:
        from nba_duckdb.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                if season_value:
                    cur.execute(
                        "SELECT metadata_json FROM gold.model_artifacts "
                        "WHERE model_name = 'win_probability' AND season = %s "
                        "ORDER BY trained_at DESC LIMIT 1",
                        [season_value],
                    )
                    row = cur.fetchone()
                    if row:
                        meta = row["metadata_json"]
                        if isinstance(meta, str):
                            meta = json.loads(meta)
                        coefficients = meta.get("coefficients")
                        if coefficients:
                            _coefficients_by_season[season_value] = coefficients
                            logger.info("Loaded trained win probability model for %s", season_value)
                            return coefficients

                if not _fallback_loaded:
                    _fallback_loaded = True
                    cur.execute(
                        "SELECT metadata_json FROM gold.model_artifacts "
                        "WHERE model_name = 'win_probability' ORDER BY trained_at DESC LIMIT 1"
                    )
                    row = cur.fetchone()
                    if row:
                        meta = row["metadata_json"]
                        if isinstance(meta, str):
                            meta = json.loads(meta)
                        _fallback_coefficients = meta.get("coefficients")
                        if _fallback_coefficients:
                            logger.info("Loaded fallback win probability coefficients")
    except Exception as e:
        logger.debug("Could not load trained win prob model: %s", e)

    if season_value:
        _coefficients_by_season[season_value] = _fallback_coefficients
    return _fallback_coefficients


def _win_probability(
    margin: int,
    seconds_remaining: float,
    season: str | None = None,
    home_has_ball: bool | None = None,
    elo_diff: float = 0.0,
    coefficients: dict | None = None,
) -> float:
    """Estimate win probability for the home team.

    Uses trained logistic regression if available, else probit baseline.
    """
    coefficients = coefficients or _load_trained_coefficients(season=season)
    if coefficients is not None:
        poss_flag = 0.0
        if home_has_ball is True:
            poss_flag = 1.0
        elif home_has_ball is False:
            poss_flag = -1.0
        return predict_from_coefficients(
            coefficients, float(margin), seconds_remaining, poss_flag, elo_diff
        )

    # Fallback to probit baseline
    return probit_baseline(float(margin), seconds_remaining)


def compute_game_flow(
    pbp_df: pl.DataFrame,
    game_id: str,
    *,
    season: str | None = None,
    home_team_id: int | None = None,
    away_team_id: int | None = None,
    pregame_elo_diff: float = 0.0,
    coefficients: dict | None = None,
) -> pl.DataFrame:
    """Compute score margin at each event for game flow visualization.

    Args:
        pbp_df: PBP DataFrame for a single game
        game_id: Game ID

    Returns:
        DataFrame with columns:
        - game_id, period, clock_seconds_remaining
        - game_seconds_elapsed (0 = tip-off)
        - home_score, away_score, margin (home perspective)
        - home_win_prob
    """
    if pbp_df.is_empty():
        return pl.DataFrame()

    events = pbp_df.sort(["period", "clock_seconds_remaining"], descending=[False, True])

    flow_points = []
    for row in events.iter_rows(named=True):
        period = row.get("period", 1)
        clock = row.get("clock_seconds_remaining", 0.0)

        # Parse scores
        try:
            home = int(row.get("score_home", 0) or 0)
            away = int(row.get("score_away", 0) or 0)
        except (ValueError, TypeError):
            continue

        if home == 0 and away == 0:
            continue

        # Calculate game seconds elapsed
        # Each period is 12 min = 720 seconds, OT is 5 min = 300 seconds
        if period <= 4:
            seconds_elapsed = (period - 1) * 720 + (720 - clock)
        else:
            seconds_elapsed = 4 * 720 + (period - 5) * 300 + (300 - clock)

        # Total seconds remaining in regulation
        if period <= 4:
            total_remaining = (4 - period) * 720 + clock
        else:
            total_remaining = clock  # OT

        margin = home - away
        possession_flag = infer_home_possession_flag(
            row,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
        )
        home_has_ball = True if possession_flag > 0 else False if possession_flag < 0 else None
        win_prob = _win_probability(
            margin,
            total_remaining,
            season=season,
            home_has_ball=home_has_ball,
            elo_diff=pregame_elo_diff,
            coefficients=coefficients,
        )

        flow_points.append({
            "game_id": game_id,
            "period": period,
            "clock_seconds_remaining": clock,
            "game_seconds_elapsed": round(seconds_elapsed, 1),
            "home_score": home,
            "away_score": away,
            "margin": margin,
            "home_win_prob": round(win_prob, 3),
        })

    if not flow_points:
        return pl.DataFrame()

    return pl.DataFrame(flow_points).unique(subset=["game_seconds_elapsed"], keep="last")


def detect_runs(flow_df: pl.DataFrame, run_threshold: int = 8) -> pl.DataFrame:
    """Detect scoring runs (e.g., 8-0, 10-2).

    Args:
        flow_df: Game flow DataFrame
        run_threshold: Minimum point swing to count as a run

    Returns:
        DataFrame of detected runs with start/end times and point swing
    """
    if flow_df.is_empty():
        return pl.DataFrame()

    sorted_flow = flow_df.sort("game_seconds_elapsed")
    margins = sorted_flow["margin"].to_list()
    times = sorted_flow["game_seconds_elapsed"].to_list()

    runs = []
    i = 0
    while i < len(margins) - 1:
        start_margin = margins[i]
        max_swing = 0
        best_j = i

        for j in range(i + 1, min(i + 30, len(margins))):  # Look ahead up to 30 events
            swing = abs(margins[j] - start_margin)
            if swing > max_swing:
                max_swing = swing
                best_j = j

            # If margin reverses, stop looking
            if j > i + 2 and abs(margins[j] - margins[j-1]) > 0:
                direction = 1 if margins[j] > margins[j-1] else -1
                if j > i + 3:
                    prev_dir = 1 if margins[j-1] > margins[j-2] else -1
                    if direction != prev_dir:
                        break

        if max_swing >= run_threshold:
            direction = "home" if margins[best_j] > start_margin else "away"
            runs.append({
                "start_time": times[i],
                "end_time": times[best_j],
                "point_swing": max_swing,
                "direction": direction,
                "start_margin": start_margin,
                "end_margin": margins[best_j],
            })
            i = best_j + 1
        else:
            i += 1

    return pl.DataFrame(runs) if runs else pl.DataFrame()

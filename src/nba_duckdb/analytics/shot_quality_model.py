"""Heuristic shot quality calculator.

Estimates expected field goal percentage for each shot using hardcoded,
human-readable heuristic baselines based on:
- Shot distance and zone
- Shot type (2PT vs 3PT)
- Action type (layup, dunk, jump shot, etc.)
- Shot distance within zone (granular adjustment)
- Period and game context
- Heave detection (end-of-quarter desperation shots)

Uses approximate league-average baselines per zone as the foundation.
v3: Added heave detection, improved distance model, catch-and-shoot
    from PBP description hints.
"""

import polars as pl

# Approximate league-average FG% by zone. These are heuristic defaults, not a
# calibrated model artifact.
LEAGUE_AVG_BY_ZONE = {
    "Restricted Area": 0.650,
    "In The Paint (Non-RA)": 0.405,
    "Mid-Range": 0.420,
    "Left Corner 3": 0.385,
    "Right Corner 3": 0.385,
    "Above the Break 3": 0.360,
    "Backcourt": 0.050,
}

# Adjustments by action type (additive to base zone FG%)
ACTION_TYPE_ADJUSTMENTS = {
    # At-rim finishes
    "Dunk": 0.30,
    "Alley Oop Dunk": 0.30,
    "Alley Oop Layup": 0.15,
    "Putback Dunk": 0.28,
    "Putback Layup": 0.08,
    "Tip Shot": 0.05,
    "Cutting Dunk Shot": 0.28,
    "Cutting Layup Shot": 0.08,
    # Layups
    "Layup": 0.05,
    "Driving Layup": 0.03,
    "Finger Roll Layup": 0.05,
    "Reverse Layup": -0.02,
    "Running Layup": 0.02,
    # Hook shots
    "Hook Shot": -0.02,
    "Turnaround Hook": -0.05,
    "Running Hook Shot": -0.01,
    # Jump shots (negative = harder than zone average)
    "Jump Shot": 0.0,
    "Floating Jump Shot": -0.03,
    "Fadeaway Jump Shot": -0.06,
    "Step Back Jump Shot": -0.07,
    "Turnaround Jump Shot": -0.05,
    "Pull-Up Jump Shot": -0.02,
    "Running Jump Shot": -0.03,
    "Turnaround Fadeaway": -0.07,
    # Catch and shoot (slightly better than avg)
    "Catch and Shoot": 0.02,
}

# Distance-based micro-adjustments within zones
# Longer distance within same zone = harder shot
DISTANCE_PENALTY_PER_FOOT = -0.005  # -0.5% per foot beyond zone midpoint


def _distance_adjustment(zone: str, distance_ft: float | None) -> float:
    """Adjust expected FG% based on distance within zone."""
    if distance_ft is None or distance_ft <= 0:
        return 0.0

    # Typical midpoint distances for each zone
    zone_midpoints = {
        "Restricted Area": 3.0,
        "In The Paint (Non-RA)": 8.0,
        "Mid-Range": 15.0,
        "Left Corner 3": 22.0,
        "Right Corner 3": 22.0,
        "Above the Break 3": 25.0,
    }

    midpoint = zone_midpoints.get(zone)
    if midpoint is None:
        return 0.0

    excess = distance_ft - midpoint
    if excess <= 0:
        return min(0.03, abs(excess) * 0.003)  # Slightly easier if closer than midpoint
    return excess * DISTANCE_PENALTY_PER_FOOT


def _period_adjustment(period: int | None) -> float:
    """Slight adjustments for period — 4th quarter pressure, OT fatigue."""
    if period is None:
        return 0.0
    if period >= 5:
        return -0.02  # OT fatigue
    if period == 4:
        return -0.01  # 4th quarter pressure
    return 0.0


def _is_heave(period: int | None, clock_seconds: float | None, distance: float | None) -> bool:
    """Detect end-of-quarter heave attempts.

    A heave is a desperation shot at the buzzer from long range.
    These should get very low expected FG% (~2-5%) regardless of zone.
    """
    if clock_seconds is None or period is None:
        return False
    # Shot taken with <3 seconds left in any period, from 30+ feet
    if clock_seconds <= 3.0 and distance is not None and distance >= 30:
        return True
    # Shot taken with <1 second from beyond half court
    if clock_seconds <= 1.0 and distance is not None and distance >= 40:
        return True
    return False


def compute_shot_quality(shots_df: pl.DataFrame) -> pl.DataFrame:
    """Add heuristic expected FG% and quality delta to each shot.

    Args:
        shots_df: Shot DataFrame from silver.fct_shots

    Returns:
        DataFrame with added columns:
        - expected_fg_pct_heuristic: baseline expected FG% for this shot
        - quality_delta_heuristic: actual - expected (positive = better than expected)
    """
    if shots_df.is_empty():
        return shots_df.with_columns(
            pl.lit(0.0).alias("expected_fg_pct_heuristic"),
            pl.lit(0.0).alias("quality_delta_heuristic"),
        )

    rows = []
    for shot in shots_df.iter_rows(named=True):
        zone = shot.get("shot_zone_basic", "")
        action = shot.get("action_type", "")
        made = shot.get("shot_made", False)
        distance = shot.get("shot_distance_ft", shot.get("shot_distance"))
        period = shot.get("period")
        clock = shot.get("clock_seconds_remaining", shot.get("shot_clock", None))

        # Heave detection — assign very low expected FG%
        if _is_heave(period, clock, distance):
            expected = 0.03
        else:
            # Base expected FG% from zone
            base_efg = LEAGUE_AVG_BY_ZONE.get(zone, 0.40)

            # Action type adjustment
            action_adj = ACTION_TYPE_ADJUSTMENTS.get(action, 0.0)

            # Distance within zone
            dist_adj = _distance_adjustment(zone, distance)

            # Period adjustment
            period_adj = _period_adjustment(period)

            expected = min(0.98, max(0.02, base_efg + action_adj + dist_adj + period_adj))

        # Determine point value (2 or 3)
        shot_type = shot.get("shot_type", "")
        is_three = "3" in str(zone) or "3pt" in str(shot_type).lower() or "3PT" in str(shot_type)
        point_value = 3 if is_three else 2

        # Expected points = xFG% * point_value
        expected_pts = round(expected * point_value, 3)

        # Actual outcome
        actual = 1.0 if made else 0.0
        quality = actual - expected

        rows.append({
            "expected_fg_pct_heuristic": round(expected, 3),
            "quality_delta_heuristic": round(quality, 3),
            "is_heave": _is_heave(period, clock, distance),
            "expected_pts": expected_pts,
            "point_value": point_value,
        })

    quality_df = pl.DataFrame(rows)
    return pl.concat([shots_df, quality_df], how="horizontal_extend")


def aggregate_shot_quality(
    shots_with_quality: pl.DataFrame,
    group_by: list[str] | None = None,
) -> pl.DataFrame:
    """Aggregate shot quality by player, zone, or other grouping.

    Args:
        shots_with_quality: Shots with expected_fg_pct_heuristic column
        group_by: Columns to group by (default: ["player_id", "shot_zone_basic"])

    Returns:
        Aggregated DataFrame with attempts, makes, actual_fg_pct,
        expected_fg_pct_heuristic, and quality_delta_heuristic.
    """
    if group_by is None:
        group_by = ["player_id", "player_name", "shot_zone_basic"]

    if shots_with_quality.is_empty():
        return pl.DataFrame()

    return (
        shots_with_quality
        .group_by(group_by)
        .agg(
            pl.len().alias("attempts"),
            pl.col("shot_made").sum().alias("makes"),
            (pl.col("shot_made").mean() * 100).round(1).alias("actual_fg_pct"),
            (pl.col("expected_fg_pct_heuristic").mean() * 100).round(1).alias("expected_fg_pct_heuristic"),
            (pl.col("quality_delta_heuristic").mean() * 100).round(1).alias("quality_delta_heuristic"),
            pl.col("expected_pts").sum().round(1).alias("total_expected_pts"),
            (pl.col("expected_pts").mean()).round(3).alias("avg_expected_pts_per_shot"),
        )
        .sort("attempts", descending=True)
    )

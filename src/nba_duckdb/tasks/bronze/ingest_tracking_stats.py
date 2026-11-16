"""Bronze: Ingest player tracking stats (12 Hawk-Eye categories) into DuckDB.

Categories: SpeedDistance, Rebounding, Possessions, CatchShoot, PullUpShot,
Defense, Drives, Passing, ElbowTouch, PostTouch, PaintTouch, Efficiency
"""

import json
import logging
from datetime import datetime, timezone

from nba_duckdb.defaults import get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.tasks.bronze._season_payloads import upsert_then_fail_on_holes
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.tracking_stats")

TRACKING_CATEGORIES = [
    "SpeedDistance",
    "Rebounding",
    "Possessions",
    "CatchShoot",
    "PullUpShot",
    "Defense",
    "Drives",
    "Passing",
    "ElbowTouch",
    "PostTouch",
    "PaintTouch",
    "Efficiency",
]


def run(**kwargs):
    season = kwargs.get("season")
    seasons = normalize_requested_seasons(kwargs.get("seasons")) or ([season] if season else get_seasons())
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    failures = []

    for season in seasons:
        for cat in TRACKING_CATEGORIES:
            logger.info("Fetching tracking: %s / %s", cat, season)
            try:
                data = nba_client.get_tracking_stats(
                    season=season, pt_measure_type=cat, player_or_team="Player",
                )
                rows.append({
                    "season": season,
                    "category": cat,
                    "level": "player",
                    "tracking_json": json.dumps(data),
                    "ingested_at": now,
                })
            except Exception as e:
                logger.warning("Failed %s player %s: %s", cat, season, e)
                failures.append(f"{season}/{cat}/player: {e}")

            # Also fetch team-level for some categories
            if cat in ("SpeedDistance", "Rebounding", "Drives", "Passing", "Efficiency"):
                try:
                    data = nba_client.get_tracking_stats(
                        season=season, pt_measure_type=cat, player_or_team="Team",
                    )
                    rows.append({
                        "season": season,
                        "category": cat,
                        "level": "team",
                        "tracking_json": json.dumps(data),
                        "ingested_at": now,
                    })
                except Exception as e:
                    logger.warning("Failed %s team %s: %s", cat, season, e)
                    failures.append(f"{season}/{cat}/team: {e}")

    count = upsert_then_fail_on_holes(
        "tracking_stats", rows, conflict_cols=["season", "category", "level"], failures=failures
    )
    logger.info(
        "Upserted %d tracking stat records across %d categories, %d seasons",
        count, len(TRACKING_CATEGORIES), len(seasons),
    )
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {
    "layer": "bronze",
    "outputs": ("bronze.tracking_stats",),
    "graphs": ("default",),
    "modes": ("live",),
    "live_order": 70,
}

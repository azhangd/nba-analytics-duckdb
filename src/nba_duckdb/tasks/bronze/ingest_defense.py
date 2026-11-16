"""Bronze: Ingest Synergy play type data (offensive/defensive tendencies) into DuckDB."""

import json
import logging
from datetime import datetime, timezone

from nba_duckdb.defaults import get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.tasks.bronze._season_payloads import upsert_then_fail_on_holes
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.defense")

PLAY_TYPES = [
    "Isolation", "Transition", "PRBallHandler", "PRRollman",
    "Postup", "Spotup", "Handoff", "Cut", "OffScreen", "Putbacks", "Misc",
]


def run(**kwargs):
    season = kwargs.get("season")
    seasons = normalize_requested_seasons(kwargs.get("seasons")) or ([season] if season else get_seasons())
    all_rows = []
    failures = []

    for season in seasons:
        for play_type in PLAY_TYPES:
            for grouping in ["offensive", "defensive"]:
                for pt in ["P", "T"]:  # Player and Team level
                    try:
                        raw = nba_client.get_synergy_play_types(
                            season=season,
                            play_type=play_type,
                            player_or_team=pt,
                            type_grouping=grouping,
                        )
                        all_rows.append({
                            "season": season,
                            "play_type": play_type,
                            "type_grouping": grouping,
                            "player_or_team": pt,
                            "defense_json": json.dumps(raw),
                            "ingested_at": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception as e:
                        logger.warning("Failed: %s/%s/%s/%s: %s", season, play_type, grouping, pt, e)
                        failures.append(f"{season}/{play_type}/{grouping}/{pt}: {e}")
                        continue

    count = upsert_then_fail_on_holes(
        "defense",
        all_rows,
        conflict_cols=["season", "play_type", "type_grouping", "player_or_team"],
        failures=failures,
    )
    logger.info("Upserted %d play type combinations across %d seasons", count, len(seasons))
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {
    "layer": "bronze",
    "outputs": ("bronze.defense",),
    "graphs": ("default",),
    "modes": ("live",),
    "live_order": 100,
}

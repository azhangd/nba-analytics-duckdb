"""Bronze: Ingest hustle stats (deflections, contested shots, loose balls, etc.) into DuckDB."""

import json
import logging
from datetime import datetime, timezone

from nba_duckdb.db import upsert_rows
from nba_duckdb.defaults import get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.hustle")


def run(**kwargs):
    season = kwargs.get("season")
    seasons = normalize_requested_seasons(kwargs.get("seasons")) or ([season] if season else get_seasons())
    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for season in seasons:
        logger.info("Fetching player hustle stats for %s", season)
        try:
            player_data = nba_client.get_hustle_stats_player(season=season)
            rows.append({
                "season": season,
                "level": "player",
                "hustle_json": json.dumps(player_data),
                "ingested_at": now,
            })
        except Exception as e:
            logger.warning("Failed to fetch player hustle for %s: %s", season, e)

        logger.info("Fetching team hustle stats for %s", season)
        try:
            team_data = nba_client.get_hustle_stats_team(season=season)
            rows.append({
                "season": season,
                "level": "team",
                "hustle_json": json.dumps(team_data),
                "ingested_at": now,
            })
        except Exception as e:
            logger.warning("Failed to fetch team hustle for %s: %s", season, e)

    count = upsert_rows("bronze", "hustle", rows, conflict_cols=["season", "level"])
    logger.info("Upserted %d hustle stat records across %d seasons", count, len(seasons))
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.hustle',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.hustle',),
 'regular_season_only': True,
 'live_order': 80,
 'fixture_order': None}

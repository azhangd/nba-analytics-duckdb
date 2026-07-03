"""Bronze: Ingest player tracking / shooting dashboard data into DuckDB."""

import json
import logging
from datetime import datetime, timezone

from nba_duckdb.db import upsert_rows
from nba_duckdb.defaults import get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.tracking")


def run(**kwargs):
    season = kwargs.get("season")
    seasons = normalize_requested_seasons(kwargs.get("seasons")) or ([season] if season else get_seasons())
    rows = []

    for season in seasons:
        logger.info("Fetching league-wide player shooting data for season %s", season)
        raw = nba_client.get_player_shooting(season=season)
        rows.append({
            "season": season,
            "tracking_json": json.dumps(raw),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

    count = upsert_rows("bronze", "tracking", rows, conflict_cols=["season"])
    logger.info("Upserted player shooting data for %d seasons", len(seasons))
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.tracking',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.tracking',),
 'regular_season_only': True,
 'live_order': 110,
 'fixture_order': None}

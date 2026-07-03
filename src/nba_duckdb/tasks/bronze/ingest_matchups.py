"""Bronze: Ingest player-vs-player defensive matchup data into DuckDB."""

import json
import logging
import os
from datetime import datetime, timezone

from nba_duckdb.db import upsert_rows
from nba_duckdb.defaults import ALL_TEAM_IDS, get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.matchups")


def run(**kwargs):
    team_ids_raw = os.environ.get("NBA_DUCKDB_TEAM_IDS", ALL_TEAM_IDS)
    team_ids = [int(t.strip()) for t in team_ids_raw.split(",")]
    season = kwargs.get("season")
    seasons = normalize_requested_seasons(kwargs.get("seasons")) or ([season] if season else get_seasons())
    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for season in seasons:
        for team_id in team_ids:
            logger.info("Fetching matchups for team %d / %s (offense)", team_id, season)
            try:
                off_data = nba_client.get_season_matchups(
                    season=season, off_team_id=team_id,
                )
                rows.append({
                    "season": season,
                    "team_id": team_id,
                    "direction": "offense",
                    "matchup_json": json.dumps(off_data),
                    "ingested_at": now,
                })
            except Exception as e:
                logger.warning("Failed offense matchups for %d / %s: %s", team_id, season, e)

            logger.info("Fetching matchups for team %d / %s (defense)", team_id, season)
            try:
                def_data = nba_client.get_season_matchups(
                    season=season, def_team_id=team_id,
                )
                rows.append({
                    "season": season,
                    "team_id": team_id,
                    "direction": "defense",
                    "matchup_json": json.dumps(def_data),
                    "ingested_at": now,
                })
            except Exception as e:
                logger.warning("Failed defense matchups for %d / %s: %s", team_id, season, e)

    count = upsert_rows("bronze", "matchups", rows, conflict_cols=["season", "team_id", "direction"])
    logger.info("Upserted %d matchup records across %d seasons", count, len(seasons))
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.matchups',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.matchups',),
 'regular_season_only': True,
 'live_order': 90,
 'fixture_order': None}

"""Bronze: Ingest team rosters and coaching staff into DuckDB.

The NBA `CommonTeamRoster` endpoint returns two resultSets in a single response:
  * `CommonTeamRoster` — players on the team for the season
  * `Coaches` — head + assistant coaches on the team for the season

Both are persisted to bronze in this task; one HTTP call per (team, season).
"""

import json
import logging
import os
from datetime import datetime, timezone

from nba_duckdb.db import upsert_rows
from nba_duckdb.defaults import ALL_TEAM_IDS, get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.rosters")


def run(**kwargs):
    team_ids_raw = os.environ.get("NBA_DUCKDB_TEAM_IDS", ALL_TEAM_IDS)
    team_ids = [int(t.strip()) for t in team_ids_raw.split(",")]
    season = kwargs.get("season")
    seasons = normalize_requested_seasons(kwargs.get("seasons")) or ([season] if season else get_seasons())

    roster_rows = []
    coach_rows = []

    for season in seasons:
        for team_id in team_ids:
            logger.info("Fetching roster for team %d, season %s", team_id, season)
            raw = nba_client.get_roster(team_id=team_id, season=season)
            now_iso = datetime.now(timezone.utc).isoformat()

            for rs in raw.get("resultSets", []):
                name = rs.get("name")
                headers = rs.get("headers", [])

                if name == "CommonTeamRoster":
                    for row in rs.get("rowSet", []):
                        player = dict(zip(headers, row))
                        roster_rows.append({
                            "player_id": player.get("PLAYER_ID", 0),
                            "team_id": team_id,
                            "player_name": player.get("PLAYER", ""),
                            "jersey_number": player.get("NUM", ""),
                            "position": player.get("POSITION", ""),
                            "height": player.get("HEIGHT", ""),
                            "weight": player.get("WEIGHT", ""),
                            "birth_date": player.get("BIRTH_DATE", ""),
                            "experience": player.get("EXP", ""),
                            "season": season,
                            "raw_json": json.dumps(player),
                            "ingested_at": now_iso,
                        })

                elif name == "Coaches":
                    for row in rs.get("rowSet", []):
                        coach = dict(zip(headers, row))
                        coach_id = coach.get("COACH_ID")
                        if coach_id is None:
                            continue
                        coach_rows.append({
                            "coach_id": str(coach_id),
                            "team_id": team_id,
                            "season": season,
                            "first_name": coach.get("FIRST_NAME") or "",
                            "last_name": coach.get("LAST_NAME") or "",
                            "coach_name": coach.get("COACH_NAME") or "",
                            "is_assistant": int(coach.get("IS_ASSISTANT") or 0),
                            "coach_type": coach.get("COACH_TYPE") or "",
                            "sort_sequence": _to_int(coach.get("SORT_SEQUENCE")),
                            "school": coach.get("SCHOOL") or "",
                            "birth_date": coach.get("BIRTH_DATE") or "",
                            "raw_json": json.dumps(coach),
                            "ingested_at": now_iso,
                        })

    roster_count = upsert_rows(
        "bronze", "rosters", roster_rows, conflict_cols=["player_id", "team_id", "season"]
    )
    coach_count = upsert_rows(
        "bronze", "coaches", coach_rows, conflict_cols=["coach_id", "team_id", "season"]
    )

    logger.info(
        "Upserted %d players + %d coaches across %d teams, %d seasons",
        roster_count, coach_count, len(team_ids), len(seasons),
    )
    return {"rows_written": roster_count, "coach_rows_written": coach_count}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.rosters', 'bronze.coaches'),
 'mutates': (),
 'graphs': ('default', 'quick'),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.rosters', 'bronze.coaches'),
 'regular_season_only': True,
 'live_order': 20,
 'fixture_order': None}

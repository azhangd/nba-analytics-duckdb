"""Bronze: Ingest Synergy play type data (offensive/defensive tendencies) into DuckDB."""

import json
import logging
from datetime import datetime, timezone

from nba_duckdb.db import upsert_rows
from nba_duckdb.defaults import get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
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
    attempts = 0

    for season in seasons:
        for play_type in PLAY_TYPES:
            for grouping in ["offensive", "defensive"]:
                for pt in ["P", "T"]:  # Player and Team level
                    attempts += 1
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

    if attempts and not all_rows:
        sample = "; ".join(failures[:5])
        raise RuntimeError(
            f"Failed to fetch all {attempts} Synergy play-type combinations. "
            f"First failures: {sample}"
        )
    if failures:
        logger.warning(
            "Fetched %d/%d Synergy play-type combinations; first failures: %s",
            len(all_rows),
            attempts,
            "; ".join(failures[:5]),
        )

    count = upsert_rows(
        "bronze", "defense", all_rows,
        conflict_cols=["season", "play_type", "type_grouping", "player_or_team"],
    )
    logger.info("Upserted %d play type combinations across %d seasons", count, len(seasons))
    return {"rows_written": count}

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.defense',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.defense',),
 'regular_season_only': True,
 'live_order': 100,
 'fixture_order': None}

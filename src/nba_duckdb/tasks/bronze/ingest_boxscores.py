"""Bronze: Ingest completed-game box scores into DuckDB."""

import json
import logging
import os
from datetime import datetime, timezone

from nba_duckdb.db import get_conn, read_table, upsert_rows
from nba_duckdb.season_utils import (
    filter_frame_to_competitions,
    requested_or_default_seasons,
)
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.boxscores")
FLUSH_EVERY = 50


def _load_json(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _assert_target_games_written(game_ids: list[str]) -> None:
    if not game_ids:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT game_id, traditional_json FROM bronze.boxscores")
            rows = {str(row["game_id"]): row for row in cur.fetchall()}
    missing = [
        game_id
        for game_id in game_ids
        if game_id not in rows or not _load_json(rows[game_id].get("traditional_json"))
    ]
    if missing:
        missing_summary = ", ".join(missing[:10])
        raise RuntimeError(
            "Box score ingestion incomplete for targeted games: "
            f"{len(missing)} missing/incomplete game(s): {missing_summary}"
        )


def run(**kwargs):
    game_ids = [str(game_id) for game_id in kwargs.get("game_ids", []) or []]
    target_seasons = requested_or_default_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
    )
    target_competitions = kwargs.get("competitions")
    team_ids_raw = os.environ.get("NBA_DUCKDB_TEAM_IDS", "").strip()
    team_ids = (
        {int(value.strip()) for value in team_ids_raw.split(",") if value.strip()}
        if team_ids_raw
        else None
    )

    if not game_ids:
        schedule = read_table("bronze", "schedule", "game_status = 3")
        if schedule.is_empty():
            logger.info("No completed games found in schedule")
            return {"rows_written": 0}

        import polars as pl

        if target_seasons and "season" in schedule.columns:
            schedule = schedule.filter(pl.col("season").is_in(target_seasons))
        schedule = filter_frame_to_competitions(schedule, target_competitions)
        team_games = schedule
        if team_ids is not None:
            team_games = schedule.filter(
                pl.col("home_team_id").is_in(team_ids)
                | pl.col("away_team_id").is_in(team_ids)
            )
        game_ids = team_games["game_id"].unique().to_list()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT game_id, traditional_json, advanced_json, "
                "traditional_source, advanced_source FROM bronze.boxscores"
            )
            existing_rows = {row["game_id"]: row for row in cur.fetchall()}

    already_done = {
        game_id
        for game_id, row in existing_rows.items()
        if _load_json(row.get("traditional_json"))
    }
    todo = [game_id for game_id in game_ids if game_id not in already_done]
    max_retries = 5 if not already_done else 3

    logger.info("Fetching box scores for %d target games", len(todo))

    if not todo:
        _assert_target_games_written([str(game_id) for game_id in game_ids])
        return {"rows_written": 0}

    all_rows = []
    total_written = 0
    failed_game_ids: list[str] = []
    for i, game_id in enumerate(todo):
        if i > 0 and i % 50 == 0:
            logger.info("Progress: %d/%d games", i, len(todo))

        try:
            existing = existing_rows.get(game_id, {})
            boxscore = _load_json(existing.get("traditional_json"))
            traditional_source = str(existing.get("traditional_source") or "unknown")
            if not boxscore:
                boxscore, traditional_source = nba_client.get_boxscore_with_source(
                    game_id=game_id,
                    max_retries=max_retries,
                )

            advanced = _load_json(existing.get("advanced_json"))
            advanced_source = str(existing.get("advanced_source") or "unknown")
            if not advanced:
                try:
                    advanced = nba_client.get_boxscore_advanced(game_id=game_id, max_retries=max(3, max_retries))
                    advanced_source = "stats_v3"
                except Exception as e:
                    logger.info("Advanced box score unavailable for %s: %s", game_id, e)

            all_rows.append({
                "game_id": game_id,
                "traditional_json": json.dumps(boxscore),
                "advanced_json": json.dumps(advanced) if advanced else None,
                "traditional_source": traditional_source,
                "advanced_source": advanced_source,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("Failed to fetch box score for %s: %s", game_id, e)
            failed_game_ids.append(game_id)
            continue

        if len(all_rows) >= FLUSH_EVERY:
            written = upsert_rows("bronze", "boxscores", all_rows, conflict_cols=["game_id"])
            total_written += written
            logger.info("  Flushed %d rows (total: %d)", written, total_written)
            all_rows = []

    if all_rows:
        written = upsert_rows("bronze", "boxscores", all_rows, conflict_cols=["game_id"])
        total_written += written
    if failed_game_ids:
        failed_summary = ", ".join(failed_game_ids[:10])
        raise RuntimeError(
            "Box score ingestion left holes for "
            f"{len(failed_game_ids)} game(s): {failed_summary}"
        )
    _assert_target_games_written([str(game_id) for game_id in game_ids])
    logger.info("Upserted box scores for %d games", total_written)
    return {
        "rows_written": total_written,
        "game_ids": todo,
        "seasons": target_seasons,
        "competitions": list(target_competitions or []),
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': ('bronze.schedule',),
 'optional_inputs': (),
 'outputs': ('bronze.boxscores',),
 'mutates': (),
 'graphs': ('default', 'quick', 'summer_league'),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.boxscores',),
 'regular_season_only': True,
 'live_order': 30,
 'fixture_order': None}

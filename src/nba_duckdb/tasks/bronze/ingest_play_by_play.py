"""Bronze: Ingest completed-game play-by-play into DuckDB."""

import json
import logging
import os
import time
from datetime import datetime, timezone

from nba_duckdb.db import get_conn, read_table, upsert_rows
from nba_duckdb.exceptions import LiveEndpointUnavailableError
from nba_duckdb.ingestion_state import (
    eligible_items,
    incomplete_items,
    make_item,
    mark_item_failed,
    mark_item_running,
    mark_item_success,
    mark_items_success,
    mark_running_items_interrupted,
    summarize_items,
)
from nba_duckdb.orchestration import heartbeat_current_task
from nba_duckdb.season_utils import (
    filter_frame_to_competitions,
    requested_or_default_seasons,
)
from nba_duckdb.utils import nba_client
from nba_duckdb.utils.env import positive_int

logger = logging.getLogger("nba_duckdb.tasks.bronze.play_by_play")
SOURCE = "play-by-play"


def _item_season(game_id: str, game_seasons: dict[str, str], target_seasons: list[str]) -> str:
    if game_id in game_seasons:
        return game_seasons[game_id]
    if len(target_seasons) == 1:
        return target_seasons[0]
    return ""


def _flush_batch(batch: list[dict], batch_items: list[dict]) -> int:
    if not batch:
        return 0
    written = upsert_rows("bronze", "play_by_play", batch, conflict_cols=["game_id"])
    for item in batch_items:
        mark_item_success(SOURCE, item, rows_written=1)
    return written


def _assert_items_complete(items: list[dict]) -> dict:
    item_state = summarize_items(SOURCE, items)
    incomplete = incomplete_items(SOURCE, items)
    if incomplete:
        examples = ", ".join(
            f"{item['game_id']}:{item['status']}" for item in incomplete[:10]
        )
        raise RuntimeError(
            "Play-by-play ingestion incomplete for targeted games: "
            f"{item_state['status_counts']}; examples: {examples}. "
            "Resume with `nba-duckdb run-live --resume-latest` or "
            "`nba-duckdb backfill-source pbp --season <season>`. "
            "If both NBA endpoints are actively blocked, wait 30-60 minutes before resuming."
        )
    return item_state


def run(**kwargs):
    requested_game_ids = [str(game_id) for game_id in kwargs.get("game_ids", []) or []]
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

    schedule = read_table("bronze", "schedule", "game_status = 3")
    game_seasons: dict[str, str] = {}
    if not schedule.is_empty():
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
        if requested_game_ids:
            team_games = team_games.filter(pl.col("game_id").is_in(requested_game_ids))
        game_ids = [str(game_id) for game_id in team_games["game_id"].unique().to_list()]
        for row in team_games.iter_rows(named=True):
            if row.get("season"):
                game_seasons[str(row["game_id"])] = str(row["season"])
    else:
        if not requested_game_ids:
            logger.info("No completed games found in schedule")
            return {"rows_written": 0}
        game_ids = requested_game_ids

    items = [
        make_item(game_id, _item_season(game_id, game_seasons, target_seasons))
        for game_id in game_ids
    ]
    mark_running_items_interrupted(SOURCE, target_seasons[0] if len(target_seasons) == 1 else None)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT game_id FROM bronze.play_by_play")
            already_done = {row["game_id"] for row in cur.fetchall()}
    mark_items_success(
        SOURCE,
        [item for item in items if item["game_id"] in already_done],
        rows_written=1,
    )
    todo_items = eligible_items(SOURCE, items)
    max_retries = 2

    flush_every = positive_int("NBA_DUCKDB_PBP_FLUSH_EVERY", 10, logger=logger)
    progress_every = positive_int("NBA_DUCKDB_PBP_PROGRESS_EVERY", flush_every, logger=logger)
    failure_backoff_after = positive_int(
        "NBA_DUCKDB_PBP_FAILURE_BACKOFF_AFTER",
        10,
        logger=logger,
    )
    failure_backoff_seconds = positive_int(
        "NBA_DUCKDB_PBP_FAILURE_BACKOFF_SECONDS",
        120,
        logger=logger,
    )
    abort_after_failures = positive_int(
        "NBA_DUCKDB_PBP_ABORT_AFTER_FAILURES",
        30,
        logger=logger,
    )
    logger.info(
        "Fetching PBP for %d target games (flush_every=%d, max_retries=%d)",
        len(todo_items),
        flush_every,
        max_retries,
    )

    if not todo_items:
        return {"rows_written": 0, "item_state": _assert_items_complete(items)}

    batch: list[dict] = []
    batch_items: list[dict] = []
    failed_game_ids: list[str] = []
    consecutive_failures = 0
    total_written = 0
    for i, item in enumerate(todo_items):
        game_id = item["game_id"]
        if i > 0 and i % progress_every == 0:
            logger.info(
                "Progress: %d/%d games (written so far: %d)",
                i,
                len(todo_items),
                total_written,
            )
            heartbeat_current_task(
                {
                    "source": SOURCE,
                    "processed": i,
                    "total": len(todo_items),
                    "rows_written": total_written,
                }
            )

        mark_item_running(SOURCE, item)
        try:
            raw, source = nba_client.get_play_by_play_with_source(
                game_id=game_id,
                max_retries=max_retries,
            )
            batch.append({
                "game_id": game_id,
                "pbp_json": json.dumps(raw),
                "source": source,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })
            batch_items.append(item)
            consecutive_failures = 0
        except Exception as e:
            logger.warning("Failed to fetch PBP for %s: %s", game_id, e)
            failed_game_ids.append(game_id)
            consecutive_failures += 1
            mark_item_failed(
                SOURCE,
                item,
                e,
                retry_delay_seconds=failure_backoff_seconds,
            )
            if consecutive_failures >= abort_after_failures:
                if batch:
                    total_written += _flush_batch(batch, batch_items)
                raise LiveEndpointUnavailableError(
                    "Play-by-play ingestion saw "
                    f"{consecutive_failures} consecutive fetch failures; "
                    "likely endpoint-blocked or rate-limited after live CDN and stats "
                    "fallback attempts. Resume with `nba-duckdb run-live --resume-latest` "
                    "or `nba-duckdb backfill-source pbp --season <season>`. "
                    "If both endpoints are blocked, wait 30-60 minutes before resuming."
                ) from e
            if consecutive_failures % failure_backoff_after == 0:
                logger.warning(
                    "Backing off PBP fetches for %d seconds after %d consecutive failures",
                    failure_backoff_seconds,
                    consecutive_failures,
                )
                time.sleep(failure_backoff_seconds)
            continue

        if len(batch) >= flush_every:
            total_written += _flush_batch(batch, batch_items)
            logger.info(
                "Flushed %d PBP games (total written this task: %d)",
                len(batch),
                total_written,
            )
            batch = []
            batch_items = []

    if batch:
        total_written += _flush_batch(batch, batch_items)

    if failed_game_ids:
        failed_summary = ", ".join(failed_game_ids[:10])
        raise RuntimeError(
            "Play-by-play ingestion left holes for "
            f"{len(failed_game_ids)} game(s): {failed_summary}"
        )
    item_state = _assert_items_complete(items)
    logger.info("Upserted PBP for %d games", total_written)
    return {
        "rows_written": total_written,
        "game_ids": [item["game_id"] for item in todo_items],
        "seasons": target_seasons,
        "competitions": list(target_competitions or []),
        "item_state": item_state,
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': ('bronze.schedule',),
 'optional_inputs': (),
 'outputs': ('bronze.play_by_play',),
 'mutates': (),
 'graphs': ('default', 'quick', 'summer_league'),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.play_by_play',),
 'regular_season_only': True,
 'live_order': 40,
 'fixture_order': None}

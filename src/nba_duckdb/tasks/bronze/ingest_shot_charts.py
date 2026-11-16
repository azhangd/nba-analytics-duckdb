"""Bronze: Ingest shot chart detail data into DuckDB."""

import json
import logging
from datetime import datetime, timezone

from nba_duckdb.competitions import competition_for_league_id
from nba_duckdb.db import get_conn, upsert_rows
from nba_duckdb.defaults import get_team_ids
from nba_duckdb.ingestion_state import (
    eligible_items,
    ensure_items,
    make_item,
    mark_item_failed,
    mark_item_running,
    mark_item_success,
    mark_items_success,
    mark_running_items_interrupted,
    summarize_source,
)
from nba_duckdb.orchestration import heartbeat_current_task
from nba_duckdb.season_utils import completed_games_in_scope, requested_or_default_seasons
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.shot_charts")

MAX_RETRIES = 2
FLUSH_EVERY = 10
FAILURE_BACKOFF_AFTER = 5
FAILURE_BACKOFF_SECONDS = 300
ABORT_AFTER_FAILURES = 15
SOURCE = "shot-charts"


def _season_type_for_game_id(game_id: str) -> str:
    prefix = str(game_id)[:3]
    if prefix == "001":
        return "Pre Season"
    if prefix == "004":
        return "Playoffs"
    if prefix == "005":
        return "PlayIn"
    if prefix == "006":
        # The NBA Cup final; ShotChartDetail returns nothing for it as Regular Season.
        return "IST"
    return "Regular Season"


def _shot_count(raw: dict) -> int:
    result_sets = raw.get("resultSets") or []
    return len(result_sets[0].get("rowSet") or []) if result_sets else 0


def _season_type_for_game(game_id: str, league_id: str) -> str:
    if str(league_id) != "00":
        return competition_for_league_id(league_id).season_type
    return _season_type_for_game_id(game_id)


def _flush_batch(batch: list[dict], batch_items: list[dict]) -> int:
    if not batch:
        return 0
    written = upsert_rows("bronze", "shot_charts", batch, conflict_cols=["game_id", "team_id"])
    for item in batch_items:
        mark_item_success(SOURCE, item, rows_written=1)
    return written


def run(**kwargs):
    requested_game_ids = [str(game_id) for game_id in kwargs.get("game_ids", []) or []]
    target_seasons = requested_or_default_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
    )
    target_competitions = kwargs.get("competitions")
    team_ids = get_team_ids()
    schedule = completed_games_in_scope(kwargs)
    if schedule.is_empty():
        logger.info("No completed games found in schedule")
        return {"rows_written": 0, "seasons": target_seasons}

    # Build list of game-team targets for home and away teams.
    items = []
    game_seasons = {}
    game_league_ids = {}
    for row in schedule.iter_rows(named=True):
        game_id = str(row["game_id"])
        if game_id.startswith("003"):
            # All-Star weekend: the mini-games have no shot charts and nothing reads them.
            continue
        game_seasons[game_id] = str(row["season"])
        game_league_ids[game_id] = str(row.get("league_id") or "00")
        for team_id in (row["home_team_id"], row["away_team_id"]):
            if team_id and (team_ids is None or int(team_id) in team_ids):
                items.append(make_item(game_id, game_seasons[game_id], int(team_id)))

    mark_running_items_interrupted(SOURCE, target_seasons[0] if len(target_seasons) == 1 else None)

    # Skip pairs already ingested with shots; stored empty charts are fetched again.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT game_id, team_id,
                       COALESCE(json_array_length(shot_chart_json, '$.resultSets[0].rowSet'), 0) > 0 AS has_shots
                FROM bronze.shot_charts
                """
            )
            stored = {(str(r["game_id"]), int(r["team_id"])): bool(r["has_shots"]) for r in cur.fetchall()}

    ensure_items(SOURCE, items)
    for item in items:
        if stored.get((item["game_id"], int(item["team_id"]))) is False:
            mark_item_failed(SOURCE, item, "stored shot chart is empty")
    mark_items_success(
        SOURCE,
        [item for item in items if stored.get((item["game_id"], int(item["team_id"])))],
        rows_written=1,
    )
    todo_items = eligible_items(SOURCE, items)
    max_retries = MAX_RETRIES

    # Collapse to one API request per game (team_id=0) and fan out the payload
    # to the remaining team rows for that game.
    game_targets: dict[str, list[dict]] = {}
    for item in todo_items:
        game_targets.setdefault(item["game_id"], []).append(item)
    todo_games = sorted(game_targets.keys())
    flush_every = FLUSH_EVERY
    progress_every = flush_every
    failure_backoff_after = FAILURE_BACKOFF_AFTER
    failure_backoff_seconds = FAILURE_BACKOFF_SECONDS
    abort_after_failures = ABORT_AFTER_FAILURES
    logger.info(
        "Fetching shot charts: %d remaining out of %d game-team pairs "
        "(%d game calls, flush_every=%d, max_retries=%d)",
        len(todo_items),
        len(items),
        len(todo_games),
        flush_every,
        max_retries,
    )
    source_season = target_seasons[0] if len(target_seasons) == 1 else None

    total_written = 0
    batch = []
    batch_items: list[dict] = []
    failed_games: list[str] = []
    consecutive_failures = 0

    for i, game_id in enumerate(todo_games):
        if i > 0 and i % progress_every == 0:
            logger.info("  Progress: %d/%d", i, len(todo_games))
            heartbeat_current_task(
                {
                    "source": SOURCE,
                    "processed": i,
                    "total": len(todo_games),
                    "rows_written": total_written,
                }
            )

        game_items = sorted(game_targets.get(game_id, []), key=lambda item: int(item["team_id"]))
        for item in game_items:
            mark_item_running(SOURCE, item)
        try:
            raw = nba_client.get_shot_chart(
                game_id=game_id,
                team_id=0,
                league_id=game_league_ids.get(game_id, "00"),
                season=str(game_seasons.get(game_id) or ""),
                season_type=_season_type_for_game(
                    game_id,
                    game_league_ids.get(game_id, "00"),
                ),
                max_retries=max_retries,
            )
            if not _shot_count(raw):
                raise ValueError("shot chart came back empty for a finished game")
            for item in game_items:
                batch.append({
                    "game_id": game_id,
                    "team_id": int(item["team_id"]),
                    "shot_chart_json": json.dumps(raw),
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                })
                batch_items.append(item)
            consecutive_failures = 0
        except Exception as e:
            logger.warning("Failed to fetch shots for %s: %s", game_id, e)
            failed_games.append(game_id)
            consecutive_failures += 1
            if batch:
                written = _flush_batch(batch, batch_items)
                total_written += written
                logger.info("  Flushed %d rows before backoff/failure (total: %d)", written, total_written)
                batch = []
                batch_items = []
            for item in game_items:
                mark_item_failed(
                    SOURCE,
                    item,
                    e,
                    retry_delay_seconds=failure_backoff_seconds,
                    deferred=True,
                )
            if consecutive_failures >= abort_after_failures:
                logger.warning(
                    "Deferring remaining shot-chart fetches after %d consecutive failures",
                    consecutive_failures,
                )
                break
            if consecutive_failures % failure_backoff_after == 0:
                logger.warning(
                    "Deferring shot-chart retry for %d seconds after %d consecutive failures",
                    failure_backoff_seconds,
                    consecutive_failures,
                )
            continue

        if len(batch) >= flush_every:
            written = _flush_batch(batch, batch_items)
            total_written += written
            logger.info("  Flushed %d rows (total: %d)", written, total_written)
            batch = []
            batch_items = []

    if batch:
        written = _flush_batch(batch, batch_items)
        total_written += written

    logger.info("Upserted shot charts for %d game-team pairs", total_written)
    item_state = summarize_source(SOURCE, source_season)
    result = {
        "rows_written": total_written,
        "game_ids": requested_game_ids,
        "seasons": target_seasons,
        "competitions": list(target_competitions or []),
        "deferred_games": len(set(failed_games)),
        "item_state": item_state,
    }
    if failed_games:
        result["status"] = "deferred"
    return result

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {
    "layer": "bronze",
    "inputs": ("bronze.schedule",),
    "outputs": ("bronze.shot_charts",),
    "graphs": ("default", "summer_league"),
    "modes": ("live",),
    "live_order": 50,
}

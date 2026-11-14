"""Bronze: per-game detail that the regular box scores don't have.

- misc (BoxScoreMiscV3): points off turnovers, second chance, fast break, paint
- rotation (GameRotation): official substitution stints

Both are best effort. A component the NBA won't return is stored as
"unavailable" and downstream falls back (lineups are rebuilt from play-by-play).
With full_refresh, a missing component fails the task instead.
"""

import json
import logging
import time
from datetime import datetime, timezone

from nba_duckdb.db import get_conn, read_table, upsert_rows
from nba_duckdb.season_utils import (
    filter_frame_to_competitions,
    requested_or_default_seasons,
)
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.game_detail")

COMPONENTS = ("misc", "rotation")
FLUSH_EVERY = 50
MISC_RETRIES = 1
STRICT_MISC_RETRIES = 3
# GameRotation tends to fail for everything once it fails at all, so it gets one
# short try, and the first failure stops calls for the rest of the run.
ROTATION_RETRIES = 1
ROTATION_TIMEOUT_SECONDS = 10
RECOVERY_PASSES = 2
RECOVERY_DELAY_SECONDS = 20
UNAVAILABLE_STATUS = "unavailable"


def _detail_payload(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def _is_unavailable(payload) -> bool:
    return _detail_payload(payload).get("_status") == UNAVAILABLE_STATUS


def _is_complete(component: str, payload, *, strict: bool) -> bool:
    doc = _detail_payload(payload)
    if doc.get("_status") == UNAVAILABLE_STATUS:
        return not strict
    if component == "misc":
        boxscore = doc.get("boxScoreMisc", {})
        return bool(boxscore.get("homeTeam") and boxscore.get("awayTeam"))
    return bool(doc.get("resultSets") or doc.get("resultSet"))


def _unavailable(error: Exception) -> dict[str, str]:
    message = str(error).strip() or error.__class__.__name__
    return {"_status": UNAVAILABLE_STATUS, "error": message[:200]}


def _fetch(detail: dict, component: str, game_id: str, *, strict: bool) -> bool:
    """Fetch one component into detail and return whether it came back complete."""
    try:
        if component == "misc":
            detail["misc"] = nba_client.get_boxscore_misc(
                game_id=game_id,
                max_retries=STRICT_MISC_RETRIES if strict else MISC_RETRIES,
            )
        else:
            detail["rotation"] = nba_client.get_game_rotation(
                game_id=game_id,
                max_retries=ROTATION_RETRIES,
                timeout=ROTATION_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        logger.warning("%s failed for %s: %s", component, game_id, exc)
        detail[component] = _unavailable(exc)
        return False
    return _is_complete(component, detail[component], strict=True)


def _incomplete(detail: dict, *, strict: bool) -> list[str]:
    return [c for c in COMPONENTS if not _is_complete(c, detail.get(c), strict=strict)]


def _row(game_id: str, detail: dict) -> dict:
    return {
        "game_id": game_id,
        "detail_json": json.dumps(detail),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


def _game_ids(kwargs, target_seasons) -> list[str]:
    requested = [str(game_id) for game_id in kwargs.get("game_ids", []) or []]
    if requested:
        return requested
    schedule = read_table("bronze", "schedule", "game_status = 3")
    if target_seasons and not schedule.is_empty():
        import polars as pl

        schedule = schedule.filter(pl.col("season").is_in(target_seasons))
        schedule = filter_frame_to_competitions(schedule, kwargs.get("competitions"))
    return schedule["game_id"].unique().to_list() if not schedule.is_empty() else []


def run(**kwargs):
    target_seasons = requested_or_default_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
    )
    strict = bool(kwargs.get("full_refresh"))
    game_ids = _game_ids(kwargs, target_seasons)
    if not game_ids:
        logger.info("No completed games found in schedule")
        return {"rows_written": 0, "seasons": target_seasons}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT game_id, detail_json FROM bronze.game_detail WHERE game_id = ANY(?)",
                [game_ids],
            )
            details = {
                row["game_id"]: _detail_payload(row["detail_json"]) for row in cur.fetchall()
            }

    todo = [game_id for game_id in game_ids if _incomplete(details.get(game_id, {}), strict=strict)]
    logger.info("Fetching game detail: %d remaining out of %d total games", len(todo), len(game_ids))

    total_written = 0
    batch = []
    rotation_circuit_open = False
    for i, game_id in enumerate(todo):
        if i > 0 and i % 20 == 0:
            logger.info("  Progress: %d/%d", i, len(todo))
        detail = details.setdefault(game_id, {})

        if not _is_complete("misc", detail.get("misc"), strict=strict):
            _fetch(detail, "misc", game_id, strict=strict)

        if not _is_complete("rotation", detail.get("rotation"), strict=strict):
            if rotation_circuit_open:
                detail["rotation"] = _unavailable(
                    RuntimeError("rotation endpoint circuit open after a failure")
                )
            elif not _fetch(detail, "rotation", game_id, strict=strict):
                rotation_circuit_open = True
                logger.warning(
                    "Rotation endpoint failed; skipping it for the rest of this run. "
                    "Lineups will be rebuilt from play-by-play."
                )
                if strict:
                    raise RuntimeError(
                        "Official rotation endpoint unavailable during a full refresh"
                    )

        batch.append(_row(game_id, detail))
        if len(batch) >= FLUSH_EVERY:
            total_written += upsert_rows("bronze", "game_detail", batch, conflict_cols=["game_id"])
            batch = []
    if batch:
        total_written += upsert_rows("bronze", "game_detail", batch, conflict_cols=["game_id"])

    failed = [game_id for game_id in todo if strict and _incomplete(details[game_id], strict=True)]
    for attempt in range(RECOVERY_PASSES):
        if not failed:
            break
        if attempt:
            time.sleep(RECOVERY_DELAY_SECONDS)
        logger.info("Retrying %d incomplete game(s), pass %d/%d", len(failed), attempt + 1, RECOVERY_PASSES)
        for game_id in failed:
            for component in _incomplete(details[game_id], strict=True):
                _fetch(details[game_id], component, game_id, strict=strict)
        total_written += upsert_rows(
            "bronze",
            "game_detail",
            [_row(game_id, details[game_id]) for game_id in failed],
            conflict_cols=["game_id"],
        )
        failed = [game_id for game_id in failed if _incomplete(details[game_id], strict=True)]

    misc_holes = sum(_is_unavailable(details[game_id].get("misc")) for game_id in todo)
    rotation_holes = sum(_is_unavailable(details[game_id].get("rotation")) for game_id in todo)
    if misc_holes:
        logger.warning("Misc box score unavailable for %d game(s)", misc_holes)
    if rotation_holes:
        logger.warning(
            "Official rotation data unavailable for %d game(s); "
            "downstream lineups will use play-by-play reconstruction",
            rotation_holes,
        )
    if failed:
        summary = ", ".join(
            f"{game_id}({','.join(_incomplete(details[game_id], strict=True))})" for game_id in failed[:10]
        )
        raise RuntimeError(f"Game detail ingestion left holes for {len(failed)} game(s): {summary}")

    logger.info("Upserted game detail for %d games", total_written)
    return {
        "rows_written": total_written,
        "game_ids": todo,
        "seasons": target_seasons,
        "misc_holes": misc_holes,
        "rotation_holes": rotation_holes,
        "rotation_circuit_open": rotation_circuit_open,
    }


# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {
    "layer": "bronze",
    "inputs": ("bronze.schedule",),
    "outputs": ("bronze.game_detail",),
    "graphs": ("default",),
    "modes": ("live",),
    "live_order": 120,
}

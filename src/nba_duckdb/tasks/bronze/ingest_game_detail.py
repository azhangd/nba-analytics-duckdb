"""Bronze: Ingest extended game-level box scores into DuckDB.

Fetches per-game data that complements the traditional/advanced box scores:
- BoxScoreMiscV3: fast break pts, pts off TOV, 2nd chance pts, paint pts
- BoxScoreScoringV3: assisted/unassisted FG%, scoring type breakdown
- WinProbabilityPBP: optional best-effort official win probability
- GameRotation: official stint/rotation data
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

from nba_duckdb.db import get_conn, read_table, upsert_rows
from nba_duckdb.season_utils import requested_or_default_seasons
from nba_duckdb.utils import nba_client
from nba_duckdb.utils.env import positive_int

logger = logging.getLogger("nba_duckdb.tasks.bronze.game_detail")

FLUSH_EVERY = 50
OPTIONAL_DETAIL_KEYS = ("misc", "scoring", "win_prob")
ROTATION_DETAIL_KEYS = ("rotation",)
DEFAULT_OPTIONAL_RETRIES = 1
STRICT_OPTIONAL_RETRIES = 3
ROTATION_RECOVERY_PASSES = 2
ROTATION_RECOVERY_DELAY_SECONDS = 20
UNAVAILABLE_STATUS = "unavailable"
SKIPPED_STATUS = "skipped"
# Default to fetching misc + scoring alongside rotation so downstream
# silver.fct_game_detail (paint/fast-break/off-TOV/2nd-chance points) stays
# populated. Set ENABLE_OPTIONAL_GAME_DETAIL=0 to skip these to save NBA API
# calls when only rotation data is required.
_OPTIONAL_TOGGLE = os.environ.get("ENABLE_OPTIONAL_GAME_DETAIL", "").strip().lower()
ENABLE_OPTIONAL_DETAIL = _OPTIONAL_TOGGLE not in {"0", "false", "no"}
_ROTATION_TOGGLE = os.environ.get("ENABLE_GAME_ROTATION", "").strip().lower()
ENABLE_ROTATION_DETAIL = _ROTATION_TOGGLE not in {"0", "false", "no"}


def _detail_payload(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _detail_component_complete(
    component: str,
    payload,
    *,
    treat_unavailable_as_complete: bool = True,
) -> bool:
    doc = _detail_payload(payload)
    if doc.get("_status") == SKIPPED_STATUS:
        return True
    if (
        doc.get("_status") == UNAVAILABLE_STATUS
        and treat_unavailable_as_complete
    ):
        return True
    if component == "misc":
        boxscore = doc.get("boxScoreMisc", {})
        if boxscore.get("homeTeam") and boxscore.get("awayTeam"):
            return True
    if component == "scoring":
        boxscore = doc.get("boxScoreScoring", {})
        if boxscore.get("homeTeam") and boxscore.get("awayTeam"):
            return True
    if component == "win_prob" and doc.get("_status") == SKIPPED_STATUS:
        return True
    result_sets = doc.get("resultSets")
    if isinstance(result_sets, list) and result_sets:
        return True
    result_set = doc.get("resultSet")
    if result_set:
        return True
    return False


def _optional_unavailable_payload(error: Exception) -> dict[str, str]:
    message = str(error).strip() or error.__class__.__name__
    return {
        "_status": UNAVAILABLE_STATUS,
        "error": message[:200],
    }


def _optional_skipped_payload(reason: str) -> dict[str, str]:
    return {
        "_status": SKIPPED_STATUS,
        "reason": reason[:200],
    }


def _call_optional_fetcher(fetcher, *, game_id: str, max_retries: int):
    try:
        return fetcher(game_id=game_id, max_retries=max_retries)
    except TypeError as exc:
        message = str(exc)
        if "max_retries" in message and "unexpected keyword argument" in message:
            return fetcher(game_id=game_id)
        raise


def _fetch_optional_component(
    detail: dict,
    component: str,
    game_id: str,
    *,
    include_win_prob: bool,
    max_retries: int,
) -> None:
    if component == "misc":
        try:
            detail["misc"] = _call_optional_fetcher(
                nba_client.get_boxscore_misc,
                game_id=game_id,
                max_retries=max_retries,
            )
        except Exception as exc:
            logger.warning("misc failed for %s: %s", game_id, exc)
            detail["misc"] = _optional_unavailable_payload(exc)
        return

    if component == "scoring":
        try:
            detail["scoring"] = _call_optional_fetcher(
                nba_client.get_boxscore_scoring,
                game_id=game_id,
                max_retries=max_retries,
            )
        except Exception as exc:
            logger.warning("scoring failed for %s: %s", game_id, exc)
            detail["scoring"] = _optional_unavailable_payload(exc)
        return

    if component == "win_prob":
        if include_win_prob:
            try:
                detail["win_prob"] = nba_client.get_win_probability(game_id=game_id)
            except Exception as exc:
                logger.warning("win_prob failed for %s: %s", game_id, exc)
                detail["win_prob"] = _optional_unavailable_payload(exc)
        else:
            detail["win_prob"] = _optional_skipped_payload(
                "official endpoint skipped in default runs; downstream win probability is model-generated"
            )
        return

    raise ValueError(f"Unsupported optional component: {component}")


def _fetch_rotation_component(
    detail: dict,
    game_id: str,
    *,
    max_retries: int,
    timeout: int,
) -> bool:
    """Fetch rotation data and return whether a complete payload was received."""
    try:
        detail["rotation"] = nba_client.get_game_rotation(
            game_id=game_id,
            max_retries=max_retries,
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("rotation failed for %s: %s", game_id, exc)
        detail["rotation"] = _optional_unavailable_payload(exc)
        return False
    return _detail_component_complete("rotation", detail["rotation"])


def _fetch_required_component(detail: dict, component: str, game_id: str) -> None:
    if component == "rotation":
        _fetch_rotation_component(
            detail,
            game_id,
            max_retries=1,
            timeout=10,
        )
        return

    raise ValueError(f"Unsupported required component: {component}")


def _blocking_components(
    *,
    include_optional_detail: bool,
    include_win_prob: bool,
    strict_optional_detail: bool,
    include_rotation_detail: bool,
    strict_rotation_detail: bool,
) -> tuple[str, ...]:
    components = []
    if strict_optional_detail and include_optional_detail:
        components.extend(("misc", "scoring"))
        if include_win_prob:
            components.append("win_prob")
    if strict_rotation_detail and include_rotation_detail:
        components.extend(ROTATION_DETAIL_KEYS)
    return tuple(components)


def _incomplete_components(
    detail: dict,
    components: tuple[str, ...],
    *,
    treat_unavailable_as_complete: bool,
) -> list[str]:
    return [
        component
        for component in components
        if not _detail_component_complete(
            component,
            detail.get(component),
            treat_unavailable_as_complete=treat_unavailable_as_complete,
        )
    ]


def run(**kwargs):
    requested_game_ids = [str(game_id) for game_id in kwargs.get("game_ids", []) or []]
    target_seasons = requested_or_default_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
    )
    include_optional_detail = kwargs.get("include_optional_detail")
    if include_optional_detail is None:
        include_optional_detail = ENABLE_OPTIONAL_DETAIL or bool(kwargs.get("full_refresh"))
    else:
        include_optional_detail = bool(include_optional_detail)
    include_win_prob = include_optional_detail and bool(kwargs.get("include_win_prob"))
    strict_optional_detail = bool(kwargs.get("full_refresh") or kwargs.get("strict_optional_detail"))
    include_rotation_detail = kwargs.get("include_rotation_detail")
    if include_rotation_detail is None:
        include_rotation_detail = ENABLE_ROTATION_DETAIL
    else:
        include_rotation_detail = bool(include_rotation_detail)
    strict_rotation_detail = bool(
        kwargs.get("full_refresh") or kwargs.get("strict_rotation_detail")
    )
    treat_unavailable_as_complete = not (
        strict_optional_detail or strict_rotation_detail
    )
    optional_max_retries = STRICT_OPTIONAL_RETRIES if strict_optional_detail else DEFAULT_OPTIONAL_RETRIES
    rotation_max_retries = positive_int(
        "NBA_DUCKDB_ROTATION_MAX_RETRIES",
        1,
        logger=logger,
    )
    rotation_timeout = positive_int(
        "NBA_DUCKDB_ROTATION_TIMEOUT_SECONDS",
        10,
        logger=logger,
    )
    rotation_circuit_breaker_after = positive_int(
        "NBA_DUCKDB_ROTATION_CIRCUIT_BREAKER_AFTER",
        1,
        logger=logger,
    )
    blocking_components = _blocking_components(
        include_optional_detail=include_optional_detail,
        include_win_prob=include_win_prob,
        strict_optional_detail=strict_optional_detail,
        include_rotation_detail=include_rotation_detail,
        strict_rotation_detail=strict_rotation_detail,
    )
    if requested_game_ids:
        game_ids = requested_game_ids
    else:
        schedule = read_table("bronze", "schedule", "game_status = 3")
        if schedule.is_empty():
            logger.info("No completed games found in schedule")
            return {"rows_written": 0}

        if target_seasons:
            import polars as pl

            if "season" in schedule.columns:
                schedule = schedule.filter(pl.col("season").is_in(target_seasons))
            if schedule.is_empty():
                logger.info("No completed games found in schedule for requested seasons")
                return {"rows_written": 0, "seasons": target_seasons}

        game_ids = schedule["game_id"].unique().to_list()

    with get_conn() as conn:
        with conn.cursor() as cur:
            sql = "SELECT game_id, detail_json FROM bronze.game_detail"
            params: list = []
            if game_ids:
                sql += " WHERE game_id = ANY(%s)"
                params.append(game_ids)
            cur.execute(sql, params)
            existing_details = {
                row["game_id"]: _detail_payload(row.get("detail_json"))
                for row in cur.fetchall()
            }

    requested_detail_keys = []
    if include_optional_detail:
        requested_detail_keys.extend(OPTIONAL_DETAIL_KEYS)
    if include_rotation_detail:
        requested_detail_keys.extend(ROTATION_DETAIL_KEYS)
    todo = [
        game_id
        for game_id in game_ids
        if not all(
            _detail_component_complete(
                component,
                existing_details.get(game_id, {}).get(component),
                treat_unavailable_as_complete=treat_unavailable_as_complete,
            )
            for component in requested_detail_keys
        )
    ]
    logger.info(
        "Fetching game detail: %d remaining out of %d total games",
        len(todo), len(game_ids),
    )

    total_written = 0
    batch = []
    failed_game_ids: list[str] = []
    optional_holes: list[str] = []
    rotation_holes: list[str] = []
    consecutive_rotation_failures = 0
    rotation_circuit_open = False

    for i, game_id in enumerate(todo):
        if i > 0 and i % 20 == 0:
            logger.info("  Progress: %d/%d", i, len(todo))

        detail = dict(existing_details.get(game_id, {}))

        if include_optional_detail:
            if not _detail_component_complete(
                "misc",
                detail.get("misc"),
                treat_unavailable_as_complete=treat_unavailable_as_complete,
            ):
                _fetch_optional_component(
                    detail,
                    "misc",
                    game_id,
                    include_win_prob=include_win_prob,
                    max_retries=optional_max_retries,
                )

            if not _detail_component_complete(
                "scoring",
                detail.get("scoring"),
                treat_unavailable_as_complete=treat_unavailable_as_complete,
            ):
                _fetch_optional_component(
                    detail,
                    "scoring",
                    game_id,
                    include_win_prob=include_win_prob,
                    max_retries=optional_max_retries,
                )

            if not _detail_component_complete(
                "win_prob",
                detail.get("win_prob"),
                treat_unavailable_as_complete=treat_unavailable_as_complete,
            ):
                _fetch_optional_component(
                    detail,
                    "win_prob",
                    game_id,
                    include_win_prob=include_win_prob,
                    max_retries=optional_max_retries,
                )

        if include_rotation_detail and not _detail_component_complete(
            "rotation",
            detail.get("rotation"),
            treat_unavailable_as_complete=treat_unavailable_as_complete,
        ):
            if rotation_circuit_open:
                detail["rotation"] = _optional_unavailable_payload(
                    RuntimeError("rotation endpoint circuit open after repeated failures")
                )
            else:
                rotation_complete = _fetch_rotation_component(
                    detail,
                    game_id,
                    max_retries=rotation_max_retries,
                    timeout=rotation_timeout,
                )
                if rotation_complete:
                    consecutive_rotation_failures = 0
                else:
                    consecutive_rotation_failures += 1
                    if consecutive_rotation_failures >= rotation_circuit_breaker_after:
                        rotation_circuit_open = True
                        logger.warning(
                            "Opening rotation endpoint circuit after %d consecutive failure(s); "
                            "remaining games will use play-by-play lineup reconstruction",
                            consecutive_rotation_failures,
                        )
                        if strict_rotation_detail:
                            raise RuntimeError(
                                "Official rotation endpoint unavailable during strict ingestion; "
                                f"circuit opened after {consecutive_rotation_failures} failure(s)"
                            )
            if _detail_payload(detail.get("rotation")).get("_status") == UNAVAILABLE_STATUS:
                rotation_holes.append(game_id)
        elif not include_rotation_detail:
            detail["rotation"] = _optional_skipped_payload(
                "official rotation endpoint disabled; downstream uses play-by-play lineup reconstruction"
            )

        incomplete = _incomplete_components(
            detail,
            blocking_components,
            treat_unavailable_as_complete=treat_unavailable_as_complete,
        )
        if incomplete:
            failed_game_ids.append(f"{game_id}({','.join(incomplete)})")
            existing_details[game_id] = detail
        if include_optional_detail:
            optional_missing = [
                component
                for component in OPTIONAL_DETAIL_KEYS
                if _detail_payload(detail.get(component)).get("_status") == UNAVAILABLE_STATUS
            ]
            if optional_missing:
                optional_holes.append(f"{game_id}({','.join(optional_missing)})")

        batch.append({
            "game_id": game_id,
            "detail_json": json.dumps(detail),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

        if len(batch) >= FLUSH_EVERY:
            written = upsert_rows("bronze", "game_detail", batch, conflict_cols=["game_id"])
            total_written += written
            logger.info("  Flushed %d rows (total: %d)", written, total_written)
            batch = []

    if batch:
        written = upsert_rows("bronze", "game_detail", batch, conflict_cols=["game_id"])
        total_written += written

    if failed_game_ids:
        failed_ids = [entry.split("(", 1)[0] for entry in failed_game_ids]
        for attempt in range(ROTATION_RECOVERY_PASSES):
            logger.info(
                "Retrying %d incomplete game detail payload(s), recovery pass %d/%d",
                len(failed_ids),
                attempt + 1,
                ROTATION_RECOVERY_PASSES,
            )
            recovered_batch = []
            recovered_failures: list[str] = []
            for game_id in failed_ids:
                detail = dict(existing_details.get(game_id, {}))
                incomplete = _incomplete_components(
                    detail,
                    blocking_components,
                    treat_unavailable_as_complete=treat_unavailable_as_complete,
                )
                for component in incomplete:
                    if component in OPTIONAL_DETAIL_KEYS:
                        _fetch_optional_component(
                            detail,
                            component,
                            game_id,
                            include_win_prob=include_win_prob,
                            max_retries=optional_max_retries,
                        )
                    else:
                        _fetch_required_component(detail, component, game_id)

                recovered_batch.append({
                    "game_id": game_id,
                    "detail_json": json.dumps(detail),
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                })
                existing_details[game_id] = detail

                remaining = _incomplete_components(
                    detail,
                    blocking_components,
                    treat_unavailable_as_complete=treat_unavailable_as_complete,
                )
                if remaining:
                    recovered_failures.append(f"{game_id}({','.join(remaining)})")

            if recovered_batch:
                written = upsert_rows("bronze", "game_detail", recovered_batch, conflict_cols=["game_id"])
                total_written += written
            failed_game_ids = recovered_failures
            if not failed_game_ids:
                break
            if attempt < ROTATION_RECOVERY_PASSES - 1:
                time.sleep(ROTATION_RECOVERY_DELAY_SECONDS)

    if optional_holes:
        optional_summary = ", ".join(optional_holes[:10])
        logger.warning(
            "Optional game detail components unavailable for %d game(s): %s",
            len(optional_holes),
            optional_summary,
        )

    if rotation_holes:
        logger.warning(
            "Official rotation data unavailable for %d game(s); "
            "downstream lineups will use play-by-play reconstruction",
            len(rotation_holes),
        )

    if failed_game_ids:
        failed_summary = ", ".join(failed_game_ids[:10])
        raise RuntimeError(
            "Game detail ingestion left holes for "
            f"{len(failed_game_ids)} game(s): {failed_summary}"
        )

    logger.info("Upserted game detail for %d games", total_written)
    return {
        "rows_written": total_written,
        "game_ids": todo,
        "seasons": target_seasons,
        "optional_holes": len(optional_holes),
        "rotation_holes": len(rotation_holes),
        "rotation_circuit_open": rotation_circuit_open,
        "strict_optional_detail": strict_optional_detail,
        "strict_rotation_detail": strict_rotation_detail,
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': ('bronze.schedule',),
 'optional_inputs': (),
 'outputs': ('bronze.game_detail',),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.game_detail',),
 'regular_season_only': True,
 'live_order': 120,
 'fixture_order': None}

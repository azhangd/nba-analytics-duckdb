"""First-party task orchestration for local DuckDB pipeline runs."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from nba_duckdb import db
from nba_duckdb.exceptions import LiveEndpointUnavailableError, PipelineStateNotInitializedError
from nba_duckdb.ingestion_state import summarize_sources

logger = logging.getLogger("nba_duckdb.orchestration")

SUCCESS = "success"
DEGRADED = "degraded"
DEFERRED = "deferred"
FAILED = "failed"
INTERRUPTED = "interrupted"
RUNNING = "running"

RERUNNABLE_STATUSES = {FAILED, INTERRUPTED, RUNNING}
SUCCESS_LIKE_STATUSES = {SUCCESS, DEGRADED, DEFERRED}


@dataclass(frozen=True)
class RunContext:
    run_id: str
    command: str
    graph: str
    scope: dict[str, Any]
    resume: bool
    retry_failed: bool


@dataclass(frozen=True)
class TaskSpec:
    name: str
    task_type: str
    action: Callable[[], dict[str, Any]]
    required: bool = True


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _json_loads(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(str(value))


def _latest_incomplete_run(command: str) -> dict[str, Any] | None:
    rows = db.execute(
        """
        SELECT *
        FROM ops.pipeline_runs
        WHERE command = ?
          AND status IN ('running', 'failed', 'interrupted')
        ORDER BY updated_at DESC, started_at DESC
        LIMIT 1
        """,
        [command],
    )
    return rows[0] if rows else None


def _get_pipeline_run(run_id: str) -> dict[str, Any] | None:
    rows = db.execute("SELECT * FROM ops.pipeline_runs WHERE run_id = ?", [run_id])
    return rows[0] if rows else None


def _insert_pipeline_run(
    *,
    run_id: str,
    command: str,
    graph: str,
    scope: dict[str, Any],
) -> None:
    db.insert_rows(
        "ops",
        "pipeline_runs",
        [
            {
                "run_id": run_id,
                "command": command,
                "graph": graph,
                "scope_json": _json_dumps(scope),
                "status": RUNNING,
            }
        ],
    )


def _mark_pipeline_running(run_id: str) -> None:
    db.execute(
        """
        UPDATE ops.pipeline_runs
        SET status = 'running',
            updated_at = CURRENT_TIMESTAMP,
            finished_at = NULL
        WHERE run_id = ?
        """,
        [run_id],
    )


def _pid_is_live(pid: Any) -> bool:
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def mark_stale_running_tasks_interrupted(run_id: str) -> list[str]:
    running_rows = db.execute(
        """
        SELECT task_name, worker_pid
        FROM ops.task_runs
        WHERE run_id = ?
          AND status = 'running'
        """,
        [run_id],
    )
    live_tasks = [
        str(row["task_name"])
        for row in running_rows
        if _pid_is_live(row.get("worker_pid"))
    ]
    stale_tasks = [
        str(row["task_name"])
        for row in running_rows
        if not _pid_is_live(row.get("worker_pid"))
    ]
    if stale_tasks:
        placeholders = ", ".join("?" for _ in stale_tasks)
        db.execute(
            f"""
            UPDATE ops.task_runs
            SET status = 'interrupted',
                updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP,
                error_text = COALESCE(error_text, 'Interrupted by an earlier process')
            WHERE run_id = ?
              AND task_name IN ({placeholders})
            """,
            [run_id, *stale_tasks],
        )
    return live_tasks


def prepare_run(
    *,
    command: str,
    graph: str,
    scope: dict[str, Any],
    run_id: str | None = None,
    resume_latest: bool = False,
    retry_failed: bool = False,
) -> RunContext:
    if resume_latest and run_id:
        raise ValueError("--resume-latest cannot be combined with --run-id")
    if retry_failed and not (resume_latest or run_id):
        raise ValueError("--retry-failed requires --run-id or --resume-latest")

    existing: dict[str, Any] | None = None
    resume = resume_latest
    if resume_latest:
        existing = _latest_incomplete_run(command)
        if existing is None:
            raise RuntimeError(f"No incomplete {command} run found to resume")
    elif run_id:
        existing = _get_pipeline_run(run_id)
        resume = existing is not None

    if existing is None:
        actual_run_id = run_id or str(uuid.uuid4())
        _insert_pipeline_run(
            run_id=actual_run_id,
            command=command,
            graph=graph,
            scope=scope,
        )
        return RunContext(
            run_id=actual_run_id,
            command=command,
            graph=graph,
            scope=scope,
            resume=False,
            retry_failed=retry_failed,
        )

    actual_run_id = str(existing["run_id"])
    existing_graph = str(existing["graph"])
    if graph != existing_graph:
        logger.warning(
            "Ignoring requested graph %s while resuming run %s; stored graph is %s",
            graph,
            actual_run_id,
            existing_graph,
        )
    live_tasks = mark_stale_running_tasks_interrupted(actual_run_id)
    if live_tasks:
        task_list = ", ".join(live_tasks)
        raise RuntimeError(
            f"Run {actual_run_id} still has live running task(s): {task_list}. "
            "Wait for that process to finish or stop it before resuming."
        )
    _mark_pipeline_running(actual_run_id)
    return RunContext(
        run_id=actual_run_id,
        command=str(existing["command"]),
        graph=existing_graph,
        scope=_json_loads(existing["scope_json"]),
        resume=resume,
        retry_failed=retry_failed,
    )


def _get_task_run(run_id: str, task_name: str) -> dict[str, Any] | None:
    rows = db.execute(
        """
        SELECT *
        FROM ops.task_runs
        WHERE run_id = ?
          AND task_name = ?
        """,
        [run_id, task_name],
    )
    return rows[0] if rows else None


def _should_skip_task(
    context: RunContext,
    task_name: str,
    *,
    force_rerun_success_like: bool = False,
) -> tuple[bool, str]:
    existing = _get_task_run(context.run_id, task_name)
    if existing is None:
        if context.retry_failed:
            return True, "missing"
        return False, ""

    status = str(existing["status"])
    if status in SUCCESS_LIKE_STATUSES and not force_rerun_success_like:
        return True, "already_success"
    if (
        context.retry_failed
        and status not in RERUNNABLE_STATUSES
        and not (force_rerun_success_like and status in SUCCESS_LIKE_STATUSES)
    ):
        return True, status
    return False, ""


def _start_task(run_id: str, task_name: str, task_type: str, max_attempts: int) -> int:
    existing = _get_task_run(run_id, task_name)
    attempts = int(existing["attempts"]) + 1 if existing else 1
    row = {
        "run_id": run_id,
        "task_name": task_name,
        "task_type": task_type,
        "status": RUNNING,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "started_at": existing["started_at"] if existing and existing["started_at"] else None,
        "result_json": None,
        "error_text": None,
    }
    if row["started_at"] is None:
        db.execute(
            """
            INSERT INTO ops.task_runs (
                run_id, task_name, task_type, status, attempts, max_attempts,
                started_at, heartbeat_at, updated_at, worker_pid, progress_json,
                result_json, error_text
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP, ?, NULL, ?, ?)
            """,
            [
                row["run_id"],
                row["task_name"],
                row["task_type"],
                row["status"],
                row["attempts"],
                row["max_attempts"],
                os.getpid(),
                row["result_json"],
                row["error_text"],
            ],
        )
    else:
        db.execute(
            """
            UPDATE ops.task_runs
            SET task_type = ?,
                status = ?,
                attempts = ?,
                max_attempts = ?,
                heartbeat_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                finished_at = NULL,
                worker_pid = ?,
                progress_json = NULL,
                result_json = ?,
                error_text = ?
            WHERE run_id = ?
              AND task_name = ?
            """,
            [
                row["task_type"],
                row["status"],
                row["attempts"],
                row["max_attempts"],
                os.getpid(),
                row["result_json"],
                row["error_text"],
                row["run_id"],
                row["task_name"],
            ],
        )
    return attempts


def _result_status(result: dict[str, Any]) -> str:
    requested = str(result.get("status") or SUCCESS)
    return requested if requested in SUCCESS_LIKE_STATUSES else SUCCESS


def _finish_task_result(
    run_id: str,
    task_name: str,
    result: dict[str, Any],
    *,
    status: str | None = None,
) -> None:
    final_status = status or _result_status(result)
    db.execute(
        """
        UPDATE ops.task_runs
        SET status = ?,
            result_json = ?,
            error_text = NULL,
            heartbeat_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP
        WHERE run_id = ?
          AND task_name = ?
        """,
        [final_status, _json_dumps(result), run_id, task_name],
    )


def _finish_task_failed(run_id: str, task_name: str, error: BaseException) -> None:
    db.execute(
        """
        UPDATE ops.task_runs
        SET status = 'failed',
            error_text = ?,
            heartbeat_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP,
            progress_json = NULL
        WHERE run_id = ?
          AND task_name = ?
        """,
        [f"{type(error).__name__}: {error}", run_id, task_name],
    )


def _task_result(run_id: str, task_name: str) -> dict[str, Any]:
    row = _get_task_run(run_id, task_name)
    if row is None:
        return {"status": "missing"}
    result = {
        "status": row["status"],
        "attempts": row["attempts"],
    }
    if row.get("result_json"):
        raw_result = row["result_json"]
        result["result"] = raw_result if isinstance(raw_result, dict) else json.loads(str(raw_result))
    if row.get("error_text"):
        result["error"] = row["error_text"]
    return result


def heartbeat_current_task(progress: dict[str, Any] | None = None) -> None:
    run_id = os.environ.get("NBA_DUCKDB_ACTIVE_RUN_ID")
    task_name = os.environ.get("NBA_DUCKDB_ACTIVE_TASK_NAME")
    if not run_id or not task_name:
        return
    db.execute(
        """
        UPDATE ops.task_runs
        SET heartbeat_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            progress_json = ?
        WHERE run_id = ?
          AND task_name = ?
        """,
        [_json_dumps(progress or {}), run_id, task_name],
    )


def _run_with_task_env(context: RunContext, task_name: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    old_run_id = os.environ.get("NBA_DUCKDB_ACTIVE_RUN_ID")
    old_task_name = os.environ.get("NBA_DUCKDB_ACTIVE_TASK_NAME")
    os.environ["NBA_DUCKDB_ACTIVE_RUN_ID"] = context.run_id
    os.environ["NBA_DUCKDB_ACTIVE_TASK_NAME"] = task_name
    try:
        return action()
    finally:
        if old_run_id is None:
            os.environ.pop("NBA_DUCKDB_ACTIVE_RUN_ID", None)
        else:
            os.environ["NBA_DUCKDB_ACTIVE_RUN_ID"] = old_run_id
        if old_task_name is None:
            os.environ.pop("NBA_DUCKDB_ACTIVE_TASK_NAME", None)
        else:
            os.environ["NBA_DUCKDB_ACTIVE_TASK_NAME"] = old_task_name


def _execute_task_with_retries(
    context: RunContext,
    task: TaskSpec,
    *,
    max_attempts: int,
    retry_delay_seconds: float,
    force_rerun_success_like: bool = False,
) -> dict[str, Any]:
    skip, reason = _should_skip_task(
        context,
        task.name,
        force_rerun_success_like=force_rerun_success_like,
    )
    if skip:
        return {"status": "skipped", "reason": reason}

    last_error: BaseException | None = None
    for attempt_index in range(max_attempts):
        _start_task(context.run_id, task.name, task.task_type, max_attempts)
        try:
            result = _run_with_task_env(context, task.name, task.action)
            _finish_task_result(context.run_id, task.name, result)
            return _task_result(context.run_id, task.name)
        except LiveEndpointUnavailableError as exc:
            last_error = exc
            _finish_task_failed(context.run_id, task.name, exc)
            if not task.required:
                result = {
                    "status": DEGRADED,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                _finish_task_result(context.run_id, task.name, result, status=DEGRADED)
                return _task_result(context.run_id, task.name)
            raise
        except Exception as exc:  # noqa: BLE001 - task boundaries must record arbitrary failures
            last_error = exc
            _finish_task_failed(context.run_id, task.name, exc)
            if attempt_index < max_attempts - 1 and retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)
            elif attempt_index == max_attempts - 1 and not task.required:
                result = {
                    "status": DEGRADED,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                _finish_task_result(context.run_id, task.name, result, status=DEGRADED)
                return _task_result(context.run_id, task.name)
    assert last_error is not None
    raise last_error


def _missing_ops_state(exc: Exception) -> bool:
    message = str(exc)
    return (
        "does not exist" in message
        or "Catalog Error" in message
        or "Cannot open file" in message
        or "No such file" in message
    )


def _expected_task_names(steps: Sequence[TaskSpec]) -> list[str]:
    return [step.name for step in steps]


def _complete_pipeline_run(run_id: str, expected_tasks: Sequence[str]) -> dict[str, Any]:
    rows = db.execute(
        """
        SELECT task_name, status
        FROM ops.task_runs
        WHERE run_id = ?
        """,
        [run_id],
    )
    statuses = {str(row["task_name"]): str(row["status"]) for row in rows}
    missing = [task_name for task_name in expected_tasks if task_name not in statuses]
    success_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == SUCCESS)
    degraded_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == DEGRADED)
    deferred_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == DEFERRED)
    failed_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == FAILED)
    interrupted_count = sum(
        1 for task_name in expected_tasks if statuses.get(task_name) == INTERRUPTED
    )
    complete_count = success_count + degraded_count + deferred_count
    if complete_count == len(expected_tasks) and not missing:
        final_status = SUCCESS if degraded_count == 0 and deferred_count == 0 else DEGRADED
    else:
        final_status = FAILED
    db.execute(
        """
        UPDATE ops.pipeline_runs
        SET status = ?,
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP,
            task_count = ?,
            success_count = ?,
            degraded_count = ?,
            deferred_count = ?,
            failed_count = ?,
            interrupted_count = ?
        WHERE run_id = ?
        """,
        [
            final_status,
            len(expected_tasks),
            success_count,
            degraded_count,
            deferred_count,
            failed_count,
            interrupted_count,
            run_id,
        ],
    )
    return {
        "run_id": run_id,
        "status": final_status,
        "task_count": len(expected_tasks),
        "success_count": success_count,
        "degraded_count": degraded_count,
        "deferred_count": deferred_count,
        "failed_count": failed_count,
        "interrupted_count": interrupted_count,
        "missing_tasks": missing,
    }


def _mark_pipeline_failed(run_id: str, expected_tasks: Sequence[str]) -> None:
    rows = db.execute(
        """
        SELECT task_name, status
        FROM ops.task_runs
        WHERE run_id = ?
        """,
        [run_id],
    )
    statuses = {str(row["task_name"]): str(row["status"]) for row in rows}
    success_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == SUCCESS)
    failed_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == FAILED)
    degraded_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == DEGRADED)
    deferred_count = sum(1 for task_name in expected_tasks if statuses.get(task_name) == DEFERRED)
    interrupted_count = sum(
        1 for task_name in expected_tasks if statuses.get(task_name) == INTERRUPTED
    )
    db.execute(
        """
        UPDATE ops.pipeline_runs
        SET status = 'failed',
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP,
            task_count = ?,
            success_count = ?,
            degraded_count = ?,
            deferred_count = ?,
            failed_count = ?,
            interrupted_count = ?
        WHERE run_id = ?
        """,
        [
            len(expected_tasks),
            success_count,
            degraded_count,
            deferred_count,
            failed_count,
            interrupted_count,
            run_id,
        ],
    )


def run_steps(
    context: RunContext,
    steps: Sequence[TaskSpec],
    *,
    retries: int,
    retry_delay_seconds: float,
) -> dict[str, Any]:
    max_attempts = retries + 1
    expected_tasks = _expected_task_names(steps)
    results: dict[str, Any] = {}
    try:
        downstream_rerun_required = False
        for step in steps:
            results[step.name] = _execute_task_with_retries(
                context,
                step,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
                force_rerun_success_like=downstream_rerun_required,
            )
            if context.retry_failed and results[step.name].get("status") != "skipped":
                downstream_rerun_required = True
    except Exception:
        _mark_pipeline_failed(context.run_id, expected_tasks)
        raise

    summary = _complete_pipeline_run(context.run_id, expected_tasks)
    return {
        **summary,
        "graph": context.graph,
        "command": context.command,
        "scope": context.scope,
        "tasks": results,
    }


def list_pipeline_runs(limit: int = 20) -> list[dict[str, Any]]:
    try:
        return db.execute(
            """
            SELECT run_id, command, graph, status, started_at, updated_at, finished_at,
                   task_count, success_count, degraded_count, deferred_count,
                   failed_count, interrupted_count
            FROM ops.pipeline_runs
            ORDER BY updated_at DESC, started_at DESC
            LIMIT ?
            """,
            [limit],
            read_only=True,
        )
    except Exception as exc:  # noqa: BLE001 - observability should be harmless pre-init
        if _missing_ops_state(exc):
            return []
        raise


def get_run_detail(run_id: str) -> dict[str, Any]:
    try:
        run_rows = db.execute(
            "SELECT * FROM ops.pipeline_runs WHERE run_id = ?",
            [run_id],
            read_only=True,
        )
    except Exception as exc:  # noqa: BLE001 - return a clear CLI-facing message
        if _missing_ops_state(exc):
            raise PipelineStateNotInitializedError(
                "Run state tables not found; run `nba-duckdb init` first"
            ) from exc
        raise
    if not run_rows:
        raise RuntimeError(f"Run not found: {run_id}")
    task_rows = db.execute(
        """
        SELECT task_name, task_type, status, attempts, max_attempts,
               started_at, heartbeat_at, updated_at, finished_at, worker_pid,
               progress_json, result_json, error_text
        FROM ops.task_runs
        WHERE run_id = ?
        ORDER BY started_at, task_name
        """,
        [run_id],
        read_only=True,
    )
    run = dict(run_rows[0])
    run["scope"] = _json_loads(run.pop("scope_json", None))
    run["tasks"] = task_rows
    run["ingestion_items"] = summarize_sources(
        season=run["scope"].get("season"),
        source=run["scope"].get("source"),
        read_only=True,
    )
    return run

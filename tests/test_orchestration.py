import os

import pytest

from nba_duckdb.exceptions import LiveEndpointUnavailableError
from nba_duckdb.orchestration import (
    TaskSpec,
    get_run_detail,
    prepare_run,
    run_steps,
)


def _counting_steps(names, task_type="python"):
    """TaskSpecs that count how often each one runs."""
    calls = dict.fromkeys(names, 0)

    def make(name):
        def action():
            calls[name] += 1
            return {}

        return action

    return calls, [TaskSpec(name, task_type, make(name)) for name in names]


def test_run_state_records_successful_task(tmp_db):
    context = prepare_run(command="run-smoke", graph="default", scope={"season": "fixture"})

    result = run_steps(
        context,
        [TaskSpec("task_a", "python", lambda: {"rows_written": 1})],
        retries=0,
        retry_delay_seconds=0,
    )

    detail = get_run_detail(result["run_id"])
    assert result["status"] == "success"
    assert detail["status"] == "success"
    assert detail["task_count"] == 1
    assert detail["tasks"][0]["task_name"] == "task_a"
    assert detail["tasks"][0]["status"] == "success"
    assert detail["tasks"][0]["attempts"] == 1


def test_task_retries_until_success(tmp_db):
    attempts = {"task": 0}

    def flaky_task():
        attempts["task"] += 1
        if attempts["task"] == 1:
            raise RuntimeError("temporary failure")
        return {"ok": True}

    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})
    result = run_steps(
        context,
        [TaskSpec("flaky_task", "python", flaky_task)],
        retries=1,
        retry_delay_seconds=0,
    )

    detail = get_run_detail(result["run_id"])
    assert attempts["task"] == 2
    assert result["status"] == "success"
    assert detail["tasks"][0]["attempts"] == 2
    assert detail["tasks"][0]["status"] == "success"


def test_endpoint_unavailable_error_does_not_burn_task_retries(tmp_db):
    attempts = {"task": 0}

    def blocked_task():
        attempts["task"] += 1
        raise LiveEndpointUnavailableError("blocked")

    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})

    with pytest.raises(LiveEndpointUnavailableError, match="blocked"):
        run_steps(
            context,
            [TaskSpec("blocked_task", "python", blocked_task)],
            retries=2,
            retry_delay_seconds=0,
        )

    detail = get_run_detail(context.run_id)
    assert attempts["task"] == 1
    assert detail["status"] == "failed"
    assert detail["success_count"] == 0
    assert detail["tasks"][0]["attempts"] == 1
    assert detail["tasks"][0]["status"] == "failed"


def test_optional_task_failure_marks_run_degraded(tmp_db):
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})

    result = run_steps(
        context,
        [
            TaskSpec("required_task", "python", lambda: {"ok": True}),
            TaskSpec(
                "optional_task",
                "python",
                lambda: (_ for _ in ()).throw(RuntimeError("rate limited")),
                required=False,
            ),
        ],
        retries=0,
        retry_delay_seconds=0,
    )

    detail = get_run_detail(result["run_id"])
    statuses = {task["task_name"]: task["status"] for task in detail["tasks"]}
    assert result["status"] == "degraded"
    assert result["degraded_count"] == 1
    assert statuses == {"required_task": "success", "optional_task": "degraded"}


def test_run_detail_includes_ingestion_item_summary(tmp_db):
    from nba_duckdb.ingestion_state import eligible_items, make_item, mark_item_success

    item = make_item("0029900001", "2099-00", team_id=1610612737)
    eligible_items("shot-charts", [item])
    mark_item_success("shot-charts", item, rows_written=1)
    context = prepare_run(
        command="backfill-source",
        graph="shot-charts",
        scope={"season": "2099-00", "source": "shot-charts"},
    )
    run_steps(
        context,
        [TaskSpec("noop", "python", lambda: {"ok": True})],
        retries=0,
        retry_delay_seconds=0,
    )

    detail = get_run_detail(context.run_id)

    assert detail["ingestion_items"] == [
        {
            "source": "shot-charts",
            "season": "2099-00",
            "total_items": 1,
            "rows_written": 1,
            "status_counts": {"success": 1},
        }
    ]


def test_resume_marks_stale_running_task_interrupted_and_skips_success(tmp_db):
    db = tmp_db
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})
    run_steps(
        context,
        [TaskSpec("already_done", "python", lambda: {"ok": True})],
        retries=0,
        retry_delay_seconds=0,
    )
    db.execute(
        """
        INSERT INTO ops.task_runs (
            run_id, task_name, task_type, status, attempts, max_attempts,
            started_at, updated_at
        )
        VALUES (?, 'interrupted_task', 'python', 'running', 1, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        [context.run_id],
    )
    calls, steps = _counting_steps(["already_done", "interrupted_task"])

    resumed_context = prepare_run(
        command="run-live",
        graph="default",
        scope={"season": "ignored"},
        run_id=context.run_id,
    )
    result = run_steps(
        resumed_context,
        steps,
        retries=0,
        retry_delay_seconds=0,
    )

    detail = get_run_detail(result["run_id"])
    statuses = {task["task_name"]: task for task in detail["tasks"]}
    assert resumed_context.scope == {"season": "2025-26"}
    assert calls == {"already_done": 0, "interrupted_task": 1}
    assert result["status"] == "success"
    assert statuses["already_done"]["attempts"] == 1
    assert statuses["interrupted_task"]["attempts"] == 2
    assert statuses["interrupted_task"]["status"] == "success"


def test_resume_keeps_stored_graph_when_requested_graph_differs(tmp_db):
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})

    resumed_context = prepare_run(
        command="run-live",
        graph="quick",
        scope={"season": "ignored"},
        run_id=context.run_id,
    )

    assert resumed_context.graph == "default"
    assert resumed_context.scope == {"season": "2025-26"}


def test_resume_refuses_to_interrupt_live_running_task(tmp_db):
    db = tmp_db
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})
    db.execute(
        """
        INSERT INTO ops.task_runs (
            run_id, task_name, task_type, status, attempts, max_attempts,
            started_at, updated_at, worker_pid
        )
        VALUES (?, 'live_task', 'python', 'running', 1, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
        """,
        [context.run_id, os.getpid()],
    )

    with pytest.raises(RuntimeError, match="still has live running task"):
        prepare_run(
            command="run-live",
            graph="default",
            scope={"season": "ignored"},
            run_id=context.run_id,
        )


def test_retry_failed_only_reruns_failed_or_interrupted_tasks(tmp_db):
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})

    with pytest.raises(RuntimeError, match="boom"):
        run_steps(
            context,
            [
                TaskSpec("failed_task", "python", lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
                TaskSpec("missing_task", "python", lambda: {}),
            ],
            retries=0,
            retry_delay_seconds=0,
        )

    calls, steps = _counting_steps(["failed_task", "missing_task"])
    retry_context = prepare_run(
        command="run-live",
        graph="default",
        scope={"season": "ignored"},
        run_id=context.run_id,
        retry_failed=True,
    )
    result = run_steps(
        retry_context,
        steps,
        retries=0,
        retry_delay_seconds=0,
    )

    assert calls == {"failed_task": 1, "missing_task": 0}
    assert result["status"] == "failed"
    assert result["missing_tasks"] == ["missing_task"]


def test_retry_failed_reruns_downstream_success_after_rerun(tmp_db):
    db = tmp_db
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})
    db.insert_rows(
        "ops",
        "task_runs",
        [
            {
                "run_id": context.run_id,
                "task_name": "upstream_failed",
                "task_type": "gold",
                "status": "failed",
                "attempts": 1,
                "max_attempts": 1,
                "started_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
            {
                "run_id": context.run_id,
                "task_name": "downstream_success",
                "task_type": "gold",
                "status": "success",
                "attempts": 1,
                "max_attempts": 1,
                "started_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
            {
                "run_id": context.run_id,
                "task_name": "later_success",
                "task_type": "gold",
                "status": "success",
                "attempts": 1,
                "max_attempts": 1,
                "started_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
        ],
    )
    calls, steps = _counting_steps(
        ["upstream_failed", "downstream_success", "later_success"], "gold"
    )
    retry_context = prepare_run(
        command="run-live",
        graph="default",
        scope={"season": "ignored"},
        run_id=context.run_id,
        retry_failed=True,
    )

    result = run_steps(
        retry_context,
        steps,
        retries=0,
        retry_delay_seconds=0,
    )

    detail = get_run_detail(context.run_id)
    attempts = {task["task_name"]: task["attempts"] for task in detail["tasks"]}
    assert result["status"] == "success"
    assert calls == {"upstream_failed": 1, "downstream_success": 1, "later_success": 1}
    assert attempts == {"upstream_failed": 2, "downstream_success": 2, "later_success": 2}


def test_failed_pipeline_run_records_success_count(tmp_db):
    context = prepare_run(command="run-live", graph="default", scope={"season": "2025-26"})

    with pytest.raises(RuntimeError, match="boom"):
        run_steps(
            context,
            [
                TaskSpec("successful_task", "python", lambda: {"ok": True}),
                TaskSpec("failed_task", "python", lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
            ],
            retries=0,
            retry_delay_seconds=0,
        )

    detail = get_run_detail(context.run_id)

    assert detail["status"] == "failed"
    assert detail["task_count"] == 2
    assert detail["success_count"] == 1
    assert detail["failed_count"] == 1

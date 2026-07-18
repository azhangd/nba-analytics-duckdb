"""Orchestrator-neutral execution helpers for registered pipeline tasks."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from nba_duckdb import config, db, registry
from nba_duckdb.dbt_runner import run_dbt_command


def _run_python_task(
    task: registry.TaskDef,
    *,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    if task.name == "load_synthetic_fixtures":
        from nba_duckdb.tasks.bronze import load_synthetic_fixtures

        db.init_schema()
        return load_synthetic_fixtures.run(
            source_name=source_name or os.environ.get("NBA_DUCKDB_SOURCE", "fixtures"),
            fixtures_dir=fixtures_dir or config.fixtures_dir(None),
        )

    module = importlib.import_module(task.module_path)
    result = module.run(**scope)
    return result if isinstance(result, dict) else {"result": result}


def _run_dbt_task(task: registry.TaskDef, *, scope: dict[str, Any]) -> dict[str, Any]:
    if not task.dbt_selector:
        raise ValueError(f"Task {task.name} does not declare a dbt selector")

    args = ["build", "--select", task.dbt_selector]
    if task.dbt_exclude:
        args.extend(["--exclude", task.dbt_exclude])
    if scope.get("full_refresh"):
        args.append("--full-refresh")

    run_dbt_command(args)
    return {
        "status": "success",
        "dbt_selector": task.dbt_selector,
        "dbt_exclude": task.dbt_exclude,
        "models_built": len(task.dbt_models),
    }


def run_task(
    task: registry.TaskDef,
    *,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Execute one registry task without depending on a workflow framework."""

    if task.dbt_selector:
        return _run_dbt_task(task, scope=scope)
    return _run_python_task(
        task,
        scope=scope,
        fixtures_dir=fixtures_dir,
        source_name=source_name,
    )

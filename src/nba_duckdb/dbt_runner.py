"""Small dbt command wrapper used by CLI smoke and live runs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from nba_duckdb import db
from nba_duckdb.dependencies import MissingRequiredDependencyError


def _database_path_from_url(raw: str) -> str:
    if raw.startswith("duckdb:///"):
        return raw.removeprefix("duckdb:///")
    if raw.startswith("duckdb://"):
        return raw.removeprefix("duckdb://")
    return raw


def dbt_project_dir() -> Path:
    editable_root = Path(__file__).resolve().parents[2]
    if (editable_root / "dbt_project.yml").exists():
        return editable_root

    packaged_root = Path(__file__).resolve().parent
    if (packaged_root / "dbt_project.yml").exists():
        return packaged_root

    raise FileNotFoundError(
        "Could not find dbt_project.yml. Reinstall with the full extra or run from "
        "the repository root."
    )


def _dbt_executable() -> str:
    executable = shutil.which("dbt")
    if executable:
        return executable
    raise MissingRequiredDependencyError(
        missing_modules=("dbt",),
        missing_packages=("dbt-core",),
        hint="Install the project dependencies, then rerun the command.",
        install_command="uv sync --extra dev",
        pip_install_command='python -m pip install -e ".[dev]"',
    )


def run_dbt_command(args: list[str], *, project_dir: Path | None = None) -> dict[str, Any]:
    project_root = project_dir or dbt_project_dir()
    profiles_dir = project_root / "dbt"
    env = os.environ.copy()
    env["NBA_DUCKDB_PATH"] = _database_path_from_url(db.get_database_url())

    command = [
        _dbt_executable(),
        *args,
        "--project-dir",
        str(project_root),
        "--profiles-dir",
        str(profiles_dir),
        "--target-path",
        str(project_root / "dbt" / "target"),
    ]
    completed = subprocess.run(
        command,
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "dbt command failed: "
            + " ".join(command)
            + "\n\nstdout:\n"
            + completed.stdout
            + "\n\nstderr:\n"
            + completed.stderr
        )
    return {
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_model(
    *,
    model: str,
    full_refresh: bool = False,
    **_: object,
) -> dict[str, Any]:
    args = ["build", "--select", model]
    if full_refresh:
        args.append("--full-refresh")
    run_dbt_command(args)
    schema = "silver" if model.startswith(("dim_", "fct_")) else "gold"
    rows = db.count_rows(schema, model)
    return {
        "dbt_model": model,
        "rows_written": rows,
        "status": "success",
    }

"""Command-line entry points for local pipeline runs."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from nba_duckdb import config, registry
from nba_duckdb.db import DuckDBLockTimeoutError
from nba_duckdb.dependencies import (
    MissingOptionalDependencyError,
    MissingRequiredDependencyError,
    require_optional_groups,
)
from nba_duckdb.exceptions import PipelineStateNotInitializedError
from nba_duckdb.fixtures.generate_synthetic_fixtures import (
    SEASON as SYNTHETIC_SEASON,
)
from nba_duckdb.fixtures.generate_synthetic_fixtures import (
    generate_fixtures as generate,
)
from nba_duckdb.ingestion_state import normalize_source, summarize_sources
from nba_duckdb.orchestration import (
    TaskSpec,
    get_run_detail,
    list_pipeline_runs,
    prepare_run,
    run_steps,
)

DEFAULT_GRAPH = registry.DEFAULT_GRAPH
QUICK_GRAPH = registry.QUICK_GRAPH

BACKFILL_SOURCES = {
    "pbp": ("play-by-play", "nba_duckdb.tasks.bronze.ingest_play_by_play", True),
    "play-by-play": ("play-by-play", "nba_duckdb.tasks.bronze.ingest_play_by_play", True),
    "shot-charts": ("shot-charts", "nba_duckdb.tasks.bronze.ingest_shot_charts", False),
    "shots": ("shot-charts", "nba_duckdb.tasks.bronze.ingest_shot_charts", False),
}


class SyntheticDataInLiveWarehouseError(RuntimeError):
    """Raised when a live run points at a warehouse that contains smoke fixtures."""


class SmokeWarehouseIsolationError(RuntimeError):
    """Raised when run-smoke would write to a non-smoke warehouse by default."""


WAREHOUSE_ENV_KEYS = ("NBA_DUCKDB_PATH", "NBA_DUCKDB_DATABASE_URL")
UV_FULL_INSTALL_COMMAND = "uv sync --extra dev --extra full"
UV_LIVE_INSTALL_COMMAND = "uv sync --extra dev --extra live"
PIP_FULL_INSTALL_COMMAND = 'python -m pip install -e ".[dev,full]"'
PIP_LIVE_INSTALL_COMMAND = 'python -m pip install -e ".[dev,live]"'
SMOKE_FULL_INSTALL_HINT = (
    f"Install full pipeline dependencies with `{UV_FULL_INSTALL_COMMAND}`. "
    "For a lighter local check, run `uv run nba-duckdb run-smoke --quick`."
)
LIVE_FULL_INSTALL_HINT = (
    f"Install the full live and ML dependency set with `{UV_FULL_INSTALL_COMMAND}`."
)
LIVE_INSTALL_HINT = (
    f"Install live collection dependencies with `{UV_LIVE_INSTALL_COMMAND}`, "
    f"or install everything with `{UV_FULL_INSTALL_COMMAND}`."
)


def _duckdb_path_from_url(raw: str) -> Path:
    if raw.startswith("duckdb:///"):
        raw = raw.removeprefix("duckdb:///")
    elif raw.startswith("duckdb://"):
        raw = raw.removeprefix("duckdb://")
    return Path(raw)


def _normalized_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _warehouse_is_explicit() -> bool:
    # Smoke runs may load `.env` before reaching this check in future CLI changes.
    # Only shell-provided values are explicit overrides; values inserted from `.env`
    # are background defaults and should not redirect smoke away from its isolated
    # full or quick smoke warehouse.
    return any(
        os.environ.get(key) and not config.env_value_loaded_from_file(key)
        for key in WAREHOUSE_ENV_KEYS
    )


def _default_smoke_warehouse_path(*, quick: bool) -> Path:
    return config.quick_smoke_warehouse_path() if quick else config.smoke_warehouse_path()


def _use_smoke_warehouse_unless_explicit(*, quick: bool = False) -> dict[str, str | None] | None:
    if _warehouse_is_explicit():
        return None
    previous = {key: os.environ.get(key) for key in WAREHOUSE_ENV_KEYS}
    os.environ["NBA_DUCKDB_PATH"] = str(_default_smoke_warehouse_path(quick=quick))
    os.environ["NBA_DUCKDB_DATABASE_URL"] = ""
    config.get_settings.cache_clear()
    return previous


def _restore_default_warehouse_env(previous_env: dict[str, str | None] | None) -> None:
    if previous_env is None:
        return
    for key, value in previous_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    config.get_settings.cache_clear()


def _assert_smoke_warehouse_resolution(*, quick: bool = False) -> None:
    from nba_duckdb import db

    expected = _normalized_path(_default_smoke_warehouse_path(quick=quick))
    actual = _normalized_path(_duckdb_path_from_url(db.get_database_url()))
    if actual == expected:
        return
    raise SmokeWarehouseIsolationError(
        "run-smoke resolved to a non-smoke warehouse "
        f"({actual}) even though no explicit warehouse override was exported. "
        f"Expected {expected}."
    )


def _source_name(value: str | None = None) -> str:
    return value or os.environ.get("NBA_DUCKDB_SOURCE", "fixtures")


def _run_module(module_path: str, **kwargs: Any) -> dict[str, Any]:
    module = importlib.import_module(module_path)
    result = module.run(**kwargs)
    return result if isinstance(result, dict) else {"result": result}


def _python_task(
    module_path: str,
    scope: dict[str, Any],
    task_type: str = "python",
    required: bool = True,
) -> TaskSpec:
    task_name = module_path.rsplit(".", 1)[-1]
    task_scope = dict(scope)
    return TaskSpec(
        name=task_name,
        task_type=task_type,
        action=lambda module_path=module_path, task_scope=task_scope: _run_module(
            module_path, **task_scope
        ),
        required=required,
    )


def _dagster_pipeline_task(
    *,
    graph: str,
    mode: str,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
    offline_smoke: bool = False,
    job_name: str,
) -> TaskSpec:
    task_scope = dict(scope)

    def action() -> dict[str, Any]:
        from nba_duckdb.definitions import execute_dagster_job

        return execute_dagster_job(
            graph=graph,
            mode=mode,
            scope=task_scope,
            fixtures_dir=fixtures_dir,
            source_name=source_name,
            offline_smoke=offline_smoke,
            job_name=job_name,
        )

    return TaskSpec(
        name=job_name,
        task_type="dagster",
        action=action,
        required=True,
    )


def _offline_smoke_steps(
    *,
    graph: str,
    scope: dict[str, Any],
    fixtures_dir: Path,
    source_name: str,
) -> list[TaskSpec]:
    return [
        _dagster_pipeline_task(
            graph=graph,
            mode=registry.FIXTURE_MODE,
            scope=scope,
            fixtures_dir=fixtures_dir,
            source_name=source_name,
            offline_smoke=True,
            job_name="smoke_job" if graph == DEFAULT_GRAPH else "smoke_quick_job",
        )
    ]


def _live_steps(graph: str, scope: dict[str, Any]) -> list[TaskSpec]:
    return [
        _dagster_pipeline_task(
            graph=graph,
            mode=registry.LIVE_MODE,
            scope=scope,
            job_name="live_job" if graph == DEFAULT_GRAPH else "live_quick_job",
        )
    ]


def _task_scope_from_run_scope(scope: dict[str, Any]) -> dict[str, Any]:
    season = scope.get("season")
    seasons = scope.get("seasons") or ([season] if season else None)
    return {
        "season": season,
        "seasons": seasons,
        "game_ids": scope.get("game_ids"),
        "full_refresh": bool(scope.get("full_refresh", False)),
        "start_date": scope.get("start_date"),
        "end_date": scope.get("end_date"),
    }


def init_db(_: argparse.Namespace) -> dict[str, Any]:
    from nba_duckdb import db

    db.init_schema()
    return {"schema_initialized": True}


def generate_test_fixtures(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = config.fixtures_dir(args.fixtures_dir)
    files = generate(output_dir)
    return {"fixtures_dir": str(output_dir), "files": [str(path) for path in files]}


def _raise_if_synthetic_rows_present() -> None:
    from nba_duckdb import db

    database_path = _duckdb_path_from_url(db.get_database_url())
    if not database_path.exists():
        raise PipelineStateNotInitializedError(
            "Pipeline tables not found; run `nba-duckdb init` first"
        )

    table_rows = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM information_schema.tables
        WHERE table_schema = 'bronze'
          AND table_name = 'schedule'
        """,
        read_only=True,
    )
    if not table_rows or int(table_rows[0]["row_count"] or 0) == 0:
        raise PipelineStateNotInitializedError(
            "Pipeline tables not found; run `nba-duckdb init` first"
        )

    column_rows = db.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema IN ('bronze', 'silver', 'gold')
          AND column_name IN ('season', 'game_id')
        ORDER BY table_schema, table_name, column_name
        """,
        read_only=True,
    )
    table_columns: dict[tuple[str, str], set[str]] = {}
    for row in column_rows:
        table_key = (str(row["table_schema"]), str(row["table_name"]))
        table_columns.setdefault(table_key, set()).add(str(row["column_name"]))

    polluted_tables = []
    for (schema, table), columns in table_columns.items():
        predicates = []
        params = []
        if "season" in columns:
            predicates.append(f"{db._quote_ident('season')} = %s")
            params.append(SYNTHETIC_SEASON)
        if "game_id" in columns:
            predicates.append(f"{db._quote_ident('game_id')} LIKE '002SYN%'")
        if not predicates:
            continue
        row = db.execute(
            f"""
            SELECT COUNT(*) AS row_count
            FROM {db._quote_ident(schema)}.{db._quote_ident(table)}
            WHERE {" OR ".join(predicates)}
            """,
            params,
            read_only=True,
        )[0]
        if int(row["row_count"] or 0):
            polluted_tables.append(f"{schema}.{table}")

    if not polluted_tables:
        return

    raise SyntheticDataInLiveWarehouseError(
        "This warehouse contains synthetic smoke fixture rows "
        f"(season {SYNTHETIC_SEASON} / 002SYN game IDs) in "
        f"{', '.join(polluted_tables)}. Smoke runs default to "
        f"{config.smoke_warehouse_path()}; use a clean live warehouse for run-live, "
        "or set NBA_DUCKDB_PATH to another DuckDB file."
    )


def run_offline_smoke(args: argparse.Namespace) -> dict[str, Any]:
    graph = QUICK_GRAPH if getattr(args, "quick", False) else DEFAULT_GRAPH
    previous_warehouse_env = _use_smoke_warehouse_unless_explicit(
        quick=graph == QUICK_GRAPH
    )
    try:
        if previous_warehouse_env is not None:
            _assert_smoke_warehouse_resolution(quick=graph == QUICK_GRAPH)

        if graph == DEFAULT_GRAPH:
            require_optional_groups(
                "ml",
                hint=SMOKE_FULL_INSTALL_HINT,
                install_command=UV_FULL_INSTALL_COMMAND,
                pip_install_command=PIP_FULL_INSTALL_COMMAND,
                quick_command="uv run nba-duckdb run-smoke --quick",
            )

        from nba_duckdb import db

        fixtures_dir = config.fixtures_dir(args.fixtures_dir)
        if args.init_schema:
            db.init_schema()

        run_scope = {
            "season": SYNTHETIC_SEASON,
            "seasons": [SYNTHETIC_SEASON],
            "fixtures_dir": str(fixtures_dir),
            "source": _source_name(args.source),
            "warehouse": db.get_database_url(),
        }
        context = prepare_run(
            command="run-smoke",
            graph=graph,
            scope=run_scope,
            run_id=args.run_id,
            resume_latest=args.resume_latest,
            retry_failed=args.retry_failed,
        )
        context_scope = _task_scope_from_run_scope(context.scope)
        previous_offline_smoke = os.environ.get("NBA_DUCKDB_OFFLINE_SMOKE")
        os.environ["NBA_DUCKDB_OFFLINE_SMOKE"] = "1"
        try:
            steps = _offline_smoke_steps(
                graph=context.graph,
                scope=context_scope,
                fixtures_dir=Path(context.scope.get("fixtures_dir", fixtures_dir)),
                source_name=str(context.scope.get("source") or _source_name(args.source)),
            )
            return run_steps(
                context,
                steps,
                retries=args.retries,
                retry_delay_seconds=args.retry_delay_seconds,
            )
        finally:
            if previous_offline_smoke is None:
                os.environ.pop("NBA_DUCKDB_OFFLINE_SMOKE", None)
            else:
                os.environ["NBA_DUCKDB_OFFLINE_SMOKE"] = previous_offline_smoke
    finally:
        _restore_default_warehouse_env(previous_warehouse_env)


def run_live_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    graph = QUICK_GRAPH if args.quick else DEFAULT_GRAPH
    if graph == DEFAULT_GRAPH:
        require_optional_groups(
            "live",
            "ml",
            hint=LIVE_FULL_INSTALL_HINT,
            install_command=UV_FULL_INSTALL_COMMAND,
            pip_install_command=PIP_FULL_INSTALL_COMMAND,
        )
    else:
        require_optional_groups(
            "live",
            hint=LIVE_INSTALL_HINT,
            install_command=UV_LIVE_INSTALL_COMMAND,
            pip_install_command=PIP_LIVE_INSTALL_COMMAND,
        )

    from nba_duckdb import db

    if args.init_schema:
        db.init_schema()
    _raise_if_synthetic_rows_present()

    seasons = [args.season] if args.season else None
    run_scope: dict[str, Any] = {
        "season": args.season,
        "seasons": seasons,
        "team_ids": args.team_ids,
        "game_ids": args.game_ids,
        "full_refresh": args.full_refresh,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }
    context = prepare_run(
        command="run-live",
        graph=graph,
        scope=run_scope,
        run_id=args.run_id,
        resume_latest=args.resume_latest,
        retry_failed=args.retry_failed,
    )

    if context.scope.get("team_ids"):
        os.environ["NBA_DUCKDB_TEAM_IDS"] = ",".join(
            str(team_id) for team_id in context.scope["team_ids"]
        )

    steps = _live_steps(context.graph, _task_scope_from_run_scope(context.scope))
    return run_steps(
        context,
        steps,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay_seconds,
    )


def _resolve_backfill_source(source: str) -> tuple[str, str, bool]:
    normalized = normalize_source(source)
    if normalized not in BACKFILL_SOURCES:
        valid = ", ".join(sorted(BACKFILL_SOURCES))
        raise ValueError(f"Unsupported source {source!r}. Choose one of: {valid}")
    return BACKFILL_SOURCES[normalized]


def backfill_source(args: argparse.Namespace) -> dict[str, Any]:
    require_optional_groups(
        "live",
        hint=LIVE_INSTALL_HINT,
        install_command=UV_LIVE_INSTALL_COMMAND,
        pip_install_command=PIP_LIVE_INSTALL_COMMAND,
    )

    from nba_duckdb import db

    if args.init_schema:
        db.init_schema()

    source, module_path, required = _resolve_backfill_source(args.source)
    run_scope: dict[str, Any] = {
        "source": source,
        "season": args.season,
        "seasons": [args.season],
        "team_ids": args.team_ids,
        "game_ids": args.game_ids,
        "full_refresh": False,
        "start_date": None,
        "end_date": None,
    }
    context = prepare_run(
        command="backfill-source",
        graph=source,
        scope=run_scope,
        run_id=args.run_id,
        resume_latest=args.resume_latest,
        retry_failed=args.retry_failed,
    )

    if context.scope.get("team_ids"):
        os.environ["NBA_DUCKDB_TEAM_IDS"] = ",".join(
            str(team_id) for team_id in context.scope["team_ids"]
        )

    task_scope = _task_scope_from_run_scope(context.scope)
    steps = [
        _python_task(
            module_path,
            task_scope,
            task_type="bronze",
            required=required,
        )
    ]
    return run_steps(
        context,
        steps,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay_seconds,
    )


def ingestion_status(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "ingestion_items": summarize_sources(
            season=args.season,
            source=args.source,
            read_only=True,
        )
    }


def check_quality(_: argparse.Namespace) -> dict[str, Any]:
    from nba_duckdb import quality

    return quality.run_checks()


def list_runs(args: argparse.Namespace) -> dict[str, Any]:
    return {"runs": list_pipeline_runs(limit=args.limit)}


def show_run(args: argparse.Namespace) -> dict[str, Any]:
    return get_run_detail(args.run_id)


def list_datasets(_: argparse.Namespace) -> dict[str, Any]:
    return {"datasets": registry.dataset_rows()}


def graph_datasets(args: argparse.Namespace) -> dict[str, Any]:
    graph = QUICK_GRAPH if args.quick else DEFAULT_GRAPH
    mode = args.mode
    if args.format == "html":
        html = registry.dataset_graph_html(graph=graph, mode=mode)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html)
            return {
                "status": "ok",
                "format": "html",
                "graph": graph,
                "mode": mode,
                "output": str(output_path),
            }
        return {"format": "html", "graph": graph, "mode": mode, "html": html}
    return registry.dataset_graph(graph=graph, mode=mode)


def _add_runner_args(
    parser: argparse.ArgumentParser,
    *,
    default_retries: int,
    default_retry_delay_seconds: float,
) -> None:
    parser.add_argument("--run-id")
    parser.add_argument("--resume-latest", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--retries", type=int, default=default_retries)
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=default_retry_delay_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nba-duckdb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(func=init_db)

    fixtures_parser = subparsers.add_parser(
        "generate-test-fixtures",
        help="Generate deterministic fixtures for tests and offline smoke checks.",
    )
    fixtures_parser.add_argument("--fixtures-dir")
    fixtures_parser.set_defaults(func=generate_test_fixtures)

    run_parser = subparsers.add_parser(
        "run-smoke",
        help="Run the offline smoke pipeline with deterministic test fixtures.",
    )
    run_parser.add_argument("--fixtures-dir")
    run_parser.add_argument("--source", default=None)
    run_parser.add_argument(
        "--quick",
        action="store_true",
        help="Run the small core graph for fast local iteration; skips the full-warehouse quality gate.",
    )
    run_parser.add_argument("--no-init-schema", action="store_false", dest="init_schema")
    _add_runner_args(run_parser, default_retries=0, default_retry_delay_seconds=0.0)
    run_parser.set_defaults(func=run_offline_smoke, init_schema=True)

    live_parser = subparsers.add_parser(
        "run-live",
        help="Run the collector-backed pipeline with retry and resume support.",
    )
    live_parser.add_argument("--season")
    live_parser.add_argument("--team-ids", nargs="+")
    live_parser.add_argument("--game-ids", nargs="+")
    live_parser.add_argument("--start-date")
    live_parser.add_argument("--end-date")
    live_parser.add_argument("--full-refresh", action="store_true")
    live_parser.add_argument("--no-init-schema", action="store_false", dest="init_schema")
    live_parser.add_argument(
        "--quick",
        action="store_true",
        help="Run the small core graph for fast local iteration; skips the full-warehouse quality gate.",
    )
    _add_runner_args(live_parser, default_retries=2, default_retry_delay_seconds=120.0)
    live_parser.set_defaults(func=run_live_pipeline, init_schema=True)

    backfill_parser = subparsers.add_parser(
        "backfill-source",
        help="Resume one live source using item-level ingestion state.",
    )
    backfill_parser.add_argument("source")
    backfill_parser.add_argument("--season", required=True)
    backfill_parser.add_argument("--team-ids", nargs="+")
    backfill_parser.add_argument("--game-ids", nargs="+")
    backfill_parser.add_argument("--no-init-schema", action="store_false", dest="init_schema")
    _add_runner_args(backfill_parser, default_retries=2, default_retry_delay_seconds=120.0)
    backfill_parser.set_defaults(func=backfill_source, init_schema=True)

    ingestion_status_parser = subparsers.add_parser(
        "ingestion-status",
        help="Show item-level live ingestion progress by source and season.",
    )
    ingestion_status_parser.add_argument("--season")
    ingestion_status_parser.add_argument("--source")
    ingestion_status_parser.set_defaults(func=ingestion_status)

    datasets_parser = subparsers.add_parser(
        "datasets",
        help="Inspect declared pipeline datasets and lineage.",
    )
    datasets_subparsers = datasets_parser.add_subparsers(
        dest="datasets_command",
        required=True,
    )
    datasets_list_parser = datasets_subparsers.add_parser("list")
    datasets_list_parser.set_defaults(func=list_datasets)
    datasets_graph_parser = datasets_subparsers.add_parser(
        "graph",
        help="Emit dataset lineage from asset metadata and dbt refs.",
    )
    datasets_graph_parser.add_argument("--quick", action="store_true")
    datasets_graph_parser.add_argument(
        "--mode",
        choices=[registry.LIVE_MODE, registry.FIXTURE_MODE],
        default=registry.LIVE_MODE,
    )
    datasets_graph_parser.add_argument(
        "--format",
        choices=["json", "html"],
        default="json",
    )
    datasets_graph_parser.add_argument("--output")
    datasets_graph_parser.set_defaults(func=graph_datasets)

    quality_parser = subparsers.add_parser("quality")
    quality_parser.set_defaults(func=check_quality)

    runs_parser = subparsers.add_parser("runs", help="Inspect local pipeline run history.")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list_parser = runs_subparsers.add_parser("list")
    runs_list_parser.add_argument("--limit", type=int, default=20)
    runs_list_parser.set_defaults(func=list_runs)
    runs_show_parser = runs_subparsers.add_parser("show")
    runs_show_parser.add_argument("run_id")
    runs_show_parser.set_defaults(func=show_run)

    return parser


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("NBA_DUCKDB_LOG_LEVEL", "WARNING").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.func(args)
    except PipelineStateNotInitializedError as exc:
        print(
            json.dumps(
                {
                    "status": "not_initialized",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except DuckDBLockTimeoutError as exc:
        print(
            json.dumps(
                {
                    "status": "warehouse_busy",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    except SyntheticDataInLiveWarehouseError as exc:
        print(
            json.dumps(
                {
                    "status": "synthetic_data_in_live_warehouse",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except SmokeWarehouseIsolationError as exc:
        print(
            json.dumps(
                {
                    "status": "smoke_warehouse_isolation_error",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except MissingOptionalDependencyError as exc:
        payload = {
            "status": "missing_optional_dependency",
            "error": str(exc),
            "groups": list(exc.groups),
            "missing_modules": list(exc.missing_modules),
            "missing_packages": list(exc.missing_packages),
            "install_command": exc.install_command,
            "pip_install_command": exc.pip_install_command,
        }
        if exc.quick_command:
            payload["quick_command"] = exc.quick_command
        print(
            json.dumps(payload, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except MissingRequiredDependencyError as exc:
        print(
            json.dumps(
                {
                    "status": "missing_dependency",
                    "error": str(exc),
                    "missing_modules": list(exc.missing_modules),
                    "missing_packages": list(exc.missing_packages),
                    "install_command": exc.install_command,
                    "pip_install_command": exc.pip_install_command,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

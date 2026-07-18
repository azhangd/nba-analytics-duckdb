"""Airflow 3 DAG factory for the NBA DuckDB warehouse."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pendulum
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG, Asset, Param, get_current_context
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import ExecutionMode, InvocationMode, LoadMode, TestBehavior

from nba_duckdb import config, db, quality, registry
from nba_duckdb.competitions import (
    COMPETITIONS,
    NBA,
    SUMMER_LEAGUE_SLUGS,
)
from nba_duckdb.dbt_models import DBT_MODEL_DATASETS
from nba_duckdb.dbt_runner import dbt_project_dir
from nba_duckdb.defaults import get_default_season
from nba_duckdb.exceptions import LiveEndpointUnavailableError
from nba_duckdb.fixtures.generate_synthetic_fixtures import SEASON as SYNTHETIC_SEASON
from nba_duckdb.task_runner import run_task
from nba_duckdb.warehouse_guard import assert_no_synthetic_rows

PIPELINE_POOL = "nba_pipeline"
PIPELINE_OWNER = "nba-analytics"
PROJECT_ROOT = config.get_settings().project_root
DBT_PROJECT_PATH = dbt_project_dir()
DBT_MANIFEST_PATH = DBT_PROJECT_PATH / "dbt" / "target" / "manifest.json"
DBT_PROFILES_PATH = DBT_PROJECT_PATH / "dbt" / "profiles.yml"
BACKFILL_TASKS = {
    "play-by-play": "ingest_play_by_play",
    "shot-charts": "ingest_shot_charts",
}


def _project_path(path: Path) -> Path:
    return path.expanduser() if path.is_absolute() else PROJECT_ROOT / path


def _warehouse_path(*, mode: str, quick: bool) -> Path:
    if mode == registry.FIXTURE_MODE:
        configured = (
            config.quick_smoke_warehouse_path()
            if quick
            else config.smoke_warehouse_path()
        )
    else:
        configured = config.get_settings().duckdb_path
    return _project_path(configured).resolve(strict=False)


def _warehouse_env(*, mode: str, quick: bool) -> dict[str, str]:
    settings = config.get_settings()
    env = {
        "NBA_DUCKDB_PATH": str(_warehouse_path(mode=mode, quick=quick)),
        "NBA_DUCKDB_DATABASE_URL": "",
        "NBA_DUCKDB_RAW_ROOT": str(_project_path(settings.raw_root).resolve(strict=False)),
        "NBA_DUCKDB_ARTIFACT_ROOT": str(
            _project_path(settings.artifact_root).resolve(strict=False)
        ),
    }
    if mode == registry.FIXTURE_MODE:
        env["NBA_DUCKDB_OFFLINE_SMOKE"] = "1"
        env["NBA_DUCKDB_FIXTURES_DIR"] = str(
            _project_path(config.fixtures_dir(None)).resolve(strict=False)
        )
    return env


def _cosmos_env(*, mode: str, quick: bool) -> dict[str, str]:
    """Return only dbt runtime values that Cosmos needs to template."""

    return {
        "NBA_DUCKDB_PATH": str(_warehouse_path(mode=mode, quick=quick)),
    }


@contextmanager
def _configured_task_environment(*, mode: str, quick: bool, team_ids: list[Any]):
    overrides = _warehouse_env(mode=mode, quick=quick)
    if team_ids:
        overrides["NBA_DUCKDB_TEAM_IDS"] = ",".join(str(value) for value in team_ids)

    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    config.get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.get_settings.cache_clear()


def _params() -> dict[str, Any]:
    return dict(get_current_context()["params"])


def _scope_from_params(*, mode: str, graph: str) -> dict[str, Any]:
    params = _params()
    season = SYNTHETIC_SEASON if mode == registry.FIXTURE_MODE else params["season"]
    competitions = (
        list(params.get("competitions") or SUMMER_LEAGUE_SLUGS)
        if graph == registry.SUMMER_LEAGUE_GRAPH
        else [NBA.slug]
    )
    return {
        "season": season,
        "seasons": [season],
        "game_ids": params.get("game_ids") or None,
        "competitions": competitions,
        "full_refresh": bool(params.get("full_refresh", False)),
        "start_date": params.get("start_date"),
        "end_date": params.get("end_date"),
    }


def _json_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is None or type(scalar) in {str, int, float, bool}:
            return scalar
    return None


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"status": str(result.get("status", "success"))}
    for key, value in result.items():
        scalar = _json_scalar(value)
        if scalar is not None:
            summary[key] = scalar
        elif isinstance(value, list | tuple | set | dict):
            summary[f"{key}_count"] = len(value)
    return summary


def initialize_warehouse(*, mode: str, quick: bool) -> dict[str, Any]:
    """Initialize schemas and enforce the live/fixture warehouse boundary."""

    params = _params()
    with _configured_task_environment(
        mode=mode,
        quick=quick,
        team_ids=params.get("team_ids") or [],
    ):
        db.init_schema()
        if mode == registry.LIVE_MODE:
            assert_no_synthetic_rows()
        return {"status": "success", "warehouse": db.get_database_url()}


def execute_registered_task(
    *,
    task_name: str,
    mode: str,
    graph: str,
    quick: bool,
) -> dict[str, Any]:
    """Execute one registry task as one Airflow task instance."""

    task = registry.task_def_named(task_name)
    params = _params()
    with _configured_task_environment(
        mode=mode,
        quick=quick,
        team_ids=params.get("team_ids") or [],
    ):
        try:
            result = run_task(
                task,
                scope=_scope_from_params(mode=mode, graph=graph),
                fixtures_dir=_project_path(config.fixtures_dir(None)).resolve(strict=False),
                source_name="fixtures" if mode == registry.FIXTURE_MODE else None,
            )
        except LiveEndpointUnavailableError as exc:
            if task.required:
                raise
            return {"status": "degraded", "reason": str(exc)}
    return _result_summary(result)


def execute_quality_checks(*, mode: str, quick: bool) -> dict[str, Any]:
    """Run the final warehouse contract checks and return compact XCom metadata."""

    params = _params()
    with _configured_task_environment(
        mode=mode,
        quick=quick,
        team_ids=params.get("team_ids") or [],
    ):
        result = quality.run_checks()
    return {
        "status": "success",
        "tables_checked": len(result.get("table_counts", {})),
        "integrity_checks": len(result.get("integrity_counts", {})),
        "seasons_checked": len(result.get("coverage_counts", [])),
    }


def execute_source_backfill() -> dict[str, Any]:
    """Run one item-state-aware source backfill selected by DAG parameters."""

    params = _params()
    task = registry.task_def_named(BACKFILL_TASKS[params["source"]])
    with _configured_task_environment(
        mode=registry.LIVE_MODE,
        quick=False,
        team_ids=params.get("team_ids") or [],
    ):
        scope = _scope_from_params(
            mode=registry.LIVE_MODE,
            graph=registry.DEFAULT_GRAPH,
        )
        scope["competitions"] = [params["competition"]]
        result = run_task(task, scope=scope)
    return _result_summary(result)


def _asset(dataset: str) -> Asset:
    layer, table = dataset.split(".", 1)
    return Asset(
        name=dataset,
        uri=f"duckdb://nba-warehouse/{layer}/{table}",
        group=layer,
    )


def _pipeline_params(*, mode: str, graph: str) -> dict[str, Param]:
    params = {
        "full_refresh": Param(
            False,
            type="boolean",
            description="Rebuild incremental dbt models from scratch.",
        ),
    }
    if mode == registry.FIXTURE_MODE:
        return params
    params.update({
        "season": Param(
            get_default_season(),
            type="string",
            pattern=r"^\d{4}-\d{2}$",
            description="NBA season in YYYY-YY form.",
        ),
        "team_ids": Param(
            [],
            type="array",
            items={"type": "integer"},
            description="Optional NBA team IDs. Empty means the deployment default.",
        ),
        "game_ids": Param(
            [],
            type="array",
            items={"type": "string"},
            description="Optional explicit game IDs for a scoped refresh.",
        ),
    })
    if graph == registry.SUMMER_LEAGUE_GRAPH:
        params["competitions"] = Param(
            list(SUMMER_LEAGUE_SLUGS),
            type="array",
            items={"type": "string", "enum": list(SUMMER_LEAGUE_SLUGS)},
            minItems=1,
            uniqueItems=True,
            description="Official Summer League competitions to ingest.",
        )
    else:
        params.update({
            "start_date": Param(
                None,
                type=["null", "string"],
                format="date",
                description="Optional inclusive start date.",
            ),
            "end_date": Param(
                None,
                type=["null", "string"],
                format="date",
                description="Optional inclusive end date.",
            ),
        })
    return params


def _cosmos_group(
    task: registry.TaskDef,
    *,
    mode: str,
    quick: bool,
    retries: int,
) -> DbtTaskGroup:
    if not DBT_MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"dbt manifest not found at {DBT_MANIFEST_PATH}; run `make dbt-parse` "
            "before Airflow parses this DAG"
        )
    if not task.dbt_selector:
        raise ValueError(f"Task {task.name} has no dbt selector")

    group_id = {
        "dbt_build_feature_matrices": "dbt_feature_matrices",
        "dbt_build_summer_league": "dbt_summer_league",
    }.get(task.name, "dbt_warehouse")
    operator_args = {
        "full_refresh": "{{ params.full_refresh }}",
        "pool": PIPELINE_POOL,
        "retries": retries,
        "retry_delay": timedelta(seconds=120),
    }
    return DbtTaskGroup(
        group_id=group_id,
        project_config=ProjectConfig(
            dbt_project_path=DBT_PROJECT_PATH,
            manifest_path=DBT_MANIFEST_PATH,
            install_dbt_deps=False,
            models_relative_path="dbt/models",
            env_vars=_cosmos_env(mode=mode, quick=quick),
            project_name="nba_duckdb",
        ),
        profile_config=ProfileConfig(
            profile_name="nba_duckdb",
            target_name="dev",
            profiles_yml_filepath=DBT_PROFILES_PATH,
        ),
        execution_config=ExecutionConfig(
            # LOCAL gives every model an independently retryable Airflow task.
            # WATCHER 1.15 does not add a producer-before-consumer dependency for
            # DbtTaskGroup, which can leave consumers waiting before dbt starts.
            execution_mode=ExecutionMode.LOCAL,
            invocation_mode=InvocationMode.SUBPROCESS,
            dbt_executable_path=Path(sys.executable).with_name("dbt"),
            install_dbt_deps=False,
        ),
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST,
            select=task.dbt_selector.split(),
            exclude=task.dbt_exclude.split() if task.dbt_exclude else [],
            test_behavior=TestBehavior.BUILD,
            emit_datasets=True,
            should_detach_multiple_parents_tests=True,
        ),
        operator_args=operator_args,
    )


def _task_dependencies(tasks: list[registry.TaskDef]) -> dict[str, set[str]]:
    producer_by_dataset: dict[str, str] = {}
    mutators_by_dataset: dict[str, set[str]] = {}
    for task in tasks:
        for output in task.outputs:
            producer_by_dataset[output] = task.name
        for dataset in task.mutates:
            mutators_by_dataset.setdefault(dataset, set()).add(task.name)

    dependencies: dict[str, set[str]] = {}
    for task in tasks:
        inputs = (*task.inputs, *task.optional_inputs)
        dependencies[task.name] = {
            producer_by_dataset[dataset]
            for dataset in inputs
            if dataset in producer_by_dataset and producer_by_dataset[dataset] != task.name
        } | {
            mutator
            for dataset in inputs
            if dataset not in task.mutates
            for mutator in mutators_by_dataset.get(dataset, set())
            if mutator != task.name
        }
    return dependencies


def build_pipeline_dag(
    *,
    dag_id: str,
    graph: str,
    mode: str,
    schedule: str | None,
) -> DAG:
    """Build one live or fixture pipeline DAG from the canonical task registry."""

    quick = graph == registry.QUICK_GRAPH
    retries = 0 if mode == registry.FIXTURE_MODE else 2
    description = (
        "Offline fixture pipeline for deterministic local and CI verification."
        if mode == registry.FIXTURE_MODE
        else "NBA collector pipeline with model-level dbt orchestration through Cosmos."
    )
    selected_tasks = registry.task_defs_for(graph, mode)

    with DAG(
        dag_id=dag_id,
        description=description,
        start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        max_active_tasks=1,
        default_args={"owner": PIPELINE_OWNER},
        params=_pipeline_params(mode=mode, graph=graph),
        render_template_as_native_obj=True,
        is_paused_upon_creation=True,
        tags=["nba", "duckdb", "dbt", "cosmos", mode, graph],
        doc_md=(
            "All warehouse writers use the single-slot `nba_pipeline` pool because "
            "DuckDB does not support automatic multi-process writes. Full dbt DAGs "
            "render from a prebuilt manifest; run `make dbt-parse` after model changes."
        ),
    ) as dag:
        initialize = PythonOperator(
            task_id="initialize_warehouse",
            python_callable=initialize_warehouse,
            op_kwargs={"mode": mode, "quick": quick},
            pool=PIPELINE_POOL,
            retries=0,
        )

        nodes: dict[str, Any] = {}
        dbt_owned = set(DBT_MODEL_DATASETS)
        for task in selected_tasks:
            if task.dbt_selector:
                nodes[task.name] = _cosmos_group(
                    task,
                    mode=mode,
                    quick=quick,
                    retries=retries,
                )
                continue
            if task.outputs and set(task.outputs).issubset(dbt_owned):
                continue
            nodes[task.name] = PythonOperator(
                task_id=task.name,
                python_callable=execute_registered_task,
                op_kwargs={
                    "task_name": task.name,
                    "mode": mode,
                    "graph": graph,
                    "quick": quick,
                },
                inlets=[_asset(dataset) for dataset in (*task.inputs, *task.optional_inputs)],
                outlets=[_asset(dataset) for dataset in (*task.outputs, *task.mutates)],
                pool=PIPELINE_POOL,
                retries=retries,
                retry_delay=timedelta(seconds=120),
                show_return_value_in_logs=True,
            )

        dependencies = _task_dependencies(selected_tasks)
        for task_name, upstream_names in dependencies.items():
            if task_name not in nodes:
                continue
            for upstream_name in upstream_names:
                if upstream_name in nodes:
                    nodes[upstream_name] >> nodes[task_name]

        roots = {
            task.name
            for task in selected_tasks
            if task.name in nodes and not dependencies[task.name]
        }
        for task_name in roots:
            initialize >> nodes[task_name]

        if graph == registry.DEFAULT_GRAPH:
            upstream_names = set().union(*dependencies.values()) if dependencies else set()
            terminal_names = set(nodes) - upstream_names
            warehouse_quality = PythonOperator(
                task_id="warehouse_quality",
                python_callable=execute_quality_checks,
                op_kwargs={"mode": mode, "quick": quick},
                inlets=[
                    _asset(f"{schema}.{table}")
                    for schema, table in registry.quality_required_tables()
                ],
                outlets=[
                    Asset(
                        name="warehouse_quality",
                        uri="duckdb://nba-warehouse/quality/warehouse",
                        group="quality",
                    )
                ],
                pool=PIPELINE_POOL,
                retries=0,
            )
            for task_name in terminal_names:
                nodes[task_name] >> warehouse_quality

    return dag


def build_backfill_dag() -> DAG:
    """Build the manual, parameterized source backfill DAG."""

    with DAG(
        dag_id="nba_source_backfill",
        description="Resume one high-volume source using item-level ingestion state.",
        start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
        schedule=None,
        catchup=False,
        max_active_runs=1,
        max_active_tasks=1,
        default_args={"owner": PIPELINE_OWNER},
        params={
            **_pipeline_params(
                mode=registry.LIVE_MODE,
                graph=registry.DEFAULT_GRAPH,
            ),
            "source": Param(
                "play-by-play",
                type="string",
                enum=sorted(BACKFILL_TASKS),
                description="Collector to resume from its item-level state.",
            ),
            "competition": Param(
                NBA.slug,
                type="string",
                enum=sorted(COMPETITIONS),
                description="Competition owning the target games.",
            ),
        },
        render_template_as_native_obj=True,
        is_paused_upon_creation=True,
        tags=["nba", "duckdb", "backfill"],
    ) as dag:
        initialize = PythonOperator(
            task_id="initialize_warehouse",
            python_callable=initialize_warehouse,
            op_kwargs={"mode": registry.LIVE_MODE, "quick": False},
            pool=PIPELINE_POOL,
            retries=0,
        )
        backfill = PythonOperator(
            task_id="ingest_selected_source",
            python_callable=execute_source_backfill,
            pool=PIPELINE_POOL,
            retries=2,
            retry_delay=timedelta(seconds=120),
        )
        initialize >> backfill
    return dag


nba_warehouse_live = build_pipeline_dag(
    dag_id="nba_warehouse_live",
    graph=registry.DEFAULT_GRAPH,
    mode=registry.LIVE_MODE,
    schedule=os.environ.get("NBA_DUCKDB_AIRFLOW_LIVE_SCHEDULE") or None,
)
nba_warehouse_live_quick = build_pipeline_dag(
    dag_id="nba_warehouse_live_quick",
    graph=registry.QUICK_GRAPH,
    mode=registry.LIVE_MODE,
    schedule=os.environ.get("NBA_DUCKDB_AIRFLOW_QUICK_SCHEDULE") or None,
)
nba_summer_league = build_pipeline_dag(
    dag_id="nba_summer_league",
    graph=registry.SUMMER_LEAGUE_GRAPH,
    mode=registry.LIVE_MODE,
    schedule=os.environ.get("NBA_DUCKDB_AIRFLOW_SUMMER_SCHEDULE") or None,
)
nba_warehouse_smoke = build_pipeline_dag(
    dag_id="nba_warehouse_smoke",
    graph=registry.DEFAULT_GRAPH,
    mode=registry.FIXTURE_MODE,
    schedule=None,
)
nba_warehouse_smoke_quick = build_pipeline_dag(
    dag_id="nba_warehouse_smoke_quick",
    graph=registry.QUICK_GRAPH,
    mode=registry.FIXTURE_MODE,
    schedule=None,
)
nba_source_backfill = build_backfill_dag()

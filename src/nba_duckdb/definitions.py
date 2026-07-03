"""Dagster definitions for the local NBA DuckDB warehouse."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import dagster as dg
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from nba_duckdb import config, db, registry
from nba_duckdb.dbt_manifest import dbt_manifest_node_dataset, ensure_dbt_manifest
from nba_duckdb.dbt_models import (
    DBT_FEATURE_SELECTOR,
    DBT_MODEL_DATASETS,
    DBT_TRANSFORM_EXCLUDE,
    DBT_TRANSFORM_SELECTOR,
)
from nba_duckdb.dbt_runner import dbt_project_dir
from nba_duckdb.fixtures.generate_synthetic_fixtures import SEASON as SYNTHETIC_SEASON


def _asset_key(dataset: str) -> dg.AssetKey:
    return dg.AssetKey(dataset.split(".", 1))


def _output_name(dataset: str) -> str:
    return dataset.replace(".", "__")


def _set_offline_smoke_env() -> str | None:
    previous = os.environ.get("NBA_DUCKDB_OFFLINE_SMOKE")
    os.environ["NBA_DUCKDB_OFFLINE_SMOKE"] = "1"
    return previous


def _restore_offline_smoke_env(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("NBA_DUCKDB_OFFLINE_SMOKE", None)
        return
    os.environ["NBA_DUCKDB_OFFLINE_SMOKE"] = previous


class NbaDbtTranslator(DagsterDbtTranslator):
    """Map dbt models and sources onto the warehouse asset key convention."""

    def get_asset_key(self, dbt_resource_props: dict[str, Any]) -> dg.AssetKey:
        dataset = dbt_manifest_node_dataset(dbt_resource_props)
        if dataset is not None:
            return _asset_key(dataset)
        return super().get_asset_key(dbt_resource_props)


def _dbt_project() -> DbtProject:
    project_dir = dbt_project_dir()
    return DbtProject(
        project_dir=project_dir,
        profiles_dir=project_dir / "dbt",
        target_path=project_dir / "dbt" / "target",
    )


DBT_PROJECT = _dbt_project()
DBT_PROJECT.prepare_if_dev()
DEFAULT_DAGSTER_LOG_LEVEL = "WARNING"


def default_smoke_scope() -> dict[str, Any]:
    return {
        "season": SYNTHETIC_SEASON,
        "seasons": [SYNTHETIC_SEASON],
        "game_ids": None,
        "full_refresh": False,
        "start_date": None,
        "end_date": None,
    }


def _ensure_dbt_manifest() -> Path:
    manifest_path = Path(DBT_PROJECT.manifest_path)
    project_dir_value = getattr(DBT_PROJECT, "project_dir", None)
    project_dir = Path(project_dir_value) if project_dir_value is not None else dbt_project_dir()
    return ensure_dbt_manifest(project_dir=project_dir, manifest_path=manifest_path)


# dagster-dbt reads the manifest while building asset definitions, so importing
# this module can run dbt parse and update ignored dbt/target artifacts when stale.
DBT_MANIFEST = _ensure_dbt_manifest()


def _run_task_inner(
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


def _run_task(
    task: registry.TaskDef,
    *,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
    offline_smoke: bool = False,
) -> dict[str, Any]:
    previous_offline = _set_offline_smoke_env() if offline_smoke else None
    try:
        return _run_task_inner(
            task,
            scope=scope,
            fixtures_dir=fixtures_dir,
            source_name=source_name,
        )
    finally:
        if offline_smoke:
            _restore_offline_smoke_env(previous_offline)


def _metadata_value(value: Any) -> str | int | float | bool | None:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    item = getattr(value, "item", None)
    if not callable(item):
        return None
    try:
        scalar = item()
    except (TypeError, ValueError):
        return None
    if scalar is None or type(scalar) in {str, int, float, bool}:
        return scalar
    return None


def _dagster_metadata(result: dict[str, Any]) -> dict[str, dg.MetadataValue]:
    metadata: dict[str, dg.MetadataValue] = {}
    for key, value in result.items():
        normalized = _metadata_value(value)
        if type(normalized) is str:
            metadata[key] = dg.MetadataValue.text(normalized)
        elif type(normalized) is int:
            metadata[key] = dg.MetadataValue.int(normalized)
        elif type(normalized) is float:
            metadata[key] = dg.MetadataValue.float(normalized)
        elif type(normalized) is bool:
            metadata[key] = dg.MetadataValue.bool(normalized)
    return metadata


def _make_asset(
    task: registry.TaskDef,
    *,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
    offline_smoke: bool = False,
) -> dg.AssetsDefinition:
    outs = {
        _output_name(output): dg.AssetOut(key=_asset_key(output))
        for output in task.outputs
    }
    deps = [_asset_key(input_name) for input_name in (*task.inputs, *task.optional_inputs)]

    @dg.multi_asset(
        name=task.name,
        group_name=task.layer,
        outs=outs,
        deps=deps,
        can_subset=False,
    )
    def task_asset(context):
        context.log.info("Materializing %s", task.name)
        result = _run_task(
            task,
            scope=scope,
            fixtures_dir=fixtures_dir,
            source_name=source_name,
            offline_smoke=offline_smoke,
        )
        metadata = _dagster_metadata(result)
        for output_name in outs:
            yield dg.Output(value=None, output_name=output_name, metadata=metadata)

    return task_asset


@dbt_assets(
    manifest=DBT_MANIFEST,
    select=DBT_TRANSFORM_SELECTOR,
    exclude=DBT_TRANSFORM_EXCLUDE,
    project=DBT_PROJECT,
    dagster_dbt_translator=NbaDbtTranslator(),
)
def dbt_warehouse_models(context, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


@dbt_assets(
    manifest=DBT_MANIFEST,
    select=DBT_FEATURE_SELECTOR,
    project=DBT_PROJECT,
    dagster_dbt_translator=NbaDbtTranslator(),
)
def dbt_feature_matrices(context, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


def _make_quality_asset(*, graph: str, mode: str) -> dg.AssetsDefinition:
    quality_deps = [
        _asset_key(output)
        for task in registry.task_defs_for(graph, mode)
        if not set(task.outputs).issubset(set(DBT_MODEL_DATASETS))
        for output in task.quality_outputs
    ] + [_asset_key(output) for output in DBT_MODEL_DATASETS]

    @dg.asset(
        name="warehouse_quality",
        deps=quality_deps,
        group_name="quality",
    )
    def warehouse_quality() -> dg.MaterializeResult:
        from nba_duckdb import quality

        result = quality.run_checks()
        return dg.MaterializeResult(
            metadata={
                "table_count": len(result.get("table_counts", {})),
                "coverage_seasons": len(result.get("coverage_counts", [])),
            }
        )

    return warehouse_quality


def _assets(
    *,
    graph: str,
    mode: str,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
    offline_smoke: bool = False,
    include_quality: bool = True,
) -> list[dg.AssetsDefinition]:
    assets = [
        _make_asset(
            task,
            scope=scope,
            fixtures_dir=fixtures_dir,
            source_name=source_name,
            offline_smoke=offline_smoke,
        )
        for task in registry.task_defs_for(graph, mode)
        if not task.dbt_selector and not set(task.outputs).issubset(set(DBT_MODEL_DATASETS))
    ]
    if include_quality:
        assets.append(_make_quality_asset(graph=graph, mode=mode))
    return assets


def build_definitions(
    *,
    graph: str = registry.DEFAULT_GRAPH,
    mode: str = registry.FIXTURE_MODE,
    scope: dict[str, Any] | None = None,
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
    offline_smoke: bool = False,
    job_name: str = "smoke_job",
) -> dg.Definitions:
    selected_tasks = registry.task_defs_for(graph, mode)
    dbt_task_names = {task.name for task in selected_tasks if task.dbt_selector}
    include_quality = graph == registry.DEFAULT_GRAPH
    logger_config = {
        "loggers": {
            "console": {
                "config": {
                    "log_level": os.environ.get(
                        "NBA_DUCKDB_DAGSTER_LOG_LEVEL",
                        DEFAULT_DAGSTER_LOG_LEVEL,
                    ).upper()
                }
            }
        }
    }
    job = dg.define_asset_job(
        job_name,
        selection=dg.AssetSelection.all(),
        config=logger_config,
        executor_def=dg.in_process_executor,
    )
    return dg.Definitions(
        assets=[
            *_assets(
                graph=graph,
                mode=mode,
                scope=scope or default_smoke_scope(),
                fixtures_dir=fixtures_dir,
                source_name=source_name,
                offline_smoke=offline_smoke,
                include_quality=include_quality,
            ),
            *([dbt_warehouse_models] if "dbt_build_warehouse" in dbt_task_names else []),
            *([dbt_feature_matrices] if "dbt_build_feature_matrices" in dbt_task_names else []),
        ],
        jobs=[job],
        resources={
            "dbt": DbtCliResource(project_dir=DBT_PROJECT),
        },
    )


def execute_dagster_job(
    *,
    graph: str,
    mode: str,
    scope: dict[str, Any],
    fixtures_dir: Path | None = None,
    source_name: str | None = None,
    offline_smoke: bool = False,
    job_name: str = "pipeline_job",
) -> dict[str, Any]:
    pipeline_defs = build_definitions(
        graph=graph,
        mode=mode,
        scope=scope,
        fixtures_dir=fixtures_dir,
        source_name=source_name,
        offline_smoke=offline_smoke,
        job_name=job_name,
    )
    result = pipeline_defs.resolve_job_def(job_name).execute_in_process()
    return {
        "dagster_job": job_name,
        "dagster_run_id": result.run_id,
        "success": bool(result.success),
    }


defs = build_definitions(
    graph=registry.DEFAULT_GRAPH,
    mode=registry.FIXTURE_MODE,
    scope=default_smoke_scope(),
    offline_smoke=True,
    job_name="smoke_job",
)

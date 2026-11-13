import re
from pathlib import Path

from nba_duckdb import registry
from nba_duckdb.dbt_models import (
    DBT_CORE_MODEL_NAMES,
    DBT_FEATURE_MODEL_NAMES,
    DBT_FEATURE_SELECTOR,
    DBT_GOLD_MODEL_NAMES,
    DBT_MODEL_DATASETS,
    DBT_MODEL_NAMES,
    DBT_SUMMER_LEAGUE_MODEL_NAMES,
    DBT_SUMMER_LEAGUE_SELECTOR,
    DBT_TRANSFORM_EXCLUDE,
    DBT_TRANSFORM_SELECTOR,
)
from nba_duckdb.sql.schema import schema_sql_text


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dbt_model_files() -> list[Path]:
    return sorted(
        path
        for path in (_repo_root() / "dbt" / "models").rglob("*")
        if path.suffix in {".sql", ".py"}
    )


def _dbt_model_file_names() -> set[str]:
    return {path.stem for path in _dbt_model_files()}


def _warehouse_tables_from_schema() -> set[str]:
    sql = schema_sql_text()
    return {
        f"{schema}.{table}"
        for schema, table in re.findall(
            r"CREATE TABLE IF NOT EXISTS (silver|gold)\.([a-z_]+)\s*\(",
            sql,
        )
    }


def _registered_gold_producers() -> dict[str, list[registry.TaskDef]]:
    producers: dict[str, list[registry.TaskDef]] = {}
    for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE):
        for output in task.outputs:
            schema, table = output.split(".", 1)
            if schema == "gold":
                producers.setdefault(table, []).append(task)
    return producers


def _dbt_ls_model_names(*, selector: str, exclude: str | None = None) -> set[str]:
    from nba_duckdb import dbt_runner

    args = ["ls", "--select", selector]
    if exclude:
        args.extend(["--exclude", exclude])
    args.extend(["--resource-type", "model", "--output", "name"])
    result = dbt_runner.run_dbt_command(args)
    model_names = set(DBT_MODEL_NAMES)
    return {
        re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        for line in result["stdout"].splitlines()
    } & model_names


def test_dbt_model_files_are_registered():
    assert _dbt_model_file_names() == set(DBT_MODEL_NAMES)


def test_models_reading_runtime_tables_run_in_the_second_dbt_phase():
    runtime_models = {
        path.stem
        for path in _dbt_model_files()
        if re.search(r"source\(\s*['\"]gold_runtime['\"]", path.read_text())
    }
    assert runtime_models == set(DBT_FEATURE_MODEL_NAMES)


def test_dbt_tag_selectors_partition_registered_models():
    core_models = _dbt_ls_model_names(
        selector=DBT_TRANSFORM_SELECTOR,
        exclude=DBT_TRANSFORM_EXCLUDE,
    )
    feature_models = _dbt_ls_model_names(selector=DBT_FEATURE_SELECTOR)
    summer_league_models = _dbt_ls_model_names(selector=DBT_SUMMER_LEAGUE_SELECTOR)

    assert core_models == set(DBT_CORE_MODEL_NAMES)
    assert feature_models == set(DBT_FEATURE_MODEL_NAMES)
    assert summer_league_models == set(DBT_SUMMER_LEAGUE_MODEL_NAMES)
    assert core_models.isdisjoint(feature_models)
    assert core_models.isdisjoint(summer_league_models)
    assert feature_models.isdisjoint(summer_league_models)
    assert core_models | feature_models | summer_league_models == set(DBT_MODEL_NAMES)


def test_gold_schema_tables_have_one_declared_registry_producer():
    schema_tables = {
        table
        for schema_table in _warehouse_tables_from_schema()
        for schema, table in [schema_table.split(".", 1)]
        if schema == "gold"
    } | set(DBT_GOLD_MODEL_NAMES)
    producers = _registered_gold_producers()

    assert set(producers) == schema_tables
    for table, table_producers in producers.items():
        assert len(table_producers) == 1, table


def test_dbt_tables_are_owned_by_dbt_not_schema_sql():
    schema_tables = _warehouse_tables_from_schema()

    assert schema_tables.isdisjoint(DBT_MODEL_DATASETS)

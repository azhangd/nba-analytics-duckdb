import re
from pathlib import Path

from nba_duckdb import registry
from nba_duckdb.dbt_models import (
    DBT_CORE_MODEL_DATASETS,
    DBT_CORE_MODEL_NAMES,
    DBT_FEATURE_MODEL_DATASETS,
    DBT_FEATURE_MODEL_NAMES,
    DBT_FEATURE_SELECTOR,
    DBT_GOLD_MODEL_NAMES,
    DBT_MODEL_DATASETS,
    DBT_MODEL_NAMES,
    DBT_RUNTIME_DEPENDENT_SELECTOR,
    DBT_TRANSFORM_EXCLUDE,
    DBT_TRANSFORM_INPUTS,
    DBT_TRANSFORM_SELECTOR,
)
from nba_duckdb.sql.schema import schema_sql_text


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dbt_gold_dir() -> Path:
    return _repo_root() / "dbt" / "models" / "gold"


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


def _registered_dbt_models() -> set[str]:
    return {
        model
        for task in registry.TASK_DEFS
        for model in task.dbt_models
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


def test_dbt_model_files_are_registered_and_select_only():
    registered = _registered_dbt_models()
    actual_models = _dbt_model_file_names()

    assert actual_models == registered
    assert actual_models == set(DBT_MODEL_NAMES)

    for path in _dbt_model_files():
        if path.suffix != ".sql":
            continue
        sql = path.read_text()
        assert "{{ config(" in sql
        assert f"alias='{path.stem}'" in sql
        assert re.search(r"\bINSERT\s+INTO\b", sql, re.IGNORECASE) is None
        assert re.search(r"\b(BEGIN|COMMIT|TRUNCATE)\b", sql, re.IGNORECASE) is None


def test_dbt_gold_manifest_matches_registry():
    assert _registered_dbt_models() == set(DBT_MODEL_NAMES)


def test_dbt_gold_manifest_matches_model_files():
    assert len(DBT_MODEL_NAMES) == len(set(DBT_MODEL_NAMES))
    assert _dbt_model_file_names() == set(DBT_MODEL_NAMES)


def test_runtime_dependent_models_are_second_dbt_phase_models():
    runtime_models = {
        path.stem
        for path in _dbt_model_files()
        if re.search(r"source\(\s*['\"]gold_runtime['\"]", path.read_text())
    }
    core_task = next(task for task in registry.TASK_DEFS if task.name == "dbt_build_warehouse")
    feature_task = next(
        task for task in registry.TASK_DEFS if task.name == "dbt_build_feature_matrices"
    )

    assert runtime_models == set(DBT_FEATURE_MODEL_NAMES)
    assert set(DBT_FEATURE_MODEL_NAMES) == {"player_season_feature_matrix"}
    assert core_task.dbt_selector == DBT_TRANSFORM_SELECTOR
    assert core_task.dbt_exclude == DBT_RUNTIME_DEPENDENT_SELECTOR
    assert feature_task.dbt_selector == DBT_FEATURE_SELECTOR
    assert feature_task.dbt_exclude in (None, "")
    assert feature_task.dbt_models == DBT_FEATURE_MODEL_NAMES
    player_feature_sql = (_dbt_gold_dir() / "player_season_feature_matrix.sql").read_text()
    team_feature_sql = (_dbt_gold_dir() / "team_season_feature_matrix.sql").read_text()
    assert "requires_gold_runtime" in player_feature_sql
    assert "requires_gold_runtime" not in team_feature_sql
    assert "gold_feature" not in player_feature_sql
    assert "gold_feature" not in team_feature_sql


def test_runtime_dependent_selector_names_share_one_boundary():
    assert DBT_RUNTIME_DEPENDENT_SELECTOR == "tag:requires_gold_runtime"
    assert DBT_TRANSFORM_EXCLUDE == "tag:requires_gold_runtime"
    assert DBT_FEATURE_SELECTOR == "tag:requires_gold_runtime"


def test_dbt_tag_selectors_partition_registered_models():
    core_models = _dbt_ls_model_names(
        selector=DBT_TRANSFORM_SELECTOR,
        exclude=DBT_TRANSFORM_EXCLUDE,
    )
    feature_models = _dbt_ls_model_names(selector=DBT_FEATURE_SELECTOR)

    assert core_models == set(DBT_CORE_MODEL_NAMES)
    assert feature_models == set(DBT_FEATURE_MODEL_NAMES)
    assert core_models.isdisjoint(feature_models)
    assert core_models | feature_models == set(DBT_MODEL_NAMES)
    assert "team_season_feature_matrix" in core_models
    assert "player_season_feature_matrix" in feature_models


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


def test_dbt_gold_models_match_single_registry_task():
    registered = _registered_dbt_models()
    producers = _registered_gold_producers()

    assert registered == set(DBT_MODEL_NAMES)
    assert [
        task.name
        for task in registry.TASK_DEFS
        if task.dbt_selector
    ] == ["dbt_build_warehouse", "dbt_build_feature_matrices"]

    core_task = next(task for task in registry.TASK_DEFS if task.name == "dbt_build_warehouse")
    feature_task = next(
        task for task in registry.TASK_DEFS if task.name == "dbt_build_feature_matrices"
    )
    assert core_task.dbt_selector == DBT_TRANSFORM_SELECTOR
    assert core_task.dbt_exclude == DBT_TRANSFORM_EXCLUDE
    assert core_task.outputs == DBT_CORE_MODEL_DATASETS
    assert core_task.inputs == DBT_TRANSFORM_INPUTS
    assert core_task.task_type == "dbt"
    assert feature_task.dbt_selector == DBT_FEATURE_SELECTOR
    assert feature_task.dbt_exclude in (None, "")
    assert feature_task.outputs == DBT_FEATURE_MODEL_DATASETS
    assert feature_task.inputs[:4] == (
        "gold.player_season_stats",
        "gold.player_game_rolling_stats",
        "gold.player_season_shot_profile",
        "gold.player_season_archetypes",
    )
    assert feature_task.task_type == "dbt"

    for model in DBT_GOLD_MODEL_NAMES:
        assert model in producers
        expected_task = (
            feature_task if f"gold.{model}" in DBT_FEATURE_MODEL_DATASETS else core_task
        )
        assert producers[model] == [expected_task]

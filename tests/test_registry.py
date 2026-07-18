import importlib
import re
import sys

from nba_duckdb.dbt_models import DBT_MODEL_DATASETS
from nba_duckdb.sql.schema import schema_sql_text


def _names(tasks):
    return [task.name for task in tasks]


def _schema_tables():
    sql = schema_sql_text()
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (bronze|silver|gold)\.([a-z_]+)", sql))


def _warehouse_tables():
    return _schema_tables() | {tuple(output.split(".", 1)) for output in DBT_MODEL_DATASETS}


def _registry_outputs(graph, mode):
    from nba_duckdb import registry

    outputs = set()
    for task in registry.task_defs_for(graph, mode):
        for output in task.outputs:
            schema, table = output.split(".", 1)
            outputs.add((schema, table))
    return outputs


def test_default_live_graph_builds_full_warehouse():
    from nba_duckdb import registry

    names = _names(registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE))

    assert names[:4] == [
        "ingest_schedule",
        "ingest_rosters",
        "ingest_boxscores",
        "ingest_play_by_play",
    ]
    assert "ingest_shot_charts" in names
    assert "ingest_tracking_stats" in names
    assert "ingest_injuries" in names
    assert "dbt_build_warehouse" in names
    assert "compute_player_embeddings" in names
    assert "dbt_build_feature_matrices" in names
    assert names.index("ingest_shot_charts") < names.index("dbt_build_warehouse")
    assert names.index("dbt_build_warehouse") < names.index("compute_player_embeddings")
    assert names.index("compute_player_embeddings") < names.index("dbt_build_feature_matrices")
    assert names.index("compute_rapm") < names.index("dbt_build_feature_matrices")


def test_quick_graph_is_explicitly_smaller_than_default():
    from nba_duckdb import registry

    default_names = set(_names(registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE)))
    quick_names = set(_names(registry.task_defs_for(registry.QUICK_GRAPH, registry.LIVE_MODE)))

    assert quick_names < default_names
    assert "ingest_shot_charts" not in quick_names
    assert "dbt_build_warehouse" not in quick_names
    assert "dbt_build_feature_matrices" not in quick_names
    assert quick_names == {
        "ingest_schedule",
        "ingest_rosters",
        "ingest_boxscores",
        "ingest_play_by_play",
    }


def test_summer_league_graph_has_only_competition_safe_tasks():
    from nba_duckdb import registry

    names = _names(
        registry.task_defs_for(
            registry.SUMMER_LEAGUE_GRAPH,
            registry.LIVE_MODE,
        )
    )

    assert names == [
        "ingest_schedule",
        "ingest_boxscores",
        "ingest_play_by_play",
        "ingest_shot_charts",
        "dbt_build_summer_league",
        "validate_summer_league",
    ]
    assert "ingest_rosters" not in names
    assert "dbt_build_warehouse" not in names


def test_registry_order_satisfies_declared_dependencies():
    from nba_duckdb import registry

    for graph in registry.ALL_GRAPHS:
        for mode in registry.ALL_MODES:
            produced = set()
            selected = registry.task_defs_for(graph, mode)
            for task in selected:
                selected_outputs = {output for candidate in selected for output in candidate.outputs}
                missing = [
                    input_name
                    for input_name in (*task.inputs, *task.optional_inputs)
                    if input_name in selected_outputs and input_name not in produced
                ]
                assert missing == [], f"{graph}/{mode}/{task.name} missing {missing}"
                produced.update(task.outputs)


def test_registry_declares_clear_player_season_stats_ownership():
    from nba_duckdb import registry

    tasks = {task.name: task for task in registry.TASK_DEFS}

    assert "compute_adjusted_stats" not in tasks
    assert "compute_bpm_vorp" not in tasks
    assert "gold.player_season_stats_base" in tasks["dbt_build_warehouse"].outputs
    assert "gold.player_season_stats" in tasks["dbt_build_warehouse"].outputs
    assert "gold.team_season_feature_matrix" in tasks["dbt_build_warehouse"].outputs
    assert "compute_player_feature_matrix" not in tasks
    assert "compute_team_feature_matrix" not in tasks
    assert tasks["dbt_build_feature_matrices"].inputs[:5] == (
        "gold.player_season_stats",
        "gold.player_game_rolling_stats",
        "gold.player_season_shot_profile",
        "gold.player_season_archetypes",
        "gold.player_season_embeddings",
    )
    assert tasks["dbt_build_feature_matrices"].outputs == (
        "gold.game_flow_snapshots",
        "gold.player_season_feature_matrix",
    )
    assert "bronze.boxscores" in tasks["dbt_build_warehouse"].inputs
    assert "bronze.play_by_play" in tasks["dbt_build_warehouse"].inputs
    assert not any("gold.player_season_stats" in task.mutates for task in registry.TASK_DEFS)


def test_dbt_registration_is_graph_scoped():
    from nba_duckdb import registry
    from nba_duckdb.dbt_models import DBT_SUMMER_LEAGUE_MODEL_DATASETS

    dbt_tasks = [task for task in registry.TASK_DEFS if task.dbt_selector]

    assert [task.name for task in dbt_tasks] == [
        "dbt_build_warehouse",
        "dbt_build_feature_matrices",
        "dbt_build_summer_league",
    ]
    default_outputs = {
        output
        for task in dbt_tasks
        if "default" in task.graphs
        for output in task.outputs
    }
    assert default_outputs == set(DBT_MODEL_DATASETS) - set(
        DBT_SUMMER_LEAGUE_MODEL_DATASETS
    )
    assert dbt_tasks[-1].outputs == DBT_SUMMER_LEAGUE_MODEL_DATASETS
    assert dbt_tasks[-1].regular_season_only is False
    assert all(task.task_type == "dbt" for task in dbt_tasks)
    assert all(task.dbt_selector for task in dbt_tasks)
    assert all(task.module_path == "" for task in dbt_tasks)


def test_registry_does_not_import_task_modules_when_cli_imports(monkeypatch):
    for module_name in list(sys.modules):
        if module_name == "nba_duckdb.cli" or module_name.startswith("nba_duckdb.tasks."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delitem(sys.modules, "sklearn", raising=False)

    importlib.import_module("nba_duckdb.cli")

    assert "sklearn" not in sys.modules
    assert not any(module_name.startswith("nba_duckdb.tasks.gold.") for module_name in sys.modules)


def test_win_probability_runtime_import_does_not_require_sklearn(monkeypatch):
    for module_name in list(sys.modules):
        if module_name.startswith("sklearn") or module_name == "nba_duckdb.modeling.win_probability":
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    importlib.import_module("nba_duckdb.modeling.win_probability")

    assert "sklearn" not in sys.modules


def test_all_schema_tables_have_registered_default_producers():
    from nba_duckdb import registry
    from nba_duckdb.dbt_models import DBT_SUMMER_LEAGUE_MODEL_DATASETS

    schema_tables = _warehouse_tables()
    summer_tables = {
        tuple(dataset.split(".", 1))
        for dataset in DBT_SUMMER_LEAGUE_MODEL_DATASETS
    }
    live_outputs = _registry_outputs(registry.DEFAULT_GRAPH, registry.LIVE_MODE)
    fixture_outputs = _registry_outputs(registry.DEFAULT_GRAPH, registry.FIXTURE_MODE)
    summer_outputs = _registry_outputs(
        registry.SUMMER_LEAGUE_GRAPH,
        registry.LIVE_MODE,
    )

    assert live_outputs == schema_tables - summer_tables
    assert fixture_outputs == schema_tables - summer_tables
    assert live_outputs | summer_outputs == schema_tables


def test_quality_required_tables_are_derived_from_full_registry():
    from nba_duckdb import quality, registry
    from nba_duckdb.dbt_models import DBT_SUMMER_LEAGUE_MODEL_DATASETS

    assert quality.REQUIRED_TABLES == registry.quality_required_tables()
    summer_tables = {
        tuple(dataset.split(".", 1))
        for dataset in DBT_SUMMER_LEAGUE_MODEL_DATASETS
    }
    assert set(quality.REQUIRED_TABLES) == _warehouse_tables() - summer_tables


def test_dataset_rows_advertise_every_registered_output():
    from nba_duckdb import registry

    rows = registry.dataset_rows()
    datasets = {tuple(str(row["dataset"]).split(".", 1)) for row in rows}

    assert datasets == _warehouse_tables()
    assert all(
        {"quick", "default", "summer_league"}.intersection(row["graphs"])
        for row in rows
    )
    assert not any("library" in row["graphs"] for row in rows)
    assert {
        row["task"]
        for row in rows
        if row["dataset"] == "gold.player_season_stats" and row["writes"] == "produces"
    } == {"dbt_build_warehouse"}
    assert {
        row["task"]
        for row in rows
        if row["dataset"] == "gold.player_season_feature_matrix" and row["writes"] == "produces"
    } == {"dbt_build_feature_matrices"}
    assert {
        row["task"]
        for row in rows
        if row["dataset"] == "gold.team_season_feature_matrix" and row["writes"] == "produces"
    } == {"dbt_build_warehouse"}
    assert {
        row["layer"]
        for row in rows
        if row["dataset"] == "silver.fct_games" and row["writes"] == "produces"
    } == {"silver"}
    assert {
        row["layer"]
        for row in rows
        if row["dataset"] == "gold.player_season_stats" and row["writes"] == "produces"
    } == {"gold"}


def test_dataset_graph_exposes_lineage_without_task_imports():
    from nba_duckdb import registry

    graph = registry.dataset_graph()
    nodes = {node["dataset"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["task"]) for edge in graph["edges"]}

    assert "gold.player_season_stats" in nodes
    assert nodes["gold.player_season_stats"]["producers"] == [
        {"task": "dbt_build_warehouse", "writes": "produces"}
    ]
    assert (
        "gold.player_game_stats",
        "gold.player_season_stats",
        "dbt_build_warehouse",
    ) in edges
    assert (
        "silver.fct_games",
        "gold.player_season_stats",
        "dbt_build_warehouse",
    ) in edges
    assert (
        "gold.team_season_four_factors",
        "gold.team_season_feature_matrix",
        "dbt_build_warehouse",
    ) in edges
    assert (
        "bronze.boxscores",
        "gold.player_season_stats",
        "dbt_build_warehouse",
    ) not in edges
    assert (
        "bronze.boxscores",
        "gold.team_season_feature_matrix",
        "dbt_build_warehouse",
    ) not in edges


def test_bronze_ownership_is_mode_specific():
    from nba_duckdb import registry

    live_producers = {
        output: task.name
        for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE)
        for output in task.outputs
        if output.startswith("bronze.")
    }
    fixture_producers = {
        output: task.name
        for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.FIXTURE_MODE)
        for output in task.outputs
        if output.startswith("bronze.")
    }

    assert live_producers["bronze.schedule"] == "ingest_schedule"
    assert live_producers["bronze.boxscores"] == "ingest_boxscores"
    assert live_producers["bronze.play_by_play"] == "ingest_play_by_play"
    assert set(fixture_producers.values()) == {"load_synthetic_fixtures"}

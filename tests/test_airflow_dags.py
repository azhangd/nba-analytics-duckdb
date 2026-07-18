from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("airflow")
pytest.importorskip("cosmos")

from cosmos.constants import InvocationMode

from nba_duckdb.dbt_models import (
    DBT_CORE_MODEL_NAMES,
    DBT_FEATURE_MODEL_NAMES,
    DBT_SUMMER_LEAGUE_MODEL_NAMES,
)


def _dags():
    from nba_duckdb.airflow_dags import (
        nba_source_backfill,
        nba_summer_league,
        nba_warehouse_live,
        nba_warehouse_live_quick,
        nba_warehouse_smoke,
        nba_warehouse_smoke_quick,
    )

    return {
        dag.dag_id: dag
        for dag in (
            nba_warehouse_live,
            nba_warehouse_live_quick,
            nba_summer_league,
            nba_warehouse_smoke,
            nba_warehouse_smoke_quick,
            nba_source_backfill,
        )
    }


def _cosmos_models(dag, group_id: str) -> set[str]:
    prefix = f"{group_id}."
    suffix = "_model_build"
    return {
        task_id.removeprefix(prefix).removesuffix(suffix)
        for task_id in dag.task_ids
        if task_id.startswith(prefix) and task_id.endswith(suffix)
    }


def test_airflow_discovers_all_dags_without_import_errors():
    from airflow.dag_processing.dagbag import DagBag

    project_root = Path(__file__).resolve().parents[1]
    dag_bag = DagBag(dag_folder=project_root / "dags", safe_mode=True)

    assert dag_bag.import_errors == {}
    assert set(dag_bag.dag_ids) == {
        "nba_source_backfill",
        "nba_summer_league",
        "nba_warehouse_live",
        "nba_warehouse_live_quick",
        "nba_warehouse_smoke",
        "nba_warehouse_smoke_quick",
    }


def test_dags_are_safe_by_default_and_serialize_duckdb_writes():
    from nba_duckdb.airflow_dags import PIPELINE_POOL

    for dag in _dags().values():
        assert dag.schedule is None
        assert dag.catchup is False
        assert dag.max_active_runs == 1
        assert dag.max_active_tasks == 1
        assert dag.is_paused_upon_creation is True
        assert all(task.pool == PIPELINE_POOL for task in dag.tasks)


def test_cosmos_renders_every_dbt_model_at_model_granularity():
    live = _dags()["nba_warehouse_live"]

    assert _cosmos_models(live, "dbt_warehouse") == set(DBT_CORE_MODEL_NAMES)
    assert _cosmos_models(live, "dbt_feature_matrices") == set(DBT_FEATURE_MODEL_NAMES)
    assert all(
        live.get_task(task_id).invocation_mode == InvocationMode.SUBPROCESS
        for task_id in live.task_ids
        if task_id.endswith("_model_build")
    )


def test_summer_league_dag_renders_only_competition_safe_models():
    summer = _dags()["nba_summer_league"]

    assert _cosmos_models(summer, "dbt_summer_league") == set(
        DBT_SUMMER_LEAGUE_MODEL_NAMES
    )
    assert {
        "ingest_schedule",
        "ingest_boxscores",
        "ingest_play_by_play",
        "ingest_shot_charts",
        "validate_summer_league",
    }.issubset(summer.task_ids)
    assert "ingest_rosters" not in summer.task_ids
    assert not any("gold." in task_id for task_id in summer.task_ids)


def test_runtime_models_preserve_the_two_phase_boundary():
    live = _dags()["nba_warehouse_live"]
    core_leaf = live.get_task("dbt_warehouse.team_season_feature_matrix_model_build")
    runtime_task = live.get_task("compute_player_embeddings")
    feature_task = live.get_task(
        "dbt_feature_matrices.player_season_feature_matrix_model_build"
    )

    assert runtime_task.task_id in core_leaf.downstream_task_ids
    assert runtime_task.task_id in feature_task.upstream_task_ids
    assert "compute_rapm" in feature_task.upstream_task_ids
    assert "compute_win_prob_model" in feature_task.upstream_task_ids


def test_quick_dags_are_intentionally_small():
    dags = _dags()

    assert set(dags["nba_warehouse_live_quick"].task_ids) == {
        "initialize_warehouse",
        "ingest_schedule",
        "ingest_rosters",
        "ingest_boxscores",
        "ingest_play_by_play",
    }
    assert set(dags["nba_warehouse_smoke_quick"].task_ids) == {
        "initialize_warehouse",
        "load_synthetic_fixtures",
    }


def test_live_params_are_typed_for_manual_runs():
    live = _dags()["nba_warehouse_live"]
    summer = _dags()["nba_summer_league"]
    backfill = _dags()["nba_source_backfill"]

    assert live.params.get_param("season").schema["pattern"] == r"^\d{4}-\d{2}$"
    assert live.params.get_param("game_ids").schema["items"] == {"type": "string"}
    assert live.params.get_param("team_ids").schema["items"] == {"type": "integer"}
    assert live.params.get_param("full_refresh").schema["type"] == "boolean"
    assert backfill.params.get_param("source").schema["enum"] == [
        "play-by-play",
        "shot-charts",
    ]
    assert summer.params.get_param("competitions").schema["items"]["enum"] == [
        "summer_league_california",
        "summer_league_vegas",
        "summer_league_salt_lake_city",
    ]
    assert backfill.params.get_param("competition").schema["enum"] == [
        "nba",
        "summer_league_california",
        "summer_league_salt_lake_city",
        "summer_league_vegas",
    ]


def test_python_tasks_publish_logical_warehouse_assets():
    live = _dags()["nba_warehouse_live"]
    schedule = live.get_task("ingest_schedule")

    assert [asset.name for asset in schedule.outlets] == ["bronze.schedule"]
    assert [asset.uri for asset in schedule.outlets] == [
        "duckdb://nba-warehouse/bronze/schedule"
    ]
    assert all(str(asset.uri).startswith("duckdb://") for task in live.tasks for asset in task.outlets)

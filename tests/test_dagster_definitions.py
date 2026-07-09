from __future__ import annotations

import os

import pytest

pytest.importorskip("dagster")
from dagster import AssetKey


def test_dagster_asset_graph_exposes_default_fixture_outputs():
    from nba_duckdb import registry
    from nba_duckdb.definitions import defs

    asset_graph = defs.resolve_asset_graph()
    asset_keys = {".".join(asset_key.path) for asset_key in asset_graph.get_all_asset_keys()}
    expected_outputs = {
        output
        for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.FIXTURE_MODE)
        for output in task.outputs
    }

    assert expected_outputs <= asset_keys
    assert "warehouse_quality" in asset_keys


def test_dagster_dbt_assets_use_manifest_lineage():
    from nba_duckdb.definitions import defs

    asset_graph = defs.resolve_asset_graph()

    player_base = asset_graph.get(AssetKey(["gold", "player_season_stats_base"]))
    assert {
        ".".join(parent.path)
        for parent in player_base.parent_keys
    } >= {
        "gold.player_game_stats",
        "silver.fct_games",
        "silver.dim_players",
    }

    percentile_ranks = asset_graph.get(AssetKey(["gold", "team_season_percentile_ranks"]))
    assert {
        ".".join(parent.path)
        for parent in percentile_ranks.parent_keys
    } == {"gold.team_season_four_factors"}

    player_features = asset_graph.get(AssetKey(["gold", "player_season_feature_matrix"]))
    assert {
        ".".join(parent.path)
        for parent in player_features.parent_keys
    } >= {
        "gold.player_season_embeddings",
        "gold.player_season_rapm",
    }

    game_flow = asset_graph.get(AssetKey(["gold", "game_flow_snapshots"]))
    assert {
        "silver.fct_play_by_play",
        "silver.fct_games",
        "gold.team_game_elo_history",
        "gold.model_artifacts",
    } <= {".".join(parent.path) for parent in game_flow.parent_keys}

    team_features = asset_graph.get(AssetKey(["gold", "team_season_feature_matrix"]))
    team_feature_parents = {".".join(parent.path) for parent in team_features.parent_keys}
    assert {
        "gold.team_season_four_factors",
        "gold.team_season_elo",
        "gold.team_game_stats",
    } <= team_feature_parents
    assert {
        "gold.player_season_embeddings",
        "gold.player_season_rapm",
    }.isdisjoint(team_feature_parents)


def test_stale_dbt_manifest_is_reparsed(tmp_path):
    from nba_duckdb import dbt_manifest

    project_dir = tmp_path / "project"
    model_dir = project_dir / "dbt" / "models" / "gold"
    manifest_path = project_dir / "dbt" / "target" / "manifest.json"
    model_dir.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    project_file = project_dir / "dbt_project.yml"
    profiles_file = project_dir / "dbt" / "profiles.yml"
    project_file.write_text("name: nba_analytics\n")
    profiles_file.write_text("nba_analytics: {}\n")
    model_path = model_dir / "player_season_feature_matrix.sql"
    model_path.write_text("select 1 as player_id\n")
    manifest_path.write_text("{}\n")
    os.utime(project_file, ns=(50, 50))
    os.utime(profiles_file, ns=(50, 50))
    os.utime(manifest_path, ns=(100, 100))
    os.utime(model_path, ns=(200, 200))

    calls: list[list[str]] = []

    assert (
        dbt_manifest.ensure_dbt_manifest(
            project_dir=project_dir,
            manifest_path=manifest_path,
            run_parse=lambda args: calls.append(args),
        )
        == manifest_path
    )
    assert calls == [["parse"]]


def test_current_dbt_manifest_is_reused(tmp_path):
    from nba_duckdb import dbt_manifest

    project_dir = tmp_path / "project"
    model_dir = project_dir / "dbt" / "models" / "gold"
    manifest_path = project_dir / "dbt" / "target" / "manifest.json"
    model_dir.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    project_file = project_dir / "dbt_project.yml"
    project_file.write_text("name: nba_analytics\n")
    model_path = model_dir / "team_season_feature_matrix.sql"
    model_path.write_text("select 1 as team_id\n")
    manifest_path.write_text("{}\n")
    os.utime(model_path, ns=(100, 100))
    os.utime(project_file, ns=(100, 100))
    os.utime(manifest_path, ns=(200, 200))

    calls: list[list[str]] = []

    assert (
        dbt_manifest.ensure_dbt_manifest(
            project_dir=project_dir,
            manifest_path=manifest_path,
            run_parse=lambda args: calls.append(args),
        )
        == manifest_path
    )
    assert calls == []


def test_dagster_dbt_translator_uses_shared_dataset_mapping():
    from nba_duckdb.definitions import NbaDbtTranslator

    translator = NbaDbtTranslator()

    assert translator.get_asset_key(
        {
            "resource_type": "model",
            "schema": "gold",
            "name": "internal_name",
            "alias": "published_model",
        }
    ) == AssetKey(["gold", "published_model"])
    assert translator.get_asset_key(
        {
            "resource_type": "source",
            "source_name": "gold_runtime",
            "schema": "gold_runtime",
            "name": "runtime_source",
            "identifier": "player_season_rapm",
        }
    ) == AssetKey(["gold", "player_season_rapm"])


def test_dagster_smoke_job_is_registered():
    from nba_duckdb.definitions import defs

    assert defs.resolve_job_def("smoke_job").name == "smoke_job"

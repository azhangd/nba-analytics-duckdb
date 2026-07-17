from __future__ import annotations

import os


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


def test_manifest_nodes_map_to_warehouse_datasets():
    from nba_duckdb.dbt_manifest import dbt_manifest_node_dataset

    assert dbt_manifest_node_dataset({
        "resource_type": "model",
        "schema": "gold",
        "name": "internal_name",
        "alias": "published_model",
    }) == "gold.published_model"
    assert dbt_manifest_node_dataset({
        "resource_type": "source",
        "source_name": "gold_runtime",
        "schema": "gold_runtime",
        "name": "runtime_source",
        "identifier": "player_season_rapm",
    }) == "gold.player_season_rapm"

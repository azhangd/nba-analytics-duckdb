"""Helpers for dbt manifest freshness and lineage inspection."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nba_duckdb.dbt_runner import dbt_project_dir, run_dbt_command

DBT_MANIFEST_SOURCE_SUFFIXES = frozenset({".sql", ".py", ".yml", ".yaml"})


def dbt_manifest_path(project_dir: Path | None = None) -> Path:
    project_root = project_dir or dbt_project_dir()
    return project_root / "dbt" / "target" / "manifest.json"


def dbt_manifest_source_paths(project_dir: Path | None = None) -> tuple[Path, ...]:
    project_root = project_dir or dbt_project_dir()
    paths = [
        path
        for path in (
            project_root / "dbt_project.yml",
            project_root / "dbt" / "profiles.yml",
            project_root / "packages.yml",
            project_root / "dbt" / "packages.yml",
        )
        if path.exists()
    ]
    for root in (project_root / "dbt" / "models", project_root / "dbt" / "macros"):
        if root.exists():
            paths.extend(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix in DBT_MANIFEST_SOURCE_SUFFIXES
            )
    return tuple(sorted(paths))


def dbt_manifest_is_stale(
    *,
    manifest_path: Path | None = None,
    project_dir: Path | None = None,
) -> bool:
    project_root = project_dir or dbt_project_dir()
    manifest = manifest_path or dbt_manifest_path(project_root)
    if not manifest.exists():
        return True
    manifest_mtime = manifest.stat().st_mtime_ns
    return any(path.stat().st_mtime_ns > manifest_mtime for path in dbt_manifest_source_paths(project_root))


def ensure_dbt_manifest(
    *,
    project_dir: Path | None = None,
    manifest_path: Path | None = None,
    run_parse: Callable[[list[str]], object] | None = None,
) -> Path:
    project_root = project_dir or dbt_project_dir()
    manifest = manifest_path or dbt_manifest_path(project_root)
    if dbt_manifest_is_stale(manifest_path=manifest, project_dir=project_root):
        parse = run_parse or (lambda args: run_dbt_command(args, project_dir=project_root))
        parse(["parse"])
    return manifest


def load_dbt_manifest(
    *,
    project_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    manifest = ensure_dbt_manifest(project_dir=project_dir, manifest_path=manifest_path)
    return json.loads(manifest.read_text())


def dbt_manifest_node_dataset(node: Mapping[str, Any]) -> str | None:
    resource_type = node.get("resource_type")
    if resource_type == "model":
        config = node.get("config", {})
        schema = node.get("schema")
        if schema is None and isinstance(config, Mapping):
            schema = config.get("schema")
        schema = schema or "main"
        name = node.get("alias") or node.get("name")
    elif resource_type == "source":
        source_name = node.get("source_name")
        schema = "gold" if source_name == "gold_runtime" else node.get("schema") or source_name
        name = node.get("identifier") or node.get("name")
    else:
        return None
    if not schema or not name:
        return None
    return f"{schema}.{name}"


def dbt_manifest_edges(manifest: Mapping[str, Any]) -> set[tuple[str, str]]:
    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})
    if not isinstance(nodes, Mapping) or not isinstance(sources, Mapping):
        return set()

    resources = {**nodes, **sources}
    edges: set[tuple[str, str]] = set()
    for node in nodes.values():
        if not isinstance(node, Mapping) or node.get("resource_type") != "model":
            continue
        target = dbt_manifest_node_dataset(node)
        if target is None:
            continue
        depends_on = node.get("depends_on", {})
        if not isinstance(depends_on, Mapping):
            continue
        dependency_ids = depends_on.get("nodes", [])
        if not isinstance(dependency_ids, list):
            continue
        for dependency_id in dependency_ids:
            dependency = resources.get(dependency_id)
            if not isinstance(dependency, Mapping):
                continue
            source = dbt_manifest_node_dataset(dependency)
            if source is not None:
                edges.add((source, target))
    return edges

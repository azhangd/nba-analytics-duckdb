"""Pure-data task and dataset registry for local pipeline graphs."""

from __future__ import annotations

import ast
import html
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_GRAPH = "default"
QUICK_GRAPH = "quick"
LIVE_MODE = "live"
FIXTURE_MODE = "fixture"

GRAPH_ORDER = (DEFAULT_GRAPH, QUICK_GRAPH)
MODE_ORDER = (LIVE_MODE, FIXTURE_MODE)
LAYER_ORDER = {
    "fixture": 0,
    "bronze": 10,
    "silver": 20,
    "gold": 30,
    "quality": 40,
}

ALL_GRAPHS = (DEFAULT_GRAPH, QUICK_GRAPH)
FULL_GRAPH = (DEFAULT_GRAPH,)
ALL_MODES = (LIVE_MODE, FIXTURE_MODE)
LIVE_ONLY = (LIVE_MODE,)
FIXTURE_ONLY = (FIXTURE_MODE,)
TASKS_ROOT = Path(__file__).resolve().parent / "tasks"


@dataclass(frozen=True)
class TaskDef:
    name: str
    layer: str
    task_type: str
    module_path: str = ""
    inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    mutates: tuple[str, ...] = ()
    graphs: frozenset[str] = field(default_factory=frozenset)
    modes: frozenset[str] = field(default_factory=frozenset)
    required: bool = True
    dbt_selector: str | None = None
    dbt_exclude: str | None = None
    dbt_models: tuple[str, ...] = ()
    regular_season_only: bool = True
    quality_outputs: tuple[str, ...] = ()
    sort_orders: Mapping[str, int] = field(default_factory=dict)


def _task_name(module_path: str) -> str:
    return module_path.rsplit(".", 1)[-1]


def _orders(*, live: int | None = None, fixture: int | None = None) -> Mapping[str, int]:
    values = {}
    if live is not None:
        values[LIVE_MODE] = live
    if fixture is not None:
        values[FIXTURE_MODE] = fixture
    return values


def _python(
    module_path: str,
    *,
    layer: str,
    inputs: Sequence[str] = (),
    optional_inputs: Sequence[str] = (),
    outputs: Sequence[str] = (),
    mutates: Sequence[str] = (),
    graphs: Iterable[str],
    modes: Iterable[str],
    task_type: str | None = None,
    required: bool = True,
    quality_outputs: Sequence[str] | None = None,
    regular_season_only: bool = True,
    live_order: int | None = None,
    fixture_order: int | None = None,
) -> TaskDef:
    declared_outputs = tuple(outputs)
    return TaskDef(
        name=_task_name(module_path),
        module_path=module_path,
        layer=layer,
        task_type=task_type or layer,
        inputs=tuple(inputs),
        optional_inputs=tuple(optional_inputs),
        outputs=declared_outputs,
        mutates=tuple(mutates),
        graphs=frozenset(graphs),
        modes=frozenset(modes),
        required=required,
        regular_season_only=regular_season_only,
        quality_outputs=declared_outputs if quality_outputs is None else tuple(quality_outputs),
        sort_orders=_orders(live=live_order, fixture=fixture_order),
    )


def _dbt_transform_task(metadata: Mapping[str, Any]) -> TaskDef:
    outputs = tuple(metadata["outputs"])
    return TaskDef(
        name=str(metadata.get("name", "dbt_build_warehouse")),
        module_path="",
        layer="gold",
        task_type="dbt",
        inputs=tuple(metadata.get("inputs", ())),
        optional_inputs=tuple(metadata.get("optional_inputs", ())),
        outputs=outputs,
        graphs=frozenset(metadata.get("graphs", FULL_GRAPH)),
        modes=frozenset(metadata.get("modes", ALL_MODES)),
        required=metadata.get("required", True),
        dbt_selector=str(metadata["dbt_selector"]),
        dbt_exclude=metadata.get("dbt_exclude"),
        dbt_models=tuple(metadata.get("dbt_models", ())),
        regular_season_only=metadata.get("regular_season_only", True),
        quality_outputs=tuple(metadata.get("quality_outputs", outputs)),
        sort_orders=_orders(
            live=metadata.get("live_order"),
            fixture=metadata.get("fixture_order"),
        ),
    )


def _module_path_for(file_path: Path) -> str:
    rel_path = file_path.relative_to(TASKS_ROOT.parent).with_suffix("")
    return "nba_duckdb." + ".".join(rel_path.parts)


def _literal_graph_metadata(file_path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(file_path.read_text(), filename=str(file_path))
    entries: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        target_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if "TASK_DEF" in target_names:
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                raise TypeError(f"{file_path}: TASK_DEF must be a dict")
            entries.append(value)
        if "TASK_DEFS" in target_names:
            value = ast.literal_eval(node.value)
            if not isinstance(value, list):
                raise TypeError(f"{file_path}: TASK_DEFS must be a list")
            for item in value:
                if not isinstance(item, dict):
                    raise TypeError(f"{file_path}: TASK_DEFS entries must be dicts")
                entries.append(item)
    return entries


def _task_from_metadata(module_path: str, metadata: Mapping[str, Any]) -> TaskDef:
    if "dbt_selector" in metadata:
        return _dbt_transform_task(metadata)

    quality_outputs = metadata["quality_outputs"] if "quality_outputs" in metadata else None
    return _python(
        module_path,
        layer=metadata["layer"],
        task_type=metadata.get("task_type"),
        inputs=metadata.get("inputs", ()),
        optional_inputs=metadata.get("optional_inputs", ()),
        outputs=metadata.get("outputs", ()),
        mutates=metadata.get("mutates", ()),
        graphs=metadata["graphs"],
        modes=metadata["modes"],
        required=metadata.get("required", True),
        quality_outputs=quality_outputs,
        regular_season_only=metadata.get("regular_season_only", True),
        live_order=metadata.get("live_order"),
        fixture_order=metadata.get("fixture_order"),
    )


@lru_cache(maxsize=1)
def _discover_task_defs() -> tuple[TaskDef, ...]:
    from nba_duckdb.dbt_models import DBT_FEATURE_TASK_DEF, DBT_TRANSFORM_TASK_DEF

    task_defs: list[TaskDef] = []
    for file_path in sorted(TASKS_ROOT.rglob("*.py")):
        if file_path.name == "__init__.py":
            continue
        metadata_entries = _literal_graph_metadata(file_path)
        if not metadata_entries:
            continue
        module_path = _module_path_for(file_path)
        task_defs.extend(_task_from_metadata(module_path, entry) for entry in metadata_entries)
    task_defs.append(_dbt_transform_task(DBT_TRANSFORM_TASK_DEF))
    task_defs.append(_dbt_transform_task(DBT_FEATURE_TASK_DEF))
    return tuple(task_defs)


TASK_DEFS: tuple[TaskDef, ...] = _discover_task_defs()


@lru_cache(maxsize=1)
def _dbt_manifest_lineage_edges() -> frozenset[tuple[str, str]]:
    from nba_duckdb.dbt_manifest import dbt_manifest_edges, load_dbt_manifest

    return frozenset(dbt_manifest_edges(load_dbt_manifest()))


def task_defs_for(graph: str, mode: str) -> list[TaskDef]:
    from nba_duckdb.dbt_models import DBT_MODEL_DATASETS

    dbt_owned = set(DBT_MODEL_DATASETS)
    selected = [
        task
        for task in TASK_DEFS
        if graph in task.graphs
        and mode in task.modes
        and (
            task.dbt_selector
            or not task.outputs
            or not set(task.outputs).issubset(dbt_owned)
        )
    ]
    return _toposort(selected, mode=mode)


def _toposort(tasks: Sequence[TaskDef], *, mode: str) -> list[TaskDef]:
    by_name = {task.name: task for task in tasks}
    if len(by_name) != len(tasks):
        raise ValueError("Duplicate task names in selected pipeline graph")

    producer_by_output: dict[str, str] = {}
    mutators_by_dataset: dict[str, set[str]] = {}
    for task in tasks:
        for output in task.outputs:
            if output in producer_by_output:
                raise ValueError(f"Dataset {output} has multiple producers")
            producer_by_output[output] = task.name
        for mutated in task.mutates:
            mutators_by_dataset.setdefault(mutated, set()).add(task.name)

    dependencies = {}
    for task in tasks:
        selected_inputs = (*task.inputs, *task.optional_inputs)
        output_deps = {
            producer_by_output[input_name]
            for input_name in selected_inputs
            if input_name in producer_by_output and producer_by_output[input_name] != task.name
        }
        mutation_deps = {
            mutator
            for input_name in selected_inputs
            if input_name not in task.mutates
            for mutator in mutators_by_dataset.get(input_name, set())
            if mutator != task.name
        }
        dependencies[task.name] = output_deps | mutation_deps
    dependents: dict[str, set[str]] = {task.name: set() for task in tasks}
    for task_name, deps in dependencies.items():
        for dep in deps:
            dependents[dep].add(task_name)

    def sort_key(task_name: str) -> tuple[int, int, int, str]:
        task = by_name[task_name]
        mode_order = task.sort_orders.get(mode, 10_000)
        return (mode_order, LAYER_ORDER.get(task.layer, 999), TASK_DEFS.index(task), task.name)

    ready = sorted((task.name for task in tasks if not dependencies[task.name]), key=sort_key)
    ordered: list[TaskDef] = []
    while ready:
        task_name = ready.pop(0)
        ordered.append(by_name[task_name])
        for dependent in sorted(dependents[task_name], key=sort_key):
            dependencies[dependent].discard(task_name)
            if not dependencies[dependent] and dependent not in ready:
                ready.append(dependent)
        ready.sort(key=sort_key)

    if len(ordered) != len(tasks):
        unresolved = sorted(set(by_name) - {task.name for task in ordered})
        raise ValueError(f"Cycle or unresolved dependency in task graph: {unresolved}")
    return ordered


def dbt_models_for(graph: str = DEFAULT_GRAPH) -> list[tuple[str, bool]]:
    models: list[tuple[str, bool]] = []
    for task in task_defs_for(graph, LIVE_MODE):
        if not task.dbt_models:
            continue
        models.extend((model, task.regular_season_only) for model in task.dbt_models)
    return models


def module_paths(*, graph: str | None = None, mode: str | None = None) -> list[str]:
    tasks = TASK_DEFS if graph is None or mode is None else task_defs_for(graph, mode)
    return [task.module_path for task in tasks if task.module_path]


def quality_required_tables() -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    tables: list[tuple[str, str]] = []
    for task in task_defs_for(DEFAULT_GRAPH, LIVE_MODE):
        for output in task.quality_outputs:
            schema, table = output.split(".", 1)
            key = (schema, table)
            if key not in seen:
                seen.add(key)
                tables.append(key)
    return tables


def _dataset_layer(dataset: str) -> str:
    return dataset.split(".", 1)[0]


def dataset_rows() -> list[dict[str, object]]:
    rows = []
    seen: set[tuple[str, str, str]] = set()
    for graph in ALL_GRAPHS:
        for mode in ALL_MODES:
            for task in task_defs_for(graph, mode):
                for output in (*task.outputs, *task.mutates):
                    key = (output, task.name, "mutates" if output in task.mutates else "produces")
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "dataset": output,
                        "task": task.name,
                        "layer": _dataset_layer(output),
                        "inputs": list(task.inputs),
                        "optional_inputs": list(task.optional_inputs),
                        "writes": "mutates" if output in task.mutates else "produces",
                        "graphs": sorted(task.graphs),
                        "modes": sorted(task.modes),
                        "required": task.required,
                    })
    return rows


def all_task_rows() -> list[dict[str, object]]:
    rows = []
    for task in TASK_DEFS:
        for output in (*task.outputs, *task.mutates):
            rows.append({
                "dataset": output,
                "task": task.name,
                "layer": _dataset_layer(output),
                "inputs": list(task.inputs),
                "optional_inputs": list(task.optional_inputs),
                "writes": "mutates" if output in task.mutates else "produces",
                "graphs": sorted(task.graphs),
                "modes": sorted(task.modes),
                "required": task.required,
            })
    return rows


def dataset_graph(graph: str = DEFAULT_GRAPH, mode: str = LIVE_MODE) -> dict[str, object]:
    tasks = task_defs_for(graph, mode)
    nodes: dict[str, dict[str, object]] = {}
    edges: list[dict[str, object]] = []

    def ensure_node(dataset: str) -> None:
        layer, _, table = dataset.partition(".")
        nodes.setdefault(
            dataset,
            {
                "dataset": dataset,
                "schema": layer,
                "table": table,
                "producers": [],
                "consumers": [],
            },
        )

    def append_consumer(dataset: str, task_name: str, *, optional: bool) -> None:
        consumer = {"task": task_name, "optional": optional}
        if consumer not in nodes[dataset]["consumers"]:
            nodes[dataset]["consumers"].append(consumer)

    for task in tasks:
        task_outputs = (*task.outputs, *task.mutates)
        dbt_edges: tuple[tuple[str, str], ...] = ()
        if task.dbt_selector:
            output_set = set(task_outputs)
            dbt_edges = tuple(
                sorted(
                    edge
                    for edge in _dbt_manifest_lineage_edges()
                    if edge[1] in output_set
                )
            )
        for dataset in (*task.inputs, *task.optional_inputs, *task_outputs):
            ensure_node(dataset)
        for source, target in dbt_edges:
            ensure_node(source)
            ensure_node(target)
        for dataset in task_outputs:
            write_kind = "mutates" if dataset in task.mutates else "produces"
            nodes[dataset]["producers"].append({"task": task.name, "writes": write_kind})
        for dataset in (*task.inputs, *task.optional_inputs):
            optional = dataset in task.optional_inputs
            append_consumer(dataset, task.name, optional=optional)
        if task.dbt_selector:
            for source, target in dbt_edges:
                append_consumer(source, task.name, optional=False)
                edges.append({
                    "from": source,
                    "to": target,
                    "task": task.name,
                    "optional": False,
                })
            continue
        for dataset in (*task.inputs, *task.optional_inputs):
            optional = dataset in task.optional_inputs
            for output in task_outputs:
                edges.append({
                    "from": dataset,
                    "to": output,
                    "task": task.name,
                    "optional": optional,
                })

    task_rows = [
        {
            "task": task.name,
            "layer": task.layer,
            "task_type": task.task_type,
            "inputs": list(task.inputs),
            "optional_inputs": list(task.optional_inputs),
            "outputs": list(task.outputs),
            "mutates": list(task.mutates),
            "required": task.required,
        }
        for task in tasks
    ]
    return {
        "graph": graph,
        "mode": mode,
        "tasks": task_rows,
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": edges,
    }


def dataset_graph_html(graph: str = DEFAULT_GRAPH, mode: str = LIVE_MODE) -> str:
    payload = dataset_graph(graph=graph, mode=mode)
    nodes = payload["nodes"]
    edges = payload["edges"]
    tasks = payload["tasks"]
    graph_json = html.escape(json.dumps(payload, indent=2), quote=False)
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['task']))}</td>"
        f"<td>{html.escape(str(row['layer']))}</td>"
        f"<td>{html.escape(', '.join(row['outputs'] or row['mutates']))}</td>"
        f"<td>{html.escape(', '.join(row['inputs']))}</td>"
        "</tr>"
        for row in tasks
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>NBA DuckDB Dataset Graph</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
    h1 {{ margin-bottom: 0.25rem; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
    th, td {{ border: 1px solid #d1d5db; padding: 0.5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    pre {{ background: #111827; color: #f9fafb; padding: 1rem; overflow: auto; }}
  </style>
</head>
<body>
  <h1>NBA DuckDB Dataset Graph</h1>
  <p>Graph: {html.escape(graph)} | Mode: {html.escape(mode)} | Tasks: {len(tasks)} | Datasets: {len(nodes)} | Edges: {len(edges)}</p>
  <table>
    <thead><tr><th>Task</th><th>Layer</th><th>Writes</th><th>Reads</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>Machine-readable graph</h2>
  <pre>{graph_json}</pre>
</body>
</html>
"""

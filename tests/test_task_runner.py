from types import SimpleNamespace

from nba_duckdb import registry, task_runner


def test_run_task_executes_registered_python_module(monkeypatch):
    task = registry.TaskDef(
        name="example_task",
        layer="bronze",
        task_type="bronze",
        module_path="example.module",
    )
    calls = []
    module = SimpleNamespace(run=lambda **scope: calls.append(scope) or 7)
    monkeypatch.setattr(task_runner.importlib, "import_module", lambda _: module)

    result = task_runner.run_task(task, scope={"season": "2025-26"})

    assert result == {"result": 7}
    assert calls == [{"season": "2025-26"}]


def test_run_task_builds_dbt_selector_with_exclude_and_full_refresh(monkeypatch):
    task = registry.TaskDef(
        name="dbt_build_warehouse",
        layer="gold",
        task_type="dbt",
        dbt_selector="tag:silver tag:gold",
        dbt_exclude="tag:requires_gold_runtime",
        dbt_models=("dim_players", "player_season_stats"),
    )
    commands = []
    monkeypatch.setattr(task_runner, "run_dbt_command", commands.append)

    result = task_runner.run_task(task, scope={"full_refresh": True})

    assert commands == [
        [
            "build",
            "--select",
            "tag:silver tag:gold",
            "--exclude",
            "tag:requires_gold_runtime",
            "--full-refresh",
        ]
    ]
    assert result == {
        "status": "success",
        "dbt_selector": "tag:silver tag:gold",
        "dbt_exclude": "tag:requires_gold_runtime",
        "models_built": 2,
    }

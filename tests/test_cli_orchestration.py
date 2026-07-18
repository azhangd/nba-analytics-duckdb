import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nba_duckdb.orchestration import TaskSpec


def _flatten_step_names(steps):
    return [step.name for step in steps]


def _scope():
    return {
        "season": "2025-26",
        "seasons": ["2025-26"],
        "game_ids": None,
        "competitions": ["nba"],
        "full_refresh": False,
        "start_date": None,
        "end_date": None,
    }


def test_run_live_default_builds_full_warehouse_graph():
    from nba_duckdb import cli

    names = _flatten_step_names(cli._live_steps("default", _scope()))

    assert names == [
        "ingest_schedule",
        "ingest_rosters",
        "ingest_boxscores",
        "ingest_play_by_play",
        "ingest_shot_charts",
        "ingest_standings",
        "ingest_tracking_stats",
        "ingest_hustle",
        "ingest_matchups",
        "ingest_defense",
        "ingest_tracking",
        "ingest_game_detail",
        "ingest_injuries",
        "dbt_build_warehouse",
        "compute_rapm",
        "compute_win_prob_model",
        "refresh_player_off_court_signals",
        "compute_shot_quality_trained",
        "compute_player_embeddings",
        "dbt_build_feature_matrices",
    ]
    assert {step.task_type for step in cli._live_steps("default", _scope())} == {
        "bronze",
        "dbt",
        "gold",
    }


def test_run_live_quick_keeps_small_iteration_graph():
    from nba_duckdb import cli

    names = _flatten_step_names(cli._live_steps("quick", _scope()))

    assert names == [
        "ingest_schedule",
        "ingest_rosters",
        "ingest_boxscores",
        "ingest_play_by_play",
    ]
    assert {step.task_type for step in cli._live_steps("quick", _scope())} == {"bronze"}


def test_summer_league_command_uses_dedicated_graph():
    from nba_duckdb import cli

    names = _flatten_step_names(
        cli._live_steps(cli.SUMMER_LEAGUE_GRAPH, _scope())
    )

    assert names == [
        "ingest_schedule",
        "ingest_boxscores",
        "ingest_play_by_play",
        "ingest_shot_charts",
        "dbt_build_summer_league",
        "validate_summer_league",
    ]


def test_public_cli_uses_current_command_names():
    from nba_duckdb.cli import build_parser

    help_text = build_parser().format_help()

    assert "run-smoke" in help_text
    assert "run-summer-league" in help_text
    assert "generate-test-fixtures" in help_text
    assert "quality" in help_text
    assert "runs" in help_text
    assert "backfill-source" in help_text
    assert "ingestion-status" in help_text
    assert "datasets" in help_text
    assert "d" + "bt" not in help_text
    assert "run-" + "fixture" + "-pipeline" not in help_text
    assert "generate-" + "fixtures" not in help_text


def test_runner_retry_defaults_match_command_purpose():
    from nba_duckdb.cli import build_parser

    parser = build_parser()
    live_args = parser.parse_args(["run-live"])
    smoke_args = parser.parse_args(["run-smoke"])
    quick_args = parser.parse_args(["run-live", "--quick"])
    summer_args = parser.parse_args(["run-summer-league", "--season", "2026-27"])

    assert live_args.retries == 2
    assert live_args.retry_delay_seconds == 120.0
    assert smoke_args.retries == 0
    assert smoke_args.retry_delay_seconds == 0.0
    assert quick_args.quick is True
    assert summer_args.competitions == [
        "summer_league_california",
        "summer_league_vegas",
        "summer_league_salt_lake_city",
    ]
    assert summer_args.retries == 2


def _hide_optional_modules(monkeypatch, missing_modules):
    from nba_duckdb import dependencies

    real_find_spec = dependencies.find_spec
    missing = set(missing_modules)

    def fake_find_spec(module_name):
        if module_name in missing:
            return None
        return real_find_spec(module_name)

    monkeypatch.setattr(dependencies, "find_spec", fake_find_spec)


def test_run_smoke_default_missing_full_extras_fails_before_writing_warehouse(
    tmp_path,
    monkeypatch,
    capsys,
):
    from nba_duckdb import cli

    smoke_path = tmp_path / "smoke.duckdb"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.setenv("NBA_DUCKDB_SMOKE_PATH", str(smoke_path))
    _hide_optional_modules(
        monkeypatch,
        {
            "sklearn",
            "scipy",
            "xgboost",
            "umap",
            "joblib",
        },
    )
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "run-smoke"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "missing_optional_dependency"
    assert payload["groups"] == ["ml"]
    assert "sklearn" in payload["missing_modules"]
    assert "dbt" not in payload["missing_modules"]
    assert payload["install_command"] == "uv sync --extra dev --extra full"
    assert payload["pip_install_command"] == 'python -m pip install -e ".[dev,full]"'
    assert payload["quick_command"] == "uv run nba-duckdb run-smoke --quick"
    assert not smoke_path.exists()


def test_run_smoke_quick_does_not_require_ml(tmp_path, monkeypatch, capsys):
    from nba_duckdb import cli

    smoke_path = tmp_path / "smoke.duckdb"
    quick_smoke_path = tmp_path / "smoke-quick.duckdb"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.setenv("NBA_DUCKDB_SMOKE_PATH", str(smoke_path))
    monkeypatch.setenv("NBA_DUCKDB_QUICK_SMOKE_PATH", str(quick_smoke_path))
    _hide_optional_modules(
        monkeypatch,
        {
            "sklearn",
            "scipy",
            "xgboost",
            "umap",
            "joblib",
        },
    )
    monkeypatch.setattr(cli, "_offline_smoke_steps", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "run_steps", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "run-smoke", "--quick"])

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "ok"}
    assert quick_smoke_path.exists()
    assert not smoke_path.exists()


def test_run_live_quick_missing_live_extra_fails_before_init(
    tmp_path,
    monkeypatch,
    capsys,
):
    from nba_duckdb import cli

    db_path = tmp_path / "live.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(db_path))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    _hide_optional_modules(monkeypatch, {"nba_api", "pdfplumber"})
    monkeypatch.setattr(
        sys,
        "argv",
        ["nba-duckdb", "run-live", "--quick", "--season", "2025-26"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "missing_optional_dependency"
    assert payload["groups"] == ["live"]
    assert "nba_api" in payload["missing_modules"]
    assert payload["install_command"] == "uv sync --extra dev --extra live"
    assert payload["pip_install_command"] == 'python -m pip install -e ".[dev,live]"'
    assert "quick_command" not in payload
    assert not db_path.exists()


def test_backfill_source_missing_live_extra_fails_before_init(
    tmp_path,
    monkeypatch,
    capsys,
):
    from nba_duckdb import cli

    db_path = tmp_path / "live.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(db_path))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    _hide_optional_modules(monkeypatch, {"nba_api", "pdfplumber"})
    monkeypatch.setattr(
        sys,
        "argv",
        ["nba-duckdb", "backfill-source", "play-by-play", "--season", "2025-26"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "missing_optional_dependency"
    assert payload["groups"] == ["live"]
    assert payload["install_command"] == "uv sync --extra dev --extra live"
    assert payload["pip_install_command"] == 'python -m pip install -e ".[dev,live]"'
    assert "quick_command" not in payload
    assert not db_path.exists()


def test_run_live_default_with_live_extra_missing_ml_reports_ml_only(
    tmp_path,
    monkeypatch,
    capsys,
):
    pytest.importorskip("nba_api")
    pytest.importorskip("pdfplumber")
    from nba_duckdb import cli

    db_path = tmp_path / "live.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(db_path))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    _hide_optional_modules(
        monkeypatch,
        {
            "sklearn",
            "scipy",
            "xgboost",
            "umap",
            "joblib",
        },
    )
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "run-live", "--season", "2025-26"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "missing_optional_dependency"
    assert payload["groups"] == ["ml"]
    assert payload["install_command"] == "uv sync --extra dev --extra full"
    assert payload["pip_install_command"] == 'python -m pip install -e ".[dev,full]"'
    assert "quick_command" not in payload
    assert not db_path.exists()


def test_run_live_quick_with_live_extra_does_not_require_ml(
    tmp_path,
    monkeypatch,
    capsys,
):
    pytest.importorskip("nba_api")
    pytest.importorskip("pdfplumber")
    from nba_duckdb import cli

    db_path = tmp_path / "live.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(db_path))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    _hide_optional_modules(monkeypatch, {"sklearn", "scipy", "xgboost", "umap", "joblib"})
    monkeypatch.setattr(cli, "run_steps", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(
        sys,
        "argv",
        ["nba-duckdb", "run-live", "--quick", "--season", "2025-26"],
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "ok"}


def test_run_smoke_defaults_to_separate_smoke_warehouse(tmp_path, monkeypatch):
    from nba_duckdb import cli

    smoke_path = tmp_path / "smoke.duckdb"
    live_path = tmp_path / "live.duckdb"
    captured = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_SMOKE_PATH", raising=False)
    Path(".env").write_text(
        f"NBA_DUCKDB_PATH={live_path}\n"
        f"NBA_DUCKDB_DATABASE_URL=duckdb:///{live_path}\n"
        f"NBA_DUCKDB_SMOKE_PATH={smoke_path}\n"
    )
    monkeypatch.setattr(cli, "_offline_smoke_steps", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "require_optional_groups", lambda *_args, **_kwargs: None)

    def fake_prepare_run(**kwargs):
        captured["prepare_run"] = kwargs
        return SimpleNamespace(graph=kwargs["graph"], scope=kwargs["scope"])

    def fake_run_steps(context, steps, **kwargs):
        captured["run_steps"] = {
            "context": context,
            "steps": steps,
            "kwargs": kwargs,
        }
        return {"status": "ok"}

    monkeypatch.setattr(cli, "prepare_run", fake_prepare_run)
    monkeypatch.setattr(cli, "run_steps", fake_run_steps)

    result = cli.run_offline_smoke(
        argparse.Namespace(
            fixtures_dir=None,
            init_schema=True,
            quick=False,
            source=None,
            run_id=None,
            resume_latest=False,
            retry_failed=False,
            retries=0,
            retry_delay_seconds=0.0,
        )
    )

    assert result == {"status": "ok"}
    assert captured["prepare_run"]["scope"]["warehouse"] == str(smoke_path)
    assert smoke_path.exists()
    assert not live_path.exists()
    assert os.environ.get("NBA_DUCKDB_PATH") is None
    assert os.environ.get("NBA_DUCKDB_DATABASE_URL") is None


def test_run_smoke_cli_ignores_dotenv_live_warehouse_after_env_load(
    tmp_path,
    monkeypatch,
    capsys,
):
    from nba_duckdb import cli, config

    smoke_path = tmp_path / "smoke.duckdb"
    live_path = tmp_path / "live.duckdb"

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_SMOKE_PATH", raising=False)
    Path(".env").write_text(
        f"NBA_DUCKDB_PATH={live_path}\n"
        f"NBA_DUCKDB_DATABASE_URL=duckdb:///{live_path}\n"
        f"NBA_DUCKDB_SMOKE_PATH={smoke_path}\n"
    )
    config.load_env_file()
    assert os.environ["NBA_DUCKDB_PATH"] == str(live_path)
    assert os.environ["NBA_DUCKDB_DATABASE_URL"] == f"duckdb:///{live_path}"

    monkeypatch.setattr(cli, "_offline_smoke_steps", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "run_steps", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(cli, "require_optional_groups", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "run-smoke"])

    try:
        cli.main()

        payload = json.loads(capsys.readouterr().out)
        assert payload == {"status": "ok"}
        assert smoke_path.exists()
        assert not live_path.exists()
        assert os.environ["NBA_DUCKDB_PATH"] == str(live_path)
        assert os.environ["NBA_DUCKDB_DATABASE_URL"] == f"duckdb:///{live_path}"
    finally:
        for key in (
            "NBA_DUCKDB_PATH",
            "NBA_DUCKDB_DATABASE_URL",
            "NBA_DUCKDB_SMOKE_PATH",
            "NBA_DUCKDB_QUICK_SMOKE_PATH",
        ):
            os.environ.pop(key, None)
        config.get_settings.cache_clear()


def _assert_run_live_refuses_current_warehouse(monkeypatch, capsys, expected_table=None):
    from nba_duckdb import cli

    monkeypatch.setattr(cli, "require_optional_groups", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "run-live", "--season", "2025-26"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "synthetic_data_in_live_warehouse"
    assert "data/warehouse/smoke.duckdb" in payload["error"]
    if expected_table is not None:
        assert expected_table in payload["error"]


def test_run_live_refuses_synthetic_smoke_season(tmp_path, monkeypatch, capsys):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "polluted.duckdb"))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_SMOKE_PATH", raising=False)
    db.init_schema()
    db.insert_rows(
        "bronze",
        "schedule",
        [{"game_id": "0029900001", "season": "2099-00"}],
    )

    _assert_run_live_refuses_current_warehouse(monkeypatch, capsys)


def test_run_live_refuses_synthetic_smoke_game_id(tmp_path, monkeypatch, capsys):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "polluted.duckdb"))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_SMOKE_PATH", raising=False)
    db.init_schema()
    db.insert_rows(
        "bronze",
        "schedule",
        [{"game_id": "002SYN0001", "season": "2025-26"}],
    )

    _assert_run_live_refuses_current_warehouse(monkeypatch, capsys)


def test_run_live_refuses_synthetic_rows_in_downstream_tables(
    tmp_path,
    monkeypatch,
    capsys,
):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "polluted.duckdb"))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_SMOKE_PATH", raising=False)
    db.init_schema()
    db.execute(
        """
        CREATE TABLE gold.team_game_stats (
            game_id TEXT,
            team_id INTEGER,
            season TEXT,
            game_date TEXT
        )
        """
    )
    db.insert_rows(
        "gold",
        "team_game_stats",
        [
            {
                "game_id": "002SYN9999",
                "team_id": 1610612737,
                "season": "2025-26",
                "game_date": "01/01/2026",
            }
        ],
    )

    _assert_run_live_refuses_current_warehouse(
        monkeypatch,
        capsys,
        expected_table="gold.team_game_stats",
    )


def test_run_live_no_init_schema_before_init_returns_friendly_json(
    tmp_path,
    monkeypatch,
    capsys,
):
    from nba_duckdb import cli

    db_path = tmp_path / "missing.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(db_path))
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "require_optional_groups", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["nba-duckdb", "run-live", "--no-init-schema", "--season", "2025-26"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "not_initialized"
    assert "nba-duckdb init" in payload["error"]
    assert not db_path.exists()


def test_old_graph_names_are_not_public_cli_choices():
    from nba_duckdb.cli import build_parser

    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["run-live", "--profile", "core"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run-live", "--profile", "full"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run-live", "--profile", "exp" + "erimental"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run-live", "--" + "exp" + "erimental"])


def test_task_graph_modules_import():
    from nba_duckdb import registry
    from nba_duckdb.dependencies import missing_modules_for_groups

    if missing := missing_modules_for_groups("live", "ml"):
        pytest.skip(f"full live graph import test requires full extras: {', '.join(missing)}")

    module_paths = [
        *registry.module_paths(
            graph=registry.DEFAULT_GRAPH,
            mode=registry.LIVE_MODE,
        ),
        *registry.module_paths(
            graph=registry.QUICK_GRAPH,
            mode=registry.LIVE_MODE,
        ),
    ]

    for module_path in sorted(set(module_paths)):
        importlib.import_module(module_path)


def test_default_live_gold_tasks_are_recorded_as_gold():
    from nba_duckdb import cli

    steps = cli._live_steps("default", _scope())
    task_types = {step.name: step.task_type for step in steps if isinstance(step, TaskSpec)}

    assert {
        task_name for task_name, task_type in task_types.items() if task_type == "gold"
    } == {
        "compute_rapm",
        "compute_win_prob_model",
        "refresh_player_off_court_signals",
        "compute_shot_quality_trained",
        "compute_player_embeddings",
    }
    assert task_types["dbt_build_warehouse"] == "dbt"
    assert task_types["dbt_build_feature_matrices"] == "dbt"


def test_datasets_graph_cli_can_write_html(tmp_path):
    from nba_duckdb import cli

    output = tmp_path / "lineage.html"
    result = cli.graph_datasets(
        argparse.Namespace(
            quick=False,
            mode="live",
            format="html",
            output=str(output),
        )
    )

    assert result["status"] == "ok"
    assert output.exists()
    assert "NBA DuckDB Dataset Graph" in output.read_text()


def test_datasets_graph_cli_returns_json_graph():
    from nba_duckdb import cli

    result = cli.graph_datasets(
        argparse.Namespace(
            quick=True,
            mode="fixture",
            format="json",
            output=None,
        )
    )

    assert result["graph"] == "quick"
    assert result["mode"] == "fixture"
    assert [task["task"] for task in result["tasks"]] == ["load_synthetic_fixtures"]


def test_datasets_graph_cli_returns_manifest_backed_default_json_graph():
    from nba_duckdb import cli

    result = cli.graph_datasets(
        argparse.Namespace(
            quick=False,
            mode="live",
            format="json",
            output=None,
        )
    )
    edges = {(edge["from"], edge["to"], edge["task"]) for edge in result["edges"]}

    assert result["graph"] == "default"
    assert result["mode"] == "live"
    assert (
        "gold.player_game_stats",
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
        "gold.team_season_feature_matrix",
        "dbt_build_warehouse",
    ) not in edges


def test_ingestion_status_uses_read_only_summary(monkeypatch):
    from nba_duckdb import cli

    captured = {}

    def fake_summarize_sources(*, season, source, read_only):
        captured.update({"season": season, "source": source, "read_only": read_only})
        return [{"source": source, "season": season, "total_items": 0, "status_counts": {}}]

    monkeypatch.setattr(cli, "summarize_sources", fake_summarize_sources)

    result = cli.ingestion_status(argparse.Namespace(season="2099-00", source="play-by-play"))

    assert captured == {"season": "2099-00", "source": "play-by-play", "read_only": True}
    assert result["ingestion_items"][0]["source"] == "play-by-play"


def test_ingestion_status_before_init_returns_friendly_json(tmp_path, monkeypatch, capsys):
    from nba_duckdb import cli

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "ingestion-status"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "not_initialized"
    assert "nba-duckdb init" in payload["error"]


def test_runs_show_before_init_returns_friendly_json(tmp_path, monkeypatch, capsys):
    from nba_duckdb import cli

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "runs", "show", "missing-run"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "not_initialized"
    assert "nba-duckdb init" in payload["error"]


def test_quality_before_init_returns_friendly_json(tmp_path, monkeypatch, capsys):
    from nba_duckdb import cli

    db_path = tmp_path / "missing.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(db_path))
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "quality"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 1
    assert payload["status"] == "not_initialized"
    assert "nba-duckdb init" in payload["error"]
    assert not db_path.exists()


def test_cli_lock_timeout_returns_warehouse_busy_json(monkeypatch, capsys):
    from nba_duckdb import cli
    from nba_duckdb.db import DuckDBLockTimeoutError

    def raise_lock(_args):
        raise DuckDBLockTimeoutError("locked by another process")

    monkeypatch.setattr(cli, "init_db", raise_lock)
    monkeypatch.setattr(sys, "argv", ["nba-duckdb", "init"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    payload = json.loads(capsys.readouterr().err)
    assert exc_info.value.code == 2
    assert payload == {
        "status": "warehouse_busy",
        "error": "locked by another process",
    }


def test_duckdb_lock_timeout_is_bounded(tmp_path, monkeypatch):
    from nba_duckdb import db

    def raise_lock(*_args, **_kwargs):
        raise db.duckdb.IOException("Could not set lock on file")

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "locked.duckdb"))
    monkeypatch.setattr(db, "LOCK_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(db, "LOCK_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(db.duckdb, "connect", raise_lock)

    with pytest.raises(db.DuckDBLockTimeoutError, match="warehouse is locked"):
        db.get_conn()

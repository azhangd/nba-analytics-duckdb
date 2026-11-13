import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """A fresh warehouse with the schema initialised, used as `db`."""
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def smoke_args(*, quick: bool = False):
    import argparse

    return argparse.Namespace(
        fixtures_dir=None,
        quick=quick,
        init_schema=True,
        run_id=None,
        resume_latest=False,
        retry_failed=False,
        retries=0,
        retry_delay_seconds=0.0,
    )


@pytest.fixture(scope="session")
def _smoke_template(tmp_path_factory):
    """Build the full offline smoke warehouse once per test session."""
    from nba_duckdb.dependencies import missing_modules_for_groups

    if missing := missing_modules_for_groups("ml"):
        pytest.skip(f"full smoke needs the ml extra: {', '.join(missing)}")

    from nba_duckdb.cli import run_offline_smoke

    root = tmp_path_factory.mktemp("smoke-template")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("NBA_DUCKDB_PATH", str(root / "smoke.duckdb"))
        mp.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(root / "artifacts"))
        mp.setenv("NBA_DUCKDB_FIXTURES_DIR", str(root / "fixtures"))
        result = run_offline_smoke(smoke_args())
    assert result["status"] == "success"
    return root


@pytest.fixture
def smoke_db(_smoke_template, tmp_path, monkeypatch):
    """A private copy of the full smoke warehouse, used as `db`."""
    import shutil

    from nba_duckdb import db

    shutil.copy(_smoke_template / "smoke.duckdb", tmp_path / "smoke.duckdb")
    shutil.copytree(_smoke_template / "artifacts", tmp_path / "artifacts")
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "smoke.duckdb"))
    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NBA_DUCKDB_FIXTURES_DIR", str(_smoke_template / "fixtures"))
    return db


SCHEDULE_DEFAULTS = {
    "game_id": "0029900001",
    "game_date": "01/01/2100 00:00:00",
    "home_team_id": 1610612737,
    "away_team_id": 1610612738,
    "home_team_abbr": "AAA",
    "away_team_abbr": "BBB",
    "game_status": 3,
    "game_status_text": "Final",
    "season": "2099-00",
    "raw_json": "{}",
}


def schedule_row(**overrides):
    """A final regular-season `bronze.schedule` row; pass only the fields that differ."""
    return {**SCHEDULE_DEFAULTS, **overrides}

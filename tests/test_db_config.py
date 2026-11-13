from pathlib import Path

from nba_duckdb.db import database_path


def test_settings_use_documented_duckdb_path_env(monkeypatch, tmp_path):
    from nba_duckdb.config import get_settings

    target = tmp_path / "custom.duckdb"
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(target))
    get_settings.cache_clear()

    try:
        assert get_settings().duckdb_path == target
    finally:
        get_settings.cache_clear()


def test_dotenv_path_is_shared_by_db_and_settings(monkeypatch, tmp_path):
    from nba_duckdb.config import get_settings

    target = tmp_path / "from-dotenv.duckdb"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    (tmp_path / ".env").write_text(f"NBA_DUCKDB_PATH={target}\n")
    get_settings.cache_clear()

    try:
        assert database_path() == Path(target)
        assert get_settings().duckdb_path == target
    finally:
        get_settings.cache_clear()

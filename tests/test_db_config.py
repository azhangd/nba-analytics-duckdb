from nba_duckdb.db import DEFAULT_DATABASE_URL, get_database_url


def test_database_url_uses_project_specific_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "ignored://example")

    assert get_database_url() == DEFAULT_DATABASE_URL

    monkeypatch.setenv("NBA_DUCKDB_DATABASE_URL", "tmp/example.duckdb")

    assert get_database_url() == "tmp/example.duckdb"


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
    monkeypatch.delenv("NBA_DUCKDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    (tmp_path / ".env").write_text(f"NBA_DUCKDB_PATH={target}\n")
    get_settings.cache_clear()

    try:
        assert get_database_url() == str(target)
        assert get_settings().duckdb_path == target
    finally:
        get_settings.cache_clear()

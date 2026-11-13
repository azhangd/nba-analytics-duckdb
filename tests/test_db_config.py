from pathlib import Path

from nba_duckdb.db import database_path


def test_database_path_reads_dotenv(monkeypatch, tmp_path):
    target = tmp_path / "from-dotenv.duckdb"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    (tmp_path / ".env").write_text(f"NBA_DUCKDB_PATH={target}\n")

    assert database_path() == Path(target)
    
import pytest

pytest.importorskip("nba_api")


def test_offline_smoke_blocks_nba_api_fetches(monkeypatch):
    from nba_duckdb.utils import nba_client

    monkeypatch.setenv("NBA_DUCKDB_OFFLINE_SMOKE", "1")

    with pytest.raises(RuntimeError, match="disabled during offline smoke"):
        nba_client.get_schedule("2099-00")


def test_offline_smoke_blocks_injury_report_http(monkeypatch):
    from nba_duckdb.tasks.bronze import ingest_injuries

    monkeypatch.setenv("NBA_DUCKDB_OFFLINE_SMOKE", "1")

    with pytest.raises(RuntimeError, match="disabled during offline smoke"):
        ingest_injuries.run()

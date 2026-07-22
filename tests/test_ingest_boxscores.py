import json

import pytest

pytest.importorskip("nba_api")


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def test_existing_traditional_boxscore_is_complete_without_advanced(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
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
        ],
    )
    db.insert_rows(
        "bronze",
        "boxscores",
        [
            {
                "game_id": "0029900001",
                "traditional_json": json.dumps({"game": {"homeTeam": {}}}),
                "advanced_json": None,
            }
        ],
    )

    from nba_duckdb.tasks.bronze import ingest_boxscores

    calls = []

    def fake_fetch(*_args, **_kwargs):
        calls.append("fetch")
        raise AssertionError("completed traditional boxscore should not be refetched")

    monkeypatch.setattr(
        ingest_boxscores.nba_client,
        "get_boxscore_with_source",
        fake_fetch,
    )
    monkeypatch.setattr(ingest_boxscores.nba_client, "get_boxscore_advanced", fake_fetch)

    result = ingest_boxscores.run(season="2099-00")

    assert result["rows_written"] == 0
    assert calls == []

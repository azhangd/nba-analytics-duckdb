import json

import pytest
from conftest import schedule_row

pytest.importorskip("nba_api")


def test_existing_traditional_boxscore_is_complete_without_advanced(tmp_db, monkeypatch):
    db = tmp_db
    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row()
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

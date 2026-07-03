import json

import pytest

from nba_duckdb.exceptions import LiveEndpointUnavailableError

pytest.importorskip("nba_api")


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def _insert_schedule(db, game_ids):
    rows = []
    for index, game_id in enumerate(game_ids):
        rows.append(
            {
                "game_id": game_id,
                "game_date": "01/01/2100 00:00:00",
                "home_team_id": 1610612737,
                "away_team_id": 1610612738,
                "home_team_abbr": "AAA",
                "away_team_abbr": "BBB",
                "game_status": 3,
                "game_status_text": "Final",
                "season": "2099-00",
                "raw_json": json.dumps({"index": index}),
            }
        )
    db.insert_rows("bronze", "schedule", rows)


def test_play_by_play_ingest_writes_rows_and_ledger(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    _insert_schedule(db, ["0029900001", "0029900002"])

    from nba_duckdb.tasks.bronze import ingest_play_by_play

    def fake_fetch(game_id, **_kwargs):
        return {"game": {"actions": [{"actionNumber": 1, "gameId": game_id}]}}, "live_cdn"

    monkeypatch.setattr(ingest_play_by_play.nba_client, "get_play_by_play_with_source", fake_fetch)

    result = ingest_play_by_play.run(season="2099-00")

    assert result["rows_written"] == 2
    assert db.count_rows("bronze", "play_by_play") == 2
    sources = db.execute("SELECT DISTINCT source FROM bronze.play_by_play ORDER BY source")
    assert sources == [{"source": "live_cdn"}]
    assert result["item_state"]["status_counts"] == {"success": 2}


def test_play_by_play_resume_skips_existing_rows(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    _insert_schedule(db, ["0029900001", "0029900002"])
    db.insert_rows(
        "bronze",
        "play_by_play",
        [{"game_id": "0029900001", "pbp_json": '{"game":{"actions":[{}]}}'}],
    )

    from nba_duckdb.tasks.bronze import ingest_play_by_play

    fetched = []

    def fake_fetch(game_id, **_kwargs):
        fetched.append(game_id)
        return {"game": {"actions": [{"actionNumber": 1, "gameId": game_id}]}}, "stats_v3"

    monkeypatch.setattr(ingest_play_by_play.nba_client, "get_play_by_play_with_source", fake_fetch)

    result = ingest_play_by_play.run(season="2099-00")

    assert fetched == ["0029900002"]
    assert result["rows_written"] == 1
    assert result["item_state"]["status_counts"] == {"success": 2}


def test_play_by_play_abort_flushes_in_flight_batch(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    game_ids = [f"002990000{i}" for i in range(1, 6)]
    _insert_schedule(db, game_ids)

    from nba_duckdb.tasks.bronze import ingest_play_by_play

    monkeypatch.setenv("NBA_DUCKDB_PBP_FLUSH_EVERY", "10")
    monkeypatch.setenv("NBA_DUCKDB_PBP_ABORT_AFTER_FAILURES", "3")
    calls = []

    def fake_fetch(game_id, **_kwargs):
        calls.append(game_id)
        if len(calls) <= 2:
            return {"game": {"actions": [{"actionNumber": 1, "gameId": game_id}]}}, "live_cdn"
        raise LiveEndpointUnavailableError("blocked")

    monkeypatch.setattr(ingest_play_by_play.nba_client, "get_play_by_play_with_source", fake_fetch)

    with pytest.raises(LiveEndpointUnavailableError, match="run-live --resume-latest"):
        ingest_play_by_play.run(season="2099-00")

    assert db.count_rows("bronze", "play_by_play") == 2


def test_play_by_play_pending_retry_items_do_not_report_success(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    _insert_schedule(db, ["0029900001"])

    from nba_duckdb.ingestion_state import eligible_items, make_item, mark_item_failed
    from nba_duckdb.tasks.bronze import ingest_play_by_play

    item = make_item("0029900001", "2099-00")
    eligible_items("play-by-play", [item])
    mark_item_failed("play-by-play", item, "blocked", retry_delay_seconds=3600)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("item in retry backoff should not be fetched")

    monkeypatch.setattr(
        ingest_play_by_play.nba_client,
        "get_play_by_play_with_source",
        fail_if_called,
    )

    with pytest.raises(RuntimeError, match="incomplete for targeted games"):
        ingest_play_by_play.run(season="2099-00")

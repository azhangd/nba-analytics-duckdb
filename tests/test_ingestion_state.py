from nba_duckdb.ingestion_state import (
    eligible_items,
    make_item,
    mark_item_failed,
    mark_item_running,
    mark_item_success,
    mark_running_items_interrupted,
    summarize_source,
)


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def test_ingestion_items_track_success_failure_and_retry(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    item_a = make_item("0029900001", "2099-00")
    item_b = make_item("0029900002", "2099-00")

    assert eligible_items("play-by-play", [item_a, item_b]) == [item_a, item_b]
    mark_item_running("play-by-play", item_a)
    mark_item_success("play-by-play", item_a, rows_written=1)
    mark_item_running("play-by-play", item_b)
    mark_item_failed("play-by-play", item_b, RuntimeError("rate limited"))

    retryable = eligible_items("play-by-play", [item_a, item_b])
    summary = summarize_source("play-by-play", "2099-00")

    assert retryable == [item_b]
    assert summary["total_items"] == 2
    assert summary["status_counts"] == {"failed": 1, "success": 1}


def test_running_items_can_be_marked_interrupted_for_crash_recovery(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    item = make_item("0029900001", "2099-00", team_id=1610612737)

    eligible_items("shot-charts", [item])
    mark_item_running("shot-charts", item)
    mark_running_items_interrupted("shot-charts", "2099-00")

    assert eligible_items("shot-charts", [item]) == [item]
    assert summarize_source("shot-charts", "2099-00")["status_counts"] == {"interrupted": 1}

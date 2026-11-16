import pytest
from conftest import schedule_row

from nba_duckdb.ingestion_state import (
    eligible_items,
    make_item,
    mark_item_failed,
    mark_item_running,
    mark_item_success,
    mark_running_items_interrupted,
    summarize_source,
)


def test_ingestion_items_track_success_failure_and_retry(tmp_db):
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


def test_running_items_can_be_marked_interrupted_for_crash_recovery(tmp_db):
    item = make_item("0029900001", "2099-00", team_id=1610612737)

    eligible_items("shot-charts", [item])
    mark_item_running("shot-charts", item)
    mark_running_items_interrupted("shot-charts", "2099-00")

    assert eligible_items("shot-charts", [item]) == [item]
    assert summarize_source("shot-charts", "2099-00")["status_counts"] == {"interrupted": 1}


def test_per_game_tasks_honor_the_date_window_and_reject_unfinished_game_ids(tmp_db):
    from nba_duckdb.season_utils import GamesNotInScopeError, completed_games_in_scope

    tmp_db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0029900001", game_date="12/30/2099 00:00:00"),
            schedule_row(game_id="0029900002", game_date="01/02/2100 00:00:00"),
            schedule_row(game_id="0029900003", game_date="01/03/2100 00:00:00", game_status=2),
        ],
    )

    window = completed_games_in_scope({"season": "2099-00", "start_date": "2100-01-01", "end_date": "2100-01-31"})
    assert window["game_id"].to_list() == ["0029900002"]

    with pytest.raises(GamesNotInScopeError, match="0029900003"):
        completed_games_in_scope({"season": "2099-00", "game_ids": ["0029900002", "0029900003"]})

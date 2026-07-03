import json


def test_jersey_rank_snapshot_loads_from_user_file(tmp_path, monkeypatch):
    from nba_duckdb.tasks.gold import refresh_player_off_court_signals as task

    path = tmp_path / "jersey_ranks.json"
    path.write_text(
        json.dumps(
            {
                "snapshot_date": "2099-01-01",
                "season": "2099-00",
                "list_name": "Example Rankings",
                "release_title": "Example local ranking file",
                "source_name": "User supplied",
                "source_url": "https://example.invalid/rankings",
                "ranks": [{"player_name": "Avery Example", "rank": 1}],
            }
        )
    )
    monkeypatch.setenv("NBA_DUCKDB_JERSEY_RANKS_FILE", str(path))

    snapshot = task._load_jersey_rank_snapshot()

    assert snapshot is not None
    assert snapshot["snapshot_date"] == "2099-01-01"
    assert snapshot["ranks_by_name"] == {"avery example": 1}


def test_off_court_run_uses_safe_default_limit_and_delay(monkeypatch):
    from nba_duckdb.tasks.gold import refresh_player_off_court_signals as task

    seen = {}

    def fake_refresh(**kwargs):
        seen.update(kwargs)
        return {"ok": 1}

    monkeypatch.delenv("OFF_COURT_REFRESH_LIMIT", raising=False)
    monkeypatch.delenv("OFF_COURT_REQUEST_DELAY_SECONDS", raising=False)
    monkeypatch.setattr(task, "refresh", fake_refresh)

    assert task.run() == {"ok": 1}
    assert seen == {"limit": 25, "request_delay_seconds": 0.5}

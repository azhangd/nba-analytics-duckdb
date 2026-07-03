import pytest

pytest.importorskip("nba_api")


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def test_defense_ingest_fails_when_every_requested_combo_fails(monkeypatch):
    from nba_duckdb.tasks.bronze import ingest_defense

    def fail_fetch(**_kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ingest_defense, "PLAY_TYPES", ["Isolation"])
    monkeypatch.setattr(ingest_defense.nba_client, "get_synergy_play_types", fail_fetch)

    with pytest.raises(RuntimeError, match="Failed to fetch all 4"):
        ingest_defense.run(season="2099-00")


def test_tracking_ingest_fails_when_every_requested_category_fails(monkeypatch):
    from nba_duckdb.tasks.bronze import ingest_tracking_stats

    def fail_fetch(**_kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ingest_tracking_stats, "TRACKING_CATEGORIES", ["SpeedDistance"])
    monkeypatch.setattr(ingest_tracking_stats.nba_client, "get_tracking_stats", fail_fetch)

    with pytest.raises(RuntimeError, match="Failed to fetch all 2"):
        ingest_tracking_stats.run(season="2099-00")


def test_shot_chart_season_type_mapping():
    from nba_duckdb.tasks.bronze.ingest_shot_charts import _season_type_for_game_id

    assert _season_type_for_game_id("0012400001") == "Pre Season"
    assert _season_type_for_game_id("0022400001") == "Regular Season"
    assert _season_type_for_game_id("0032400001") == "All Star"
    assert _season_type_for_game_id("0042400001") == "Playoffs"
    assert _season_type_for_game_id("0052400001") == "PlayIn"
    assert _season_type_for_game_id("0062400001") == "Regular Season"


def test_shot_chart_ingest_defers_item_failures(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb.tasks.bronze import ingest_shot_charts

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

    def fail_fetch(**_kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fail_fetch)

    result = ingest_shot_charts.run(season="2099-00")

    assert result["status"] == "deferred"
    assert result["deferred_games"] == 1
    assert result["item_state"]["status_counts"] == {"deferred": 2}


def test_shot_chart_ingest_passes_season_and_season_type(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": "0069900001",
                "game_date": "12/01/2099 00:00:00",
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
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": []}]}

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fake_fetch)

    result = ingest_shot_charts.run(season="2099-00")

    assert result["rows_written"] == 2
    assert calls == [
        {
            "game_id": "0069900001",
            "team_id": 0,
            "season": "2099-00",
            "season_type": "Regular Season",
            "max_retries": 2,
        }
    ]


def test_shot_chart_ingest_includes_all_schedule_teams_by_default(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    monkeypatch.delenv("NBA_DUCKDB_TEAM_IDS", raising=False)
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": "0039900001",
                "game_date": "02/16/2100 00:00:00",
                "home_team_id": 1610616851,
                "away_team_id": 1610616852,
                "home_team_abbr": "CHK",
                "away_team_abbr": "SHQ",
                "game_status": 3,
                "game_status_text": "Final",
                "season": "2099-00",
                "raw_json": "{}",
            }
        ],
    )

    def fake_fetch(**_kwargs):
        return {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": []}]}

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fake_fetch)

    result = ingest_shot_charts.run(season="2099-00")
    rows = db.execute(
        """
        SELECT game_id, team_id
        FROM bronze.shot_charts
        ORDER BY team_id
        """
    )

    assert result["rows_written"] == 2
    assert [(row["game_id"], row["team_id"]) for row in rows] == [
        ("0039900001", 1610616851),
        ("0039900001", 1610616852),
    ]


def test_shot_chart_ingest_does_not_refetch_existing_pairs(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb.tasks.bronze import ingest_shot_charts

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
        "shot_charts",
        [
            {
                "game_id": "0029900001",
                "team_id": 1610612737,
                "shot_chart_json": "{}",
            },
            {
                "game_id": "0029900001",
                "team_id": 1610612738,
                "shot_chart_json": "{}",
            },
        ],
    )

    def fail_if_called(**_kwargs):
        raise AssertionError("existing pairs should not be refetched")

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fail_if_called)

    result = ingest_shot_charts.run(season="2099-00")

    assert result["rows_written"] == 0
    assert result["item_state"]["status_counts"] == {"success": 2}

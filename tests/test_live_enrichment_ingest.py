import json

import pytest
from conftest import schedule_row

pytest.importorskip("nba_api")


@pytest.mark.parametrize(
    ("module_name", "single_item", "fetchers", "error"),
    [
        ("ingest_defense", ("PLAY_TYPES", ["Isolation"]), ["get_synergy_play_types"], "Failed to fetch all 4"),
        (
            "ingest_hustle",
            None,
            ["get_hustle_stats_player", "get_hustle_stats_team"],
            "hustle stats for every requested season",
        ),
        (
            "ingest_tracking_stats",
            ("TRACKING_CATEGORIES", ["SpeedDistance"]),
            ["get_tracking_stats"],
            "Failed to fetch all 2",
        ),
    ],
)
def test_enrichment_ingest_fails_when_every_fetch_fails(
    monkeypatch, module_name, single_item, fetchers, error
):
    import importlib

    module = importlib.import_module(f"nba_duckdb.tasks.bronze.{module_name}")

    def fail_fetch(**_kwargs):
        raise RuntimeError("rate limited")

    if single_item:
        monkeypatch.setattr(module, *single_item)
    for fetcher in fetchers:
        monkeypatch.setattr(module.nba_client, fetcher, fail_fetch)

    with pytest.raises(RuntimeError, match=error):
        module.run(season="2099-00")


def test_shot_chart_season_type_mapping():
    from nba_duckdb.tasks.bronze.ingest_shot_charts import _season_type_for_game_id

    assert _season_type_for_game_id("0012400001") == "Pre Season"
    assert _season_type_for_game_id("0022400001") == "Regular Season"
    assert _season_type_for_game_id("0032400001") == "All Star"
    assert _season_type_for_game_id("0042400001") == "Playoffs"
    assert _season_type_for_game_id("0052400001") == "PlayIn"
    assert _season_type_for_game_id("0062400001") == "Regular Season"


def test_shot_chart_ingest_defers_item_failures(tmp_db, monkeypatch):
    db = tmp_db
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row()
        ],
    )

    def fail_fetch(**_kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fail_fetch)

    result = ingest_shot_charts.run(season="2099-00")

    assert result["status"] == "deferred"
    assert result["deferred_games"] == 1
    assert result["item_state"]["status_counts"] == {"deferred": 2}


def test_shot_chart_ingest_passes_season_and_season_type(tmp_db, monkeypatch):
    db = tmp_db
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0069900001", game_date="12/01/2099 00:00:00")
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
            "league_id": "00",
            "season": "2099-00",
            "season_type": "Regular Season",
            "max_retries": 2,
        }
    ]


def test_summer_shot_chart_uses_schedule_league_id(tmp_db, monkeypatch):
    db = tmp_db
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="1522600001", game_date="07/09/2026 00:00:00", home_team_abbr="ATL", away_team_abbr="BOS", season="2026-27", league_id="15", competition="summer_league_vegas")
        ],
    )
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": []}]}

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fake_fetch)

    result = ingest_shot_charts.run(
        season="2026-27",
        competitions=["summer_league_vegas"],
    )

    assert result["rows_written"] == 2
    assert calls == [
        {
            "game_id": "1522600001",
            "team_id": 0,
            "league_id": "15",
            "season": "2026-27",
            "season_type": "Regular Season",
            "max_retries": 2,
        }
    ]


def test_shot_chart_ingest_includes_all_schedule_teams_by_default(tmp_db, monkeypatch):
    db = tmp_db
    monkeypatch.delenv("NBA_DUCKDB_TEAM_IDS", raising=False)
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0039900001", game_date="02/16/2100 00:00:00", home_team_id=1610616851, away_team_id=1610616852, home_team_abbr="CHK", away_team_abbr="SHQ")
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


def test_shot_chart_ingest_does_not_refetch_existing_pairs(tmp_db, monkeypatch):
    db = tmp_db
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row()
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


def _insert_game_detail_schedule(db, game_ids):
    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id=game_id)
            for game_id in game_ids
        ],
    )


def _game_detail_payload(key):
    return {
        key: {
            "homeTeam": {"teamId": 1610612737},
            "awayTeam": {"teamId": 1610612738},
        }
    }


def test_game_detail_opens_rotation_circuit_and_uses_pbp_fallback(tmp_db, monkeypatch):
    db = tmp_db
    _insert_game_detail_schedule(db, ["0029900001", "0029900002"])

    from nba_duckdb.tasks.bronze import ingest_game_detail

    monkeypatch.setattr(
        ingest_game_detail.nba_client,
        "get_boxscore_misc",
        lambda **_kwargs: _game_detail_payload("boxScoreMisc"),
    )
    rotation_calls = []

    def fail_rotation(**kwargs):
        rotation_calls.append(kwargs)
        raise TimeoutError("rotation unavailable")

    monkeypatch.setattr(ingest_game_detail.nba_client, "get_game_rotation", fail_rotation)

    result = ingest_game_detail.run(season="2099-00")
    rows = db.execute("SELECT detail_json FROM bronze.game_detail ORDER BY game_id")

    assert result["rows_written"] == 2
    assert result["rotation_holes"] == 2
    assert result["rotation_circuit_open"] is True
    assert len(rotation_calls) == 1
    assert rotation_calls[0]["game_id"] in {"0029900001", "0029900002"}
    assert rotation_calls[0]["max_retries"] == 1
    assert rotation_calls[0]["timeout"] == 10
    assert all(
        json.loads(row["detail_json"])["rotation"]["_status"] == "unavailable"
        for row in rows
    )


def test_game_detail_strict_rotation_fails_when_circuit_opens(tmp_db, monkeypatch):
    db = tmp_db
    _insert_game_detail_schedule(db, ["0029900001"])

    from nba_duckdb.tasks.bronze import ingest_game_detail

    monkeypatch.setattr(
        ingest_game_detail.nba_client,
        "get_boxscore_misc",
        lambda **_kwargs: _game_detail_payload("boxScoreMisc"),
    )
    monkeypatch.setattr(
        ingest_game_detail.nba_client,
        "get_game_rotation",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("rotation unavailable")),
    )

    with pytest.raises(RuntimeError, match="rotation endpoint unavailable"):
        ingest_game_detail.run(season="2099-00", full_refresh=True)

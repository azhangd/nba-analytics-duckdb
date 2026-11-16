import json

import pytest
from conftest import schedule_row

pytest.importorskip("nba_api")


@pytest.mark.parametrize(
    ("module_name", "table", "single_item", "fetchers"),
    [
        ("ingest_defense", "defense", ("PLAY_TYPES", ["Isolation"]), ["get_synergy_play_types"]),
        ("ingest_hustle", "hustle", None, ["get_hustle_stats_player", "get_hustle_stats_team"]),
        ("ingest_tracking_stats", "tracking_stats", ("TRACKING_CATEGORIES", ["SpeedDistance"]), ["get_tracking_stats"]),
        ("ingest_matchups", "matchups", ("ALL_TEAM_IDS", (1610612737,)), ["get_season_matchups"]),
    ],
)
def test_season_ingest_writes_what_came_back_and_fails_on_any_hole(
    tmp_db, monkeypatch, module_name, table, single_item, fetchers
):
    import importlib

    module = importlib.import_module(f"nba_duckdb.tasks.bronze.{module_name}")
    monkeypatch.delenv("NBA_DUCKDB_TEAM_IDS", raising=False)
    calls = []

    def first_call_fails(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("rate limited")
        return {"resultSets": []}

    if single_item:
        monkeypatch.setattr(module, *single_item)
    for fetcher in fetchers:
        monkeypatch.setattr(module.nba_client, fetcher, first_call_fails)

    with pytest.raises(RuntimeError, match=rf"bronze\.{table}: 1 request\(s\) failed"):
        module.run(season="2099-00")
    assert tmp_db.count_rows("bronze", table) == len(calls) - 1


def test_shot_chart_season_type_mapping():
    from nba_duckdb.tasks.bronze.ingest_shot_charts import _season_type_for_game_id

    assert _season_type_for_game_id("0012400001") == "Pre Season"
    assert _season_type_for_game_id("0022400001") == "Regular Season"
    assert _season_type_for_game_id("0042400001") == "Playoffs"
    assert _season_type_for_game_id("0052400001") == "PlayIn"
    assert _season_type_for_game_id("0062400001") == "IST"


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
        return {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": [[1]]}]}

    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fake_fetch)

    result = ingest_shot_charts.run(season="2099-00")

    assert result["rows_written"] == 2
    assert calls == [
        {
            "game_id": "0069900001",
            "team_id": 0,
            "league_id": "00",
            "season": "2099-00",
            "season_type": "IST",
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
        return {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": [[1]]}]}

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
            schedule_row(game_id="0029900001", game_date="02/16/2100 00:00:00", home_team_id=1610616851, away_team_id=1610616852, home_team_abbr="CHK", away_team_abbr="SHQ")
        ],
    )

    def fake_fetch(**_kwargs):
        return {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": [[1]]}]}

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
        ("0029900001", 1610616851),
        ("0029900001", 1610616852),
    ]


SHOT_CHART_WITH_SHOTS = {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": [[1]]}]}
EMPTY_SHOT_CHART = {"resultSets": [{"name": "Shot_Chart_Detail", "headers": [], "rowSet": []}]}


def test_shot_chart_refetches_stored_empty_charts_and_defers_empty_responses(tmp_db, monkeypatch):
    from nba_duckdb.tasks.bronze import ingest_shot_charts

    tmp_db.insert_rows("bronze", "schedule", [schedule_row(), schedule_row(game_id="0032500004")])
    tmp_db.insert_rows(
        "bronze",
        "shot_charts",
        [{"game_id": "0029900001", "team_id": team_id, "shot_chart_json": json.dumps(EMPTY_SHOT_CHART)}
         for team_id in (1610612737, 1610612738)],
    )
    calls = []
    monkeypatch.setattr(
        ingest_shot_charts.nba_client,
        "get_shot_chart",
        lambda **kwargs: calls.append(kwargs["game_id"]) or EMPTY_SHOT_CHART,
    )

    first = ingest_shot_charts.run(season="2099-00")

    assert calls == ["0029900001"]
    assert first["status"] == "deferred"
    assert first["item_state"]["status_counts"] == {"deferred": 2}


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
                "shot_chart_json": json.dumps(SHOT_CHART_WITH_SHOTS),
            },
            {
                "game_id": "0029900001",
                "team_id": 1610612738,
                "shot_chart_json": json.dumps(SHOT_CHART_WITH_SHOTS),
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


def _rotation_payload():
    return {"resultSets": [{"rowSet": [[1]]}]}


def test_game_detail_keeps_fetching_rotation_after_one_failure(tmp_db, monkeypatch):
    _insert_game_detail_schedule(tmp_db, ["0029900001", "0029900002", "0029900003"])

    from nba_duckdb.tasks.bronze import ingest_game_detail

    monkeypatch.setattr(
        ingest_game_detail.nba_client,
        "get_boxscore_misc",
        lambda **_kwargs: _game_detail_payload("boxScoreMisc"),
    )
    calls = []

    def rotation(**kwargs):
        calls.append(kwargs["game_id"])
        if len(calls) == 1:
            raise TimeoutError("one slow response")
        return _rotation_payload()

    monkeypatch.setattr(ingest_game_detail.nba_client, "get_game_rotation", rotation)

    result = ingest_game_detail.run(season="2099-00")

    assert len(calls) == 3
    assert result["rotation_holes"] == 1
    assert result["skipped_components"] == []


def test_game_detail_skips_a_failing_endpoint_and_retries_it_next_run(tmp_db, monkeypatch):
    game_ids = [f"00299000{n:02d}" for n in range(1, 8)]
    _insert_game_detail_schedule(tmp_db, game_ids)

    from nba_duckdb.tasks.bronze import ingest_game_detail

    monkeypatch.setattr(
        ingest_game_detail.nba_client,
        "get_boxscore_misc",
        lambda **_kwargs: _game_detail_payload("boxScoreMisc"),
    )
    calls = []

    def down(**kwargs):
        calls.append(kwargs["game_id"])
        raise TimeoutError("rotation down")

    monkeypatch.setattr(ingest_game_detail.nba_client, "get_game_rotation", down)
    first = ingest_game_detail.run(season="2099-00")

    assert len(calls) == ingest_game_detail.MAX_CONSECUTIVE_FAILURES
    assert first["skipped_components"] == ["rotation"]
    assert first["rotation_holes"] == len(game_ids)

    monkeypatch.setattr(
        ingest_game_detail.nba_client, "get_game_rotation", lambda **_kwargs: _rotation_payload()
    )
    second = ingest_game_detail.run(season="2099-00")
    rows = tmp_db.execute("SELECT detail_json FROM bronze.game_detail")

    assert second["rotation_holes"] == 0
    assert all("_status" not in json.loads(row["detail_json"])["rotation"] for row in rows)


def test_game_detail_full_refresh_fails_when_rotation_stays_unavailable(tmp_db, monkeypatch):
    _insert_game_detail_schedule(tmp_db, ["0029900001"])

    from nba_duckdb.tasks.bronze import ingest_game_detail

    monkeypatch.setattr(ingest_game_detail, "RECOVERY_DELAY_SECONDS", 0)
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

    with pytest.raises(RuntimeError, match=r"left holes for 1 game\(s\): 0029900001\(rotation\)"):
        ingest_game_detail.run(season="2099-00", full_refresh=True)


def test_injury_report_that_parses_to_nothing_keeps_the_stored_snapshot(tmp_db, monkeypatch):
    from datetime import date

    from nba_duckdb.tasks.bronze import ingest_injuries

    stored = {"rows": [{"player": "Kept"}]}
    tmp_db.insert_rows("bronze", "injuries", [{"fetched_date": date.today().isoformat(), "injuries_json": json.dumps(stored)}])
    monkeypatch.setattr(ingest_injuries, "_find_latest_pdf", lambda _client: ("https://example.invalid/report.pdf", b"%PDF"))
    monkeypatch.setattr(ingest_injuries, "_parse_pdf", lambda _bytes: [])

    with pytest.raises(ValueError, match="Parsed no injury entries"):
        ingest_injuries.run()
    assert json.loads(tmp_db.execute("SELECT injuries_json FROM bronze.injuries")[0]["injuries_json"]) == stored

import pytest

pytest.importorskip("nba_api")


def _schedule_row(game_id: str, *, competition: str, league_id: str) -> dict:
    return {
        "game_id": game_id,
        "game_date": "07/09/2026 00:00:00",
        "home_team_id": 1610612737,
        "away_team_id": 1610612738,
        "home_team_abbr": "ATL",
        "away_team_abbr": "BOS",
        "game_status": 3,
        "game_status_text": "Final",
        "season": "2026-27",
        "league_id": league_id,
        "competition": competition,
        "raw_json": "{}",
    }


def test_collectors_do_not_cross_competition_boundaries(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.tasks.bronze import (
        ingest_boxscores,
        ingest_play_by_play,
        ingest_shot_charts,
    )

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "summer.duckdb"))
    db.init_schema()
    db.insert_rows(
        "bronze",
        "schedule",
        [
            _schedule_row("0022600001", competition="nba", league_id="00"),
            _schedule_row(
                "1522600001",
                competition="summer_league_vegas",
                league_id="15",
            ),
        ],
    )

    boxscore_calls = []
    pbp_calls = []
    shot_calls = []

    def fake_boxscore(game_id, **_kwargs):
        boxscore_calls.append(game_id)
        return {"boxScoreTraditional": {"gameId": game_id}}

    def fake_pbp(game_id, **_kwargs):
        pbp_calls.append(game_id)
        return {"game": {"actions": [{"actionNumber": 1}]}}, "stats_v3"

    def fake_shots(**kwargs):
        shot_calls.append(kwargs)
        return {
            "resultSets": [
                {"name": "Shot_Chart_Detail", "headers": [], "rowSet": [[1]]}
            ]
        }

    monkeypatch.setattr(ingest_boxscores.nba_client, "get_boxscore", fake_boxscore)
    monkeypatch.setattr(
        ingest_boxscores.nba_client,
        "get_boxscore_advanced",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        ingest_play_by_play.nba_client,
        "get_play_by_play_with_source",
        fake_pbp,
    )
    monkeypatch.setattr(ingest_shot_charts.nba_client, "get_shot_chart", fake_shots)

    scope = {
        "season": "2026-27",
        "competitions": ["summer_league_vegas"],
    }
    boxscore_result = ingest_boxscores.run(**scope)
    pbp_result = ingest_play_by_play.run(**scope)
    shot_result = ingest_shot_charts.run(**scope)

    assert boxscore_result["rows_written"] == 1
    assert pbp_result["rows_written"] == 1
    assert shot_result["rows_written"] == 2
    assert boxscore_calls == ["1522600001"]
    assert pbp_calls == ["1522600001"]
    assert [call["game_id"] for call in shot_calls] == ["1522600001"]
    assert shot_calls[0]["league_id"] == "15"
    assert db.execute_sql("SELECT game_id FROM bronze.boxscores") == [
        {"game_id": "1522600001"}
    ]
    assert db.execute_sql("SELECT game_id FROM bronze.play_by_play") == [
        {"game_id": "1522600001"}
    ]

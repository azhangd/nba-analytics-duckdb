from datetime import date

import pytest

pytest.importorskip("nba_api")

from nba_duckdb.tasks.bronze.ingest_schedule import (
    _date_range_from_values,
    _ingest_season,
    _latest_final_date,
    run,
)


def test_date_range_from_values_handles_single_date_and_reversed_bounds():
    assert _date_range_from_values("2025-04-13", None) == {date(2025, 4, 13)}
    assert _date_range_from_values(None, "2025-04-13") == {date(2025, 4, 13)}
    assert _date_range_from_values("2025-04-15", "2025-04-13") == {
        date(2025, 4, 13),
        date(2025, 4, 14),
        date(2025, 4, 15),
    }


def test_date_range_from_values_ignores_invalid_dates():
    assert _date_range_from_values("not-a-date", None) == set()


def test_latest_final_date_normalizes_duckdb_datetime(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": "0029900001",
                "game_date": "06/22/2100 00:00:00",
                "home_team_id": 1610612737,
                "away_team_id": 1610612738,
                "game_status": 3,
                "season": "2099-00",
            }
        ],
    )

    assert _latest_final_date("2099-00") == date(2100, 6, 22)


def test_specific_game_refresh_requires_one_explicit_season():
    with pytest.raises(ValueError, match="exactly one explicit season"):
        run(game_ids=["002SYN0001"])

    with pytest.raises(ValueError, match="exactly one explicit season"):
        run(seasons=["2099-00", "2100-01"], game_ids=["002SYN0001"])


def test_current_season_cold_load_prefers_cdn_schedule(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.tasks.bronze import ingest_schedule

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()

    def fail_stats_schedule(*_args, **_kwargs):
        raise AssertionError("stats schedule should not be called when the CDN succeeds")

    monkeypatch.setattr(ingest_schedule.nba_client, "get_schedule", fail_stats_schedule)
    monkeypatch.setattr(
        ingest_schedule.nba_client,
        "get_current_schedule_from_cdn",
        lambda _season: {
            "leagueSchedule": {
                "seasonYear": "2099-00",
                "gameDates": [
                    {
                        "gameDate": "10/21/2099 00:00:00",
                        "games": [
                            {
                                "gameId": "0029900001",
                                "gameStatus": 3,
                                "gameStatusText": "Final",
                                "homeTeam": {
                                    "teamId": 1610612737,
                                    "teamTricode": "ATL",
                                },
                                "awayTeam": {
                                    "teamId": 1610612738,
                                    "teamTricode": "BOS",
                                },
                            }
                        ],
                    }
                ],
            }
        },
    )

    result = _ingest_season("2099-00", is_current=True)

    assert result["rows_written"] == 1
    assert result["used_cached_schedule"] is False
    assert result["used_scoreboard_fallback"] is False

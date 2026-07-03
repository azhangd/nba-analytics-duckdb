import json


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    db.execute(
        """
        CREATE TABLE silver.fct_games (
            game_id TEXT,
            season TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER
        )
        """
    )
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "0029900001",
                "season": "2099-00",
                "home_team_id": 1610612737,
                "away_team_id": 1610612738,
            }
        ],
    )
    return db


def test_stats_v3_pbp_keeps_events_and_leaves_legacy_coordinates_unmapped(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    db.insert_rows(
        "bronze",
        "play_by_play",
        [
            {
                "game_id": "0029900001",
                "source": "stats_v3",
                "pbp_json": json.dumps(
                    {
                        "game": {
                            "actions": [
                                {
                                    "actionNumber": 1,
                                    "period": 1,
                                    "clock": "PT11M22.00S",
                                    "teamId": 1610612737,
                                    "personId": 990001,
                                    "playerNameI": "E. Player",
                                    "actionType": "2pt",
                                    "subType": "layup",
                                    "description": "Layup",
                                    "scoreHome": "2",
                                    "scoreAway": "0",
                                    "shotResult": "Made",
                                    "isFieldGoal": 1,
                                    "xLegacy": 12,
                                    "yLegacy": 22,
                                }
                            ]
                        }
                    }
                ),
            }
        ],
    )

    from nba_duckdb import dbt_runner

    result = dbt_runner.run_model(model="fct_play_by_play")
    rows = db.execute("SELECT pbp_source, loc_x, loc_y FROM silver.fct_play_by_play")

    assert result["rows_written"] == 1
    assert rows == [{"pbp_source": "stats_v3", "loc_x": None, "loc_y": None}]


def test_live_cdn_pbp_maps_cdn_coordinates(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    db.insert_rows(
        "bronze",
        "play_by_play",
        [
            {
                "game_id": "0029900001",
                "source": "live_cdn",
                "pbp_json": json.dumps(
                    {
                        "game": {
                            "actions": [
                                {
                                    "actionNumber": 1,
                                    "period": 1,
                                    "clock": "PT11M22.00S",
                                    "actionType": "2pt",
                                    "shotResult": "Made",
                                    "isFieldGoal": 1,
                                    "x": 12.5,
                                    "y": 22.5,
                                }
                            ]
                        }
                    }
                ),
            }
        ],
    )

    from nba_duckdb import dbt_runner

    dbt_runner.run_model(model="fct_play_by_play")
    rows = db.execute("SELECT pbp_source, loc_x, loc_y FROM silver.fct_play_by_play")

    assert rows == [{"pbp_source": "live_cdn", "loc_x": 12.5, "loc_y": 22.5}]

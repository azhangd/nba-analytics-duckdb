import json


def test_dim_players_supplements_from_all_boxscore_game_types(tmp_path, monkeypatch):
    from nba_duckdb import db, dbt_runner

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    db.insert_rows(
        "bronze",
        "rosters",
        [
            {
                "player_id": 1,
                "team_id": 10,
                "player_name": "Roster Player",
                "jersey_number": "1",
                "position": "G",
                "height": "6-1",
                "weight": "180",
                "birth_date": "",
                "experience": "1",
                "season": "2099-00",
                "raw_json": "{}",
            }
        ],
    )
    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": "0019900001",
                "game_date": "10/01/2099 00:00:00",
                "home_team_id": 10,
                "away_team_id": 20,
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
        "boxscores",
        [
            {
                "game_id": "0019900001",
                "traditional_json": json.dumps(
                    {
                        "game": {
                            "homeTeam": {
                                "teamId": 10,
                                "players": [
                                    {
                                        "personId": 2,
                                        "firstName": "Camp",
                                        "familyName": "Player",
                                        "jerseyNum": "2",
                                        "position": "F",
                                    }
                                ],
                            },
                            "awayTeam": {"teamId": 20, "players": []},
                        }
                    }
                ),
                "advanced_json": "{}",
            }
        ],
    )

    result = dbt_runner.run_model(model="dim_players")
    players = db.execute("SELECT player_id, full_name, season FROM silver.dim_players ORDER BY player_id")

    assert result["rows_written"] == 2
    assert players == [
        {"player_id": 1, "full_name": "Roster Player", "season": "2099-00"},
        {"player_id": 2, "full_name": "Camp Player", "season": "2099-00"},
    ]

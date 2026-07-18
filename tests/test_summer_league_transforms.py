from nba_duckdb.transforms.silver.summer_league import (
    build_scoped_fact_rows,
    scoped_columns,
    summer_game_scope,
)


def test_summer_fact_scope_excludes_nba_and_uses_schedule_season():
    schedule = [
        {
            "game_id": "1522600001",
            "season": "2026-27",
            "league_id": "15",
            "competition": "summer_league_vegas",
        },
        {
            "game_id": "0022600001",
            "season": "2026-27",
            "league_id": "00",
            "competition": "nba",
        },
    ]
    bronze = [
        {"game_id": "1522600001", "payload": "summer"},
        {"game_id": "0022600001", "payload": "nba"},
    ]

    rows = build_scoped_fact_rows(
        schedule,
        bronze,
        lambda scoped: [
            {
                "game_id": row["game_id"],
                "season": "2025-26",
                "value": row["payload"],
            }
            for row in scoped
        ],
    )

    assert rows == [
        {
            "game_id": "1522600001",
            "season": "2026-27",
            "league_id": "15",
            "competition": "summer_league_vegas",
            "value": "summer",
        }
    ]
    assert summer_game_scope(schedule) == {
        "1522600001": {
            "season": "2026-27",
            "league_id": "15",
            "competition": "summer_league_vegas",
        }
    }


def test_scoped_columns_puts_competition_grain_before_fact_values():
    assert scoped_columns(("game_id", "player_id", "season", "points")) == (
        "game_id",
        "season",
        "league_id",
        "competition",
        "player_id",
        "points",
    )

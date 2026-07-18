import json

import polars as pl
import pytest

from nba_duckdb.fixtures.generate_synthetic_fixtures import (
    BOXSCORES,
    GAME_ID,
    PLAY_BY_PLAY,
    SCHEDULE,
    SHOT_CHARTS,
)
from nba_duckdb.transforms.frames import require_columns, select_columns
from nba_duckdb.transforms.silver.boxscores import build_fct_boxscore_rows
from nba_duckdb.transforms.silver.play_by_play import build_fct_play_by_play_rows
from nba_duckdb.transforms.silver.shots import build_fct_shot_rows


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def test_build_fct_boxscore_rows_from_fixture_payload():
    rows = build_fct_boxscore_rows([
        {
            "game_id": GAME_ID,
            "traditional_json": json.dumps(BOXSCORES[0]),
            "advanced_json": "{}",
        }
    ])

    assert len(rows) == 16
    assert rows[0]["game_id"] == GAME_ID
    assert rows[0]["player_id"] == 910001
    assert rows[0]["pts"] == 10


def test_build_fct_play_by_play_rows_preserves_source_coordinate_semantics():
    rows = build_fct_play_by_play_rows([
        {
            "game_id": GAME_ID,
            "source": "stats_v3",
            "pbp_json": json.dumps(PLAY_BY_PLAY[0]),
        }
    ])

    assert len(rows) == 9
    assert rows[0]["action_id"] == 1
    assert rows[0]["pbp_source"] == "stats_v3"
    assert rows[0]["loc_x"] is None
    assert rows[0]["loc_y"] is None


def test_build_fct_play_by_play_uses_source_action_id_for_paired_events():
    rows = build_fct_play_by_play_rows([
        {
            "game_id": GAME_ID,
            "source": "stats_v3",
            "pbp_json": json.dumps({
                "game": {
                    "actions": [
                        {"actionId": 10, "actionNumber": 9, "description": "Turnover"},
                        {"actionId": 11, "actionNumber": 9, "description": "Steal"},
                    ]
                }
            }),
        }
    ])

    assert [row["action_number"] for row in rows] == [9, 9]
    assert [row["action_id"] for row in rows] == [10, 11]


def test_build_fct_shots_preserves_game_event_id():
    rows = build_fct_shot_rows([
        {
            "game_id": GAME_ID,
            "team_id": SHOT_CHARTS[0]["team_id"],
            "shot_chart_json": json.dumps(SHOT_CHARTS[0]["shot_chart"]),
        }
    ])

    assert rows[0]["game_event_id"] == 1


def test_sql_fct_games_derives_status_scores_and_type(tmp_path, monkeypatch):
    from nba_duckdb import dbt_runner

    db = _init_tmp_db(tmp_path, monkeypatch)
    game = SCHEDULE[0]
    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": game["gameId"],
                "game_date": game["gameDate"],
                "home_team_id": game["homeTeam"]["teamId"],
                "away_team_id": game["awayTeam"]["teamId"],
                "home_team_abbr": game["homeTeam"]["teamTricode"],
                "away_team_abbr": game["awayTeam"]["teamTricode"],
                "game_status": game["gameStatus"],
                "game_status_text": "Final",
                "season": game["season"],
                "raw_json": json.dumps(game),
            }
        ],
    )

    result = dbt_runner.run_model(model="fct_games")
    rows = db.execute_sql(
        """
        SELECT game_id, status, game_type, home_score
        FROM silver.fct_games
        """
    )

    assert result["rows_written"] == 1
    assert rows == [
        {
            "game_id": GAME_ID,
            "status": "Final",
            "game_type": "regular_season",
            "home_score": 96,
        }
    ]


def test_sql_coach_models_shape_dimensions_and_roles(tmp_path, monkeypatch):
    from nba_duckdb import dbt_runner

    db = _init_tmp_db(tmp_path, monkeypatch)
    db.insert_rows(
        "bronze",
        "coaches",
        [
            {
                "coach_id": "c1",
                "team_id": 10,
                "season": "2099-00",
                "first_name": "Pat",
                "last_name": "Coach",
                "coach_name": "",
                "is_assistant": 0,
                "coach_type": "",
                "sort_sequence": 1,
            },
            {
                "coach_id": "c2",
                "team_id": 10,
                "season": "2099-00",
                "first_name": "Lead",
                "last_name": "Assistant",
                "coach_name": "Lead Assistant",
                "is_assistant": 1,
                "coach_type": "Assistant Coach",
                "sort_sequence": 2,
            },
            {
                "coach_id": "c3",
                "team_id": 10,
                "season": "2099-00",
                "first_name": "Associate",
                "last_name": "Head",
                "coach_name": "Associate Head",
                "is_assistant": 1,
                "coach_type": "Associate Head Coach",
                "sort_sequence": 3,
            },
        ],
    )

    dbt_runner.run_model(model="dim_coaches")
    dbt_runner.run_model(model="fct_team_coach_seasons")

    coaches = db.execute_sql("SELECT coach_id, full_name FROM silver.dim_coaches ORDER BY coach_id")
    roles = db.execute_sql(
        """
        SELECT coach_id, role, coach_type, sort_seq
        FROM silver.fct_team_coach_seasons
        ORDER BY coach_id
        """
    )

    assert coaches == [
        {"coach_id": "c1", "full_name": "Pat Coach"},
        {"coach_id": "c2", "full_name": "Lead Assistant"},
        {"coach_id": "c3", "full_name": "Associate Head"},
    ]
    assert roles == [
        {"coach_id": "c1", "role": "head", "coach_type": "", "sort_seq": 1},
        {"coach_id": "c2", "role": "assistant", "coach_type": "Assistant Coach", "sort_seq": 2},
        {"coach_id": "c3", "role": "head", "coach_type": "Associate Head Coach", "sort_seq": 3},
    ]


def test_sql_external_identities_are_name_derived(tmp_path, monkeypatch):
    from nba_duckdb import dbt_runner

    db = _init_tmp_db(tmp_path, monkeypatch)
    db.execute(
        """
        CREATE TABLE silver.dim_players (
            player_id INTEGER,
            full_name TEXT
        )
        """
    )
    db.insert_rows(
        "silver",
        "dim_players",
        [
            {"player_id": 15, "full_name": "  Nikola   Jokic  "},
            {"player_id": 0, "full_name": "Skipped Player"},
            {"player_id": 16, "full_name": ""},
        ],
    )

    result = dbt_runner.run_model(model="dim_player_external_identities")
    rows = db.execute_sql(
        """
        SELECT player_id, wikidata_qid, wikipedia_title, source_confidence, source_note
        FROM silver.dim_player_external_identities
        """
    )

    assert result["rows_written"] == 1
    assert rows == [
        {
            "player_id": 15,
            "wikidata_qid": "",
            "wikipedia_title": "Nikola_Jokic",
            "source_confidence": 0.25,
            "source_note": "Deterministic name-derived identity; verify before using externally",
        }
    ]


def test_build_fct_shot_rows_filters_to_bronze_team():
    rows = build_fct_shot_rows([
        {
            "game_id": SHOT_CHARTS[0]["game_id"],
            "team_id": SHOT_CHARTS[0]["team_id"],
            "shot_chart_json": json.dumps(SHOT_CHARTS[0]["shot_chart"]),
        }
    ])

    assert len(rows) == 6
    assert {row["team_id"] for row in rows} == {SHOT_CHARTS[0]["team_id"]}
    assert {row["shot_context"] for row in rows}


def test_sql_player_game_stats_adds_game_score_and_shot_splits(tmp_path, monkeypatch):
    from nba_duckdb import dbt_runner

    db = _init_tmp_db(tmp_path, monkeypatch)
    db.execute(
        """
        CREATE TABLE silver.fct_boxscores (
            game_id TEXT,
            player_id INTEGER,
            team_id INTEGER,
            player_name TEXT,
            started BOOLEAN,
            counts_as_gp BOOLEAN,
            minutes DOUBLE,
            fgm INTEGER,
            fga INTEGER,
            fg3m INTEGER,
            fg3a INTEGER,
            ftm INTEGER,
            fta INTEGER,
            oreb INTEGER,
            dreb INTEGER,
            reb INTEGER,
            ast INTEGER,
            stl INTEGER,
            blk INTEGER,
            tov INTEGER,
            pf INTEGER,
            pts INTEGER,
            plus_minus INTEGER,
            off_rating DOUBLE,
            def_rating DOUBLE,
            net_rating DOUBLE,
            usg_pct DOUBLE,
            ts_pct DOUBLE,
            pace DOUBLE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE silver.fct_shots (
            game_id TEXT,
            player_id INTEGER,
            shot_zone_basic TEXT,
            shot_type TEXT,
            shot_made BOOLEAN
        )
        """
    )
    db.insert_rows(
        "silver",
        "fct_boxscores",
        [
            {
                "game_id": "002SYN0001",
                "player_id": 1,
                "team_id": 10,
                "player_name": "Test Player",
                "started": True,
                "counts_as_gp": True,
                "minutes": 30.0,
                "fgm": 8,
                "fga": 16,
                "fg3m": 1,
                "fg3a": 4,
                "ftm": 2,
                "fta": 2,
                "oreb": 1,
                "dreb": 4,
                "reb": 5,
                "ast": 5,
                "stl": 1,
                "blk": 0,
                "tov": 2,
                "pf": 2,
                "pts": 20,
                "plus_minus": 3,
                "off_rating": 110.0,
                "def_rating": 100.0,
                "net_rating": 10.0,
                "usg_pct": 0.25,
                "ts_pct": 0.58,
                "pace": 98.0,
            }
        ],
    )
    db.insert_rows(
        "silver",
        "fct_shots",
        [
            {
                "game_id": "002SYN0001",
                "player_id": 1,
                "shot_zone_basic": "Restricted Area",
                "shot_type": "2PT Field Goal",
                "shot_made": True,
            },
            {
                "game_id": "002SYN0001",
                "player_id": 1,
                "shot_zone_basic": "Above the Break 3",
                "shot_type": "3PT Field Goal",
                "shot_made": False,
            },
        ],
    )

    result = dbt_runner.run_model(model="player_game_stats")
    rows = db.execute_sql(
        """
        SELECT game_score, paint_attempts, paint_makes, three_attempts, three_makes
        FROM gold.player_game_stats
        """
    )

    assert result["rows_written"] == 1
    assert rows == [
        {
            "game_score": 15.6,
            "paint_attempts": 1,
            "paint_makes": 1,
            "three_attempts": 1,
            "three_makes": 0,
        }
    ]


def test_sql_team_game_stats_computes_ratings_and_margins(tmp_path, monkeypatch):
    from nba_duckdb import dbt_runner

    db = _init_tmp_db(tmp_path, monkeypatch)
    db.execute(
        """
        CREATE TABLE silver.fct_boxscores (
            game_id TEXT,
            team_id INTEGER,
            minutes DOUBLE,
            pts INTEGER,
            fga INTEGER,
            fta INTEGER,
            oreb INTEGER,
            tov INTEGER
        )
        """
    )
    db.execute(
        """
        CREATE TABLE silver.fct_games (
            game_id TEXT,
            season TEXT,
            game_date TEXT,
            game_type TEXT
        )
        """
    )
    db.insert_rows(
        "silver",
        "fct_boxscores",
        [
            {
                "game_id": "002SYN0001",
                "team_id": 10,
                "minutes": 240.0,
                "pts": 100,
                "fga": 80,
                "fta": 20,
                "oreb": 10,
                "tov": 12,
            },
            {
                "game_id": "002SYN0001",
                "team_id": 20,
                "minutes": 240.0,
                "pts": 90,
                "fga": 75,
                "fta": 15,
                "oreb": 8,
                "tov": 14,
            },
        ],
    )
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "002SYN0001",
                "season": "2099-00",
                "game_date": "01/01/2100",
                "game_type": "regular_season",
            }
        ],
    )

    result = dbt_runner.run_model(model="team_game_stats")
    rows = db.execute_sql(
        """
        SELECT team_id, pts, opp_pts, margin, is_win, off_rtg, def_rtg, net_rtg
        FROM gold.team_game_stats
        ORDER BY team_id
        """
    )

    assert result["rows_written"] == 2
    assert rows == [
        {
            "team_id": 10,
            "pts": 100,
            "opp_pts": 90,
            "margin": 10,
            "is_win": True,
            "off_rtg": 110.1,
            "def_rtg": 102.7,
            "net_rtg": 7.4,
        },
        {
            "team_id": 20,
            "pts": 90,
            "opp_pts": 100,
            "margin": -10,
            "is_win": False,
            "off_rtg": 102.7,
            "def_rtg": 110.1,
            "net_rtg": -7.4,
        },
    ]


def test_frame_helpers_fail_with_clear_missing_column_message():
    frame = pl.DataFrame([{"game_id": "1"}])

    with pytest.raises(ValueError, match="missing required columns: season"):
        require_columns(frame, ["game_id", "season"], context="test frame")

    assert select_columns(frame, ["game_id"], context="test frame").columns == ["game_id"]


def test_full_refresh_task_reads_all_upstream_and_removes_stale_rows(tmp_path, monkeypatch):
    from nba_duckdb import db, dbt_runner

    _init_tmp_db(tmp_path, monkeypatch)
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
            },
            {
                "game_id": "0029800001",
                "game_date": "01/01/2099 00:00:00",
                "home_team_id": 1610612739,
                "away_team_id": 1610612740,
                "home_team_abbr": "CCC",
                "away_team_abbr": "DDD",
                "game_status": 3,
                "game_status_text": "Final",
                "season": "2098-99",
                "raw_json": "{}",
            },
        ],
    )
    db.execute("CREATE TABLE silver.fct_games (game_id TEXT, season TEXT)")
    db.insert_rows("silver", "fct_games", [{"game_id": "STALE", "season": "stale"}])

    result = dbt_runner.run_model(model="fct_games", full_refresh=True)

    rows = db.execute_sql("SELECT game_id, season FROM silver.fct_games ORDER BY game_id")
    assert result["rows_written"] == 2
    assert rows == [
        {"game_id": "0029800001", "season": "2098-99"},
        {"game_id": "0029900001", "season": "2099-00"},
    ]

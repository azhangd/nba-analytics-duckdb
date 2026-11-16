import json

import polars as pl
import pytest
from conftest import schedule_row

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


def test_stats_v3_play_by_play_uses_live_vocabulary_and_carries_score():
    def action(action_id, **fields):
        return {"actionId": action_id, "actionNumber": action_id, "period": 1, "clock": "PT11M00.00S",
                "scoreHome": "", "scoreAway": "", "shotResult": "", "isFieldGoal": 0, "shotValue": 0, **fields}

    rows = build_fct_play_by_play_rows([
        {
            "game_id": GAME_ID,
            "source": "stats_v3",
            "pbp_json": json.dumps({"game": {"actions": [
                action(3, teamId=1610612737, personId=11, actionType="Made Shot", subType="Jump Shot", shotValue=3,
                       shotResult="Made", isFieldGoal=1, scoreHome="3", scoreAway="0", description="A 26' 3PT Jump Shot (3 PTS)"),
                action(4, teamId=1610612738, personId=21, actionType="Missed Shot", subType="Jump Shot", shotValue=2,
                       shotResult="Missed", isFieldGoal=1, description="MISS B 15' Jump Shot"),
                action(5, teamId=0, personId=1610612737, actionType="Rebound", subType="Unknown", description="Home Rebound"),
                action(6, teamId=1610612737, personId=11, actionType="Free Throw", subType="Free Throw 1 of 2",
                       description="MISS A Free Throw 1 of 2"),
                action(7, teamId=1610612737, personId=11, actionType="Free Throw", subType="Free Throw 2 of 2",
                       scoreHome="4", scoreAway="0", description="A Free Throw 2 of 2 (4 PTS)"),
                action(8, teamId=1610612738, personId=22, actionType="", description="C STEAL (1 STL)"),
                action(1, teamId=0, personId=0, actionType="period", subType="start", scoreHome="0", scoreAway="0",
                       description="Start of 1st Period"),
            ]}}),
        }
    ])

    by_id = {row["action_id"]: row for row in rows}
    assert [row["action_id"] for row in rows] == [1, 3, 4, 5, 6, 7, 8]
    assert by_id[3]["action_type"] == "3pt"
    assert by_id[4]["action_type"] == "2pt"
    assert (by_id[5]["team_id"], by_id[5]["player_id"]) == (1610612737, None)
    assert [(by_id[i]["action_type"], by_id[i]["sub_type"], by_id[i]["shot_result"]) for i in (6, 7)] == [
        ("freethrow", "1 of 2", "Missed"),
        ("freethrow", "2 of 2", "Made"),
    ]
    assert by_id[8]["action_type"] == "steal"
    assert [(row["score_home"], row["score_away"]) for row in rows] == [
        ("0", "0"), ("3", "0"), ("3", "0"), ("3", "0"), ("3", "0"), ("4", "0"), ("4", "0"),
    ]


def test_build_fct_shots_preserves_game_event_id():
    rows = build_fct_shot_rows([
        {
            "game_id": GAME_ID,
            "team_id": SHOT_CHARTS[0]["team_id"],
            "shot_chart_json": json.dumps(SHOT_CHARTS[0]["shot_chart"]),
        }
    ])

    assert rows[0]["game_event_id"] == 1


def test_sql_fct_games_derives_status_scores_and_type(tmp_db):
    from nba_duckdb import dbt_runner

    db = tmp_db
    game = SCHEDULE[0]
    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id=game["gameId"], game_date=game["gameDate"], home_team_id=game["homeTeam"]["teamId"], away_team_id=game["awayTeam"]["teamId"], home_team_abbr=game["homeTeam"]["teamTricode"], away_team_abbr=game["awayTeam"]["teamTricode"], game_status=game["gameStatus"], season=game["season"], raw_json=json.dumps(game))
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


def test_fct_games_labels_game_type_from_the_game_id_prefix(tmp_db):
    from nba_duckdb import dbt_runner

    tmp_db.insert_rows(
        "bronze",
        "schedule",
        [schedule_row(game_id=game_id) for game_id in ("0012500001", "0022500001", "0032500001", "0042500001", "0052500001", "0062500001")],
    )

    dbt_runner.run_model(model="fct_games")
    rows = tmp_db.execute_sql("SELECT game_id, game_type FROM silver.fct_games ORDER BY game_id")

    assert [row["game_type"] for row in rows] == [
        "preseason", "regular_season", "all_star", "playoffs", "play_in", "nba_cup",
    ]


def test_elo_history_runs_in_calendar_order_across_new_year(tmp_db):
    from nba_duckdb.dbt_runner import run_dbt_command

    tmp_db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0029900002", game_date="01/02/2100 00:00:00", raw_json='{"homeTeam": {"score": 110}, "awayTeam": {"score": 100}}'),
            schedule_row(game_id="0029900001", game_date="10/30/2099 00:00:00", raw_json='{"homeTeam": {"score": 100}, "awayTeam": {"score": 90}}'),
        ],
    )

    run_dbt_command(["build", "--select", "+team_game_elo_history"])
    rows = tmp_db.execute_sql(
        """
        SELECT game_id, CAST(game_date AS TEXT) AS game_date, elo_before
        FROM gold.team_game_elo_history
        WHERE is_home
        ORDER BY game_date
        """
    )

    assert [row["game_date"] for row in rows] == ["2099-10-30", "2100-01-02"]
    assert rows[0]["elo_before"] == 1500.0
    assert rows[1]["elo_before"] > 1500.0


def test_sql_coach_models_shape_dimensions_and_roles(tmp_db):
    from nba_duckdb import dbt_runner

    db = tmp_db
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
                "is_assistant": 1,
                "coach_type": "Head Coach",
                "sort_sequence": 1,
            },
            {
                "coach_id": "c2",
                "team_id": 10,
                "season": "2099-00",
                "first_name": "Lead",
                "last_name": "Assistant",
                "coach_name": "Lead Assistant",
                "is_assistant": 2,
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
                "is_assistant": 9,
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
        {"coach_id": "c1", "role": "head", "coach_type": "Head Coach", "sort_seq": 1},
        {"coach_id": "c2", "role": "assistant", "coach_type": "Assistant Coach", "sort_seq": 2},
        {"coach_id": "c3", "role": "assistant", "coach_type": "Associate Head Coach", "sort_seq": 3},
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


def test_sql_player_game_stats_adds_game_score_and_shot_splits(tmp_db):
    from nba_duckdb import dbt_runner

    db = tmp_db
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


def test_sql_team_game_stats_computes_ratings_and_margins(tmp_db):
    from nba_duckdb import dbt_runner

    db = tmp_db
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


def test_full_refresh_task_reads_all_upstream_and_removes_stale_rows(tmp_db):
    from nba_duckdb import db, dbt_runner

    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(),
            schedule_row(game_id="0029800001", game_date="01/01/2099 00:00:00", home_team_id=1610612739, away_team_id=1610612740, home_team_abbr="CCC", away_team_abbr="DDD", season="2098-99"),
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


def test_adjusted_stats_uses_opponent_defense_from_the_same_season():
    from nba_duckdb.transforms.gold.adjusted_stats import build_adjusted_stats

    games = pl.DataFrame({
        "game_id": ["g1", "g2"],
        "home_team_id": [1, 1],
        "away_team_id": [2, 2],
        "season": ["2025-26", "2026-27"],
    })
    team_log = pl.DataFrame({
        "team_id": [2, 2],
        "season": ["2025-26", "2026-27"],
        "def_rtg": [100.0, 120.0],
    })
    player_games = pl.DataFrame({
        "player_id": [7, 7],
        "game_id": ["g1", "g2"],
        "team_id": [1, 1],
        "minutes": [30.0, 30.0],
        "pts": [22.0, 22.0],
        "fga": [15, 15],
        "ts_pct": [0.6, 0.6],
        "net_rating": [0.0, 0.0],
    })

    adjusted, league_avg = build_adjusted_stats(
        player_games=player_games, team_log=team_log, fct_games=games
    )

    by_season = dict(adjusted.select(["season", "adj_ppg"]).iter_rows())
    assert by_season["2025-26"] == round(22.0 * league_avg / 100.0, 1)
    assert by_season["2026-27"] == round(22.0 * league_avg / 120.0, 1)


MATCHUP_HEADERS = ["SEASON_ID", "OFF_PLAYER_ID", "OFF_PLAYER_NAME", "DEF_PLAYER_ID", "DEF_PLAYER_NAME", "MATCHUP_MIN", "PARTIAL_POSS"]


def _matchup_bronze(team_id, direction, pairs):
    rows = [["22099", off, f"O{off}", dfn, f"D{dfn}", "10:00", 20.0] for off, dfn in pairs]
    return {
        "season": "2099-00",
        "team_id": team_id,
        "direction": direction,
        "matchup_json": json.dumps({"resultSets": [{"headers": MATCHUP_HEADERS, "rowSet": rows}]}),
    }


def test_matchups_keep_one_row_per_pair_with_both_team_ids():
    from nba_duckdb.transforms.silver.enrichment import build_fct_matchup_rows

    # Team 1 attacks team 2. Player 21 was traded, so he defended player 11 for teams 2 and 3.
    rows = build_fct_matchup_rows([
        _matchup_bronze(1, "offense", [(11, 20), (11, 21)]),
        _matchup_bronze(2, "defense", [(11, 20), (11, 21)]),
        _matchup_bronze(3, "defense", [(11, 21)]),
    ])

    assert sorted((r["off_player_id"], r["def_player_id"], r["off_team_id"], r["def_team_id"]) for r in rows) == [
        (11, 20, 1, 2),
        (11, 21, 1, None),
    ]


def test_defense_play_types_read_the_real_synergy_headers():
    from nba_duckdb.transforms.silver.enrichment import build_fct_defense_play_type_rows

    headers = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "SF_POSS_PCT", "FT_POSS_PCT", "TOV_POSS_PCT", "SCORE_POSS_PCT"]
    rows = build_fct_defense_play_type_rows([{
        "season": "2099-00",
        "player_or_team": "P",
        "type_grouping": "defensive",
        "play_type": "Isolation",
        "defense_json": json.dumps({"resultSets": [{"headers": headers, "rowSet": [[7, "P7", 1, 0.17, 0.18, 0.08, 0.55]]}]}),
    }])

    assert {k: rows[0][k] for k in ("sfpct", "ft_pct", "to_pct", "score_pct")} == {
        "sfpct": 0.17, "ft_pct": 0.18, "to_pct": 0.08, "score_pct": 0.55,
    }


def _box(game_date, team_id, player_id, position="F"):
    player = {"personId": player_id, "firstName": "P", "familyName": str(player_id), "position": position}
    return {
        "game_date": game_date,
        "season": "2099-00",
        "traditional_json": {"game": {"homeTeam": {"teamId": team_id, "players": [player]}, "awayTeam": {}}},
    }


def test_dim_players_takes_position_and_team_from_the_latest_roster_and_latest_game():
    from nba_duckdb.transforms.silver.players import build_dim_player_rows

    roster = [
        {"player_id": 1, "team_id": 10, "player_name": "Traded", "jersey_number": "1", "position": "G-F",
         "season": "2099-00", "ingested_at": "2099-11-01"},
        {"player_id": 1, "team_id": 20, "player_name": "Traded", "jersey_number": "1", "position": "G-F",
         "season": "2099-00", "ingested_at": "2099-12-01"},
    ]
    # Player 2 isn't on a roster; his latest game is for team 30. Rows arrive out of date order.
    boxscores = [
        _box("01/02/2100 00:00:00", 30, 2),
        _box("12/30/2099 00:00:00", 40, 2),
        _box("01/02/2100 00:00:00", 20, 1, position="F"),
    ]

    players = {row["player_id"]: row for row in build_dim_player_rows(roster, boxscores)}

    assert (players[1]["current_team_id"], players[1]["position"]) == (20, "G-F")
    assert (players[2]["current_team_id"], players[2]["position"]) == (30, "")


def test_dim_teams_keeps_only_nba_franchises(tmp_db):
    from nba_duckdb import dbt_runner

    tmp_db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0029900001"),
            schedule_row(game_id="0039900001", home_team_id=1610616859, away_team_id=1610616861, home_team_abbr="STR", away_team_abbr="WLD"),
            schedule_row(game_id="0019900001", home_team_id=1610612737, away_team_id=15016, away_team_abbr="MEL"),
        ],
    )

    dbt_runner.run_model(model="dim_teams")
    rows = tmp_db.execute_sql("SELECT team_id FROM silver.dim_teams ORDER BY team_id")

    assert [row["team_id"] for row in rows] == [1610612737, 1610612738]

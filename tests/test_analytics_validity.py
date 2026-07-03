import numpy as np
import pytest


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def _create_dim_teams(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.dim_teams (
            team_id INTEGER,
            abbreviation TEXT,
            full_name TEXT
        )
        """
    )


def _create_dim_players(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.dim_players (
            player_id INTEGER,
            full_name TEXT,
            team_id INTEGER,
            season TEXT
        )
        """
    )


def _create_fct_games(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.fct_games (
            game_id TEXT,
            season TEXT,
            game_type TEXT DEFAULT 'regular_season',
            game_date TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT
        )
        """
    )


def _create_fct_lineups(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.fct_lineups (
            game_id TEXT,
            stint_number INTEGER,
            period INTEGER,
            team_id INTEGER,
            player_ids_str TEXT,
            player_count INTEGER,
            start_clock_seconds REAL,
            end_clock_seconds REAL,
            duration_seconds REAL,
            points_for INTEGER,
            points_against INTEGER
        )
        """
    )


def _create_fct_boxscores(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.fct_boxscores (
            game_id TEXT,
            player_id INTEGER,
            team_id INTEGER,
            player_name TEXT
        )
        """
    )


def _create_fct_hustle(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS silver.fct_hustle (
            season TEXT,
            player_id INTEGER,
            team_id INTEGER,
            deflections REAL,
            contested_shots REAL
        )
        """
    )


def _create_player_game_stats(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.player_game_stats (
            game_id TEXT,
            player_id INTEGER,
            team_id INTEGER,
            player_name TEXT,
            started BOOLEAN,
            counts_as_gp BOOLEAN,
            minutes REAL,
            fgm INTEGER,
            pts INTEGER,
            reb INTEGER,
            oreb INTEGER,
            dreb INTEGER,
            ast INTEGER,
            stl INTEGER,
            blk INTEGER,
            tov INTEGER,
            fga INTEGER,
            fg3m INTEGER,
            fg3a INTEGER,
            ftm INTEGER,
            fta INTEGER,
            pf INTEGER,
            plus_minus INTEGER,
            off_rating REAL,
            def_rating REAL,
            ts_pct REAL,
            pace REAL,
            paint_makes INTEGER,
            paint_attempts INTEGER,
            three_makes INTEGER,
            three_attempts INTEGER,
            midrange_makes INTEGER,
            midrange_attempts INTEGER,
            game_score REAL,
            net_rating REAL,
            usg_pct REAL
        )
        """
    )


def _create_team_game_stats(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_game_stats (
            game_id TEXT,
            team_id INTEGER,
            season TEXT,
            game_date TEXT,
            pts INTEGER,
            opp_pts INTEGER,
            margin INTEGER,
            is_win BOOLEAN,
            off_rtg REAL,
            def_rtg REAL,
            net_rtg REAL
        )
        """
    )


def _create_player_season_stats(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.player_season_stats (
            player_id INTEGER,
            season TEXT,
            player_name TEXT,
            team_id INTEGER,
            position TEXT,
            games_played INTEGER,
            mpg REAL,
            ppg REAL,
            rpg REAL,
            apg REAL,
            spg REAL,
            bpg REAL,
            topg REAL,
            fg_pct REAL,
            fg3_pct REAL,
            ft_pct REAL,
            avg_ts_pct REAL,
            avg_game_score REAL,
            plus_minus_avg REAL,
            avg_usg_pct REAL,
            avg_off_rating REAL,
            avg_def_rating REAL,
            pts_per_36 REAL,
            reb_per_36 REAL,
            ast_per_36 REAL,
            ppg_pct REAL,
            rpg_pct REAL,
            apg_pct REAL,
            spg_pct REAL,
            bpg_pct REAL,
            obpm REAL,
            dbpm REAL,
            bpm_approx REAL,
            vorp_approx REAL
        )
        """
    )


def _create_team_elo_tables(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_elo (
            team_id INTEGER,
            season TEXT,
            team_abbreviation TEXT,
            comparison_scope TEXT,
            comparison_team_count INTEGER,
            elo_rating REAL,
            current_wins INTEGER,
            current_losses INTEGER,
            games_played INTEGER,
            projected_wins REAL,
            projected_losses REAL,
            projected_win_pct REAL,
            remaining_games INTEGER,
            win_pct REAL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_game_elo_history (
            team_id INTEGER,
            season TEXT,
            game_id TEXT,
            game_date TEXT,
            team_abbreviation TEXT,
            opp_team_id INTEGER,
            opp_team_abbreviation TEXT,
            is_home BOOLEAN,
            result TEXT,
            margin INTEGER,
            elo_before REAL,
            elo_after REAL,
            elo_delta REAL,
            opp_elo_before REAL,
            opp_elo_after REAL
        )
        """
    )


def _seed_dim_teams(db, team_ids):
    _create_dim_teams(db)
    db.insert_rows(
        "silver",
        "dim_teams",
        [
            {
                "team_id": team_id,
                "abbreviation": f"T{index:02d}",
                "full_name": f"Synthetic Team {index:02d}",
            }
            for index, team_id in enumerate(team_ids, start=1)
        ],
    )


def _create_team_season_four_factors(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_four_factors (
            team_id INTEGER,
            season TEXT,
            team_abbreviation TEXT,
            games INTEGER,
            ppg REAL,
            opp_ppg REAL,
            pace REAL,
            off_efg_pct REAL,
            off_tov_pct REAL,
            off_oreb_pct REAL,
            off_ft_rate REAL,
            def_efg_pct REAL,
            def_tov_pct REAL,
            def_oreb_pct REAL,
            def_ft_rate REAL,
            pyth_win_pct REAL
        )
        """
    )


def _create_player_dbt_mart_inputs(db):
    db.execute(
        """
        CREATE TABLE gold.player_season_shot_profile (
            team_id INTEGER,
            season TEXT,
            player_id INTEGER,
            player_name TEXT,
            shot_bucket TEXT,
            attempts INTEGER,
            makes INTEGER,
            fg_pct REAL,
            freq_pct REAL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE gold.player_season_clutch_stats (
            player_id INTEGER,
            season TEXT,
            player_name TEXT,
            team_id INTEGER,
            clutch_games INTEGER,
            clutch_ppg REAL,
            clutch_ts_pct REAL
        )
        """
    )


def _create_team_feature_matrix_inputs(db):
    _seed_dim_teams(db, [100])
    _create_team_season_four_factors(db)
    _create_team_elo_tables(db)
    _create_team_game_stats(db)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_shot_profile (
            team_id INTEGER,
            season TEXT,
            shot_bucket TEXT,
            freq_pct REAL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_starter_bench_stats (
            team_id INTEGER,
            season TEXT,
            role TEXT,
            ppg REAL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_play_type_stats (
            offense_team_id INTEGER,
            season TEXT,
            play_type TEXT,
            frequency_pct REAL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_clutch_stats (
            offense_team_id INTEGER,
            season TEXT,
            clutch_ppp REAL
        )
        """
    )


def test_player_season_split_stats_grain_and_source_reconciliation(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner

    _create_fct_games(db)
    _create_player_game_stats(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "0029900001",
                "season": "2099-00",
                "game_type": "regular_season",
                "game_date": "2100-01-01",
                "home_team_id": 100,
                "away_team_id": 200,
                "home_score": 102,
                "away_score": 99,
                "status": "Final",
            },
            {
                "game_id": "0029900002",
                "season": "2099-00",
                "game_type": "regular_season",
                "game_date": "2100-01-02",
                "home_team_id": 200,
                "away_team_id": 100,
                "home_score": 120,
                "away_score": 100,
                "status": "Final",
            },
        ],
    )
    db.insert_rows(
        "gold",
        "player_game_stats",
        [
            {
                "game_id": "0029900001",
                "player_id": 1,
                "team_id": 100,
                "player_name": "Synthetic Guard",
                "minutes": 30.0,
                "pts": 20,
                "reb": 6,
                "ast": 7,
                "fgm": 8,
                "fga": 15,
                "fg3m": 2,
                "fg3a": 5,
                "ftm": 2,
                "fta": 2,
                "plus_minus": 3,
                "net_rating": 4.0,
                "game_score": 18.0,
                "usg_pct": 0.25,
            },
            {
                "game_id": "0029900002",
                "player_id": 1,
                "team_id": 100,
                "player_name": "Synthetic Guard",
                "minutes": 28.0,
                "pts": 10,
                "reb": 4,
                "ast": 5,
                "fgm": 4,
                "fga": 12,
                "fg3m": 1,
                "fg3a": 4,
                "ftm": 1,
                "fta": 2,
                "plus_minus": -20,
                "net_rating": -18.0,
                "game_score": 8.0,
                "usg_pct": 0.22,
            },
        ],
    )

    result = dbt_runner.run_model(model="player_season_split_stats")
    rows = db.execute(
        """
        SELECT split_type, split_value, games, ppg, minutes
        FROM gold.player_season_split_stats
        ORDER BY split_type, split_value
        """
    )
    duplicate_count = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM (
            SELECT player_id, season, team_id, split_type, split_value
            FROM gold.player_season_split_stats
            GROUP BY player_id, season, team_id, split_type, split_value
            HAVING COUNT(*) > 1
        )
        """
    )[0]["row_count"]
    home_away_total = db.execute(
        """
        SELECT SUM(ppg * games) AS pts
        FROM gold.player_season_split_stats
        WHERE split_type = 'home_away'
        """
    )[0]["pts"]

    assert result["rows_written"] == 9
    assert duplicate_count == 0
    assert all(row["games"] > 0 for row in rows)
    assert all(row["ppg"] is not None and row["minutes"] is not None for row in rows)
    assert home_away_total == pytest.approx(30.0)
    assert {
        (row["split_type"], row["split_value"])
        for row in rows
    } >= {("home_away", "Home"), ("home_away", "Away"), ("rest_days", "B2B")}


def test_lineup_season_stats_grain_and_minutes_reconciliation(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner

    _create_fct_games(db)
    _create_fct_lineups(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "0029900001",
                "season": "2099-00",
                "game_type": "regular_season",
                "game_date": "2100-01-01",
                "home_team_id": 100,
                "away_team_id": 200,
                "home_score": 102,
                "away_score": 99,
                "status": "Final",
            },
            {
                "game_id": "0029900002",
                "season": "2099-00",
                "game_type": "regular_season",
                "game_date": "2100-01-03",
                "home_team_id": 100,
                "away_team_id": 200,
                "home_score": 110,
                "away_score": 105,
                "status": "Final",
            },
        ],
    )
    db.insert_rows(
        "silver",
        "fct_lineups",
        [
            {
                "game_id": "0029900001",
                "stint_number": 1,
                "period": 1,
                "team_id": 100,
                "player_ids_str": "5,4,3,2,1",
                "player_count": 5,
                "duration_seconds": 300.0,
                "points_for": 12,
                "points_against": 10,
            },
            {
                "game_id": "0029900002",
                "stint_number": 1,
                "period": 1,
                "team_id": 100,
                "player_ids_str": "1,2,3,4,5",
                "player_count": 5,
                "duration_seconds": 600.0,
                "points_for": 20,
                "points_against": 15,
            },
            {
                "game_id": "0029900002",
                "stint_number": 2,
                "period": 1,
                "team_id": 100,
                "player_ids_str": "1,2,3,4",
                "player_count": 4,
                "duration_seconds": 600.0,
                "points_for": 30,
                "points_against": 1,
            },
        ],
    )

    result = dbt_runner.run_model(model="lineup_season_stats")
    row = db.execute("SELECT * FROM gold.lineup_season_stats")[0]
    duplicate_count = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM (
            SELECT team_id, season, player_ids_str
            FROM gold.lineup_season_stats
            GROUP BY team_id, season, player_ids_str
            HAVING COUNT(*) > 1
        )
        """
    )[0]["row_count"]
    total_minutes = db.execute(
        "SELECT SUM(total_minutes) AS total_minutes FROM gold.lineup_season_stats"
    )[0]["total_minutes"]

    assert result["rows_written"] == 1
    assert duplicate_count == 0
    assert row["player_ids_str"] == "1,2,3,4,5"
    assert row["stints"] == 2
    assert row["total_minutes"] == pytest.approx(15.0)
    assert row["total_pts_for"] == 32
    assert row["total_pts_against"] == 25
    assert row["net_rating_per_48"] == pytest.approx(22.4)
    assert total_minutes == pytest.approx(15.0)


def test_player_combo_season_stats_grain_and_combo_totals(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner

    _create_dim_players(db)
    _create_fct_boxscores(db)
    _create_fct_games(db)
    _create_fct_lineups(db)
    db.insert_rows(
        "silver",
        "dim_players",
        [
            {
                "player_id": player_id,
                "full_name": f"Player {player_id}",
                "team_id": 100,
                "season": "2099-00",
            }
            for player_id in range(1, 6)
        ],
    )
    db.insert_rows(
        "silver",
        "fct_boxscores",
        [
            {
                "game_id": "0029900001",
                "player_id": player_id,
                "team_id": 100,
                "player_name": f"Box Player {player_id}",
            }
            for player_id in range(1, 6)
        ],
    )
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "0029900001",
                "season": "2099-00",
                "game_type": "regular_season",
                "game_date": "2100-01-01",
                "home_team_id": 100,
                "away_team_id": 200,
                "home_score": 102,
                "away_score": 99,
                "status": "Final",
            }
        ],
    )
    db.insert_rows(
        "silver",
        "fct_lineups",
        [
            {
                "game_id": "0029900001",
                "stint_number": 1,
                "period": 1,
                "team_id": 100,
                "player_ids_str": "5,4,3,2,1",
                "player_count": 5,
                "duration_seconds": 600.0,
                "points_for": 22,
                "points_against": 10,
            }
        ],
    )

    result = dbt_runner.run_model(model="player_combo_season_stats")
    duplicate_count = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM (
            SELECT team_id, season, combo_type, player_ids
            FROM gold.player_combo_season_stats
            GROUP BY team_id, season, combo_type, player_ids
            HAVING COUNT(*) > 1
        )
        """
    )[0]["row_count"]
    row = db.execute(
        """
        SELECT *
        FROM gold.player_combo_season_stats
        WHERE combo_type = '2-man' AND player_ids = '1,2'
        """
    )[0]

    assert result["rows_written"] == 10
    assert duplicate_count == 0
    assert row["player_names"] == "Player 1,Player 2"
    assert row["stints"] == 1
    assert row["total_minutes"] == pytest.approx(10.0)
    assert row["pts_for"] == 22
    assert row["pts_against"] == 10
    assert row["net_rating_per_48"] == pytest.approx(57.6)
    assert db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM gold.player_combo_season_stats
        WHERE total_minutes IS NULL OR pts_for IS NULL OR pts_against IS NULL
        """
    )[0]["row_count"] == 0


def test_team_season_feature_matrix_grain_and_core_inputs(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner

    _create_team_feature_matrix_inputs(db)
    db.insert_rows(
        "gold",
        "team_season_four_factors",
        [
            {
                "team_id": 100,
                "season": "2099-00",
                "team_abbreviation": "AAA",
                "games": 2,
                "ppg": 110.0,
                "opp_ppg": 103.0,
                "pace": 99.5,
                "off_efg_pct": 0.55,
                "off_tov_pct": 0.12,
                "off_oreb_pct": 0.28,
                "off_ft_rate": 0.22,
                "def_efg_pct": 0.50,
                "def_tov_pct": 0.14,
                "def_oreb_pct": 0.24,
                "def_ft_rate": 0.19,
                "pyth_win_pct": 0.68,
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_elo",
        [
            {
                "team_id": 100,
                "season": "2099-00",
                "team_abbreviation": "AAA",
                "elo_rating": 1550.0,
                "current_wins": 50,
                "current_losses": 32,
                "win_pct": 0.61,
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_game_stats",
        [
            {
                "game_id": "0029900001",
                "team_id": 100,
                "season": "2099-00",
                "game_date": "2100-01-01",
                "pts": 110,
                "opp_pts": 100,
                "margin": 10,
                "is_win": True,
                "off_rtg": 112.0,
                "def_rtg": 102.0,
                "net_rtg": 10.0,
            },
            {
                "game_id": "0029900002",
                "team_id": 100,
                "season": "2099-00",
                "game_date": "2100-01-03",
                "pts": 104,
                "opp_pts": 108,
                "margin": -4,
                "is_win": False,
                "off_rtg": 106.0,
                "def_rtg": 110.0,
                "net_rtg": -4.0,
            },
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_shot_profile",
        [
            {"team_id": 100, "season": "2099-00", "shot_bucket": "Paint", "freq_pct": 0.45},
            {"team_id": 100, "season": "2099-00", "shot_bucket": "3PT", "freq_pct": 0.35},
            {"team_id": 100, "season": "2099-00", "shot_bucket": "Midrange", "freq_pct": 0.20},
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_play_type_stats",
        [
            {
                "offense_team_id": 100,
                "season": "2099-00",
                "play_type": "Transition",
                "frequency_pct": 0.18,
            },
            {
                "offense_team_id": 100,
                "season": "2099-00",
                "play_type": "Isolation",
                "frequency_pct": 0.07,
            },
            {
                "offense_team_id": 100,
                "season": "2099-00",
                "play_type": "PRBallHandler",
                "frequency_pct": 0.21,
            },
            {
                "offense_team_id": 100,
                "season": "2099-00",
                "play_type": "Spotup",
                "frequency_pct": 0.24,
            },
            {
                "offense_team_id": 100,
                "season": "2099-00",
                "play_type": "Postup",
                "frequency_pct": 0.05,
            },
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_starter_bench_stats",
        [
            {"team_id": 100, "season": "2099-00", "role": "Starter", "ppg": 70.0},
            {"team_id": 100, "season": "2099-00", "role": "Bench", "ppg": 35.0},
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_clutch_stats",
        [{"offense_team_id": 100, "season": "2099-00", "clutch_ppp": 1.12}],
    )

    result = dbt_runner.run_model(model="team_season_feature_matrix")
    row = db.execute("SELECT * FROM gold.team_season_feature_matrix")[0]
    duplicate_count = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM (
            SELECT team_id, season
            FROM gold.team_season_feature_matrix
            GROUP BY team_id, season
            HAVING COUNT(*) > 1
        )
        """
    )[0]["row_count"]

    assert result["rows_written"] == 1
    assert duplicate_count == 0
    assert row["team_abbreviation"] == "T01"
    assert row["ppg"] == pytest.approx(110.0)
    assert row["l5_wins"] == 1
    assert row["l5_losses"] == 1
    assert row["l5_net_rtg"] == pytest.approx(3.0)
    assert row["paint_freq"] == pytest.approx(0.45)
    assert row["three_freq"] == pytest.approx(0.35)
    assert row["starter_ppg"] == pytest.approx(70.0)
    assert row["bench_ppg"] == pytest.approx(35.0)
    assert row["clutch_ppp"] == pytest.approx(1.12)
    assert db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM gold.team_season_feature_matrix
        WHERE pace IS NULL OR elo_rating IS NULL OR transition_freq IS NULL
        """
    )[0]["row_count"] == 0


def test_team_percentile_scope_is_data_driven_per_season(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner
    from nba_duckdb.defaults import ALL_TEAM_IDS

    full_team_ids = [int(value) for value in ALL_TEAM_IDS.split(",")]
    rows = [
        {
            "team_id": team_id,
            "season": "2098-99",
            "team_abbreviation": f"F{index:02d}",
            "games": 1,
            "ppg": 100 + index,
            "opp_ppg": 99,
            "pace": 100.0,
            "off_efg_pct": 50 + index / 10,
            "off_tov_pct": 12,
            "off_oreb_pct": 25,
            "off_ft_rate": 20,
            "def_efg_pct": 50,
            "def_tov_pct": 12,
            "def_oreb_pct": 25,
            "def_ft_rate": 20,
        }
        for index, team_id in enumerate(full_team_ids, start=1)
    ]
    rows.extend(
        [
            {
                "team_id": 900001 + index,
                "season": "2099-00",
                "team_abbreviation": f"S{index:02d}",
                "games": 1,
                "ppg": 100 + index,
                "opp_ppg": 99,
                "pace": 100.0,
                "off_efg_pct": 50 + index,
                "off_tov_pct": 12,
                "off_oreb_pct": 25,
                "off_ft_rate": 20,
                "def_efg_pct": 50,
                "def_tov_pct": 12,
                "def_oreb_pct": 25,
                "def_ft_rate": 20,
            }
            for index in range(2)
        ]
    )
    _create_team_season_four_factors(db)
    db.insert_rows("gold", "team_season_four_factors", rows)

    dbt_runner.run_model(model="team_season_percentile_ranks")

    scopes = {
        row["season"]: (row["comparison_scope"], row["comparison_team_count"])
        for row in db.execute(
            """
            SELECT season, MIN(comparison_scope) AS comparison_scope,
                   MIN(comparison_team_count) AS comparison_team_count
            FROM gold.team_season_percentile_ranks
            GROUP BY season
            ORDER BY season
            """
        )
    }

    assert scopes == {
        "2098-99": ("full_league", 30),
        "2099-00": ("loaded_sample", 2),
    }


def test_team_elo_labels_loaded_sample_and_suppresses_projections(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner

    _seed_dim_teams(db, [1610612737, 1610612738])
    _create_fct_games(db)
    _create_team_elo_tables(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "0029900001",
                "season": "2099-00",
                "game_date": "2100-01-01",
                "home_team_id": 1610612737,
                "away_team_id": 1610612738,
                "home_score": 101,
                "away_score": 99,
                "status": "Final",
            }
        ],
    )

    result = dbt_runner.run_model(model="team_season_elo")
    rows = db.execute(
        """
        SELECT comparison_scope, comparison_team_count, projected_wins,
               projected_losses, projected_win_pct
        FROM gold.team_season_elo
        ORDER BY team_id
        """
    )

    assert result["rows_written"] == 2
    assert {row["comparison_scope"] for row in rows} == {"loaded_sample"}
    assert {row["comparison_team_count"] for row in rows} == {2}
    assert all(row["projected_wins"] is None for row in rows)
    assert all(row["projected_losses"] is None for row in rows)
    assert all(row["projected_win_pct"] is None for row in rows)


def test_team_elo_empty_scoped_refresh_deletes_stale_rows(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner

    _seed_dim_teams(db, [1610612737, 1610612738])
    _create_fct_games(db)
    _create_team_elo_tables(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": "0029800001",
                "season": "2098-99",
                "game_date": "2099-01-01",
                "home_team_id": 1610612737,
                "away_team_id": 1610612738,
                "home_score": 101,
                "away_score": 99,
                "status": "Final",
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_elo",
        [{"team_id": 1610612737, "season": "2099-00", "elo_rating": 1510.0}],
    )
    db.insert_rows(
        "gold",
        "team_game_elo_history",
        [
            {
                "team_id": 1610612737,
                "season": "2099-00",
                "game_id": "0029900001",
                "elo_before": 1500.0,
                "elo_after": 1510.0,
            }
        ],
    )

    result = dbt_runner.run_model(model="team_season_elo", full_refresh=True)

    assert result["rows_written"] == 2
    stale_rows = db.execute(
        "SELECT COUNT(*) AS row_count FROM gold.team_season_elo WHERE season = '2099-00'"
    )[0]["row_count"]
    assert stale_rows == 0


def test_bpm_vorp_transform_computes_approx_columns(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb.transforms.gold.bpm_vorp import build_bpm_vorp

    _create_fct_games(db)
    _create_player_game_stats(db)
    _create_player_season_stats(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [{"game_id": "0029900001", "season": "2099-00"}],
    )
    _create_team_season_four_factors(db)
    _create_player_dbt_mart_inputs(db)
    db.insert_rows(
        "gold",
        "team_season_four_factors",
        [{"team_id": 1610612737, "season": "2099-00", "pace": 100.0}],
    )
    db.insert_rows(
        "gold",
        "player_game_stats",
        [
            {
                "game_id": "0029900001",
                "player_id": 990001,
                "team_id": 1610612737,
                "player_name": "Synthetic Guard",
                "minutes": 32.0,
                "pts": 24,
                "reb": 6,
                "oreb": 1,
                "dreb": 5,
                "ast": 7,
                "stl": 2,
                "blk": 1,
                "tov": 3,
                "fga": 18,
                "fg3a": 7,
                "pf": 2,
            }
        ],
    )
    db.insert_rows(
        "gold",
        "player_season_stats",
        [
            {
                "player_id": 990001,
                "season": "2099-00",
                "player_name": "Synthetic Guard",
                "avg_usg_pct": 0.27,
                "games_played": 1,
            }
        ],
    )

    result, league_avg_pace = build_bpm_vorp(
        player_games=db.read_table("gold", "player_game_stats"),
        fct_games=db.read_table("silver", "fct_games"),
        season_stats=db.read_table("gold", "player_season_stats"),
        four_factors=db.read_table("gold", "team_season_four_factors"),
    )
    row = result.row(0, named=True)

    assert result.height == 1
    assert league_avg_pace == 100.0
    assert row["player_id"] == 990001
    assert row["obpm"] is not None
    assert row["dbpm"] is not None
    assert row["bpm_approx"] is not None
    assert row["vorp_approx"] is not None


def test_library_gold_consumers_resolve_bpm_approx_columns(tmp_path, monkeypatch):
    pytest.importorskip("sklearn")
    pytest.importorskip("scipy")
    db = _init_tmp_db(tmp_path, monkeypatch)
    from nba_duckdb import dbt_runner
    from nba_duckdb.tasks.gold import compute_rapm

    _create_dim_players(db)
    _create_fct_games(db)
    _create_fct_lineups(db)
    _create_fct_hustle(db)
    _create_player_season_stats(db)
    _create_team_elo_tables(db)
    _create_player_game_stats(db)
    _create_team_game_stats(db)
    db.insert_rows(
        "silver",
        "dim_players",
        [{"player_id": pid, "full_name": f"Synthetic Player {pid}"} for pid in range(1, 11)],
    )
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {
                "game_id": f"002990000{game}",
                "season": "2099-00",
                "game_date": f"2100-01-0{game}",
                "home_team_id": 100,
                "away_team_id": 200,
                "home_score": 100 + game,
                "away_score": 95,
                "status": "Final",
            }
            for game in (1, 2)
        ],
    )
    lineup_rows = []
    for game in (1, 2):
        game_id = f"002990000{game}"
        for team_id, players, points_for, points_against in (
            (100, "1,2,3,4,5", 12 + game, 9),
            (200, "6,7,8,9,10", 9, 12 + game),
        ):
            lineup_rows.append(
                {
                    "game_id": game_id,
                    "stint_number": 1,
                    "period": 1,
                    "team_id": team_id,
                    "player_ids_str": players,
                    "player_count": 5,
                    "start_clock_seconds": 720.0,
                    "end_clock_seconds": 420.0,
                    "duration_seconds": 300.0,
                    "points_for": points_for,
                    "points_against": points_against,
                }
            )
    db.insert_rows("silver", "fct_lineups", lineup_rows)
    db.insert_rows(
        "gold",
        "player_season_stats",
        [
            {
                "player_id": 1,
                "season": "2099-00",
                "player_name": "Synthetic Player 1",
                "team_id": 100,
                "position": "G",
                "games_played": 30,
                "mpg": 32.0,
                "ppg": 24.0,
                "rpg": 6.0,
                "apg": 7.0,
                "avg_ts_pct": 0.61,
                "avg_game_score": 18.0,
                "plus_minus_avg": 5.0,
                "bpm_approx": 7.5,
                "vorp_approx": 3.1,
            },
            {
                "player_id": 6,
                "season": "2099-00",
                "player_name": "Synthetic Player 6",
                "team_id": 200,
                "position": "F",
                "games_played": 30,
                "mpg": 31.0,
                "ppg": 21.0,
                "rpg": 8.0,
                "apg": 4.0,
                "avg_ts_pct": 0.58,
                "avg_game_score": 15.0,
                "plus_minus_avg": 2.0,
                "bpm_approx": 4.0,
                "vorp_approx": 1.8,
            },
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_elo",
        [
            {"team_id": 100, "season": "2099-00", "team_abbreviation": "AAA", "win_pct": 0.7},
            {"team_id": 200, "season": "2099-00", "team_abbreviation": "BBB", "win_pct": 0.5},
        ],
    )
    _create_team_season_four_factors(db)
    db.insert_rows(
        "gold",
        "team_season_four_factors",
        [
            {"team_id": 100, "season": "2099-00", "pace": 100.0},
            {"team_id": 200, "season": "2099-00", "pace": 100.0},
        ],
    )
    _create_player_dbt_mart_inputs(db)

    dbt_runner.run_model(model="player_season_on_off_stats")
    dbt_runner.run_model(model="player_game_rolling_stats")
    dbt_runner.run_model(model="player_season_archetypes")
    monkeypatch.setattr(
        compute_rapm,
        "build_design_matrix",
        lambda *_args, **_kwargs: (
            np.eye(10),
            np.ones(10),
            np.ones(10),
            list(range(1, 11)),
            np.array(["0029900001", "0029900002"] * 5),
        ),
    )
    monkeypatch.setattr(
        compute_rapm,
        "fit_rapm",
        lambda *_args, **_kwargs: (np.ones(10), 1.0, 0.1),
    )
    monkeypatch.setattr(
        compute_rapm,
        "bootstrap_ci",
        lambda *_args, **_kwargs: (np.zeros(10), np.ones(10)),
    )

    rapm_result = compute_rapm.run(season="2099-00")
    mvp_result = dbt_runner.run_model(model="player_season_mvp_ladder")
    feature_result = dbt_runner.run_model(model="player_season_feature_matrix")

    rapm_row = db.execute(
        "SELECT drapm_prior, rapm_blended FROM gold.player_season_rapm WHERE player_id = 1"
    )[0]
    mvp_row = db.execute(
        "SELECT bpm_approx, vorp_approx FROM gold.player_season_mvp_ladder WHERE player_id = 1"
    )[0]
    feature_row = db.execute(
        "SELECT bpm_approx, vorp_approx FROM gold.player_season_feature_matrix WHERE player_id = 1"
    )[0]

    assert rapm_result["rows_written"] == 10
    assert rapm_row["drapm_prior"] == 7.5
    assert rapm_row["rapm_blended"] > 1.0
    assert mvp_result["rows_written"] == 2
    assert mvp_row["bpm_approx"] == pytest.approx(7.5)
    assert mvp_row["vorp_approx"] == pytest.approx(3.1)
    assert feature_result["rows_written"] == 2
    assert feature_row["bpm_approx"] == pytest.approx(7.5)
    assert feature_row["vorp_approx"] == pytest.approx(3.1)


def test_public_docs_and_source_avoid_overclaim_phrases():
    from pathlib import Path

    root = Path(__file__).parents[1]
    texts = [root.joinpath("README.md").read_text()]
    texts.extend(
        path.read_text()
        for path in sorted(root.joinpath("src").rglob("*"))
        if path.is_file() and path.suffix in {".py", ".sql", ".md"}
    )
    serialized = "\n".join(texts)

    banned_phrases = [
        "official " + "BPM",
        "validated " + "model",
        "matching " + "Synergy",
        "league " + "percentile",
    ]
    for phrase in banned_phrases:
        assert phrase not in serialized

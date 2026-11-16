import pytest


def _duplicate_keys(db, table, keys):
    """Count key combinations that appear more than once in `table`."""
    columns = ", ".join(keys)
    return db.execute(
        f"SELECT COUNT(*) AS row_count FROM "
        f"(SELECT {columns} FROM {table} GROUP BY {columns} HAVING COUNT(*) > 1)"
    )[0]["row_count"]


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
            game_date DATE,
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
            game_date DATE,
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
            game_date DATE,
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
            attempts INTEGER
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS gold.team_season_starter_bench_stats (
            team_id INTEGER,
            season TEXT,
            role TEXT,
            ppg REAL,
            pts_per_team_game REAL
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


def test_player_season_split_stats_grain_and_source_reconciliation(tmp_db):
    db = tmp_db
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
    duplicate_count = _duplicate_keys(db, "gold.player_season_split_stats", ["player_id", "season", "team_id", "split_type", "split_value"])
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


def test_lineup_season_stats_grain_and_minutes_reconciliation(tmp_db):
    db = tmp_db
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
    duplicate_count = _duplicate_keys(db, "gold.lineup_season_stats", ["team_id", "season", "player_ids_str"])
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


def test_player_combo_season_stats_grain_and_combo_totals(tmp_db):
    db = tmp_db
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
    duplicate_count = _duplicate_keys(db, "gold.player_combo_season_stats", ["team_id", "season", "combo_type", "player_ids"])
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


def test_team_season_feature_matrix_grain_and_core_inputs(tmp_db):
    db = tmp_db
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
            {"team_id": 100, "season": "2099-00", "shot_bucket": "paint_2", "attempts": 45},
            {"team_id": 100, "season": "2099-00", "shot_bucket": "three", "attempts": 35},
            {"team_id": 100, "season": "2099-00", "shot_bucket": "non_paint_2", "attempts": 20},
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
            {"team_id": 100, "season": "2099-00", "role": "Starter", "ppg": 14.0, "pts_per_team_game": 70.0},
            {"team_id": 100, "season": "2099-00", "role": "Bench", "ppg": 8.0, "pts_per_team_game": 40.0},
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_clutch_stats",
        [{"offense_team_id": 100, "season": "2099-00", "clutch_ppp": 1.12}],
    )

    result = dbt_runner.run_model(model="team_season_feature_matrix")
    row = db.execute("SELECT * FROM gold.team_season_feature_matrix")[0]
    duplicate_count = _duplicate_keys(db, "gold.team_season_feature_matrix", ["team_id", "season"])

    assert result["rows_written"] == 1
    assert duplicate_count == 0
    assert row["team_abbreviation"] == "T01"
    assert row["ppg"] == pytest.approx(110.0)
    assert row["l5_wins"] == 1
    assert row["l5_losses"] == 1
    assert row["l5_avg_margin"] == pytest.approx(3.0)
    assert (row["paint_freq"], row["three_freq"], row["mid_freq"]) == pytest.approx((45.0, 35.0, 20.0))
    # Points per team game, not per player appearance, so they add up to the team's ppg.
    assert row["starter_ppg"] == pytest.approx(70.0)
    assert row["bench_ppg"] == pytest.approx(40.0)
    assert row["starter_ppg"] + row["bench_ppg"] == pytest.approx(row["ppg"])
    assert row["clutch_ppp"] == pytest.approx(1.12)
    assert db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM gold.team_season_feature_matrix
        WHERE pace IS NULL OR elo_rating IS NULL OR transition_freq IS NULL
        """
    )[0]["row_count"] == 0


def test_team_percentile_scope_is_data_driven_per_season(tmp_db):
    db = tmp_db
    from nba_duckdb import dbt_runner
    from nba_duckdb.defaults import ALL_TEAM_IDS

    full_team_ids = list(ALL_TEAM_IDS)
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


def test_team_elo_labels_loaded_sample_and_suppresses_projections(tmp_db):
    db = tmp_db
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


def test_team_elo_empty_scoped_refresh_deletes_stale_rows(tmp_db):
    db = tmp_db
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


def test_bpm_vorp_transform_computes_approx_columns(tmp_db):
    db = tmp_db
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


def test_bpm_vorp_transform_keeps_traded_player_at_player_season_grain():
    import polars as pl

    from nba_duckdb.transforms.gold.bpm_vorp import build_bpm_vorp

    player_games = pl.DataFrame(
        {
            "game_id": ["0029900001", "0029900002"],
            "player_id": [990001, 990001],
            "team_id": [1610612737, 1610612738],
            "minutes": [30.0, 34.0],
            "pts": [20, 24],
            "reb": [5, 7],
            "oreb": [1, 2],
            "dreb": [4, 5],
            "ast": [6, 8],
            "stl": [1, 2],
            "blk": [0, 1],
            "tov": [2, 3],
            "fga": [15, 18],
            "fg3a": [6, 7],
            "pf": [2, 3],
        }
    )
    games = pl.DataFrame(
        {
            "game_id": ["0029900001", "0029900002"],
            "season": ["2099-00", "2099-00"],
        }
    )
    season_stats = pl.DataFrame(
        {
            "player_id": [990001],
            "season": ["2099-00"],
            "avg_usg_pct": [0.25],
        }
    )
    four_factors = pl.DataFrame(
        {
            "team_id": [1610612737, 1610612738],
            "season": ["2099-00", "2099-00"],
            "pace": [96.0, 104.0],
            "ppg": [110.0, 112.0],
            "opp_ppg": [108.0, 114.0],
        }
    )

    result, league_avg_pace = build_bpm_vorp(
        player_games=player_games,
        fct_games=games,
        season_stats=season_stats,
        four_factors=four_factors,
    )

    assert result.height == 1
    assert result.row(0, named=True)["player_id"] == 990001
    assert result.row(0, named=True)["season"] == "2099-00"
    assert league_avg_pace == 100.0


def test_library_gold_consumers_resolve_bpm_approx_columns(tmp_db):
    db = tmp_db
    from nba_duckdb import dbt_runner

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
    mvp_result = dbt_runner.run_model(model="player_season_mvp_ladder")
    feature_result = dbt_runner.run_model(model="player_season_feature_matrix")

    mvp_row = db.execute(
        "SELECT bpm_approx, vorp_approx FROM gold.player_season_mvp_ladder WHERE player_id = 1"
    )[0]
    feature_row = db.execute(
        "SELECT bpm_approx, vorp_approx FROM gold.player_season_feature_matrix WHERE player_id = 1"
    )[0]

    assert mvp_result["rows_written"] == 2
    assert mvp_row["bpm_approx"] == pytest.approx(7.5)
    assert mvp_row["vorp_approx"] == pytest.approx(3.1)
    assert feature_result["rows_written"] == 2
    assert feature_row["bpm_approx"] == pytest.approx(7.5)
    assert feature_row["vorp_approx"] == pytest.approx(3.1)


def test_games_a_player_missed_do_not_count_in_rolling_or_split_stats(tmp_db):
    db = tmp_db
    from nba_duckdb import dbt_runner

    _create_fct_games(db)
    _create_player_game_stats(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {"game_id": f"002990000{day}", "season": "2099-00", "game_type": "regular_season",
             "game_date": f"2100-01-0{day}", "home_team_id": 100, "away_team_id": 200,
             "home_score": 100, "away_score": 90, "status": "Final"}
            for day in (1, 2, 3)
        ],
    )
    played = {"player_id": 1, "team_id": 100, "player_name": "Synthetic Guard", "counts_as_gp": True,
              "minutes": 30.0, "pts": 20, "fga": 15, "fta": 2, "game_score": 15.0}
    db.insert_rows(
        "gold",
        "player_game_stats",
        [
            {**played, "game_id": "0029900001"},
            {**played, "game_id": "0029900002", "counts_as_gp": False, "minutes": 0.0, "pts": 0,
             "fga": 0, "fta": 0, "game_score": 0.0},
            {**played, "game_id": "0029900003"},
        ],
    )

    dbt_runner.run_model(model="player_game_rolling_stats")
    dbt_runner.run_model(model="player_season_split_stats")

    rolling = db.execute(
        "SELECT game_id, game_number FROM gold.player_game_rolling_stats ORDER BY game_number"
    )
    home = db.execute(
        "SELECT games, ppg FROM gold.player_season_split_stats WHERE split_value = 'Home'"
    )[0]
    assert [(row["game_id"], row["game_number"]) for row in rolling] == [
        ("0029900001", 1),
        ("0029900003", 2),
    ]
    assert (home["games"], home["ppg"]) == (2, 20.0)


def _seed_player_season_inputs(db, game_count, rows, plays=()):
    """Regular-season games one day apart, player game lines and play-by-play for player_season_stats_base."""
    db.execute(
        "CREATE TABLE silver.dim_players (player_id INTEGER, full_name TEXT, position TEXT, jersey_number TEXT)"
    )
    _create_fct_games(db)
    _create_player_game_stats(db)
    db.execute(
        "CREATE TABLE silver.fct_play_by_play (game_id TEXT, team_id INTEGER, player_id INTEGER, action_type TEXT)"
    )
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {"game_id": f"00299000{game:02d}", "season": "2099-00", "game_date": f"2100-01-{game:02d}",
             "home_team_id": 100, "away_team_id": 200, "status": "Final"}
            for game in range(1, game_count + 1)
        ],
    )
    db.insert_rows("gold", "player_game_stats", rows)
    if plays:
        db.insert_rows("silver", "fct_play_by_play", list(plays))


def test_traded_player_is_listed_under_the_team_he_played_most_games_for(tmp_db):
    from nba_duckdb import dbt_runner

    def line(game, player_id, team_id, played=True):
        return {"game_id": f"00299000{game:02d}", "player_id": player_id, "team_id": team_id,
                "player_name": f"Synthetic Player {player_id}", "counts_as_gp": played,
                "minutes": 20.0 if played else 0.0, "pts": 10 if played else 0}

    _seed_player_season_inputs(
        tmp_db,
        6,
        [
            # Player 1 played two games for team 100, then sat inactive three times for team 200 before playing once.
            line(1, 1, 100), line(2, 1, 100),
            line(3, 1, 200, played=False), line(4, 1, 200, played=False), line(5, 1, 200, played=False),
            line(6, 1, 200),
            # Player 2 played one game for each team; the tie goes to the later team.
            line(1, 2, 100), line(2, 2, 200),
        ],
    )

    dbt_runner.run_model(model="player_season_stats_base")
    rows = tmp_db.execute("SELECT player_id, team_id FROM gold.player_season_stats_base ORDER BY player_id")

    assert [(row["player_id"], row["team_id"]) for row in rows] == [(1, 100), (2, 200)]


def test_shooting_percentiles_need_100_attempts(tmp_db):
    from nba_duckdb import dbt_runner

    def line(player_id, attempts, makes):
        return {"game_id": "0029900001", "player_id": player_id, "team_id": 100,
                "player_name": f"Synthetic Player {player_id}", "counts_as_gp": True, "minutes": 30.0,
                "fga": attempts, "fgm": makes, "fg3a": attempts, "fg3m": makes}

    _seed_player_season_inputs(tmp_db, 1, [line(1, 10, 10), line(2, 100, 50), line(3, 100, 30)])

    dbt_runner.run_model(model="player_season_stats_base")
    rows = tmp_db.execute(
        "SELECT player_id, fg_shoot_pct, fg3_shoot_pct FROM gold.player_season_stats_base ORDER BY player_id"
    )

    assert [(row["player_id"], row["fg_shoot_pct"], row["fg3_shoot_pct"]) for row in rows] == [
        (1, None, None),
        (2, 100, 100),
        (3, 0, 0),
    ]


def test_season_usage_comes_from_season_totals_with_team_turnovers(tmp_db):
    from nba_duckdb import dbt_runner

    def line(game, player_id, minutes, fga, fta, tov):
        return {"game_id": f"00299000{game:02d}", "player_id": player_id, "team_id": 100,
                "player_name": f"Synthetic Player {player_id}", "counts_as_gp": minutes > 0, "minutes": minutes,
                "fga": fga, "fta": fta, "tov": tov, "usg_pct": 0.30}

    turnover = {"game_id": "0029900001", "team_id": 100, "action_type": "turnover"}
    _seed_player_season_inputs(
        tmp_db,
        2,
        [
            line(1, 1, 30.0, 20, 5, 3), line(1, 2, 18.0, 10, 0, 1),
            # Game 2 has no play-by-play, so team turnovers are unknown there.
            line(2, 1, 0.0, 0, 0, 0), line(2, 2, 48.0, 40, 0, 0),
        ],
        # Four player turnovers plus one team turnover (shot clock) in game 1.
        [{**turnover, "player_id": 1}] * 3 + [{**turnover, "player_id": 2}, {**turnover, "player_id": None}],
    )

    dbt_runner.run_model(model="player_season_stats_base")
    rows = tmp_db.execute("SELECT player_id, avg_usg_pct FROM gold.player_season_stats_base ORDER BY player_id")

    # Player 1, game 1 only: (20 + 0.44 * 5 + 3) * (48 / 5) / (30 * (30 + 0.44 * 5 + 5)) = 0.2168
    assert [(row["player_id"], row["avg_usg_pct"]) for row in rows] == [(1, pytest.approx(0.217)), (2, None)]


def test_hot_and_cold_flags_use_only_games_so_far(tmp_db):
    from datetime import date, timedelta

    from nba_duckdb import dbt_runner

    _create_fct_games(tmp_db)
    _create_player_game_stats(tmp_db)
    # Fifteen quiet games, a five-game hot streak, then two wild games that later widen the season's spread.
    scores = [10.0] * 15 + [20.0] * 5 + [100.0, -50.0]
    game_ids = [f"00299000{game:02d}" for game in range(1, len(scores) + 1)]
    tmp_db.insert_rows(
        "silver",
        "fct_games",
        [
            {"game_id": game_id, "season": "2099-00", "game_date": date(2100, 1, 1) + timedelta(days=day),
             "home_team_id": 100, "away_team_id": 200, "status": "Final"}
            for day, game_id in enumerate(game_ids)
        ],
    )
    tmp_db.insert_rows(
        "gold",
        "player_game_stats",
        [
            {"game_id": game_id, "player_id": 1, "team_id": 100, "player_name": "Synthetic Guard",
             "counts_as_gp": True, "minutes": 30.0, "game_score": score}
            for game_id, score in zip(game_ids, scores)
        ],
    )

    dbt_runner.run_model(model="player_game_rolling_stats")
    row = tmp_db.execute("SELECT is_hot FROM gold.player_game_rolling_stats WHERE game_number = 20")[0]

    # Last 5 (20.0) minus last 20 (12.5) is 7.5, above the 4.4 spread of the first 20 games.
    assert row["is_hot"] is True


def test_shot_profiles_count_only_regular_season_games(tmp_db):
    db = tmp_db
    from nba_duckdb import dbt_runner

    _create_fct_games(db)
    db.insert_rows(
        "silver",
        "fct_games",
        [
            {"game_id": game_id, "season": "2099-00", "game_type": game_type, "game_date": "2100-01-01",
             "home_team_id": 100, "away_team_id": 200, "status": "Final"}
            for game_id, game_type in (
                ("0019900001", "preseason"),
                ("0029900001", "regular_season"),
                ("0039900001", "all_star"),
                ("0049900001", "playoffs"),
            )
        ],
    )
    db.execute(
        """
        CREATE TABLE silver.fct_shots AS
        SELECT game_id, 1 AS player_id, 'Synthetic Guard' AS player_name, 100 AS team_id,
               '2099-00' AS season, 'Restricted Area' AS shot_zone_basic, '2PT Field Goal' AS shot_type,
               TRUE AS shot_made
        FROM silver.fct_games
        """
    )

    dbt_runner.run_model(model="team_season_shot_profile")
    dbt_runner.run_model(model="player_season_shot_profile")

    assert db.execute("SELECT SUM(attempts) AS n FROM gold.team_season_shot_profile")[0]["n"] == 1
    assert db.execute("SELECT SUM(attempts) AS n FROM gold.player_season_shot_profile")[0]["n"] == 1


def test_team_percentiles_leave_missing_values_unranked(tmp_db):
    from nba_duckdb import dbt_runner

    def team(team_id, pace):
        return {
            "team_id": team_id, "season": "2099-00", "team_abbreviation": f"T{team_id}", "games": 1,
            "ppg": 100, "opp_ppg": 99, "pace": pace, "off_efg_pct": 50, "off_tov_pct": 12, "off_oreb_pct": 25,
            "off_ft_rate": 20, "def_efg_pct": 50, "def_tov_pct": 12, "def_oreb_pct": 25, "def_ft_rate": 20,
        }

    _create_team_season_four_factors(tmp_db)
    tmp_db.insert_rows("gold", "team_season_four_factors", [team(1, 95.0), team(2, 105.0), team(3, None)])

    dbt_runner.run_model(model="team_season_percentile_ranks")
    rows = tmp_db.execute("SELECT team_id, pace_pct FROM gold.team_season_percentile_ranks ORDER BY team_id")

    assert [(row["team_id"], row["pace_pct"]) for row in rows] == [(1, 0), (2, 100), (3, None)]


def test_timeout_stats_skip_coach_challenges(tmp_db):
    from nba_duckdb import dbt_runner

    _create_fct_games(tmp_db)
    tmp_db.insert_rows("silver", "fct_games", [{"game_id": "0029900001", "season": "2099-00", "game_type": "regular_season"}])
    tmp_db.execute(
        "CREATE TABLE silver.fct_play_by_play (game_id TEXT, team_id INTEGER, period INTEGER, "
        "clock_seconds_remaining DOUBLE, action_type TEXT, sub_type TEXT)"
    )
    tmp_db.insert_rows(
        "silver",
        "fct_play_by_play",
        [
            {"game_id": "0029900001", "team_id": 1, "period": 4, "clock_seconds_remaining": 90.0, "action_type": "timeout", "sub_type": sub_type}
            for sub_type in ("full", "Regular", "challenge", "Coach Challenge")
        ],
    )

    dbt_runner.run_model(model="team_season_timeout_stats")

    assert tmp_db.execute("SELECT total_timeouts FROM gold.team_season_timeout_stats")[0]["total_timeouts"] == 2


def test_player_clutch_stats_use_the_score_before_each_play(tmp_db):
    from nba_duckdb import dbt_runner

    _create_fct_games(tmp_db)
    game_ids = ["0029900001", "0029900002"]
    tmp_db.insert_rows("silver", "fct_games", [{"game_id": game_id, "season": "2099-00"} for game_id in game_ids])
    tmp_db.execute(
        "CREATE TABLE silver.fct_play_by_play (game_id TEXT, period INTEGER, action_id BIGINT, "
        "clock_seconds_remaining DOUBLE, player_id INTEGER, player_name TEXT, team_id INTEGER, action_type TEXT, "
        "sub_type TEXT, description TEXT, shot_result TEXT, is_field_goal BOOLEAN, score_home TEXT, score_away TEXT)"
    )
    # Down 6, player 1's layup makes it 4: not clutch. Down 4, player 2's 3 makes it 7: clutch.
    plays = [
        (None, None, "", False, "94", "100"),
        (1, 100, "2pt", True, "96", "100"),
        (2, 200, "3pt", True, "96", "103"),
    ]
    tmp_db.insert_rows(
        "silver",
        "fct_play_by_play",
        [
            {"game_id": game_id, "period": 4, "action_id": action_id, "clock_seconds_remaining": 60.0 - action_id,
             "player_id": player_id, "player_name": f"Player {player_id}", "team_id": team_id,
             "action_type": action_type, "sub_type": "", "description": action_type.upper(), "shot_result": "Made",
             "is_field_goal": is_field_goal, "score_home": score_home, "score_away": score_away}
            for game_id in game_ids
            for action_id, (player_id, team_id, action_type, is_field_goal, score_home, score_away) in enumerate(plays)
        ],
    )

    dbt_runner.run_model(model="player_season_clutch_stats")

    rows = tmp_db.execute("SELECT player_id, points FROM gold.player_season_clutch_stats")
    assert rows == [{"player_id": 2, "points": 6}]


def test_overtime_ato_is_clutch_only_within_five_points(tmp_db):
    from nba_duckdb import dbt_runner

    _create_fct_games(tmp_db)
    margins = {"0029900001": 10, "0029900002": 3}
    tmp_db.insert_rows("silver", "fct_games", [{"game_id": game_id, "season": "2099-00"} for game_id in margins])
    tmp_db.execute(
        "CREATE TABLE silver.fct_play_by_play (game_id TEXT, action_number INTEGER, period INTEGER, "
        "clock_seconds_remaining DOUBLE, team_id INTEGER, action_type TEXT, sub_type TEXT, shot_result TEXT, "
        "score_home TEXT, score_away TEXT)"
    )
    tmp_db.execute(
        "CREATE TABLE silver.fct_possessions (game_id TEXT, possession_number INTEGER, period INTEGER, "
        "start_clock_seconds DOUBLE, end_clock_seconds DOUBLE, end_type TEXT, is_garbage_time BOOLEAN)"
    )
    # Team 1 calls a timeout in overtime, then scores on the next possession.
    tmp_db.insert_rows(
        "silver",
        "fct_play_by_play",
        [
            row
            for game_id, margin in margins.items()
            for row in (
                {"game_id": game_id, "action_number": 1, "period": 5, "clock_seconds_remaining": 200.0, "team_id": 1,
                 "action_type": "timeout", "sub_type": "full", "shot_result": "",
                 "score_home": str(100 + margin), "score_away": "100"},
                {"game_id": game_id, "action_number": 2, "period": 5, "clock_seconds_remaining": 190.0, "team_id": 1,
                 "action_type": "2pt", "sub_type": "", "shot_result": "Made",
                 "score_home": str(102 + margin), "score_away": "100"},
            )
        ],
    )
    tmp_db.insert_rows(
        "silver",
        "fct_possessions",
        [
            {"game_id": game_id, "possession_number": 1, "period": 5, "start_clock_seconds": 200.0,
             "end_clock_seconds": 190.0, "end_type": "made_2", "is_garbage_time": False}
            for game_id in margins
        ],
    )

    dbt_runner.run_model(model="team_season_ato_stats")

    row = tmp_db.execute("SELECT offensive_ato_possessions, clutch_ato_possessions FROM gold.team_season_ato_stats")[0]
    assert (row["offensive_ato_possessions"], row["clutch_ato_possessions"]) == (2, 1)


def test_bpm_is_centered_on_each_teams_rating():
    import polars as pl

    from nba_duckdb.transforms.gold.bpm_vorp import build_bpm_vorp

    def game_line(game_id, player_id, team_id, minutes, pts, ast):
        return {"game_id": game_id, "player_id": player_id, "team_id": team_id, "minutes": minutes, "pts": pts,
                "reb": 5, "oreb": 1, "dreb": 4, "ast": ast, "stl": 1, "blk": 0, "tov": 2, "fga": 12, "fg3a": 4, "pf": 2}

    player_games = pl.DataFrame([
        game_line("g1", 1, 10, 36.0, 30, 8), game_line("g1", 2, 10, 12.0, 4, 1),
        game_line("g1", 3, 20, 30.0, 18, 4), game_line("g1", 4, 20, 18.0, 10, 2),
    ])
    games = pl.DataFrame({"game_id": ["g1"], "season": ["2099-00"]})
    season_stats = pl.DataFrame({"player_id": [1, 2, 3, 4], "season": ["2099-00"] * 4, "avg_usg_pct": [0.3, 0.15, 0.22, 0.18]})
    # Team 10 is +8 per 100 possessions, team 20 is -8.
    four_factors = pl.DataFrame({
        "team_id": [10, 20], "season": ["2099-00"] * 2, "pace": [100.0, 100.0],
        "ppg": [112.0, 104.0], "opp_ppg": [104.0, 112.0],
    })

    result, _ = build_bpm_vorp(
        player_games=player_games, fct_games=games, season_stats=season_stats, four_factors=four_factors
    )
    bpm = dict(result.select(["player_id", "bpm_approx"]).iter_rows())

    assert 5 * (bpm[1] * 36 + bpm[2] * 12) / 48 == pytest.approx(8.0, abs=0.3)
    assert 5 * (bpm[3] * 30 + bpm[4] * 18) / 48 == pytest.approx(-8.0, abs=0.3)

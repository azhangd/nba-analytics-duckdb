def test_summer_league_dbt_models_and_quality_gate_end_to_end(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.dbt_runner import run_dbt_command
    from nba_duckdb.fixtures.generate_synthetic_fixtures import (
        SEASON,
        generate_fixtures,
    )
    from nba_duckdb.tasks.bronze import load_synthetic_fixtures
    from nba_duckdb.tasks.quality import validate_summer_league

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "summer.duckdb"))
    fixtures_dir = tmp_path / "fixtures"
    generate_fixtures(fixtures_dir)
    db.init_schema()
    load_synthetic_fixtures.run(fixtures_dir=fixtures_dir)
    summer_game_id = db.execute_sql(
        "SELECT game_id FROM bronze.schedule ORDER BY game_id LIMIT 1"
    )[0]["game_id"]
    db.execute_sql(
        """
        UPDATE bronze.schedule
        SET league_id = '15',
            competition = 'summer_league_vegas'
        WHERE game_id = %s
        """,
        [summer_game_id],
    )

    run_dbt_command(
        [
            "build",
            "--select",
            "dim_players",
            "fct_games",
            "fct_boxscores",
            "fct_play_by_play",
            "fct_shots",
        ]
    )
    for table in ("fct_games", "fct_boxscores", "fct_play_by_play", "fct_shots"):
        assert db.execute_sql(
            f"SELECT COUNT(*) AS count FROM silver.{table} WHERE game_id = %s",
            [summer_game_id],
        ) == [{"count": 0}]

    run_dbt_command(["build", "--select", "tag:summer_league"])

    result = validate_summer_league.run(
        season=SEASON,
        competitions=["summer_league_vegas"],
    )

    assert result["status"] == "success"
    assert result["schedule_games"] == 1
    assert result["completed_games"] == 1
    assert db.count_rows("silver", "summer_league_games") == 1
    assert db.count_rows("silver", "summer_league_boxscores") > 0
    assert db.count_rows("silver", "summer_league_play_by_play") > 0
    assert db.count_rows("silver", "summer_league_shots") > 0

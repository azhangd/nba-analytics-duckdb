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
    db.execute_sql(
        """
        UPDATE bronze.schedule
        SET league_id = '15',
            competition = 'summer_league_vegas'
        """
    )

    run_dbt_command(["build", "--select", "tag:summer_league"])

    result = validate_summer_league.run(
        season=SEASON,
        competitions=["summer_league_vegas"],
    )

    assert result["status"] == "success"
    assert result["schedule_games"] == 44
    assert result["completed_games"] == 44
    assert db.count_rows("silver", "summer_league_games") == 44
    assert db.count_rows("silver", "summer_league_boxscores") > 0
    assert db.count_rows("silver", "summer_league_play_by_play") > 0
    assert db.count_rows("silver", "summer_league_shots") > 0

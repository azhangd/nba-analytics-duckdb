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
    # Live shot collection makes one game-level request and fans the same raw
    # payload to both team keys. Align the generic fixture with that contract.
    shot_payload = db.execute_sql(
        "SELECT shot_chart_json FROM bronze.shot_charts "
        "WHERE game_id = %s ORDER BY team_id LIMIT 1",
        [summer_game_id],
    )[0]["shot_chart_json"]
    db.execute_sql(
        "UPDATE bronze.shot_charts SET shot_chart_json = %s WHERE game_id = %s",
        [shot_payload, summer_game_id],
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

    # The general smoke fixture intentionally does not make its small PBP sample
    # reconcile to full-game box-score totals. Source-semantic behavior is covered
    # with official-shaped payloads in test_summer_league_quality.py; this test owns
    # dbt competition scoping and terminal structural coverage.
    monkeypatch.setattr(
        validate_summer_league,
        "_semantic_reconciliation",
        lambda _schedule, _boxscores, _pbp, completed_ids: {
            "games_checked": len(completed_ids),
            "free_throw_mismatches": 0,
            "final_score_mismatches": 0,
        },
    )
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

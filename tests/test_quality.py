import pytest
from conftest import schedule_row

from nba_duckdb.ingestion_state import eligible_items, make_item, mark_item_failed


def _insert_schedule(db):
    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row()
        ],
    )


def test_quality_coverage_detects_partial_play_by_play(tmp_db):
    db = tmp_db
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "boxscores",
        [{"game_id": "0029900001", "traditional_json": "{}", "advanced_json": "{}"}],
    )

    from nba_duckdb import quality

    failures, rows = quality._season_coverage_failures()

    assert rows[0]["completed_games"] == 1
    assert rows[0]["play_by_play_games"] == 0
    assert failures == ["season 2099-00 has 0/1 completed-game play-by-play rows"]


def test_quality_coverage_passes_when_raw_core_sources_are_complete(tmp_db):
    db = tmp_db
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "boxscores",
        [{"game_id": "0029900001", "traditional_json": "{}", "advanced_json": "{}"}],
    )
    db.insert_rows(
        "bronze",
        "play_by_play",
        [{"game_id": "0029900001", "pbp_json": '{"game":{"actions":[{}]}}'}],
    )

    from nba_duckdb import quality

    failures, _rows = quality._season_coverage_failures()

    assert failures == []


def test_quality_coverage_excludes_non_team_showcase_games(tmp_db):
    db = tmp_db
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0039900001", game_date="02/15/2100 00:00:00", home_team_id=1610616860, away_team_id=1610616861, home_team_abbr="AS1", away_team_abbr="AS2")
        ],
    )
    db.insert_rows(
        "bronze",
        "boxscores",
        [{"game_id": "0029900001", "traditional_json": "{}", "advanced_json": "{}"}],
    )
    db.insert_rows(
        "bronze",
        "play_by_play",
        [{"game_id": "0029900001", "pbp_json": '{"game":{"actions":[{}]}}'}],
    )

    from nba_duckdb import quality

    failures, rows = quality._season_coverage_failures()

    assert rows[0]["completed_games"] == 1
    assert failures == []


def test_quality_coverage_respects_team_scope(tmp_db, monkeypatch):
    db = tmp_db
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "schedule",
        [
            schedule_row(game_id="0029900002", game_date="01/02/2100 00:00:00", home_team_id=1610612747, away_team_id=1610612748, home_team_abbr="CCC", away_team_abbr="DDD")
        ],
    )
    db.insert_rows(
        "bronze",
        "boxscores",
        [{"game_id": "0029900001", "traditional_json": "{}", "advanced_json": "{}"}],
    )
    db.insert_rows(
        "bronze",
        "play_by_play",
        [{"game_id": "0029900001", "pbp_json": '{"game":{"actions":[{}]}}'}],
    )

    from nba_duckdb import quality

    monkeypatch.setenv("NBA_DUCKDB_TEAM_IDS", "1610612737")
    scoped_failures, scoped_rows = quality._season_coverage_failures()
    assert scoped_rows[0]["completed_games"] == 1
    assert scoped_failures == []

    monkeypatch.setenv("NBA_DUCKDB_TEAM_IDS", "1610612747")
    other_failures, other_rows = quality._season_coverage_failures()
    assert other_rows[0]["completed_games"] == 1
    assert other_failures == [
        "season 2099-00 has 0/1 completed-game boxscores",
        "season 2099-00 has 0/1 completed-game play-by-play rows",
    ]


def test_quality_detects_failed_core_ingestion_items(tmp_db):
    item = make_item("0029900001", "2099-00")
    eligible_items("play-by-play", [item])
    mark_item_failed("play-by-play", item, "blocked")

    from nba_duckdb import quality

    failures, rows = quality._ledger_failures({"2099-00"})

    assert rows[0]["status"] == "failed"
    assert failures == ["play-by-play 2099-00 has 1 failed ingestion items"]


def test_public_run_checks_scopes_ledger_failures_to_covered_seasons(smoke_db):
    old_item = make_item("0029800001", "2098-99")
    eligible_items("play-by-play", [old_item])
    mark_item_failed("play-by-play", old_item, "old blocked item")

    from nba_duckdb import quality

    result = quality.run_checks()

    assert result["coverage_counts"][0]["season"] == "2099-00"
    assert result["ledger_counts"] == []


def test_quality_detects_duplicate_natural_keys(smoke_db):
    db = smoke_db
    db.insert_rows(
        "silver",
        "fct_play_by_play",
        [
            {
                "game_id": "002SYN0001",
                "action_id": 1,
                "action_number": 1,
                "period": 1,
                "pbp_source": "fixture",
            }
        ],
    )

    from nba_duckdb import quality

    with pytest.raises(RuntimeError, match="silver.fct_play_by_play_unique_action"):
        quality.run_checks()


def test_quality_allows_empty_injury_report(smoke_db):
    db = smoke_db
    db.execute("DELETE FROM silver.dim_injuries")

    from nba_duckdb import quality

    result = quality.run_checks()

    assert result["missing_tables"] == []


def test_quality_allows_empty_min_games_tables_only_before_20_games(smoke_db):
    db = smoke_db
    for qualified_table in (
        "gold.player_season_mvp_ladder",
        "gold.player_season_embeddings",
        "gold.player_season_similarity",
    ):
        db.execute(f"DELETE FROM {qualified_table}")

    from nba_duckdb import quality

    db.execute("UPDATE gold.player_season_stats SET games_played = LEAST(games_played, 19)")
    quality.run_checks()

    db.execute("UPDATE gold.player_season_stats SET games_played = 20")
    with pytest.raises(RuntimeError, match="gold.player_season_mvp_ladder has no rows"):
        quality.run_checks()


def test_quality_requires_injury_table_to_exist(smoke_db):
    db = smoke_db
    db.execute("DROP TABLE silver.dim_injuries")

    from nba_duckdb import quality

    with pytest.raises(RuntimeError, match="silver.dim_injuries is missing"):
        quality.run_checks()


def test_quality_detects_duplicate_shot_profile_grains(smoke_db):
    db = smoke_db
    db.execute(
        """
        INSERT INTO gold.team_season_shot_profile
        SELECT * FROM gold.team_season_shot_profile LIMIT 1
        """
    )
    db.execute(
        """
        INSERT INTO gold.player_season_shot_profile
        SELECT * FROM gold.player_season_shot_profile LIMIT 1
        """
    )

    from nba_duckdb import quality

    counts = quality._duplicate_key_counts()

    assert counts["gold.team_season_shot_profile_unique_team_bucket"] == 1
    assert counts["gold.player_season_shot_profile_unique_player_bucket"] == 1

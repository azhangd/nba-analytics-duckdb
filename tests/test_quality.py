import argparse

import pytest

from nba_duckdb.ingestion_state import eligible_items, make_item, mark_item_failed


def _init_tmp_db(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()
    return db


def _run_full_smoke(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.cli import run_offline_smoke
    from nba_duckdb.dependencies import missing_modules_for_groups

    if missing := missing_modules_for_groups("ml"):
        pytest.skip(f"full smoke quality tests require full extras: {', '.join(missing)}")

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "smoke.duckdb"))
    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NBA_DUCKDB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    result = run_offline_smoke(
        argparse.Namespace(
            fixtures_dir=None,
            source=None,
            quick=False,
            init_schema=True,
            run_id=None,
            resume_latest=False,
            retry_failed=False,
            retries=0,
            retry_delay_seconds=0.0,
        )
    )
    assert result["status"] == "success"
    return db


def _insert_schedule(db):
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
            }
        ],
    )


def _insert_minimal_required_tables(db):
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "rosters",
        [
            {
                "player_id": 990001,
                "team_id": 1610612737,
                "player_name": "Example Player",
                "season": "2099-00",
                "raw_json": "{}",
            }
        ],
    )
    db.insert_rows(
        "bronze",
        "boxscores",
        [{"game_id": "0029900001", "traditional_json": '{"game":{}}', "advanced_json": None}],
    )
    db.insert_rows(
        "bronze",
        "play_by_play",
        [
            {
                "game_id": "0029900001",
                "pbp_json": '{"game":{"actions":[{"actionNumber":1}]}}',
                "source": "fixture",
            }
        ],
    )
    db.insert_rows(
        "silver",
        "dim_teams",
        [
            {"team_id": 1610612737, "abbreviation": "AAA"},
            {"team_id": 1610612738, "abbreviation": "BBB"},
        ],
    )
    db.insert_rows(
        "silver",
        "dim_players",
        [{"player_id": 990001, "full_name": "Example Player", "current_team_id": 1610612737}],
    )
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
                "status": "Final",
            }
        ],
    )
    db.insert_rows(
        "silver",
        "fct_boxscores",
        [
            {
                "game_id": "0029900001",
                "player_id": 990001,
                "team_id": 1610612737,
                "player_name": "Example Player",
            }
        ],
    )
    db.insert_rows(
        "silver",
        "fct_play_by_play",
        [
            {
                "game_id": "0029900001",
                "action_number": 1,
                "period": 1,
                "pbp_source": "fixture",
            }
        ],
    )
    db.insert_rows(
        "silver",
        "fct_possessions",
        [
            {
                "game_id": "0029900001",
                "possession_number": 1,
                "period": 1,
                "offense_team_id": 1610612737,
                "event_count": 1,
            }
        ],
    )
    db.insert_rows(
        "gold",
        "player_game_stats",
        [
            {
                "game_id": "0029900001",
                "player_id": 990001,
                "team_id": 1610612737,
                "player_name": "Example Player",
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_game_stats",
        [
            {
                "game_id": "0029900001",
                "team_id": 1610612737,
                "season": "2099-00",
                "game_date": "2100-01-01",
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_elo",
        [{"team_id": 1610612737, "season": "2099-00", "elo_rating": 1500.0}],
    )
    db.insert_rows(
        "gold",
        "player_season_stats",
        [
            {
                "player_id": 990001,
                "season": "2099-00",
                "team_id": 1610612737,
                "games_played": 1,
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_four_factors",
        [
            {
                "team_id": 1610612737,
                "season": "2099-00",
                "games": 1,
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_percentile_ranks",
        [
            {
                "team_id": 1610612737,
                "season": "2099-00",
            }
        ],
    )
    db.insert_rows(
        "gold",
        "team_season_starter_bench_stats",
        [{"team_id": 1610612737, "season": "2099-00", "role": "starter", "games": 1}],
    )
    db.insert_rows(
        "gold",
        "player_season_load_management",
        [{"player_id": 990001, "season": "2099-00", "games_played": 1}],
    )
    db.insert_rows(
        "gold",
        "team_season_clutch_stats",
        [{"offense_team_id": 1610612737, "season": "2099-00", "clutch_possessions": 1}],
    )
    db.insert_rows(
        "gold",
        "team_season_opponent_scouting",
        [{"team_id": 1610612737, "season": "2099-00", "opponent_id": 1610612738}],
    )
    db.insert_rows(
        "gold",
        "team_season_timeout_stats",
        [{"team_id": 1610612737, "season": "2099-00", "total_timeouts": 1}],
    )
    db.insert_rows(
        "gold",
        "team_season_ato_stats",
        [{"team_id": 1610612737, "season": "2099-00", "timeout_count": 1}],
    )
    db.insert_rows(
        "gold",
        "player_season_clutch_stats",
        [{"player_id": 990001, "season": "2099-00", "clutch_games": 1}],
    )


def test_quality_coverage_detects_partial_play_by_play(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
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


def test_quality_coverage_passes_when_raw_core_sources_are_complete(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
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


def test_quality_coverage_excludes_non_team_showcase_games(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": "0039900001",
                "game_date": "02/15/2100 00:00:00",
                "home_team_id": 1610616860,
                "away_team_id": 1610616861,
                "home_team_abbr": "AS1",
                "away_team_abbr": "AS2",
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


def test_quality_coverage_respects_team_scope(tmp_path, monkeypatch):
    db = _init_tmp_db(tmp_path, monkeypatch)
    _insert_schedule(db)
    db.insert_rows(
        "bronze",
        "schedule",
        [
            {
                "game_id": "0029900002",
                "game_date": "01/02/2100 00:00:00",
                "home_team_id": 1610612747,
                "away_team_id": 1610612748,
                "home_team_abbr": "CCC",
                "away_team_abbr": "DDD",
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


def test_quality_detects_failed_core_ingestion_items(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    item = make_item("0029900001", "2099-00")
    eligible_items("play-by-play", [item])
    mark_item_failed("play-by-play", item, "blocked")

    from nba_duckdb import quality

    failures, rows = quality._ledger_failures()

    assert rows[0]["status"] == "failed"
    assert failures == ["play-by-play 2099-00 has 1 failed ingestion items"]


def test_public_run_checks_scopes_ledger_failures_to_covered_seasons(tmp_path, monkeypatch):
    _run_full_smoke(tmp_path, monkeypatch)
    old_item = make_item("0029800001", "2098-99")
    eligible_items("play-by-play", [old_item])
    mark_item_failed("play-by-play", old_item, "old blocked item")

    from nba_duckdb import quality

    result = quality.run_checks()

    assert result["coverage_counts"][0]["season"] == "2099-00"
    assert result["ledger_counts"] == []


def test_quality_detects_duplicate_natural_keys(tmp_path, monkeypatch):
    db = _run_full_smoke(tmp_path, monkeypatch)
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


def test_quality_allows_empty_optional_source_tables(tmp_path, monkeypatch):
    db = _run_full_smoke(tmp_path, monkeypatch)
    for qualified_table in (
        "silver.dim_injuries",
        "gold.player_pageviews_daily",
        "gold.player_media_mentions_daily",
        "gold.player_jersey_rank_snapshots",
    ):
        db.execute(f"DELETE FROM {qualified_table}")

    from nba_duckdb import quality

    result = quality.run_checks()

    assert result["missing_tables"] == []


def test_quality_requires_optional_source_tables_to_exist(tmp_path, monkeypatch):
    db = _run_full_smoke(tmp_path, monkeypatch)
    db.execute("DROP TABLE gold.player_jersey_rank_snapshots")

    from nba_duckdb import quality

    with pytest.raises(RuntimeError, match="gold.player_jersey_rank_snapshots is missing"):
        quality.run_checks()


def test_quality_detects_duplicate_shot_profile_grains(tmp_path, monkeypatch):
    db = _run_full_smoke(tmp_path, monkeypatch)
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

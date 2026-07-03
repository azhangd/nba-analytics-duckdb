import argparse
import os

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from nba_duckdb import db
from nba_duckdb.cli import run_offline_smoke
from nba_duckdb.fixtures.generate_synthetic_fixtures import BOXSCORES, GAME_ID, PLAY_BY_PLAY
from nba_duckdb.transforms.silver.boxscores import extract_players


def test_offline_smoke_pipeline_populates_core_tables(tmp_path, monkeypatch):
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
    assert db.count_rows("bronze", "schedule") == 44
    assert db.count_rows("silver", "dim_players") == 32
    assert db.count_rows("silver", "fct_possessions") == 264
    assert db.count_rows("gold", "team_season_elo") == 4
    assert db.count_rows("gold", "player_season_stats") == 32
    assert db.count_rows("gold", "team_season_four_factors") == 4
    assert db.count_rows("gold", "team_season_percentile_ranks") == 4
    assert db.count_rows("gold", "team_season_starter_bench_stats") == 8
    assert db.count_rows("gold", "player_season_load_management") == 32
    assert db.count_rows("gold", "team_season_clutch_stats") == 4
    assert db.count_rows("gold", "team_season_opponent_scouting") == 8
    assert db.count_rows("gold", "team_season_timeout_stats") == 4
    assert db.count_rows("gold", "team_season_ato_stats") == 4
    assert db.count_rows("gold", "player_season_clutch_stats") > 0
    scopes = db.execute(
        """
        SELECT 'elo' AS table_name, MIN(comparison_scope) AS comparison_scope
        FROM gold.team_season_elo
        UNION ALL
        SELECT 'player_season_stats', MIN(comparison_scope)
        FROM gold.player_season_stats
        UNION ALL
        SELECT 'team_season_percentile_ranks', MIN(comparison_scope)
        FROM gold.team_season_percentile_ranks
        ORDER BY table_name
        """
    )
    assert {row["table_name"]: row["comparison_scope"] for row in scopes} == {
        "elo": "loaded_sample",
        "team_season_percentile_ranks": "loaded_sample",
        "player_season_stats": "loaded_sample",
    }


def test_offline_smoke_populates_full_warehouse_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "full.duckdb"))
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
    assert db.count_rows("bronze", "shot_charts") == 88
    assert db.count_rows("bronze", "tracking_stats") == 3
    assert db.count_rows("bronze", "game_detail") == 44
    assert db.count_rows("silver", "fct_shots") == 528
    assert db.count_rows("silver", "fct_lineups") == 352
    assert db.count_rows("silver", "fct_hustle") == 32
    assert db.count_rows("silver", "fct_tracking") == 96
    assert db.count_rows("gold", "player_zone_season_shot_quality") == 24
    assert db.count_rows("gold", "team_season_shot_profile") == 12
    assert db.count_rows("gold", "player_season_shot_profile") == 24
    assert db.count_rows("gold", "team_season_play_type_stats") == 4
    assert db.count_rows("gold", "game_flow_snapshots") == 352
    assert db.count_rows("gold", "player_season_archetypes") == 32
    assert db.count_rows("gold", "player_season_embeddings") == 24
    assert db.count_rows("gold", "player_season_similarity") == 240
    assert db.count_rows("gold", "player_season_feature_matrix") == 32
    assert db.count_rows("gold", "team_season_feature_matrix") == 4
    adjusted = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM gold.player_season_stats
        WHERE adj_ppg IS NOT NULL
          AND adj_ts_pct IS NOT NULL
          AND adj_net_rtg IS NOT NULL
        """
    )[0]
    assert adjusted["row_count"] == 32


def test_offline_smoke_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "idempotent.duckdb"))
    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NBA_DUCKDB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    args = argparse.Namespace(
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

    first = run_offline_smoke(args)
    before = {
        "silver.fct_games": db.count_rows("silver", "fct_games"),
        "silver.fct_boxscores": db.count_rows("silver", "fct_boxscores"),
        "silver.fct_play_by_play": db.count_rows("silver", "fct_play_by_play"),
        "gold.player_game_stats": db.count_rows("gold", "player_game_stats"),
        "gold.player_zone_season_shot_quality": db.count_rows("gold", "player_zone_season_shot_quality"),
    }
    second = run_offline_smoke(args)
    after = {
        "silver.fct_games": db.count_rows("silver", "fct_games"),
        "silver.fct_boxscores": db.count_rows("silver", "fct_boxscores"),
        "silver.fct_play_by_play": db.count_rows("silver", "fct_play_by_play"),
        "gold.player_game_stats": db.count_rows("gold", "player_game_stats"),
        "gold.player_zone_season_shot_quality": db.count_rows("gold", "player_zone_season_shot_quality"),
    }

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert after == before


def test_offline_smoke_restores_network_guard_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "env.duckdb"))
    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NBA_DUCKDB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.delenv("NBA_DUCKDB_OFFLINE_SMOKE", raising=False)

    result = run_offline_smoke(
        argparse.Namespace(
            fixtures_dir=None,
            source=None,
            quick=True,
            init_schema=True,
            run_id=None,
            resume_latest=False,
            retry_failed=False,
            retries=0,
            retry_delay_seconds=0.0,
        )
    )

    assert result["status"] == "success"
    assert "NBA_DUCKDB_OFFLINE_SMOKE" not in os.environ


def test_boxscore_parser_flattens_player_rows():
    game = BOXSCORES[0]["game"]
    rows = []
    rows.extend(extract_players(game["homeTeam"], GAME_ID, {}))
    rows.extend(extract_players(game["awayTeam"], GAME_ID, {}))

    assert len(rows) == 16
    assert rows[0]["game_id"] == GAME_ID
    assert rows[0]["player_id"] == 910001
    assert rows[0]["pts"] == 10


def test_play_by_play_fixture_matches_live_payload_shape():
    actions = PLAY_BY_PLAY[0]["game"]["actions"]

    assert len(actions) == 9
    assert actions[0]["actionNumber"] == 1
    assert actions[0]["actionType"] == "period"
    assert actions[1]["teamId"] == 1610612737
    assert actions[1]["actionType"] == "2pt"

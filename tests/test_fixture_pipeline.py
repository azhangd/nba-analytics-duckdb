import os

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from conftest import smoke_args

from nba_duckdb.cli import run_offline_smoke
from nba_duckdb.fixtures.generate_synthetic_fixtures import BOXSCORES, GAME_ID, PLAY_BY_PLAY
from nba_duckdb.transforms.silver.boxscores import extract_players


def test_offline_smoke_populates_warehouse_tables(smoke_db):
    db = smoke_db
    expected_counts = {
        ("bronze", "schedule"): 44,
        ("bronze", "shot_charts"): 88,
        ("bronze", "tracking_stats"): 3,
        ("bronze", "game_detail"): 44,
        ("silver", "dim_players"): 32,
        ("silver", "fct_possessions"): 264,
        ("silver", "fct_shots"): 528,
        ("silver", "fct_lineups"): 352,
        ("silver", "fct_hustle"): 32,
        ("silver", "fct_tracking"): 96,
        ("gold", "team_season_elo"): 4,
        ("gold", "player_season_stats"): 32,
        ("gold", "team_season_four_factors"): 4,
        ("gold", "team_season_percentile_ranks"): 4,
        ("gold", "team_season_starter_bench_stats"): 8,
        ("gold", "player_season_load_management"): 32,
        ("gold", "team_season_clutch_stats"): 4,
        ("gold", "team_season_opponent_scouting"): 8,
        ("gold", "team_season_timeout_stats"): 4,
        ("gold", "team_season_ato_stats"): 4,
        ("gold", "player_zone_season_shot_quality"): 24,
        ("gold", "team_season_shot_profile"): 12,
        ("gold", "player_season_shot_profile"): 24,
        ("gold", "team_season_play_type_stats"): 4,
        ("gold", "game_flow_snapshots"): 352,
        ("gold", "player_season_archetypes"): 32,
        ("gold", "player_season_embeddings"): 24,
        ("gold", "player_season_similarity"): 240,
        ("gold", "player_season_feature_matrix"): 32,
        ("gold", "team_season_feature_matrix"): 4,
    }
    actual = {key: db.count_rows(*key) for key in expected_counts}
    assert actual == expected_counts
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
        """
    )
    assert {row["comparison_scope"] for row in scopes} == {"loaded_sample"}
    adjusted = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM gold.player_season_stats
        WHERE adj_ppg IS NOT NULL AND adj_ts_pct IS NOT NULL AND adj_net_rtg IS NOT NULL
        """
    )[0]
    assert adjusted["row_count"] == 32


def test_offline_smoke_is_idempotent(smoke_db):
    db = smoke_db
    tables = [
        ("silver", "fct_games"),
        ("silver", "fct_boxscores"),
        ("silver", "fct_play_by_play"),
        ("gold", "player_game_stats"),
        ("gold", "player_zone_season_shot_quality"),
    ]
    before = {table: db.count_rows(*table) for table in tables}

    assert run_offline_smoke(smoke_args())["status"] == "success"
    assert {table: db.count_rows(*table) for table in tables} == before


def test_offline_smoke_restores_network_guard_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "env.duckdb"))
    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NBA_DUCKDB_FIXTURES_DIR", str(tmp_path / "fixtures"))
    monkeypatch.delenv("NBA_DUCKDB_OFFLINE_SMOKE", raising=False)

    result = run_offline_smoke(smoke_args(quick=True))

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

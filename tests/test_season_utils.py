from nba_duckdb import season_utils
from nba_duckdb.defaults import get_team_ids


def test_requested_or_default_seasons_prefers_explicit_values():
    assert season_utils.requested_or_default_seasons(season="2024-25", seasons=["2025-26"]) == ["2025-26"]
    assert season_utils.requested_or_default_seasons(season="2024-25") == ["2024-25"]


def test_requested_or_default_seasons_falls_back_to_default_season(monkeypatch):
    monkeypatch.setattr(season_utils, "get_default_season", lambda: "2025-26")

    assert season_utils.requested_or_default_seasons() == ["2025-26"]


def test_get_team_ids_treats_empty_value_as_all_teams(monkeypatch):
    monkeypatch.setenv("NBA_DUCKDB_TEAM_IDS", "")
    assert get_team_ids() is None
    monkeypatch.setenv("NBA_DUCKDB_TEAM_IDS", "1610612737, 1610612738")
    assert get_team_ids() == (1610612737, 1610612738)

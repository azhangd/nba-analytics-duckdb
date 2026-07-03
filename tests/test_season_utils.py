from nba_duckdb import season_utils


def test_requested_or_default_seasons_prefers_explicit_values():
    assert season_utils.requested_or_default_seasons(season="2024-25", seasons=["2025-26"]) == ["2025-26"]
    assert season_utils.requested_or_default_seasons(season="2024-25") == ["2024-25"]


def test_requested_or_default_seasons_falls_back_to_default_season(monkeypatch):
    monkeypatch.setattr(season_utils, "get_default_season", lambda: "2025-26")

    assert season_utils.requested_or_default_seasons() == ["2025-26"]

import polars as pl
import pytest

from nba_duckdb.analytics.elo import (
    HOME_ADVANTAGE,
    K,
    mov_multiplier,
    project_record,
    update_elo,
    win_probability,
)
from nba_duckdb.defaults import ALL_TEAM_IDS
from nba_duckdb.transforms.gold.team_season_elo import build_team_elo_rows


def test_home_edge_goes_to_the_home_team_whichever_side_it_is():
    home_wins = win_probability(1500, 1500, a_is_home=True)
    away_wins = win_probability(1500, 1500, a_is_home=False)

    assert home_wins > 0.5
    assert home_wins + away_wins == pytest.approx(1.0)
    # An even matchup: two home games and two road games go 2-2, and the other
    # 78 games of the 82 aren't scheduled yet, so they go 39-39.
    games = [{"opponent_id": 2, "home": home} for home in (True, True, False, False)]
    assert project_record(1500, 0, 0, games, {2: 1500})["projected_wins"] == 41.0


def test_road_upset_uses_the_rating_gap_including_home_court():
    # A 1400 road team beats a 1600 home team by 10: the winner was 200 points worse plus home court.
    winner, loser = update_elo(1400, 1600, 10, winner_home=False)

    expected = win_probability(1400, 1600, a_is_home=False)
    multiplier = (10 + 3) ** 0.8 / (7.5 + 0.006 * (-200 - HOME_ADVANTAGE))
    assert winner - 1400 == pytest.approx(K * multiplier * (1 - expected))
    assert 1600 - loser == pytest.approx(winner - 1400)


def test_neutral_site_game_has_no_home_edge():
    assert win_probability(1500, 1500, a_is_home=None) == 0.5

    winner, _ = update_elo(1500, 1500, 10, winner_home=None)
    assert winner - 1500 == pytest.approx(K * mov_multiplier(10, 0) * 0.5)


def test_projection_covers_82_games_when_some_are_not_scheduled():
    teams = pl.DataFrame({"team_id": list(ALL_TEAM_IDS), "abbreviation": [f"T{i:02d}" for i in range(30)]})
    base = {"season": "2099-00", "game_date": "2100-01-02", "is_neutral": False, "home_score": 0, "away_score": 0}
    # Every team has one game scheduled; the first two have also played each other.
    rows = [
        {**base, "game_id": f"00299{i:05d}", "home_team_id": ALL_TEAM_IDS[i], "away_team_id": ALL_TEAM_IDS[i + 1],
         "status": "Scheduled"}
        for i in range(0, 30, 2)
    ]
    rows.append({**base, "game_id": "0029900100", "game_date": "2100-01-01", "home_team_id": ALL_TEAM_IDS[0],
                 "away_team_id": ALL_TEAM_IDS[1], "home_score": 110, "away_score": 100, "status": "Final"})
    # A knockout game whose teams aren't known yet.
    rows.append({**base, "game_id": "0029900101", "home_team_id": 0, "away_team_id": 0, "status": "Scheduled"})

    ratings, _ = build_team_elo_rows(pl.DataFrame(rows), teams, target_seasons=["2099-00"])
    by_team = {row["team_id"]: row for row in ratings}

    assert len(ratings) == 30
    assert all(row["projected_wins"] + row["projected_losses"] == pytest.approx(82) for row in ratings)
    assert (by_team[ALL_TEAM_IDS[0]]["remaining_games"], by_team[ALL_TEAM_IDS[0]]["unscheduled_games"]) == (1, 80)
    assert (by_team[ALL_TEAM_IDS[2]]["remaining_games"], by_team[ALL_TEAM_IDS[2]]["unscheduled_games"]) == (1, 81)

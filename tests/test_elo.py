import pytest

from nba_duckdb.analytics.elo import HOME_ADVANTAGE, K, project_record, update_elo, win_probability


def test_home_edge_goes_to_the_home_team_whichever_side_it_is():
    home_wins = win_probability(1500, 1500, a_is_home=True)
    away_wins = win_probability(1500, 1500, a_is_home=False)

    assert home_wins > 0.5
    assert home_wins + away_wins == pytest.approx(1.0)
    # An even matchup: two home games and two road games project to 2-2.
    games = [{"opponent_id": 2, "home": home} for home in (True, True, False, False)]
    assert project_record(1500, 0, 0, games, {2: 1500})["projected_wins"] == 2.0


def test_road_upset_uses_the_rating_gap_including_home_court():
    # A 1400 road team beats a 1600 home team by 10: the winner was 200 points worse plus home court.
    winner, loser = update_elo(1400, 1600, 10, winner_home=False)

    expected = win_probability(1400, 1600, a_is_home=False)
    multiplier = (10 + 3) ** 0.8 / (7.5 + 0.006 * (-200 - HOME_ADVANTAGE))
    assert winner - 1400 == pytest.approx(K * multiplier * (1 - expected))
    assert 1600 - loser == pytest.approx(winner - 1400)

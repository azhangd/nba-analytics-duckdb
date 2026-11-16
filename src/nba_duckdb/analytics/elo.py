"""Elo rating system with margin-of-victory adjustment.

Based on FiveThirtyEight's NBA Elo methodology:
- K-factor: 20
- Home court advantage: 50 Elo points
- MOV multiplier: (MOV + 3)^0.8 / (7.5 + 0.006 * elo_diff)
  - Sublinear in margin (diminishing returns for blowouts)
  - Autocorrelation correction (favorites expected to win by more)
- Win probability: 1 / (1 + 10^(-elo_diff/400))

Additionally computes projected record by simulating remaining schedule
using pairwise Elo-based win probabilities.
"""

# Default starting Elo for all teams
DEFAULT_ELO = 1500.0

# K-factor: how much each game moves the rating
K = 20.0

# Home court advantage in Elo points. FiveThirtyEight's original 100 overstated
# today's home edge: replaying 2025-26 (1,230 games), pre-game log loss was
# lowest at 50 (0.6001, vs 0.6116 at 100), flat from 30 to 60. Home teams won
# 55.4%, about 38 points between even teams.
HOME_ADVANTAGE = 50.0


def _home_adjusted_diff(elo_a: float, elo_b: float, a_is_home: bool) -> float:
    # Every game has a home team: the edge goes to A when A is home, else to B.
    return elo_a - elo_b + (HOME_ADVANTAGE if a_is_home else -HOME_ADVANTAGE)


def win_probability(elo_a: float, elo_b: float, *, a_is_home: bool) -> float:
    """Probability that team A beats team B; the home team is A or else B."""
    diff = _home_adjusted_diff(elo_a, elo_b, a_is_home)
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def mov_multiplier(margin: int, elo_diff: float) -> float:
    """Margin-of-victory multiplier with autocorrelation correction.

    Sublinear in margin (blowouts count less per point) and adjusts
    for the fact that favorites are expected to win by more.
    """
    # Sublinear margin component: (|margin| + 3)^0.8
    mov_component = (abs(margin) + 3.0) ** 0.8

    # Autocorrelation correction: prevents rating inflation for favorites.
    # elo_diff is winner minus loser with home court; negative for an upset,
    # which makes the upset count for more.
    autocorr = 7.5 + 0.006 * elo_diff

    return mov_component / autocorr


def update_elo(
    winner_elo: float,
    loser_elo: float,
    margin: int,
    *,
    winner_home: bool,
) -> tuple[float, float]:
    """Update Elo ratings after a game.

    Returns (new_winner_elo, new_loser_elo).
    """
    # Expected win probability for the winner
    expected = win_probability(winner_elo, loser_elo, a_is_home=winner_home)
    elo_diff = _home_adjusted_diff(winner_elo, loser_elo, winner_home)
    mov_mult = mov_multiplier(margin, elo_diff)

    # Elo shift
    shift = K * mov_mult * (1.0 - expected)

    return winner_elo + shift, loser_elo - shift


def project_record(
    team_elo: float,
    current_wins: int,
    current_losses: int,
    remaining_games: list[dict],
    all_elos: dict[int, float],
) -> dict:
    """Project final record based on current Elo and remaining schedule.

    Args:
        team_elo: This team's current Elo
        current_wins: Wins so far
        current_losses: Losses so far
        remaining_games: List of {opponent_id, home} for unplayed games
        all_elos: Dict of team_id -> current Elo for all teams

    Returns:
        {projected_wins, projected_losses, win_pct, remaining_expected_wins}
    """
    expected_remaining = 0.0
    for game in remaining_games:
        opp_elo = all_elos.get(game["opponent_id"], DEFAULT_ELO)
        wp = win_probability(team_elo, opp_elo, a_is_home=game["home"])
        expected_remaining += wp

    proj_wins = current_wins + expected_remaining
    proj_losses = current_losses + (len(remaining_games) - expected_remaining)
    total = proj_wins + proj_losses

    return {
        "projected_wins": round(proj_wins, 1),
        "projected_losses": round(proj_losses, 1),
        "win_pct": round(proj_wins / total, 3) if total > 0 else 0.5,
        "remaining_expected_wins": round(expected_remaining, 1),
        "remaining_games": len(remaining_games),
    }

# How much to trust the numbers

Short version: the box-score stats are just arithmetic on what you loaded, and
the fancier metrics are home-made approximations. Season usage and team pace,
ratings and turnovers have been checked against Basketball-Reference; nothing
else has been checked against it, the NBA's own advanced stats, or any betting
or tracking system.

## What's what

- **Plain summaries.** Player and team game stats, four factors, clutch,
  starters vs. bench, opponent scouting, timeouts and after-timeout plays.
  These just add up the games in your database. Player season ratings are
  weighted by minutes, so a two-minute stint doesn't count as much as a full
  game. Season usage comes from season totals with Basketball-Reference's
  formula; on 2024-25 and 2025-26 it is within 0.5 points of theirs for 99% of
  players with 500+ minutes. A coach's challenge is charged as a timeout but
  isn't counted as one.
  - Team possessions, pace and ratings use Basketball-Reference's formulas:
    possessions are the average of both teams' estimates, pace is possessions
    per 48 minutes (so overtime counts), and season figures come from season
    totals, not an average of games. Team turnovers include the ones charged
    to no player (shot clock, 8 seconds and so on), counted from the
    play-by-play. For all 30 teams in 2024-25 and 2025-26, pace, offensive and
    defensive rating and TOV% are within 0.1 of Basketball-Reference, and
    season turnovers within 1.
  - Starter and bench points are per team game, so they add up to the team's
    points per game, give or take 0.1 of rounding.
- **Simple formulas.** Elo ratings, and `bpm_approx` and `vorp_approx`.
  - Elo follows FiveThirtyEight's NBA method, with the home edge set to 50
    points instead of their 100. 50 predicted 2025-26 best; the comment in
    `src/nba_duckdb/analytics/elo.py` has the numbers.
  - BPM is a box-score estimate, shifted per team as Basketball-Reference
    does, so each team's players add up to how the team actually played.
    It still hasn't been checked against Basketball-Reference's numbers, and
    anything built on it inherits that.
- **Rule-based.** Play-type labels and the heuristic shot quality columns
  (`expected_fg_pct_heuristic`, `quality_delta_heuristic`), which come from
  hard-coded baselines.
  - Play types are guessed from play-by-play text, which never mentions
    screens or handoffs. So no possession is labelled pick-and-roll, handoff
    or off-screen, and a turnover or a trip to the line with no shot
    described counts as Miscellaneous.
- **Experimental.** The MVP ladder and the feature matrices. Useful for poking
  around, but nothing in them is a calibrated forecast.

## Partial data

If you only loaded some teams, percentiles and ranks are computed against
whoever is in the database. Tables that have them include a
`comparison_scope` column: `full_league` means all 30 teams were loaded for
that season, `loaded_sample` means they weren't. `comparison_team_count` and
`comparison_player_count` tell you how many were in the comparison. One season
can be complete while another isn't.

Elo season projections are only filled in when all 30 teams are loaded.

## Summer League

Summer League games go into their own `silver.summer_league_*` tables and never
feed the regular-season gold tables. The California Classic, Las
Vegas and Salt Lake City are kept as separate competitions, even when a team
plays in more than one.

The NBA labels July 2026 Summer League as season `2026-27`, and its stats
endpoints want `SeasonType=Regular Season` alongside the Summer League ID. We
store what the NBA sends; it doesn't mean those games count as regular season.

## About the data source

The NBA stats endpoints aren't a documented or supported API. A successful run
means they answered at the time, not that they always will, and it doesn't give
you any right to redistribute the data. Raw responses and databases stay on
your machine and out of git.

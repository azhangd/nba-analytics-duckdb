# How much to trust the numbers

Short version: the box-score stats are just arithmetic on what you loaded, and
the fancier metrics are home-made approximations. Season usage, team pace,
ratings and turnovers, and BPM and VORP have been checked against
Basketball-Reference; nothing else has been checked against it, the NBA's own
advanced stats, or any betting or tracking system.

## What's what

- **Plain summaries.** Player and team game stats, four factors, clutch,
  starters vs. bench, opponent scouting, timeouts and after-timeout plays.
  These just add up the games in your database. Player season ratings are
  weighted by minutes, so a two-minute stint doesn't count as much as a full
  game. Season usage comes from season totals with Basketball-Reference's
  formula; on 2024-25 and 2025-26 it is within 0.5 points of theirs for 99% of
  players with 500+ minutes. A coach's challenge is charged as a timeout but
  isn't counted as one. Clutch means the same everywhere, timeouts included:
  the last 5 minutes of the 4th or overtime with the score within 5 before
  the play.
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
  - Neutral-site games, such as the NBA Cup semifinals in Las Vegas and games
    abroad, give neither team the home edge. The NBA marks them in the
    schedule, and `fct_games.is_neutral` carries the flag.
  - Projected records cover all 82 games. Games that aren't on the schedule
    yet, like NBA Cup knockout and makeup games, count as half a win each;
    `team_season_elo.unscheduled_games` says how many there are.
  - BPM is Basketball-Reference's Box Plus/Minus 2.0, with the coefficients
    from their explanation page (cited in
    `src/nba_duckdb/transforms/gold/bpm_vorp.py`): box score stats per 100
    team possessions, weighted by a position and offensive role estimated from
    the box score, then shifted per team so its players, weighted by minutes,
    add up to the team's net rating adjusted for schedule and for playing with
    a lead. OBPM is done the same way with offense, and DBPM is BPM - OBPM.
    VORP is (BPM + 2) x minutes / (48 x 82).
  - Like Basketball-Reference, the published BPM is rated game by game: each
    game's box score gets its own team adjustment, so the team's players add
    up to a target built from who actually played (their season BPMs) and
    the game's margin and average lead. A player's BPM is his game BPMs
    averaged by minutes, so a team's players, weighted by minutes, now add up
    to the average of its game targets rather than its season net rating.
  - Basketball-Reference also blends 50 minutes of each player's listed
    position (PG to C) into the position estimate. The NBA only lists G, F
    or C; mapping those to numbers didn't change the match, so it's left out.
    That's why the columns keep `_approx`.
  - Against Basketball-Reference in 2022-23 to 2025-26, players with 500+
    minutes (360 to 379 a season):

    | Season  | BPM r | BPM slope | BPM median / 90th pct gap | OBPM median / 90th | DBPM median / 90th | VORP median / 90th |
    |---------|-------|-----------|---------------------------|--------------------|--------------------|--------------------|
    | 2022-23 | 1.000 | 1.00      | 0.0 / 0.1                 | 0.0 / 0.1          | 0.0 / 0.1          | 0.03 / 0.07        |
    | 2023-24 | 1.000 | 1.00      | 0.0 / 0.1                 | 0.0 / 0.1          | 0.0 / 0.1          | 0.03 / 0.07        |
    | 2024-25 | 1.000 | 1.00      | 0.0 / 0.1                 | 0.0 / 0.1          | 0.0 / 0.1          | 0.03 / 0.06        |
    | 2025-26 | 1.000 | 1.00      | 0.0 / 0.1                 | 0.0 / 0.1          | 0.0 / 0.1          | 0.03 / 0.06        |

    and players with 250 to 500 minutes (49 to 70 a season):

    | Season  | BPM r | BPM slope | BPM median / 90th pct gap | OBPM median / 90th | DBPM median / 90th | VORP median / 90th |
    |---------|-------|-----------|---------------------------|--------------------|--------------------|--------------------|
    | 2022-23 | 0.999 | 0.98      | 0.0 / 0.2                 | 0.0 / 0.1          | 0.1 / 0.1          | 0.02 / 0.05        |
    | 2023-24 | 0.999 | 1.01      | 0.1 / 0.2                 | 0.05 / 0.2         | 0.1 / 0.1          | 0.03 / 0.05        |
    | 2024-25 | 0.999 | 1.01      | 0.1 / 0.2                 | 0.1 / 0.1          | 0.0 / 0.1          | 0.03 / 0.05        |
    | 2025-26 | 0.999 | 1.00      | 0.0 / 0.1                 | 0.0 / 0.1          | 0.0 / 0.1          | 0.02 / 0.04        |

    The biggest BPM gap among players with 250+ minutes is 0.3. Rated from
    season totals instead, players with 500+ minutes had a slope of 0.96-0.98
    and a 90th percentile gap of 0.4-0.5, and partial-season players were off
    by up to 1.7 (Jahmai Mashack 2025-26: -5.3 against -7.0, now -7.0).
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

BPM and VORP only cover games between loaded teams, and are left empty for a
season whose games can't tell each team's offense from its defense (two teams
that only play each other, say).

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

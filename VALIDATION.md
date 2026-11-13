# How much to trust the numbers

Short version: the box-score stats are just arithmetic on what you loaded, and
the fancier metrics are home-made approximations. Nothing here has been checked
against Basketball-Reference, the NBA's own advanced stats, or any betting or
tracking system.

## What's what

- **Plain summaries.** Player and team game stats, four factors, clutch,
  starters vs. bench, opponent scouting, timeouts and after-timeout plays.
  These just add up the games in your database.
- **Simple formulas.** Elo ratings, and `bpm_approx` and `vorp_approx`. The
  BPM and VORP columns are box-score approximations that haven't been compared
  with Basketball-Reference, and anything built on them inherits that.
- **Rule-based.** Play-type labels and the heuristic shot quality columns
  (`expected_fg_pct_heuristic`, `quality_delta_heuristic`), which come from
  hard-coded baselines.
- **Experimental models.** RAPM, win probability, the trained shot model,
  player embeddings, similarity, the MVP ladder and the feature matrices.
  Useful for poking around, but they aren't calibrated forecasts.

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
feed the regular-season gold tables or models. The California Classic, Las
Vegas and Salt Lake City are kept as separate competitions, even when a team
plays in more than one.

The NBA labels July 2026 Summer League as season `2026-27`, and its stats
endpoints want `SeasonType=Regular Season` alongside the Summer League ID. We
store what the NBA sends; it doesn't mean those games count as regular season.

## Avoiding leakage in the models

The win probability model trains on earlier games and tests on later ones.
Its Elo inputs are each team's rating going into that game (from
`gold.team_game_elo_history`), not the end-of-season rating. Possession is
taken from the home team's side when an event makes it clear, and left neutral
when it doesn't. `gold.game_flow_snapshots` uses the same features and the
model for the matching season.

The trained shot model holds out whole games, picked by date, so no game is in
both training and evaluation. It doesn't use same-season tracking averages,
because those would leak later games into earlier ones. After evaluation it's
refit on all loaded shots, and the metadata records the split sizes and
feature version.

That keeps the holdout numbers honest, but it doesn't make either model a
calibrated forecast.

## About the data source

The NBA stats endpoints aren't a documented or supported API. A successful run
means they answered at the time, not that they always will, and it doesn't give
you any right to redistribute the data. Raw responses and databases stay on
your machine and out of git.

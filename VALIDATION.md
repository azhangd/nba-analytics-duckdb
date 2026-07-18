# Analytics Validity

This project is a reproducible NBA data engineering pipeline, not a packaged
forecasting product. Gold outputs are useful analytical tables, but their
interpretation depends on the loaded warehouse scope and on whether the metric is
descriptive, heuristic, or research-oriented.

## Verification Status

The repository is verified with deterministic offline fixture smoke runs,
quality checks, artifact-policy checks, and wheel packaging checks. Live runs use
the same registered warehouse graph, but they depend on public NBA endpoint
availability, response shapes, and rate limits.

## Output Tiers

- **Descriptive marts** summarize loaded games without claiming model validity.
  Examples: player game stats, team game stats, team-season four factors,
  clutch summaries, starter/bench summaries, opponent scouting, timeout
  analysis, and ATO team stats.
- **Transparent heuristics** are simple calculations with readable assumptions.
  Examples: Elo ratings/projections and BPM/VORP-style approximations.
- **Rule-based analytics** use deterministic rules or hardcoded
  baselines. Examples: play-type classification and heuristic shot quality.
- **Research-oriented analytics** combine several derived signals into
  exploratory outputs such as MVP-style rankings, feature matrices, embeddings,
  similarity tables, RAPM, and trained win-probability artifacts. They are
  produced by the pipeline, but they should be interpreted as transparent
  analysis aids rather than calibrated or externally validated predictive
  models.

## Scope Metadata

Scoped runs are valid for pipeline verification and team-level exploration. They
are not evidence for full-league conclusions.

Tables with percentile or ranking fields include `comparison_scope` metadata
where supported. `full_league` means the loaded season includes 30 NBA teams for
that comparison. `loaded_sample` means the comparison was computed over only the
rows present in the local warehouse. The scope flag applies to all `_pct`
percentile columns in that row.

`comparison_team_count` and `comparison_player_count` record the denominator
used for the comparison. A warehouse can be full league for one season and a
loaded sample for another.

## Competition Scope

Summer League is stored with explicit `league_id` and `competition` fields.
Its normalized facts live in `silver.summer_league_*` tables and are not fed
into the regular-season gold or ML graph. California Classic, Las Vegas, and
Salt Lake City are separate competitions even when the same NBA team appears in
more than one event.

The feeds are first-party NBA-operated web and stats resources, but this project
uses them through an undocumented and unsupported integration. A successful
pipeline run proves response availability and end-to-end coverage at that time;
it does not establish an NBA service-level commitment or grant redistribution
rights. Raw live payloads and generated warehouses remain local and untracked.

Summer League schedules use the following NBA season label, so July 2026 is
stored as `2026-27`. The stats endpoints also use `SeasonType=Regular Season`
with the Summer League ID. These are source-system conventions, not claims that
Summer League games are NBA regular-season games.

## Approximation Labels

`bpm_approx` and `vorp_approx` are box-score impact approximations. They are not
parity-tested against Basketball-Reference metrics. Downstream tables that use
these columns inherit the same approximation caveat unless this document says
otherwise.

`expected_fg_pct_heuristic` and `quality_delta_heuristic` come from hardcoded
shot-quality baselines and adjustments. The trained shot-quality table uses
separate trained-model column names and should be interpreted as a local model
artifact, not a validated shot-making model.

RAPM and win-probability artifacts are research-oriented local models. They are
useful for reproducible experimentation, but they are not calibrated forecasts
and have not been externally validated against production betting, tracking, or
league systems.

## Model Evaluation Controls

The trained win-probability model uses a chronological game split. Elo features
come from each team's rating before that game in `gold.team_game_elo_history`,
not from the season-final rating. Possession is oriented from the home team's
perspective for events that identify a clear post-event possession; ambiguous
events use a neutral value. `gold.game_flow_snapshots` consumes that same feature
contract and the model artifact for the matching season.

The trained shot-quality model also evaluates on a chronological, whole-game
holdout: no game can appear in both its training and evaluation partitions.
Same-season aggregate tracking statistics are excluded because they would expose
later-season information to earlier held-out games. After evaluation, the
production artifact is refit on all eligible loaded shots. Its metadata records
the evaluation partition sizes, production training size, feature-contract
version, and exclusion of same-season priors.

These controls make the local holdout metrics reproducible and prevent the known
same-season leakage paths. They do not turn either model into an externally
calibrated forecast; the research-oriented interpretation above still applies.

Elo outputs are transparent rating heuristics. Projection fields are only
populated when the loaded season has full-team coverage; scoped samples keep
ratings and current records but do not present season projections as complete.

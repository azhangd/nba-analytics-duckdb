# Examples

Small scripts that query the warehouse. They read `data/warehouse/nba.duckdb` unless you pass `--warehouse` or set `NBA_DUCKDB_PATH`:

    uv run python examples/basic_team_summary/analysis.py

- [basic_team_summary](basic_team_summary/) prints a team summary from
  `gold.team_game_stats`, `gold.team_season_elo` and
  `gold.team_season_four_factors`.

Please don't commit output from live data.

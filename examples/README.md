# Examples

Small scripts that query the warehouse. They run against the fake smoke data:

    make smoke
    make example-basic-team-summary

They read `data/warehouse/smoke.duckdb` unless you set `NBA_DUCKDB_PATH`.

- [basic_team_summary](basic_team_summary/) prints a team summary from
  `gold.team_game_stats`, `gold.team_season_elo` and
  `gold.team_season_four_factors`.

Please don't commit output from live data.

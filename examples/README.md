# Examples

Examples are small, reproducible analyses that run against a local DuckDB
warehouse. They are meant to show how to query the gold layer without committing
live data, exports, charts, notebooks, or generated artifacts.

Start with the fixture-backed warehouse:

```bash
make smoke
make example-basic-team-summary
```

`make smoke` writes to `data/warehouse/smoke.duckdb` by default. The example
script and Make target read that same smoke warehouse unless you set
`NBA_DUCKDB_PATH`.
Use `make clean-data` only when you intentionally want to remove local
warehouses and generated data.

Live warehouses work too, but results from live runs should stay local. If an
analysis needs larger notebooks, dashboards, or generated reports, keep those
outside this repository and open an issue describing the work.

## Current Examples

- `basic_team_summary`: prints a small team-level summary using
  `gold.team_game_stats`, `gold.team_season_elo`, and `gold.team_season_four_factors`.

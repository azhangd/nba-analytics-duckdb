# Basic Team Summary

This example reads a local DuckDB warehouse and prints a team-level summary from
supported gold tables. It is intentionally small so it can run in CI against the
synthetic fixture warehouse.

Run it after building the smoke warehouse:

```bash
make smoke
make example-basic-team-summary
```

The Make target reads `data/warehouse/smoke.duckdb` by default, which is where
`run-smoke` writes when no `NBA_DUCKDB_PATH` is exported. The script has the
same default, so this also works after `make smoke`:

```bash
uv run python examples/basic_team_summary/analysis.py
```

Or point it at a specific warehouse:

```bash
NBA_DUCKDB_PATH=data/warehouse/nba.duckdb uv run python examples/basic_team_summary/analysis.py
```

The output is scoped to whatever games are loaded in the warehouse. Fixture runs
use season `2099-00` and fake team codes so the repository does not ship real
NBA data. Live scoped runs are useful for local exploration but should not be
interpreted as full-league evidence unless the warehouse has full-league
coverage.

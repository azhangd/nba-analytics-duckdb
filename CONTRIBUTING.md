# Contributing

Thanks for helping out. Small, focused PRs are the easiest to review. For
anything big (a new data source, a new gold table, a schema change, or a
change to what the CLI does by default), open an issue first so we can talk
it through.

## Setting up

    make install          # enough for most changes
    make install-full     # if you touch the full graph or the ML tables
    make install-airflow  # if you touch the DAGs

## Before you open a PR

    make lint
    make test
    make smoke-quick
    make check-artifacts

If you changed the full graph or the ML tables, also run `make smoke` and
`make quality`. If you changed the DAGs, task metadata or dbt selection, run
`make airflow-check` and `make airflow-smoke`.

## Adding a table

Most tables should be dbt models. Put them in `dbt/models/silver/` or
`dbt/models/gold/`, use `ref()` and `source()` for inputs, and add the model
name to the right list in `src/nba_duckdb/dbt_models.py`. SQL is best for
joins and aggregates. If you need a Python model, keep the model file thin
and put the logic in `src/nba_duckdb/transforms/`.

Use a Python task in `src/nba_duckdb/tasks/` instead when the table needs the
NBA API, resumable per-game state, or ML training. Add a `TASK_DEF` to the
module so the CLI and Airflow pick it up, and put its DDL in
`src/nba_duckdb/sql/schema/`. If a dbt model reads the table, list it in
`dbt/models/sources.yml`.

Each table should have exactly one producer. Either way, add a test that runs
against the fake fixtures, and update `VALIDATION.md` if the new numbers are
approximate or only make sense for a full league.

## Data

Don't commit real NBA data: no DuckDB files, raw API responses, exports,
notebooks or model files. `make check-artifacts` catches most of that, and
`tests/test_no_real_data.py` checks that the fixtures stay fake. If you're
adding a new data source, say in the issue where it comes from and what its
terms of use allow.

## Examples

Small example scripts go in `examples/` and should run against the smoke
warehouse. Bigger analyses, notebooks and dashboards are better off in their
own repo; feel free to open an issue and link to them.

## Using AI tools

That's fine, but you should understand the change well enough to explain it
in review. If there are parts you didn't check yourself, say so in the PR.

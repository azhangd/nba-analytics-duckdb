# Running it with Airflow

You don't need Airflow to use this project; `nba-duckdb run-live` does the same
work from the command line. Airflow is for when you want it to run on a
schedule, with retries and a UI showing what happened.

## Setup

    make install-airflow
    make airflow-prepare
    make airflow-dev

`airflow-prepare` builds the dbt manifest, sets up Airflow's local database
and creates the `nba_pipeline` pool. You can run it as many times as you like.
`airflow-dev` starts everything and prints the UI address and a login.

Airflow's files live in `.airflow/` (ignored by git). This setup uses SQLite
and is only meant for your own machine.

To check the DAGs without starting the UI:

    make airflow-check   # the DAGs load and look right
    make airflow-smoke   # runs the whole fixture DAG end to end

## The DAGs

| DAG | What it does |
| --- | --- |
| `nba_warehouse_live` | The full live build, models included, then the quality checks |
| `nba_warehouse_live_quick` | Just schedule, rosters, box scores and play-by-play |
| `nba_summer_league` | Summer League games for the three events |
| `nba_source_backfill` | Resume play-by-play or shot chart collection |
| `nba_warehouse_smoke` | The full build from the fake fixtures |
| `nba_warehouse_smoke_quick` | Loads the fixtures and nothing else |

They all start paused with no schedule, so cloning the repo never starts
hitting the NBA's servers. To schedule one, set a cron expression in the
scheduler's environment and unpause the DAG:

    NBA_DUCKDB_AIRFLOW_QUICK_SCHEDULE="15 10 * * *"
    NBA_DUCKDB_AIRFLOW_LIVE_SCHEDULE="30 11 * * 1"
    NBA_DUCKDB_AIRFLOW_SUMMER_SCHEDULE="30 12 * * *"

When you trigger a DAG by hand you can set the season, team IDs, game IDs,
dates and whether to do a full refresh.

## How it fits together

```text
bronze collectors
  -> dbt models (one Airflow task each)
  -> RAPM, win probability, shot quality, embeddings
  -> the two feature-matrix dbt models
  -> quality checks
```

The DAGs read task info from the project's task registry and dbt models from
`dbt/target/manifest.json`. Parsing a DAG never runs dbt, so run
`make dbt-parse` after you change a model.

Play-by-play and shot charts keep their own per-game progress in
`ops.ingestion_items`. A backfill picks up the games that are left, rather than
making each game an Airflow task.

## Only one task at a time

DuckDB can't take writes from more than one process. Every task that touches
the database goes through the `nba_pipeline` pool, which has one slot, and each
DAG allows one active run and one active task. Don't raise the pool size while
the DAGs share a DuckDB file.

## Why each dbt model is its own task

With Cosmos, every dbt model shows up as its own task, so you can see and
retry a single model. The cost is speed: on the fixtures the DAG takes about
100 seconds, compared with about 13 for a single `dbt build`. Next to a real
live run that doesn't matter.

Cosmos's watcher mode (one dbt build, many tasks watching it) would be faster,
but in Cosmos 1.15 it can schedule a watching task before the build. With only
one task slot, that task sits in the slot waiting and nothing else runs.

## Running it for real

This repo gives you the DAGs, not a hosted Airflow. On a server you'll want to:

- run Airflow on Linux, with PostgreSQL or MySQL instead of SQLite
- build `dbt/target/manifest.json` into whatever you deploy
- install the `airflow` and `full` extras everywhere Airflow runs
- use the same absolute paths for the project, profiles, fixtures, artifacts
  and the DuckDB file on every component
- create the one-slot `nba_pipeline` pool before unpausing anything
- set `AIRFLOW__COSMOS__ENABLE_DATASET_AIRFLOW3_URI=True`

`LocalExecutor` on one machine is enough. A distributed executor wouldn't help,
because DuckDB still only allows one writer.

## Links

- [Installing Airflow](https://airflow.apache.org/docs/apache-airflow/stable/installation/installing-from-pypi.html)
- [Airflow pools](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html)
- [Airflow in production](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/production-deployment.html)
- [Cosmos execution modes](https://astronomer.github.io/astronomer-cosmos/guides/run_dbt/execution-modes.html)
- [DuckDB concurrency](https://duckdb.org/docs/stable/connect/concurrency)

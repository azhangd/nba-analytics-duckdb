# Airflow Operations

Airflow 3 is the scheduled execution and operational history surface for this
project. Cosmos translates the dbt manifest into model-level Airflow tasks. The
CLI remains a direct local harness for development and recovery; it is not a
second scheduler.

## Architecture

The full pipeline has two dbt phases with Python work between them:

```text
bronze collectors
  -> Cosmos dbt_warehouse (45 independently visible models)
  -> RAPM, win probability, signals, shot quality, embeddings
  -> Cosmos dbt_feature_matrices (2 independently visible models)
  -> warehouse quality gate
```

Summer League has a deliberately smaller path:

```text
official competition schedules (LeagueID 13, 15, 16)
  -> traditional/advanced box scores, play-by-play, shot charts
  -> Cosmos dbt_summer_league (4 competition-scoped silver models)
  -> cross-source reconciliation and hashed payload-manifest gate
```

The DAG factory reads the checked project registry for Python task metadata and
reads `dbt/target/manifest.json` for dbt nodes. DAG parsing never invokes dbt.
Run `make dbt-parse` after changing a model, source, macro, test, or selector.

Airflow owns DAG runs, task attempts, retries, schedules, and operator logs.
The existing `ops.ingestion_items` tables remain the item-level checkpoint for
large play-by-play and shot-chart collections, so a source backfill can resume
individual games without mapping an entire season into Airflow tasks. Task
return values are reduced to small JSON summaries before they enter XCom.

## Local Setup

Install the scheduler, the full warehouse dependencies, and the development
tools:

```bash
make install-airflow
make airflow-prepare
```

`airflow-prepare` performs three idempotent setup actions:

1. builds the dbt manifest;
2. migrates the local Airflow metadata database;
3. creates or updates the one-slot `nba_pipeline` pool.

Start the local scheduler, API server, triggerer, and UI:

```bash
make airflow-dev
```

Airflow prints the local UI URL and generated development credentials. The
default `AIRFLOW_HOME` is `.airflow/`, which is ignored by git. This standalone
configuration uses SQLite for Airflow metadata and is for development only.

Run structural checks or the complete fixture DAG without keeping the UI up:

```bash
make airflow-check
make airflow-smoke
```

The full Airflow smoke invokes every Cosmos model task and ends with all 69
warehouse contract checks. `nba_warehouse_smoke_quick` exists for fast UI and
operator checks but intentionally does not exercise dbt or ML.

## DAG Inventory

| DAG | Purpose | Default schedule |
| --- | --- | --- |
| `nba_warehouse_live` | Full live warehouse, ML phase, and quality gate | Manual |
| `nba_warehouse_live_quick` | Schedule, rosters, box scores, and play-by-play | Manual |
| `nba_summer_league` | California, Las Vegas, and Salt Lake City event data plus scoped silver facts | Manual |
| `nba_warehouse_smoke` | Deterministic full fixture verification | Manual |
| `nba_warehouse_smoke_quick` | Fixture loading only | Manual |
| `nba_source_backfill` | Resume play-by-play or shot-chart item state | Manual |

Every DAG is paused when first created. Live schedules are deliberately opt-in
so cloning the repository cannot start public endpoint traffic. Set standard
cron expressions in the scheduler environment, then unpause the intended DAG:

```bash
NBA_DUCKDB_AIRFLOW_QUICK_SCHEDULE="15 10 * * *"
NBA_DUCKDB_AIRFLOW_LIVE_SCHEDULE="30 11 * * 1"
NBA_DUCKDB_AIRFLOW_SUMMER_SCHEDULE="30 12 * * *"
```

Airflow reparses the DAG after an environment change. Use a deployment-specific
schedule and timezone rather than committing a schedule that assumes one
operator's data freshness requirements.

Live and backfill DAGs expose typed Airflow Params for season, team IDs, game
IDs, date bounds, and full refresh. `nba_summer_league` additionally validates
its competition list against the three official Summer League feeds.
`nba_source_backfill` validates both the source and owning competition.

## DuckDB Concurrency Contract

DuckDB supports concurrent writers inside one process, but does not
automatically support writes from multiple processes. Airflow therefore uses
three layers of protection:

- every warehouse task uses the global `nba_pipeline` pool;
- that pool has exactly one slot;
- each DAG has `max_active_runs=1` and `max_active_tasks=1`.

Do not increase the pool size while DAGs point at the same DuckDB file. Scaling
the scheduler and scaling warehouse writes are different concerns. A future
move to a client/server warehouse can revisit this limit.

## Cosmos Execution Choice

The full warehouse DAG uses two `DbtTaskGroup` instances, and the independent
Summer League DAG uses a third. All three use `ExecutionMode.LOCAL`,
`TestBehavior.BUILD`, manifest-based rendering, and subprocess invocation.
This gives each dbt model its own retryable Airflow task while keeping dbt
tests attached to the model build that owns them. Subprocess isolation also
ensures the DuckDB adapter closes its connections between tasks.

On the fixture benchmark used during this migration, the complete LOCAL DAG
took about 100 seconds; the previous single dbt command completed the same
small fixture workload in about 13 seconds. The overhead is the cost of 47
independent dbt invocations and is negligible relative to full live collection,
but it is intentionally documented.

Cosmos 1.15 watcher mode was also evaluated. It runs one dbt build and exposes
consumer tasks, but its current `DbtTaskGroup` graph does not make those
consumers downstream of the producer. With this project's one-active-task
DuckDB contract, an Airflow DAG test scheduled a consumer first and it occupied
the only task slot while waiting for producer XCom state. Watcher is therefore
not the default until that ordering is safe for this two-phase task-group
design.

## Production Deployment

The repository provides DAG code and local operational commands, not a hosted
Airflow control plane. For a durable deployment:

- run Airflow on Linux;
- use PostgreSQL or MySQL for Airflow metadata instead of SQLite;
- build `dbt/target/manifest.json` into the deployed DAG artifact or image;
- install the locked `airflow` and `full` extras in every scheduler and worker;
- give every component the same absolute project, manifest, profile, fixture,
  artifact, raw-data, and DuckDB paths;
- create the `nba_pipeline` pool with one slot before enabling DAGs;
- keep live credentials and environment configuration outside source control;
- enable the Airflow 3 Cosmos asset URI format with
  `AIRFLOW__COSMOS__ENABLE_DATASET_AIRFLOW3_URI=True`;
- set an OpenLineage namespace if lineage is exported beyond Airflow.

The bundled `LocalExecutor` configuration is appropriate for one Linux host.
The one-slot warehouse pool remains required even if the executor can launch
many processes. A distributed executor would require a shared filesystem for
this DuckDB design and still cannot run concurrent warehouse writers, so it is
not a useful scaling target without changing the warehouse architecture.

## References

- [Airflow installation and constraints](https://airflow.apache.org/docs/apache-airflow/stable/installation/installing-from-pypi.html)
- [Airflow public interface](https://airflow.apache.org/docs/apache-airflow/stable/public-airflow-interface.html)
- [Airflow LocalExecutor](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/executor/local.html)
- [Airflow pools](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html)
- [Airflow production deployment](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/production-deployment.html)
- [Cosmos execution modes](https://astronomer.github.io/astronomer-cosmos/guides/run_dbt/execution-modes.html)
- [Cosmos local execution mode](https://astronomer.github.io/astronomer-cosmos/guides/run_dbt/airflow-worker/local-execution-mode.html)
- [Cosmos watcher mode](https://astronomer.github.io/astronomer-cosmos/guides/run_dbt/airflow-worker/watcher-execution-mode.html)
- [DuckDB concurrency](https://duckdb.org/docs/stable/connect/concurrency)

# Contributing

Thanks for considering a contribution. This project aims to stay useful as both
a local NBA analytics pipeline and a reproducible data-engineering reference.
The main rule is that code merged into the package should be tested,
scope-aware, and safe to publish.

## Contribution Lanes

### Pipeline and Mart Code

Use this lane for source collectors, dbt silver/gold models, Airflow DAG tasks,
quality checks, and runner fixes.

Expected bar:

- Put reusable payload parsing and dataframe aggregation under
  `src/nba_duckdb/transforms/`. Put basketball-stat logic under
  `src/nba_duckdb/analytics/` and trained models or artifact helpers under
  `src/nba_duckdb/modeling/`. Keep bronze collectors and Python task modules
  focused on scope, source access, and materialization.
- Add or update tests that prove the public behavior, preferably from synthetic
  fixtures or mocked live sources.
- Keep long live collectors resumable with item-level state before adding them
  to the public runner.
- Prefer dbt models for deterministic warehouse tables. Use registered Python
  tasks for live collection, item-level resume state, external calls,
  model-artifact side effects, or ML work that is clearer outside dbt.
- Update `VALIDATION.md` when the output is scoped, approximate, heuristic, or
  research-oriented.

### How To Add A Table

First decide who should own it.

Use dbt when the table is a deterministic warehouse transform:

1. Add a model under `dbt/models/silver/` or `dbt/models/gold/`.
2. Use `ref()` and `source()` for inputs so dbt and Cosmos can show lineage.
3. If the model is Python, keep the dbt file as a small adapter: config,
   explicit refs/sources, and one call into `src/nba_duckdb/transforms/`.
4. Put reusable parsing, dataframe, and metric logic in `transforms/`; do not
   import from `src/nba_duckdb/tasks/`.
5. Add model tests or docs in the matching `schema.yml`.
6. Add the model name to `src/nba_duckdb/dbt_models.py`.
7. Add fixture-backed tests and quality checks when the table is part of the
   full smoke path.

Use a registered Python task when the table needs live API access, item-level
resume state, external calls, model artifacts, or heavier ML side effects:

1. Add DDL only for Python-owned tables under `src/nba_duckdb/sql/schema/`.
   dbt-owned silver and gold tables do not belong in schema SQL.
2. Add or update one module under `src/nba_duckdb/tasks/` that produces the
   table.
3. Declare `TASK_DEF` metadata in that module so Airflow, the CLI, quality
   checks, and diagrams can find it.
4. Materialize rows through the dataset helpers when the task refreshes a
   scoped table.
5. Add deterministic fixture or mocked-source coverage.
6. Run `make airflow-check` or `uv run nba-duckdb datasets graph` to confirm the
   task and lineage appear.

For either path, update `VALIDATION.md` if the table introduces scoped,
approximate, heuristic, or research-oriented interpretation.

Every non-ops warehouse table should have exactly one registered producer. If a
task updates an existing table in place, pause and consider whether that output
should instead be a base table plus a single final producer.

### How To Add A dbt Model

Use this path for deterministic silver or gold tables that can be expressed as
SQL or as a single-output dbt Python model:

1. Add the model under `dbt/models/silver/` or `dbt/models/gold/`.
2. Prefer SQL for joins, windows, and aggregates. Use dbt Python when JSON
   parsing, row-wise logic, Polars, or a simple iterative algorithm makes Python
   clearer.
3. Keep dbt Python model files thin. Reusable code should live in
   `src/nba_duckdb/transforms/`, and dbt model files should not import from
   `src/nba_duckdb/tasks/`.
4. Add model tests or docs in the local `schema.yml`.
5. Add the model name to the silver or gold list in `src/nba_duckdb/dbt_models.py`.
6. If the model reads a new Python-produced table, add that table to
   `dbt/models/sources.yml`.
7. Add quality checks for the table's grain and fixture-backed coverage.
8. Run `uv run dbt build --project-dir . --profiles-dir dbt --target-path dbt/target`
   and inspect the model task with `make airflow-check` or `make airflow-dev`.

### Reproducible Analysis Examples

Use this lane for small analyses that help users understand what the warehouse
can answer.

Expected bar:

- Put examples under `examples/`.
- Prefer Python scripts plus Markdown over notebooks.
- Make examples runnable against fixture-backed smoke data.
- Print results to the console or describe the expected output in Markdown.
- Do not commit live-data outputs, raw API payloads, exports, charts, DuckDB
  files, or model artifacts.

### External Work

Larger reports, dashboards, notebooks, or live-data projects should stay outside
this repository. Open an issue describing the work and link to the external
project if it is public. This keeps the core repository reproducible while still
making it easy to discuss adjacent analysis.

## Data And Artifact Policy

CI enforces the mechanical parts of the policy:

- no tracked `.duckdb`, `.duckdb.wal`, `.parquet`, `.jsonl`, notebook, or model
  artifact files;
- no tracked CSV/JSON-style data files outside approved fixture paths;
- no tracked generated output directories such as `data/`, `logs/`, `dist/`, or
  `build/`;
- no unexpectedly large tracked files.

Reviewers still rely on contributor judgment for semantic claims that cannot be
fully checked by CI, such as whether a metric is appropriately labeled or
whether an external data source can be redistributed. When in doubt, leave the
data out of the repository and document how to regenerate it locally.

## Pull Request Routing

Open a direct pull request for focused changes such as:

- documentation and typo fixes;
- small bugfixes that come with a test;
- small improvements to existing examples;
- artifact-policy or cleanup fixes.

Open a proposal issue first for:

- a new data source, gold table, mart, or schema change;
- changes to the default graph or public CLI behavior;
- large analyses or new research, heuristic, or approximate metrics.

For a new data source, the proposal must describe where the data comes from and
its terms of use. The project does not add sources whose terms cannot be met,
and it does not commit raw payloads or generated data.

Smaller focused pull requests are easier to review than broad changes. If a
larger design would be hard to explain across several small pull requests, open
a proposal issue first and describe the intended sequence there.

Please do not open a pull request for committed data, DuckDB files, notebooks,
generated reports, exports, or broad refactor-only work that is not tied to a
concrete issue.

## Local Checks

Before opening a pull request, run:

```bash
make lint
make test
make smoke-quick
make check-artifacts
```

`make install` sets up the light contributor environment. It is enough for
docs, CLI work, quality checks, and quick smoke runs. If you touch the full
warehouse graph, ML-derived tables, live collectors, or release validation,
run:

```bash
make install-full
make smoke
make quality
```

If you update an example, also run its documented command against a
fixture-backed warehouse.

If you change DAG construction, task metadata, dbt selection, or orchestration
boundaries, also run:

```bash
make install-airflow
make airflow-check
make airflow-smoke
```

`make diagrams` and `make check-diagrams` validate curated diagrams against the
dbt manifest, the registry, and schema metadata. When the manifest is missing
or stale, these commands may run `dbt parse` and write ignored files under
`dbt/target/`.

`make quality` checks `data/warehouse/smoke.duckdb` unless you export
`NBA_DUCKDB_PATH`, so it pairs with the full smoke warehouse for local PR
checks.

`make clean` removes caches and build outputs. Use `make clean-data` only when
you intentionally want to remove local warehouses, generated fixtures, and
artifacts.

Review bandwidth is often the limiting factor in open-source projects. If you
are waiting for feedback, consider reviewing another open pull request or
commenting on an issue you understand. Clear, constructive review helps the
project and is a good way to learn the codebase.

## Pull Request Expectations

- Keep changes focused.
- Use a clear title; conventional prefixes such as `fix:`, `feat:`, `docs:`,
  or `chore:` are encouraged.
- Explain the rationale for the change and what changed.
- Link the proposal issue when the routing guide calls for one.
- List only the verification that CI cannot see, or write `docs only`.
- Mention any warehouse scope assumptions, such as fixture-only, team-scoped,
  partial-season, or full-league inputs.
- Update `VALIDATION.md` when the change adds or changes scoped, approximate,
  heuristic, or research-oriented metrics.
- Do not commit generated artifacts, credentials, or raw data.

## AI-Assisted Contributions

AI-assisted pull requests are welcome, but the author should understand the core
ideas behind the change and be able to explain the design during review. If an
agent wrote most of the code, call out any assumptions or areas you did not
fully verify so reviewers know where to focus.

This is a small project, so review may be asynchronous. Clear reproduction steps
and small PRs are the fastest path to a useful review.

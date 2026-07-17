.PHONY: install install-full install-airflow lint test init generate-test-fixtures dbt-parse smoke smoke-quick quality runs ingestion-status airflow-prepare airflow-check airflow-smoke airflow-dev diagrams check-diagrams check-artifacts check-wheel example-basic-team-summary clean clean-data

AIRFLOW_HOME ?= $(CURDIR)/.airflow
AIRFLOW_ENV = AIRFLOW_HOME="$(AIRFLOW_HOME)" AIRFLOW__CORE__DAGS_FOLDER="$(CURDIR)/dags" AIRFLOW__CORE__EXECUTOR=LocalExecutor AIRFLOW__CORE__LOAD_EXAMPLES=False AIRFLOW__OPENLINEAGE__NAMESPACE=nba-analytics-duckdb AIRFLOW__COSMOS__ENABLE_DATASET_AIRFLOW3_URI=True

install:
	uv sync --extra dev

install-full:
	uv sync --extra dev --extra full

install-airflow:
	uv sync --extra dev --extra full --extra airflow

lint:
	uv run ruff check src tests scripts examples dags

test:
	uv run pytest

init:
	uv run nba-duckdb init

generate-test-fixtures:
	uv run nba-duckdb generate-test-fixtures

dbt-parse:
	uv run dbt parse --project-dir . --profiles-dir dbt --target-path dbt/target

smoke:
	uv run nba-duckdb run-smoke

smoke-quick:
	uv run nba-duckdb run-smoke --quick

quality:
	NBA_DUCKDB_PATH=$${NBA_DUCKDB_PATH:-data/warehouse/smoke.duckdb} uv run nba-duckdb quality

runs:
	uv run nba-duckdb runs list

ingestion-status:
	uv run nba-duckdb ingestion-status

airflow-prepare: dbt-parse
	$(AIRFLOW_ENV) uv run airflow db migrate
	$(AIRFLOW_ENV) uv run airflow pools set nba_pipeline 1 "Serializes DuckDB warehouse writers"

airflow-check: dbt-parse
	$(AIRFLOW_ENV) uv run pytest tests/test_airflow_dags.py -q

airflow-smoke: airflow-prepare
	$(AIRFLOW_ENV) uv run airflow dags test nba_warehouse_smoke -f "$(CURDIR)/dags/nba_warehouse.py"

airflow-dev: airflow-prepare
	$(AIRFLOW_ENV) uv run airflow standalone

diagrams:
	uv run python scripts/generate_diagrams.py

check-diagrams:
	uv run python scripts/generate_diagrams.py --check

check-artifacts:
	uv run python scripts/check_artifacts.py

check-wheel:
	uv build
	uv run python scripts/check_wheel_smoke.py

example-basic-team-summary:
	NBA_DUCKDB_PATH=$${NBA_DUCKDB_PATH:-data/warehouse/smoke.duckdb} uv run python examples/basic_team_summary/analysis.py

clean:
	rm -rf logs dist build .airflow .pytest_cache .ruff_cache

clean-data:
	rm -rf data

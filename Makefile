.PHONY: install install-full lint test init generate-test-fixtures dbt-parse smoke smoke-quick quality runs ingestion-status diagrams check-diagrams check-artifacts check-wheel example-basic-team-summary clean clean-data

install:
	uv sync --extra dev

install-full:
	uv sync --extra dev --extra full

lint:
	uv run ruff check src tests scripts examples

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
	rm -rf logs dist build .pytest_cache .ruff_cache

clean-data:
	rm -rf data

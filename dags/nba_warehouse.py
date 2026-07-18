"""Airflow discovery module for NBA DuckDB warehouse DAGs."""

from nba_duckdb.airflow_dags import (
    nba_source_backfill,
    nba_summer_league,
    nba_warehouse_live,
    nba_warehouse_live_quick,
    nba_warehouse_smoke,
    nba_warehouse_smoke_quick,
)

__all__ = [
    "nba_summer_league",
    "nba_source_backfill",
    "nba_warehouse_live",
    "nba_warehouse_live_quick",
    "nba_warehouse_smoke",
    "nba_warehouse_smoke_quick",
]

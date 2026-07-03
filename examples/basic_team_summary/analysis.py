"""Print a small team summary from a local NBA DuckDB warehouse."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_WAREHOUSE = Path("data/warehouse/smoke.duckdb")

QUERY = """
WITH team_summary AS (
    SELECT
        log.season,
        log.team_id,
        COALESCE(MAX(elo.team_abbreviation), CAST(log.team_id AS VARCHAR)) AS team,
        COUNT(*) AS games,
        CAST(SUM(CASE WHEN log.is_win THEN 1 ELSE 0 END) AS INTEGER) AS wins,
        ROUND(AVG(log.pts), 1) AS ppg,
        ROUND(AVG(log.opp_pts), 1) AS opp_ppg,
        ROUND(AVG(log.margin), 1) AS avg_margin,
        ROUND(MAX(elo.elo_rating), 1) AS elo_rating,
        COALESCE(MAX(elo.comparison_scope), 'loaded_sample') AS comparison_scope,
        ROUND(MAX(factors.off_efg_pct), 3) AS off_efg_pct,
        ROUND(MAX(factors.def_efg_pct), 3) AS def_efg_pct
    FROM gold.team_game_stats AS log
    LEFT JOIN gold.team_season_elo AS elo
      ON elo.team_id = log.team_id
     AND elo.season = log.season
    LEFT JOIN gold.team_season_four_factors AS factors
      ON factors.team_id = log.team_id
     AND factors.season = log.season
    GROUP BY log.season, log.team_id
)
SELECT
    season,
    team,
    games,
    wins,
    games - wins AS losses,
    ppg,
    opp_ppg,
    avg_margin,
    elo_rating,
    comparison_scope,
    off_efg_pct,
    def_efg_pct
FROM team_summary
ORDER BY season, wins DESC, avg_margin DESC, team;
"""


def _warehouse_path(raw: str | None) -> Path:
    return Path(raw or os.environ.get("NBA_DUCKDB_PATH") or DEFAULT_WAREHOUSE)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _render_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    rendered_rows = [[_format_value(value) for value in row] for row in rows]
    widths = [
        max(len(column), *(len(row[index]) for row in rendered_rows))
        for index, column in enumerate(columns)
    ]
    header = "  ".join(column.ljust(widths[index]) for index, column in enumerate(columns))
    divider = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rendered_rows
    ]
    return "\n".join([header, divider, *body])


def _uses_synthetic_fixture_season(columns: list[str], rows: list[tuple[Any, ...]]) -> bool:
    if "season" not in columns:
        return False
    season_index = columns.index("season")
    seasons = {row[season_index] for row in rows}
    return "2099-00" in seasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--warehouse",
        help="Path to the DuckDB warehouse. Defaults to NBA_DUCKDB_PATH or data/warehouse/smoke.duckdb.",
    )
    args = parser.parse_args()

    warehouse = _warehouse_path(args.warehouse)
    if not warehouse.exists():
        print(
            f"Warehouse not found: {warehouse}. Run `make smoke` first, "
            "or pass --warehouse/NBA_DUCKDB_PATH for a live warehouse.",
            file=sys.stderr,
        )
        return 1

    with duckdb.connect(str(warehouse), read_only=True) as conn:
        result = conn.execute(QUERY)
        columns = [column[0] for column in result.description]
        rows = result.fetchall()

    if not rows:
        print("No team summary rows found. Run `make smoke` or a live pipeline first.", file=sys.stderr)
        return 1

    if _uses_synthetic_fixture_season(columns, rows):
        print(
            "Synthetic smoke warehouse: season 2099-00 and fake team codes are test fixtures, "
            "not NBA results.\n"
        )

    print(_render_table(columns, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

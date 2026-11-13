"""Safety checks shared by CLI and scheduled warehouse runs."""

from __future__ import annotations

from nba_duckdb import config, db
from nba_duckdb.exceptions import (
    PipelineStateNotInitializedError,
    SyntheticDataInLiveWarehouseError,
)
from nba_duckdb.fixtures.generate_synthetic_fixtures import SEASON as SYNTHETIC_SEASON


def assert_no_synthetic_rows() -> None:
    """Fail closed before live collection writes into a fixture warehouse."""

    table_rows = db.execute(
        """
        SELECT COUNT(*) AS row_count
        FROM information_schema.tables
        WHERE table_schema = 'bronze'
          AND table_name = 'schedule'
        """,
        read_only=True,
    )
    if not table_rows or int(table_rows[0]["row_count"] or 0) == 0:
        raise PipelineStateNotInitializedError(
            "Pipeline tables not found; run `nba-duckdb init` first"
        )

    column_rows = db.execute(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema IN ('bronze', 'silver', 'gold')
          AND column_name IN ('season', 'game_id')
        ORDER BY table_schema, table_name, column_name
        """,
        read_only=True,
    )
    table_columns: dict[tuple[str, str], set[str]] = {}
    for row in column_rows:
        table_key = (str(row["table_schema"]), str(row["table_name"]))
        table_columns.setdefault(table_key, set()).add(str(row["column_name"]))

    polluted_tables = []
    for (schema, table), columns in table_columns.items():
        predicates = []
        params = []
        if "season" in columns:
            predicates.append(f"{db._quote_ident('season')} = ?")
            params.append(SYNTHETIC_SEASON)
        if "game_id" in columns:
            predicates.append(f"{db._quote_ident('game_id')} LIKE '002SYN%'")
        if not predicates:
            continue
        row = db.execute(
            f"""
            SELECT COUNT(*) AS row_count
            FROM {db._quote_ident(schema)}.{db._quote_ident(table)}
            WHERE {" OR ".join(predicates)}
            """,
            params,
            read_only=True,
        )[0]
        if int(row["row_count"] or 0):
            polluted_tables.append(f"{schema}.{table}")

    if polluted_tables:
        raise SyntheticDataInLiveWarehouseError(
            "This warehouse contains synthetic smoke fixture rows "
            f"(season {SYNTHETIC_SEASON} / 002SYN game IDs) in "
            f"{', '.join(polluted_tables)}. Smoke runs default to "
            f"{config.smoke_warehouse_path()}; use a clean live warehouse, "
            "or set NBA_DUCKDB_PATH to another DuckDB file."
        )

"""Shared write step for the season-level bronze tasks (hustle, tracking, matchups, defense)."""

from nba_duckdb.db import upsert_rows


def upsert_then_fail_on_holes(
    table: str,
    rows: list[dict],
    *,
    conflict_cols: list[str],
    failures: list[str],
) -> int:
    """Write the payloads that came back, then fail if any request didn't.

    Failing the task keeps the run resumable (`run-live --resume-latest`) instead of
    reporting success while older rows stay in place for the requests that failed.
    """
    count = upsert_rows("bronze", table, rows, conflict_cols=conflict_cols) if rows else 0
    if failures:
        raise RuntimeError(
            f"bronze.{table}: {len(failures)} request(s) failed, {len(rows)} written; "
            f"first failures: {'; '.join(failures[:5])}"
        )
    return count

"""Small database checks for local and CI pipeline runs."""

from __future__ import annotations

import os
from typing import Any

from nba_duckdb import db, registry
from nba_duckdb.defaults import ALL_TEAM_IDS
from nba_duckdb.exceptions import PipelineStateNotInitializedError

REQUIRED_TABLES = registry.quality_required_tables()

# These datasets are backed by time-sensitive or explicitly optional public
# sources. Their tables must exist, but a valid run can produce zero rows (for
# example, an empty offseason injury report or no user-supplied jersey ranks).
ALLOW_EMPTY_TABLES = frozenset({
    "silver.dim_injuries",
    "gold.player_pageviews_daily",
    "gold.player_media_mentions_daily",
    "gold.player_jersey_rank_snapshots",
})

INTEGRITY_QUERIES = {
    "silver.fct_boxscores_missing_games": """
        SELECT COUNT(*) AS row_count
        FROM silver.fct_boxscores boxscores
        LEFT JOIN silver.fct_games games ON games.game_id = boxscores.game_id
        WHERE games.game_id IS NULL
    """,
    "silver.fct_boxscores_missing_players": """
        SELECT COUNT(*) AS row_count
        FROM silver.fct_boxscores boxscores
        LEFT JOIN silver.dim_players players ON players.player_id = boxscores.player_id
        WHERE players.player_id IS NULL
    """,
    "silver.fct_play_by_play_missing_games": """
        SELECT COUNT(*) AS row_count
        FROM silver.fct_play_by_play plays
        LEFT JOIN silver.fct_games games ON games.game_id = plays.game_id
        WHERE games.game_id IS NULL
    """,
    "gold.player_game_stats_missing_players": """
        SELECT COUNT(*) AS row_count
        FROM gold.player_game_stats stats
        LEFT JOIN silver.dim_players players ON players.player_id = stats.player_id
        WHERE players.player_id IS NULL
    """,
}

UNIQUE_KEY_CHECKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "silver.fct_games_unique_game_id": ("silver.fct_games", ("game_id",)),
    "silver.fct_boxscores_unique_player_game": (
        "silver.fct_boxscores",
        ("game_id", "player_id"),
    ),
    "silver.fct_play_by_play_unique_action": (
        "silver.fct_play_by_play",
        ("game_id", "action_id"),
    ),
    "silver.fct_possessions_unique_possession": (
        "silver.fct_possessions",
        ("game_id", "possession_number"),
    ),
    "silver.fct_shots_unique_shot": (
        "silver.fct_shots",
        ("game_id", "game_event_id"),
    ),
    "gold.player_game_stats_unique_player_game": (
        "gold.player_game_stats",
        ("game_id", "player_id"),
    ),
    "gold.team_game_stats_unique_team_game": ("gold.team_game_stats", ("game_id", "team_id")),
    "gold.team_season_elo_unique_team_season": ("gold.team_season_elo", ("team_id", "season")),
    "gold.team_game_elo_history_unique_team_game": (
        "gold.team_game_elo_history",
        ("team_id", "season", "game_id"),
    ),
    "gold.player_season_stats_unique_player_season": (
        "gold.player_season_stats",
        ("player_id", "season"),
    ),
    "gold.team_season_four_factors_unique_team_season": ("gold.team_season_four_factors", ("team_id", "season")),
    "gold.team_season_percentile_ranks_unique_team_season": (
        "gold.team_season_percentile_ranks",
        ("team_id", "season"),
    ),
    "gold.team_season_starter_bench_stats_unique_team_role": (
        "gold.team_season_starter_bench_stats",
        ("team_id", "season", "role"),
    ),
    "gold.player_season_load_management_unique_player_season": (
        "gold.player_season_load_management",
        ("player_id", "season"),
    ),
    "gold.team_season_clutch_stats_unique_team_season": (
        "gold.team_season_clutch_stats",
        ("offense_team_id", "season"),
    ),
    "gold.team_season_opponent_scouting_unique_matchup_season": (
        "gold.team_season_opponent_scouting",
        ("team_id", "opponent_id", "season"),
    ),
    "gold.team_season_timeout_stats_unique_team_season": (
        "gold.team_season_timeout_stats",
        ("team_id", "season"),
    ),
    "gold.team_season_ato_stats_unique_team_season": ("gold.team_season_ato_stats", ("team_id", "season")),
    "gold.player_season_clutch_stats_unique_player_season": (
        "gold.player_season_clutch_stats",
        ("player_id", "season"),
    ),
    "gold.team_season_shot_profile_unique_team_bucket": (
        "gold.team_season_shot_profile",
        ("season", "team_id", "shot_bucket"),
    ),
    "gold.player_season_shot_profile_unique_player_bucket": (
        "gold.player_season_shot_profile",
        ("season", "team_id", "player_id", "shot_bucket"),
    ),
    "gold.player_zone_season_shot_quality_unique_player_zone": (
        "gold.player_zone_season_shot_quality",
        ("season", "player_id", "team_id", "shot_zone_basic"),
    ),
    "gold.team_season_play_type_stats_unique_team_type": (
        "gold.team_season_play_type_stats",
        ("season", "offense_team_id", "play_type"),
    ),
    "gold.team_season_play_type_splits_unique_split": (
        "gold.team_season_play_type_splits",
        ("season", "offense_team_id", "play_type", "split_type", "split_value"),
    ),
}

CORE_LEDGER_SOURCES = {"play-by-play"}
CORE_TEAM_IDS = tuple(int(team_id) for team_id in ALL_TEAM_IDS.split(","))


def _missing_pipeline_state(exc: Exception) -> bool:
    message = str(exc)
    return (
        "does not exist" in message
        or "Catalog Error" in message
        or "Cannot open file" in message
        or "No such file" in message
    )


def _ensure_initialized_for_read() -> None:
    try:
        db.execute("SELECT 1 FROM ops.pipeline_runs LIMIT 1", read_only=True)
    except Exception as exc:  # noqa: BLE001 - convert DuckDB setup errors for CLI users
        if _missing_pipeline_state(exc):
            raise PipelineStateNotInitializedError(
                "Pipeline tables not found; run `nba-duckdb init` first"
            ) from exc
        raise


def _parse_team_ids(raw: str | None) -> tuple[int, ...]:
    if not raw or not raw.strip():
        return CORE_TEAM_IDS
    team_ids = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    return team_ids or CORE_TEAM_IDS


def _active_team_scope() -> tuple[int, ...]:
    return _parse_team_ids(os.environ.get("NBA_DUCKDB_TEAM_IDS", ALL_TEAM_IDS))


def _season_coverage_failures() -> tuple[list[str], list[dict[str, Any]]]:
    known_placeholders = ", ".join("?" for _ in CORE_TEAM_IDS)
    scoped_team_ids = _active_team_scope()
    scoped_placeholders = ", ".join("?" for _ in scoped_team_ids)
    rows = db.execute(
        f"""
        SELECT schedule.season,
               COUNT(DISTINCT schedule.game_id) AS completed_games,
               COUNT(DISTINCT boxscores.game_id) AS boxscore_games,
               COUNT(DISTINCT plays.game_id) AS play_by_play_games
        FROM bronze.schedule schedule
        LEFT JOIN bronze.boxscores boxscores ON boxscores.game_id = schedule.game_id
        LEFT JOIN bronze.play_by_play plays ON plays.game_id = schedule.game_id
        WHERE schedule.game_status = 3
          AND schedule.home_team_id IN ({known_placeholders})
          AND schedule.away_team_id IN ({known_placeholders})
          AND (
              schedule.home_team_id IN ({scoped_placeholders})
              OR schedule.away_team_id IN ({scoped_placeholders})
          )
        GROUP BY schedule.season
        ORDER BY schedule.season
        """,
        [*CORE_TEAM_IDS, *CORE_TEAM_IDS, *scoped_team_ids, *scoped_team_ids],
        read_only=True,
    )
    failures = []
    for row in rows:
        completed = int(row["completed_games"] or 0)
        boxscores = int(row["boxscore_games"] or 0)
        pbp = int(row["play_by_play_games"] or 0)
        if completed != boxscores:
            failures.append(
                f"season {row['season']} has {boxscores}/{completed} completed-game boxscores"
            )
        if completed != pbp:
            failures.append(
                f"season {row['season']} has {pbp}/{completed} completed-game play-by-play rows"
            )
    return failures, rows


def _ledger_failures(seasons: set[str] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    if seasons is not None and not seasons:
        return [], []

    source_placeholders = ", ".join("?" for _ in CORE_LEDGER_SOURCES)
    params: list[Any] = sorted(CORE_LEDGER_SOURCES)
    season_filter = ""
    if seasons is not None:
        ordered_seasons = sorted(seasons)
        season_placeholders = ", ".join("?" for _ in ordered_seasons)
        season_filter = f" AND season IN ({season_placeholders})"
        params.extend(ordered_seasons)
    rows = db.execute(
        f"""
        SELECT source, season, status, COUNT(*) AS item_count
        FROM ops.ingestion_items
        WHERE source IN ({source_placeholders})
          {season_filter}
          AND status <> 'success'
        GROUP BY source, season, status
        ORDER BY source, season, status
        """,
        params,
        read_only=True,
    )
    failures = [
        f"{row['source']} {row['season']} has {row['item_count']} {row['status']} ingestion items"
        for row in rows
    ]
    return failures, rows


def _duplicate_key_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for check_name, (qualified_table, columns) in UNIQUE_KEY_CHECKS.items():
        schema, table = qualified_table.split(".", 1)
        quoted_columns = [db._quote_ident(column) for column in columns]
        key_list = ", ".join(quoted_columns)
        not_null = " AND ".join(f"{column} IS NOT NULL" for column in quoted_columns)
        row = db.execute(
            f"""
            SELECT COALESCE(SUM(duplicate_rows), 0) AS duplicate_rows
            FROM (
                SELECT COUNT(*) - 1 AS duplicate_rows
                FROM {db._quote_ident(schema)}.{db._quote_ident(table)}
                WHERE {not_null}
                GROUP BY {key_list}
                HAVING COUNT(*) > 1
            ) duplicates
            """,
            read_only=True,
        )[0]
        counts[check_name] = int(row["duplicate_rows"] or 0)
    return counts


def _missing_required_tables() -> list[str]:
    existing = {
        (str(row["table_schema"]), str(row["table_name"]))
        for row in db.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            """,
            read_only=True,
        )
    }
    return [
        f"{schema}.{table}"
        for schema, table in REQUIRED_TABLES
        if (schema, table) not in existing
    ]


def run_checks() -> dict[str, Any]:
    _ensure_initialized_for_read()
    missing_tables = _missing_required_tables()
    table_counts = table_counts_for(REQUIRED_TABLES)
    integrity_counts = {
        name: int(db.execute(query, read_only=True)[0]["row_count"])
        for name, query in INTEGRITY_QUERIES.items()
    }
    duplicate_key_counts = _duplicate_key_counts()
    coverage_failures, coverage_counts = _season_coverage_failures()
    scoped_seasons = {
        str(row["season"])
        for row in coverage_counts
        if row.get("season") is not None
    }
    ledger_failures, ledger_counts = _ledger_failures(scoped_seasons)

    failures = [f"{table_name} is missing" for table_name in missing_tables]
    failures.extend(
        f"{table_name} has no rows"
        for table_name, row_count in table_counts.items()
        if row_count == 0
        and table_name not in ALLOW_EMPTY_TABLES
        and table_name not in missing_tables
    )
    failures.extend(
        f"{check_name} found {row_count} rows"
        for check_name, row_count in integrity_counts.items()
        if row_count != 0
    )
    failures.extend(
        f"{check_name} found {row_count} duplicate rows"
        for check_name, row_count in duplicate_key_counts.items()
        if row_count != 0
    )
    failures.extend(coverage_failures)
    failures.extend(ledger_failures)
    if failures:
        raise RuntimeError("; ".join(failures))

    return {
        "missing_tables": missing_tables,
        "table_counts": table_counts,
        "integrity_counts": integrity_counts,
        "duplicate_key_counts": duplicate_key_counts,
        "coverage_counts": coverage_counts,
        "ledger_counts": ledger_counts,
    }


def table_counts_for(tables: list[tuple[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for schema, table in tables:
        try:
            row = db.execute(
                f'SELECT COUNT(*) AS row_count FROM "{schema}"."{table}"',
                read_only=True,
            )[0]
            counts[f"{schema}.{table}"] = int(row["row_count"])
        except Exception:
            counts[f"{schema}.{table}"] = 0
    return counts


def table_counts() -> dict[str, int]:
    return table_counts_for(REQUIRED_TABLES)

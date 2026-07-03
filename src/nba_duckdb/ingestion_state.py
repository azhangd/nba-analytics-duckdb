"""Item-level state for resumable live ingestion."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from nba_duckdb import db
from nba_duckdb.exceptions import PipelineStateNotInitializedError

PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
INTERRUPTED = "interrupted"
DEFERRED = "deferred"
SKIPPED = "skipped"

ELIGIBLE_STATUSES = {PENDING, FAILED, INTERRUPTED, DEFERRED}


def _missing_ops_state(exc: Exception) -> bool:
    message = str(exc)
    return (
        "does not exist" in message
        or "Catalog Error" in message
        or "Cannot open file" in message
        or "No such file" in message
    )


def normalize_source(source: str) -> str:
    return source.strip().lower().replace("_", "-")


def item_key(game_id: str, team_id: int | None = None) -> str:
    team_part = "game" if team_id is None else str(int(team_id))
    return f"{game_id}:{team_part}"


def make_item(game_id: str, season: str, team_id: int | None = None) -> dict[str, Any]:
    return {
        "game_id": str(game_id),
        "season": str(season or ""),
        "team_id": int(team_id) if team_id is not None else None,
        "item_key": item_key(str(game_id), int(team_id) if team_id is not None else None),
    }


def _dedupe_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        season = str(item.get("season") or "")
        game_id = str(item.get("game_id") or "")
        team_id = item.get("team_id")
        normalized = make_item(game_id, season, int(team_id) if team_id is not None else None)
        deduped[(season, normalized["item_key"])] = normalized
    return list(deduped.values())


def ensure_items(source: str, items: Iterable[dict[str, Any]]) -> int:
    source = normalize_source(source)
    target_items = _dedupe_items(items)
    if not target_items:
        return 0

    existing: set[tuple[str, str]] = set()
    for season in sorted({item["season"] for item in target_items}):
        rows = db.execute(
            """
            SELECT season, item_key
            FROM ops.ingestion_items
            WHERE source = ?
              AND season = ?
            """,
            [source, season],
        )
        existing.update((str(row["season"]), str(row["item_key"])) for row in rows)

    new_rows = [
        {
            "source": source,
            "season": item["season"],
            "item_key": item["item_key"],
            "game_id": item["game_id"],
            "team_id": item["team_id"],
            "status": PENDING,
        }
        for item in target_items
        if (item["season"], item["item_key"]) not in existing
    ]
    return db.insert_rows("ops", "ingestion_items", new_rows) if new_rows else 0


def mark_running_items_interrupted(source: str, season: str | None = None) -> int:
    source = normalize_source(source)
    params: list[Any] = [source]
    where = "source = ? AND status = 'running'"
    if season:
        where += " AND season = ?"
        params.append(season)
    db.execute(
        f"""
        UPDATE ops.ingestion_items
        SET status = 'interrupted',
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP,
            last_error = COALESCE(last_error, 'Interrupted by an earlier process')
        WHERE {where}
        """,
        params,
    )
    return 0


def fetch_item_states(source: str, items: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    source = normalize_source(source)
    target_items = _dedupe_items(items)
    states: dict[tuple[str, str], dict[str, Any]] = {}
    for season in sorted({item["season"] for item in target_items}):
        rows = db.execute(
            """
            SELECT *
            FROM ops.ingestion_items
            WHERE source = ?
              AND season = ?
            """,
            [source, season],
        )
        for row in rows:
            states[(str(row["season"]), str(row["item_key"]))] = row
    return states


def eligible_items(source: str, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    source = normalize_source(source)
    target_items = _dedupe_items(items)
    ensure_items(source, target_items)
    states = fetch_item_states(source, target_items)
    eligible: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for item in target_items:
        state = states.get((item["season"], item["item_key"]))
        if state is None:
            eligible.append(item)
            continue
        status = str(state.get("status") or PENDING)
        if status not in ELIGIBLE_STATUSES:
            continue
        next_retry_at = state.get("next_retry_at")
        if next_retry_at and _as_aware_datetime(next_retry_at) > now:
            continue
        eligible.append(item)
    return eligible


def mark_item_running(source: str, item: dict[str, Any]) -> None:
    source = normalize_source(source)
    db.execute(
        """
        UPDATE ops.ingestion_items
        SET status = 'running',
            attempts = attempts + 1,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP,
            finished_at = NULL,
            next_retry_at = NULL,
            last_error = NULL
        WHERE source = ?
          AND season = ?
          AND item_key = ?
        """,
        [source, item["season"], item["item_key"]],
    )


def mark_item_success(source: str, item: dict[str, Any], *, rows_written: int = 1) -> None:
    source = normalize_source(source)
    db.execute(
        """
        UPDATE ops.ingestion_items
        SET status = 'success',
            rows_written = ?,
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP,
            next_retry_at = NULL,
            last_error = NULL
        WHERE source = ?
          AND season = ?
          AND item_key = ?
        """,
        [rows_written, source, item["season"], item["item_key"]],
    )


def mark_item_failed(
    source: str,
    item: dict[str, Any],
    error: BaseException | str,
    *,
    retry_delay_seconds: float | None = None,
    deferred: bool = False,
) -> None:
    source = normalize_source(source)
    next_retry_at = None
    if retry_delay_seconds and retry_delay_seconds > 0:
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)
    status = DEFERRED if deferred else FAILED
    if isinstance(error, BaseException):
        message = str(error).strip() or error.__class__.__name__
    else:
        message = str(error)
    db.execute(
        """
        UPDATE ops.ingestion_items
        SET status = ?,
            last_error = ?,
            next_retry_at = ?,
            updated_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP
        WHERE source = ?
          AND season = ?
          AND item_key = ?
        """,
        [
            status,
            message[:500],
            next_retry_at.isoformat() if next_retry_at else None,
            source,
            item["season"],
            item["item_key"],
        ],
    )


def mark_items_success(source: str, items: Iterable[dict[str, Any]], *, rows_written: int = 1) -> None:
    source = normalize_source(source)
    deduped = _dedupe_items(items)
    ensure_items(source, deduped)
    for season in sorted({item["season"] for item in deduped}):
        item_keys = [item["item_key"] for item in deduped if item["season"] == season]
        if not item_keys:
            continue
        placeholders = ", ".join("?" for _ in item_keys)
        db.execute(
            f"""
            UPDATE ops.ingestion_items
            SET status = 'success',
                rows_written = ?,
                updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP,
                next_retry_at = NULL,
                last_error = NULL
            WHERE source = ?
              AND season = ?
              AND item_key IN ({placeholders})
            """,
            [rows_written, source, season, *item_keys],
        )


def summarize_items(source: str, items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    source = normalize_source(source)
    deduped = _dedupe_items(items)
    ensure_items(source, deduped)
    states = fetch_item_states(source, deduped)
    summary: dict[str, Any] = {
        "source": source,
        "total_items": len(deduped),
        "rows_written": 0,
        "status_counts": {},
    }
    for item in deduped:
        state = states.get((item["season"], item["item_key"])) or {}
        status = str(state.get("status") or PENDING)
        summary["rows_written"] += int(state.get("rows_written") or 0)
        summary["status_counts"][status] = summary["status_counts"].get(status, 0) + 1
    return summary


def incomplete_items(source: str, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    source = normalize_source(source)
    deduped = _dedupe_items(items)
    ensure_items(source, deduped)
    states = fetch_item_states(source, deduped)
    incomplete: list[dict[str, Any]] = []
    for item in deduped:
        state = states.get((item["season"], item["item_key"])) or {}
        status = str(state.get("status") or PENDING)
        if status != SUCCESS:
            incomplete.append({**item, "status": status, "last_error": state.get("last_error")})
    return incomplete


def summarize_sources(
    season: str | None = None,
    source: str | None = None,
    *,
    read_only: bool = False,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_parts: list[str] = []
    if season:
        where_parts.append("season = ?")
        params.append(season)
    if source:
        where_parts.append("source = ?")
        params.append(normalize_source(source))
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    try:
        rows = db.execute(
            f"""
            SELECT source, season, status, COUNT(*) AS item_count,
                   COALESCE(SUM(rows_written), 0) AS rows_written
            FROM ops.ingestion_items
            {where}
            GROUP BY source, season, status
            ORDER BY source, season, status
            """,
            params,
            read_only=read_only,
        )
    except Exception as exc:  # noqa: BLE001 - observability should be harmless pre-init
        if read_only and _missing_ops_state(exc):
            raise PipelineStateNotInitializedError(
                "Run state tables not found; run `nba-duckdb init` first"
            ) from exc
        raise
    summaries: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["source"]), str(row["season"]))
        summary = summaries.setdefault(
            key,
            {
                "source": key[0],
                "season": key[1],
                "total_items": 0,
                "rows_written": 0,
                "status_counts": {},
            },
        )
        count = int(row["item_count"])
        summary["total_items"] += count
        summary["rows_written"] += int(row["rows_written"] or 0)
        summary["status_counts"][str(row["status"])] = count
    return list(summaries.values())


def summarize_source(source: str, season: str | None = None, *, read_only: bool = False) -> dict[str, Any]:
    summaries = summarize_sources(season=season, source=source, read_only=read_only)
    if not summaries:
        return {
            "source": normalize_source(source),
            "season": season,
            "total_items": 0,
            "rows_written": 0,
            "status_counts": {},
        }
    if len(summaries) == 1:
        return summaries[0]
    combined = {
        "source": normalize_source(source),
        "season": season,
        "total_items": 0,
        "rows_written": 0,
        "status_counts": {},
    }
    for summary in summaries:
        combined["total_items"] += summary["total_items"]
        combined["rows_written"] += summary["rows_written"]
        for status, count in summary["status_counts"].items():
            combined["status_counts"][status] = combined["status_counts"].get(status, 0) + count
    return combined


def _as_aware_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

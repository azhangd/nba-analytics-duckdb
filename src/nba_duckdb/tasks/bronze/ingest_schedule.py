"""Bronze: Ingest NBA season schedule into DuckDB."""

import json
import logging
import os
import time
from datetime import date, datetime, timedelta

from nba_duckdb.competitions import (
    NBA,
    Competition,
    competitions_for_slugs,
)
from nba_duckdb.db import get_conn, upsert_rows
from nba_duckdb.defaults import get_seasons
from nba_duckdb.season_utils import normalize_requested_seasons
from nba_duckdb.utils import nba_client

logger = logging.getLogger("nba_duckdb.tasks.bronze.schedule")


def _existing_schedule_count(season: str, competition: Competition = NBA) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM bronze.schedule
                WHERE season = %s
                  AND competition = %s
                """,
                [season, competition.slug],
            )
            row = cur.fetchone()
    return int(row["cnt"]) if row else 0


def _latest_final_date(season: str, competition: Competition = NBA) -> date | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(to_date(game_date, 'MM/DD/YYYY HH24:MI:SS')) AS latest_final
                FROM bronze.schedule
                WHERE season = %s
                  AND competition = %s
                  AND game_status = 3
                """,
                [season, competition.slug],
            )
            row = cur.fetchone()
    if not row or row["latest_final"] is None:
        return None
    latest_final = row["latest_final"]
    if isinstance(latest_final, datetime):
        return latest_final.date()
    if isinstance(latest_final, date):
        return latest_final
    return _parse_iso_date(str(latest_final).split(" ")[0])


def _build_schedule_row(
    game: dict,
    season: str,
    game_date: str,
    competition: Competition = NBA,
) -> dict:
    home = game.get("homeTeam", game.get("HomeTeam", {})) or {}
    away = game.get("awayTeam", game.get("AwayTeam", {})) or {}
    return {
        "game_id": game.get("gameId", game.get("GameID", "")),
        "game_date": game_date,
        "home_team_id": home.get("teamId", home.get("TeamID", 0)),
        "away_team_id": away.get("teamId", away.get("TeamID", 0)),
        "home_team_abbr": home.get("teamTricode", home.get("TeamTricode", "")),
        "away_team_abbr": away.get("teamTricode", away.get("TeamTricode", "")),
        "game_status": game.get("gameStatus", game.get("GameStatus", 0)),
        "game_status_text": game.get("gameStatusText", game.get("GameStatusText", "")),
        "season": season,
        "league_id": competition.league_id,
        "competition": competition.slug,
        "raw_json": json.dumps(game),
    }


def _season_scoreboard_range(season: str) -> tuple[date, date]:
    start_year = int(season.split("-")[0])
    # Scoreboard endpoint is reliable for daily historical lookups; scan
    # preseason through finals for the requested season.
    return date(start_year, 10, 1), date(start_year + 1, 6, 30)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _date_range_from_values(start_date: str | None, end_date: str | None) -> set[date]:
    start = _parse_iso_date(start_date)
    end = _parse_iso_date(end_date)
    if start is None and end is None:
        return set()
    if start is None:
        start = end
    if end is None:
        end = start
    if start is None or end is None:
        return set()
    if end < start:
        start, end = end, start

    days: set[date] = set()
    current = start
    while current <= end:
        days.add(current)
        current += timedelta(days=1)
    return days


def _ingest_season_from_scoreboard(season: str) -> int:
    start_date, end_date = _season_scoreboard_range(season)
    rows: list[dict] = []
    failed_dates: list[str] = []
    current = start_date
    while current <= end_date:
        iso_date = current.isoformat()
        try:
            raw = nba_client.get_scoreboard_for_date(iso_date, max_retries=5)
        except Exception as exc:
            logger.warning("Scoreboard fetch failed for %s (%s); retrying once", iso_date, exc)
            time.sleep(2)
            try:
                raw = nba_client.get_scoreboard_for_date(iso_date, max_retries=5)
            except Exception as retry_exc:
                failed_dates.append(iso_date)
                logger.warning(
                    "Skipping scoreboard date %s after repeated failures: %s",
                    iso_date,
                    retry_exc,
                )
                current += timedelta(days=1)
                continue
        games = raw.get("scoreboard", {}).get("games", [])
        game_date = f"{current.strftime('%m/%d/%Y')} 00:00:00"
        for game in games:
            rows.append(
                _build_schedule_row(
                    game,
                    season=season,
                    game_date=game_date,
                    competition=NBA,
                )
            )
        current += timedelta(days=1)

    if not rows:
        raise ValueError(f"Scoreboard fallback returned no games for season {season}")
    if failed_dates:
        logger.warning(
            "Scoreboard fallback skipped %d dates for %s (%s)",
            len(failed_dates),
            season,
            ", ".join(failed_dates[:5]),
        )
    return upsert_rows("bronze", "schedule", rows, conflict_cols=["game_id"])


def _refresh_recent_statuses(season: str) -> int:
    latest_final = _latest_final_date(season, NBA)
    if latest_final is None:
        return 0

    start_date = latest_final + timedelta(days=1)
    end_date = date.today()
    if start_date > end_date:
        return 0

    rows: list[dict] = []
    current = start_date
    while current <= end_date:
        raw = nba_client.get_scoreboard_for_date(current.isoformat(), max_retries=3)
        games = raw.get("scoreboard", {}).get("games", [])
        game_date = f"{current.strftime('%m/%d/%Y')} 00:00:00"
        for game in games:
            rows.append(
                _build_schedule_row(
                    game,
                    season=season,
                    game_date=game_date,
                    competition=NBA,
                )
            )
        current += timedelta(days=1)

    if not rows:
        return 0

    return upsert_rows("bronze", "schedule", rows, conflict_cols=["game_id"])


def _refresh_specific_games(
    game_ids: list[str],
    season: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    dates: set[date] = set()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT game_id, game_date FROM bronze.schedule WHERE game_id = ANY(%s)",
                [game_ids],
            )
            for row in cur.fetchall():
                game_date = str(row.get("game_date") or "")
                date_part = game_date.split(" ")[0]
                if not date_part:
                    continue
                try:
                    dates.add(date.fromisoformat(date_part))
                except ValueError:
                    try:
                        month, day, year = date_part.split("/")
                        dates.add(date(int(year), int(month), int(day)))
                    except ValueError:
                        continue

    dates.update(_date_range_from_values(start_date, end_date))
    today = date.today()
    dates.update({today - timedelta(days=1), today, today + timedelta(days=1)})

    rows: list[dict] = []
    remaining = set(game_ids)
    for current in sorted(dates):
        raw = nba_client.get_scoreboard_for_date(current.isoformat(), max_retries=3)
        games = raw.get("scoreboard", {}).get("games", [])
        game_date = f"{current.strftime('%m/%d/%Y')} 00:00:00"
        for game in games:
            game_id = game.get("gameId", game.get("GameID", ""))
            if game_id not in remaining:
                continue
            rows.append(
                _build_schedule_row(
                    game,
                    season=season,
                    game_date=game_date,
                    competition=NBA,
                )
            )
            remaining.discard(game_id)

    if not rows:
        return 0

    return upsert_rows("bronze", "schedule", rows, conflict_cols=["game_id"])


def _ingest_season(season: str, is_current: bool) -> dict:
    existing_rows = _existing_schedule_count(season, NBA)

    rows: list[dict] = []
    used_scoreboard_fallback = False
    raw: dict | None = None
    if is_current:
        try:
            raw = nba_client.get_current_schedule_from_cdn(season)
        except ValueError as exc:
            logger.warning(
                "Current-season CDN schedule unavailable for %s; falling back to stats API: %s",
                season,
                exc,
            )

    try:
        # Initial historical backfills are prone to transient empty payloads from
        # stats.nba.com. Give cold loads a wider retry budget, while keeping
        # incremental refreshes quick when cached season rows already exist.
        if raw is None:
            schedule_retries = 2 if existing_rows > 0 else 4
            raw = nba_client.get_schedule(
                season=season,
                league_id=NBA.league_id,
                max_retries=schedule_retries,
            )
    except ValueError as exc:
        if "Empty resultSets" not in str(exc):
            raise
        if existing_rows <= 0:
            logger.warning(
                "Schedule endpoint rate-limited for %s; falling back to daily scoreboard scan",
                season,
            )
            count = _ingest_season_from_scoreboard(season)
            used_scoreboard_fallback = True
            logger.info("Upserted %d schedule rows for %s via scoreboard fallback", count, season)
            refreshed_count = 0
            total = count + refreshed_count
            return {
                "rows_written": total,
                "used_cached_schedule": False,
                "used_scoreboard_fallback": used_scoreboard_fallback,
                "refreshed_recent_status_rows": refreshed_count,
            }
        logger.warning(
            "Schedule fetch returned an empty rate-limited payload; keeping %d cached rows for %s",
            existing_rows,
            season,
        )
    else:
        assert raw is not None
        game_dates = raw.get("leagueSchedule", raw.get("LeagueSchedule", {})).get(
            "gameDates", raw.get("leagueSchedule", raw.get("LeagueSchedule", {})).get("GameDates", [])
        )
        for date_entry in game_dates:
            game_date = date_entry.get("gameDate", date_entry.get("GameDate", ""))
            for game in date_entry.get("games", date_entry.get("Games", [])):
                rows.append(
                    _build_schedule_row(
                        game,
                        season=season,
                        game_date=game_date,
                        competition=NBA,
                    )
                )

    count = upsert_rows("bronze", "schedule", rows, conflict_cols=["game_id"]) if rows else 0
    # Only poll for recent game status changes on the current/active season.
    refreshed_count = _refresh_recent_statuses(season) if is_current and existing_rows > 0 else 0
    total = count + refreshed_count
    logger.info("Upserted %d schedule rows for %s", total, season)
    return {
        "rows_written": total,
        "used_cached_schedule": not rows and existing_rows > 0,
        "used_scoreboard_fallback": used_scoreboard_fallback,
        "refreshed_recent_status_rows": refreshed_count,
    }


def _ingest_competition_season(
    season: str,
    competition: Competition,
    *,
    game_ids: set[str] | None = None,
) -> dict:
    if competition == NBA:
        raise ValueError("NBA schedule ingestion must use _ingest_season")

    raw = nba_client.get_schedule(
        season=season,
        league_id=competition.league_id,
        max_retries=4,
    )
    schedule = raw.get("leagueSchedule", raw.get("LeagueSchedule", {}))
    game_dates = schedule.get("gameDates", schedule.get("GameDates", []))
    rows: list[dict] = []
    for date_entry in game_dates:
        game_date = date_entry.get("gameDate", date_entry.get("GameDate", ""))
        for game in date_entry.get("games", date_entry.get("Games", [])):
            game_id = str(game.get("gameId", game.get("GameID", "")))
            if game_ids and game_id not in game_ids:
                continue
            rows.append(
                _build_schedule_row(
                    game,
                    season=season,
                    game_date=game_date,
                    competition=competition,
                )
            )

    if not rows and not game_ids:
        raise ValueError(
            f"Official {competition.display_name} schedule returned no games for {season}"
        )
    count = upsert_rows("bronze", "schedule", rows, conflict_cols=["game_id"]) if rows else 0
    logger.info(
        "Upserted %d schedule rows for %s (%s)",
        count,
        competition.display_name,
        season,
    )
    return {
        "rows_written": count,
        "competition": competition.slug,
        "league_id": competition.league_id,
    }


def run(
    season: str | None = None,
    seasons: list[str] | None = None,
    game_ids: list[str] | None = None,
    full_refresh: bool = False,
    **kwargs,
):
    default_season = os.environ.get("NBA_DUCKDB_DEFAULT_SEASON", "2025-26")
    target_seasons = normalize_requested_seasons(seasons) or ([season] if season else get_seasons())
    target_competitions = competitions_for_slugs(kwargs.get("competitions"))

    if game_ids:
        explicit_seasons = normalize_requested_seasons(seasons) or ([season] if season else [])
        if len(explicit_seasons) != 1:
            raise ValueError("Refreshing specific game_ids requires exactly one explicit season")
        target_season = explicit_seasons[0]
        requested_game_ids = {str(game_id) for game_id in game_ids}
        rows_written = 0
        for competition in target_competitions:
            if competition == NBA:
                rows_written += _refresh_specific_games(
                    sorted(requested_game_ids),
                    target_season,
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                )
            else:
                rows_written += _ingest_competition_season(
                    target_season,
                    competition,
                    game_ids=requested_game_ids,
                )["rows_written"]
        return {
            "rows_written": rows_written,
            "game_ids": [str(game_id) for game_id in game_ids],
            "competitions": [competition.slug for competition in target_competitions],
            "full_refresh": full_refresh,
        }

    total_rows = 0
    for target_season in target_seasons:
        for competition in target_competitions:
            if competition == NBA:
                result = _ingest_season(
                    target_season,
                    is_current=(target_season == default_season),
                )
            else:
                result = _ingest_competition_season(target_season, competition)
            total_rows += result["rows_written"]

    return {
        "rows_written": total_rows,
        "seasons": target_seasons,
        "competitions": [competition.slug for competition in target_competitions],
        "full_refresh": full_refresh,
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'bronze',
 'task_type': 'bronze',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.schedule',),
 'mutates': (),
 'graphs': ('default', 'quick'),
 'modes': ('live',),
 'required': True,
 'quality_outputs': ('bronze.schedule',),
 'regular_season_only': True,
 'live_order': 10,
 'fixture_order': None}

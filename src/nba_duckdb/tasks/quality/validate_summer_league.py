"""Fail-closed coverage checks for the Summer League ingestion graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import polars as pl

from nba_duckdb.competitions import SUMMER_LEAGUE_SLUGS, normalize_competition_slugs
from nba_duckdb.db import get_conn, read_table, upsert_rows
from nba_duckdb.season_utils import requested_or_default_seasons


def _json_document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _game_ids(frame: pl.DataFrame) -> set[str]:
    if frame.is_empty() or "game_id" not in frame.columns:
        return set()
    return {
        str(game_id)
        for game_id in frame["game_id"].drop_nulls().to_list()
        if str(game_id).strip()
    }


def _valid_payload_game_ids(
    frame: pl.DataFrame,
    payload_column: str,
    validator: Callable[[dict[str, Any]], bool],
) -> set[str]:
    if frame.is_empty() or payload_column not in frame.columns:
        return set()
    return {
        str(row["game_id"])
        for row in frame.iter_rows(named=True)
        if validator(_json_document(row.get(payload_column)))
    }


def _assert_coverage(label: str, expected: set[str], actual: set[str]) -> None:
    missing = sorted(expected - actual)
    if missing:
        examples = ", ".join(missing[:10])
        raise RuntimeError(
            f"Summer League quality gate: {label} missing {len(missing)} "
            f"completed game(s): {examples}"
        )


def _canonical_payload(value: Any) -> tuple[str, int]:
    document = _json_document(value)
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def _schedule_score(document: dict[str, Any], side: str) -> int | None:
    team = document.get(f"{side}Team", document.get(f"{side.title()}Team", {}))
    if not isinstance(team, dict):
        return None
    value = team.get("score", team.get("Score"))
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _boxscore_teams(document: dict[str, Any]) -> list[dict[str, Any]]:
    root = document.get("boxScoreTraditional", document.get("game", document))
    if not isinstance(root, dict):
        return []
    teams = [root.get("homeTeam"), root.get("awayTeam")]
    return [team for team in teams if isinstance(team, dict)]


def _team_stat(team: dict[str, Any], name: str) -> int | None:
    statistics = team.get("statistics")
    if not isinstance(statistics, dict):
        return None
    value = statistics.get(name)
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _free_throw_actions(document: dict[str, Any]) -> list[dict[str, Any]]:
    game = document.get("game")
    actions = game.get("actions") if isinstance(game, dict) else None
    if not isinstance(actions, list):
        return []
    return [
        action
        for action in actions
        if isinstance(action, dict)
        and str(action.get("actionType") or "").strip().lower()
        in {"free throw", "freethrow"}
    ]


def _is_made_free_throw(action: dict[str, Any]) -> bool:
    description = str(action.get("description") or "").lstrip().upper()
    return not (description == "MISS" or description.startswith("MISS "))


def _semantic_reconciliation(
    schedule: pl.DataFrame,
    boxscores: pl.DataFrame,
    play_by_play: pl.DataFrame,
    completed_ids: set[str],
) -> dict[str, Any]:
    schedule_by_game = {
        str(row["game_id"]): _json_document(row.get("raw_json"))
        for row in schedule.iter_rows(named=True)
        if str(row.get("game_id") or "") in completed_ids
    }
    box_by_game = {
        str(row["game_id"]): _json_document(row.get("traditional_json"))
        for row in boxscores.iter_rows(named=True)
        if str(row.get("game_id") or "") in completed_ids
    }
    pbp_by_game = {
        str(row["game_id"]): _json_document(row.get("pbp_json"))
        for row in play_by_play.iter_rows(named=True)
        if str(row.get("game_id") or "") in completed_ids
    }

    mismatches: list[dict[str, Any]] = []
    for game_id in sorted(completed_ids):
        teams = _boxscore_teams(box_by_game.get(game_id, {}))
        box_fta = [_team_stat(team, "freeThrowsAttempted") for team in teams]
        box_ftm = [_team_stat(team, "freeThrowsMade") for team in teams]
        box_points = [_team_stat(team, "points") for team in teams]
        actions = _free_throw_actions(pbp_by_game.get(game_id, {}))
        pbp_totals = {
            "attempted": len(actions),
            "made": sum(_is_made_free_throw(action) for action in actions),
        }
        box_totals = {
            "attempted": sum(value for value in box_fta if value is not None),
            "made": sum(value for value in box_ftm if value is not None),
        }
        if len(teams) != 2 or any(value is None for value in (*box_fta, *box_ftm)):
            mismatches.append({"game_id": game_id, "check": "boxscore_ft_fields"})
        elif pbp_totals != box_totals:
            mismatches.append(
                {
                    "game_id": game_id,
                    "check": "pbp_vs_boxscore_free_throws",
                    "play_by_play": pbp_totals,
                    "boxscore": box_totals,
                }
            )

        schedule_document = schedule_by_game.get(game_id, {})
        schedule_points = [
            _schedule_score(schedule_document, "home"),
            _schedule_score(schedule_document, "away"),
        ]
        if (
            len(teams) != 2
            or any(value is None for value in (*box_points, *schedule_points))
        ):
            mismatches.append({"game_id": game_id, "check": "final_score_fields"})
        elif box_points != schedule_points:
            mismatches.append(
                {
                    "game_id": game_id,
                    "check": "schedule_vs_boxscore_final_score",
                    "schedule": schedule_points,
                    "boxscore": box_points,
                }
            )

    if mismatches:
        raise RuntimeError(
            "Summer League semantic reconciliation failed for "
            f"{len({row['game_id'] for row in mismatches})} game(s): "
            f"{json.dumps(mismatches[:10], sort_keys=True)}"
        )
    return {
        "games_checked": len(completed_ids),
        "free_throw_mismatches": 0,
        "final_score_mismatches": 0,
    }


def _source_locator(source_name: str, scope: dict[str, Any], variant: str) -> str:
    game_id = scope["game_id"]
    if source_name == "schedule":
        return (
            "https://stats.nba.com/stats/scheduleleaguev2"
            f"?LeagueID={scope['league_id']}&Season={scope['season']}"
        )
    if source_name == "play_by_play" and variant == "live_cdn":
        return (
            "https://cdn.nba.com/static/json/liveData/playbyplay/"
            f"playbyplay_{game_id}.json"
        )
    if source_name == "play_by_play":
        return (
            "https://stats.nba.com/stats/playbyplayv3"
            f"?GameID={game_id}&StartPeriod=0&EndPeriod=0"
        )
    if source_name == "boxscore_traditional":
        if variant == "live_cdn":
            return (
                "https://cdn.nba.com/static/json/liveData/boxscore/"
                f"boxscore_{game_id}.json"
            )
        return f"https://stats.nba.com/stats/boxscoretraditionalv3?GameID={game_id}"
    if source_name == "boxscore_advanced":
        return f"https://stats.nba.com/stats/boxscoreadvancedv3?GameID={game_id}"
    return (
        "https://stats.nba.com/stats/shotchartdetail"
        f"?GameID={game_id}&LeagueID={scope['league_id']}"
        f"&Season={scope['season']}&SeasonType=Regular%20Season&TeamID=0"
    )


def _payload_manifest(
    schedule: pl.DataFrame,
    boxscores: pl.DataFrame,
    play_by_play: pl.DataFrame,
    shot_charts: pl.DataFrame,
) -> tuple[list[dict[str, Any]], str]:
    scope_by_game = {
        str(row["game_id"]): {
            "game_id": str(row["game_id"]),
            "season": str(row.get("season") or ""),
            "league_id": str(row.get("league_id") or ""),
            "competition": str(row.get("competition") or ""),
        }
        for row in schedule.iter_rows(named=True)
    }
    entries: list[dict[str, Any]] = []
    audited_at = datetime.now(timezone.utc).isoformat()

    def boxscore_variant(payload: Any, recorded: Any, root_key: str) -> str:
        recorded_value = str(recorded or "unknown")
        if recorded_value != "unknown":
            return recorded_value
        document = _json_document(payload)
        if root_key in document:
            return "stats_v3"
        if root_key == "boxScoreTraditional" and "game" in document:
            return "live_cdn"
        return "unknown"

    def add(
        source_name: str,
        game_id: str,
        payload: Any,
        variant: str,
        ingested_at: Any,
    ) -> None:
        scope = scope_by_game.get(game_id)
        document = _json_document(payload)
        if scope is None or not document:
            return
        payload_sha256, payload_bytes = _canonical_payload(document)
        entries.append(
            {
                "source_name": source_name,
                "item_key": game_id,
                "game_id": game_id,
                "season": scope["season"],
                "competition": scope["competition"],
                "source_locator": _source_locator(source_name, scope, variant),
                "source_variant": variant,
                "payload_sha256": payload_sha256,
                "payload_bytes": payload_bytes,
                "source_ingested_at": ingested_at,
                "audited_at": audited_at,
            }
        )

    for row in schedule.iter_rows(named=True):
        add(
            "schedule",
            str(row["game_id"]),
            row.get("raw_json"),
            "stats_schedule_v2",
            row.get("ingested_at"),
        )
    for row in play_by_play.iter_rows(named=True):
        add(
            "play_by_play",
            str(row["game_id"]),
            row.get("pbp_json"),
            str(row.get("source") or "unknown"),
            row.get("ingested_at"),
        )
    for row in boxscores.iter_rows(named=True):
        game_id = str(row["game_id"])
        add(
            "boxscore_traditional",
            game_id,
            row.get("traditional_json"),
            boxscore_variant(
                row.get("traditional_json"),
                row.get("traditional_source"),
                "boxScoreTraditional",
            ),
            row.get("ingested_at"),
        )
        add(
            "boxscore_advanced",
            game_id,
            row.get("advanced_json"),
            boxscore_variant(
                row.get("advanced_json"),
                row.get("advanced_source"),
                "boxScoreAdvanced",
            ),
            row.get("ingested_at"),
        )

    shot_payloads: dict[str, tuple[str, int, Any, Any]] = {}
    for row in shot_charts.iter_rows(named=True):
        game_id = str(row["game_id"])
        if game_id not in scope_by_game:
            continue
        payload_sha256, payload_bytes = _canonical_payload(row.get("shot_chart_json"))
        previous = shot_payloads.get(game_id)
        if previous and previous[:2] != (payload_sha256, payload_bytes):
            raise RuntimeError(
                "Summer League shot-chart fanout contains different payloads for "
                f"game {game_id}"
            )
        shot_payloads[game_id] = (
            payload_sha256,
            payload_bytes,
            row.get("ingested_at"),
            row.get("shot_chart_json"),
        )
    for game_id in sorted(shot_payloads):
        add(
            "shot_chart",
            game_id,
            shot_payloads[game_id][3],
            "stats_shot_chart_detail",
            shot_payloads[game_id][2],
        )

    entries.sort(key=lambda row: (row["game_id"], row["source_name"]))
    stable_rows = [
        {
            key: row[key]
            for key in (
                "source_name",
                "item_key",
                "game_id",
                "season",
                "competition",
                "source_locator",
                "source_variant",
                "payload_sha256",
                "payload_bytes",
            )
        }
        for row in entries
    ]
    manifest_bytes = json.dumps(
        stable_rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return entries, hashlib.sha256(manifest_bytes).hexdigest()


def _replace_source_manifest(entries: list[dict[str, Any]], game_ids: set[str]) -> None:
    if not entries:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ops.source_payload_manifest WHERE game_id = ANY(%s)",
                [sorted(game_ids)],
            )
    upsert_rows(
        "ops",
        "source_payload_manifest",
        entries,
        conflict_cols=["source_name", "item_key"],
    )


def run(**kwargs) -> dict[str, Any]:
    seasons = requested_or_default_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
    )
    competitions = normalize_competition_slugs(
        kwargs.get("competitions"),
        default=SUMMER_LEAGUE_SLUGS,
    )
    invalid = sorted(set(competitions) - set(SUMMER_LEAGUE_SLUGS))
    if invalid:
        raise ValueError(
            "Summer League quality gate received non-Summer competition(s): "
            + ", ".join(invalid)
        )

    schedule = read_table("bronze", "schedule")
    if schedule.is_empty():
        raise RuntimeError("Summer League quality gate: bronze.schedule is empty")
    schedule = schedule.filter(
        pl.col("season").is_in(seasons)
        & pl.col("competition").is_in(competitions)
    )
    requested_game_ids = {
        str(game_id) for game_id in (kwargs.get("game_ids") or [])
    }
    if requested_game_ids:
        schedule = schedule.filter(pl.col("game_id").is_in(requested_game_ids))
    if schedule.is_empty():
        raise RuntimeError(
            "Summer League quality gate: no schedule rows match the requested scope"
        )

    competition_counts = {
        str(row["competition"]): int(row["len"])
        for row in schedule.group_by("competition").len().iter_rows(named=True)
    }
    if not requested_game_ids:
        missing_competitions = [
            competition
            for competition in competitions
            if competition_counts.get(competition, 0) == 0
        ]
        if missing_competitions:
            raise RuntimeError(
                "Summer League quality gate: schedule missing competition(s): "
                + ", ".join(missing_competitions)
            )

    schedule_ids = _game_ids(schedule)
    completed_ids = _game_ids(schedule.filter(pl.col("game_status") == 3))

    silver_games = read_table("silver", "summer_league_games")
    _assert_coverage(
        "silver.summer_league_games",
        schedule_ids,
        _game_ids(silver_games),
    )

    semantic_reconciliation = {
        "games_checked": 0,
        "free_throw_mismatches": 0,
        "final_score_mismatches": 0,
    }
    manifest_entries: list[dict[str, Any]] = []
    manifest_sha256 = ""
    if completed_ids:
        bronze_boxscores = read_table("bronze", "boxscores")
        bronze_pbp = read_table("bronze", "play_by_play")
        bronze_shots = read_table("bronze", "shot_charts")
        _assert_coverage(
            "bronze.boxscores",
            completed_ids,
            _valid_payload_game_ids(
                bronze_boxscores,
                "traditional_json",
                lambda doc: bool(doc.get("boxScoreTraditional") or doc.get("game")),
            ),
        )
        _assert_coverage(
            "bronze.play_by_play",
            completed_ids,
            _valid_payload_game_ids(
                bronze_pbp,
                "pbp_json",
                lambda doc: bool(doc.get("game", {}).get("actions")),
            ),
        )
        _assert_coverage(
            "bronze.shot_charts",
            completed_ids,
            _valid_payload_game_ids(
                bronze_shots,
                "shot_chart_json",
                lambda doc: any(
                    result_set.get("name") == "Shot_Chart_Detail"
                    and bool(result_set.get("rowSet"))
                    for result_set in doc.get("resultSets", [])
                ),
            ),
        )
        _assert_coverage(
            "silver.summer_league_boxscores",
            completed_ids,
            _game_ids(read_table("silver", "summer_league_boxscores")),
        )
        _assert_coverage(
            "silver.summer_league_play_by_play",
            completed_ids,
            _game_ids(read_table("silver", "summer_league_play_by_play")),
        )
        _assert_coverage(
            "silver.summer_league_shots",
            completed_ids,
            _game_ids(read_table("silver", "summer_league_shots")),
        )
        semantic_reconciliation = _semantic_reconciliation(
            schedule,
            bronze_boxscores,
            bronze_pbp,
            completed_ids,
        )
        manifest_entries, manifest_sha256 = _payload_manifest(
            schedule,
            bronze_boxscores,
            bronze_pbp,
            bronze_shots,
        )
        required_sources = {
            "schedule",
            "boxscore_traditional",
            "play_by_play",
            "shot_chart",
        }
        sources_by_game: dict[str, set[str]] = {
            game_id: set() for game_id in completed_ids
        }
        for row in manifest_entries:
            if row["game_id"] in sources_by_game:
                sources_by_game[row["game_id"]].add(row["source_name"])
        incomplete_manifest_games = {
            game_id: sorted(required_sources - sources)
            for game_id, sources in sources_by_game.items()
            if not required_sources.issubset(sources)
        }
        if incomplete_manifest_games:
            raise RuntimeError(
                "Summer League source manifest is incomplete for "
                f"{len(incomplete_manifest_games)} game(s): "
                f"{json.dumps(dict(list(sorted(incomplete_manifest_games.items()))[:10]))}"
            )
        if kwargs.get("persist_manifest", True):
            _replace_source_manifest(manifest_entries, schedule_ids)

    return {
        "status": "success",
        "seasons": seasons,
        "competitions": competitions,
        "competition_counts": competition_counts,
        "schedule_games": len(schedule_ids),
        "completed_games": len(completed_ids),
        "semantic_reconciliation": semantic_reconciliation,
        "source_manifest": {
            "rows": len(manifest_entries),
            "sha256": manifest_sha256,
            "required_sources_per_completed_game": 4,
        },
    }


TASK_DEF = {
    "layer": "quality",
    "task_type": "quality",
    "inputs": (
        "bronze.schedule",
        "bronze.boxscores",
        "bronze.play_by_play",
        "bronze.shot_charts",
        "silver.summer_league_games",
        "silver.summer_league_boxscores",
        "silver.summer_league_play_by_play",
        "silver.summer_league_shots",
    ),
    "optional_inputs": (),
    "outputs": (),
    "mutates": (),
    "graphs": ("summer_league",),
    "modes": ("live",),
    "required": True,
    "quality_outputs": (),
    "regular_season_only": False,
    "live_order": 200,
}

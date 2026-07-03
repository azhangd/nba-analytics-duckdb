"""Pure transforms for game-detail team stats."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nba_duckdb.transforms.silver._parsing import load_json

FCT_GAME_DETAIL = (
    "game_id",
    "team_id",
    "team_abbreviation",
    "pts_off_tov",
    "pts_2nd_chance",
    "pts_fb",
    "pts_paint",
    "opp_pts_off_tov",
    "opp_pts_2nd_chance",
    "opp_pts_fb",
    "opp_pts_paint",
)


def safe(value: Any, typ: type = float) -> Any:
    if value is None:
        return None
    try:
        return typ(value)
    except (ValueError, TypeError):
        return None


def parse_team_rows(raw: dict[str, Any], game_id: str) -> list[dict[str, Any]]:
    """Parse team-level misc stats from either legacy V2 or V3 payloads."""
    boxscore = raw.get("boxScoreMisc", {})
    if boxscore:
        rows = []
        for team_key in ("homeTeam", "awayTeam"):
            team = boxscore.get(team_key, {})
            stats = team.get("statistics", {})
            team_id = safe(team.get("teamId"), int)
            if not team_id:
                continue
            rows.append({
                "game_id": game_id,
                "team_id": team_id,
                "team_abbreviation": team.get("teamTricode", ""),
                "pts_off_tov": safe(stats.get("pointsOffTurnovers"), int),
                "pts_2nd_chance": safe(stats.get("pointsSecondChance"), int),
                "pts_fb": safe(stats.get("pointsFastBreak"), int),
                "pts_paint": safe(stats.get("pointsPaint"), int),
                "opp_pts_off_tov": safe(stats.get("oppPointsOffTurnovers"), int),
                "opp_pts_2nd_chance": safe(stats.get("oppPointsSecondChance"), int),
                "opp_pts_fb": safe(stats.get("oppPointsFastBreak"), int),
                "opp_pts_paint": safe(stats.get("oppPointsPaint"), int),
            })
        return rows

    rows = []
    result_sets = raw.get("resultSets")
    if not isinstance(result_sets, list):
        singular = raw.get("resultSet")
        if isinstance(singular, dict):
            result_sets = [singular]
        elif isinstance(singular, list):
            result_sets = singular
        else:
            result_sets = []
    for rs in result_sets:
        if rs.get("name", "").startswith("sqlTeam"):
            headers = [h.lower() for h in rs.get("headers", [])]
            for row in rs.get("rowSet", []):
                parsed = dict(zip(headers, row, strict=False))
                team_id = safe(parsed.get("team_id"), int)
                if not team_id:
                    continue
                rows.append({
                    "game_id": game_id,
                    "team_id": team_id,
                    "team_abbreviation": parsed.get("team_abbreviation", ""),
                    "pts_off_tov": safe(parsed.get("pts_off_tov"), int),
                    "pts_2nd_chance": safe(parsed.get("pts_2nd_chance"), int),
                    "pts_fb": safe(parsed.get("pts_fb"), int),
                    "pts_paint": safe(parsed.get("pts_paint"), int),
                    "opp_pts_off_tov": safe(parsed.get("opp_pts_off_tov"), int),
                    "opp_pts_2nd_chance": safe(parsed.get("opp_pts_2nd_chance"), int),
                    "opp_pts_fb": safe(parsed.get("opp_pts_fb"), int),
                    "opp_pts_paint": safe(parsed.get("opp_pts_paint"), int),
                })
    return rows


def build_fct_game_detail_rows(game_detail_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in game_detail_rows:
        detail = load_json(row.get("detail_json"))
        misc = detail.get("misc", detail)
        rows.extend(parse_team_rows(misc, str(row.get("game_id") or "")))
    return rows

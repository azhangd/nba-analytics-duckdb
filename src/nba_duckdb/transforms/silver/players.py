"""Pure transforms for player dimensions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

DIM_PLAYERS = (
    "player_id",
    "full_name",
    "jersey_number",
    "position",
    "height_inches",
    "weight_lbs",
    "birth_date",
    "experience",
    "current_team_id",
    "season",
    "is_active",
)


def parse_height_inches(height: object) -> int:
    height_str = str(height or "")
    if not height_str or "-" not in height_str:
        return 0
    parts = height_str.split("-")
    try:
        return int(parts[0]) * 12 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def parse_weight_lbs(weight: object) -> int:
    weight_str = str(weight or "")
    return int(weight_str) if weight_str.isdigit() else 0


def build_dim_player_rows(
    roster_rows: list[Mapping[str, Any]],
    boxscore_rows: list[Mapping[str, Any]],
    *,
    default_season: str = "2025-26",
) -> list[dict]:
    seen = {}
    for row in roster_rows:
        seen[row["player_id"]] = {
            "player_id": int(row["player_id"]),
            "full_name": row["player_name"],
            "jersey_number": row["jersey_number"],
            "position": row["position"],
            "height_inches": parse_height_inches(row.get("height")),
            "weight_lbs": parse_weight_lbs(row.get("weight")),
            "birth_date": row.get("birth_date") or "",
            "experience": row.get("experience") or "",
            "current_team_id": int(row["team_id"]),
            "season": row["season"],
            "is_active": True,
        }

    for row in boxscore_rows:
        traditional = row["traditional_json"]
        if isinstance(traditional, str):
            traditional = json.loads(traditional)
        game = traditional.get("game") or traditional.get("boxScoreTraditional") or {}
        for team_key in ("homeTeam", "awayTeam"):
            team = game.get(team_key, {}) or {}
            team_id = team.get("teamId")
            boxscore_season = row.get("season") or default_season
            for player in team.get("players", []):
                player_id = player.get("personId")
                if not player_id:
                    continue
                first_name = (player.get("firstName") or "").strip()
                family_name = (player.get("familyName") or "").strip()
                full_name = f"{first_name} {family_name}".strip() or player.get("nameI", "").strip()
                current = seen.get(player_id, {})
                seen[player_id] = {
                    "player_id": int(player_id),
                    "full_name": full_name or current.get("full_name", ""),
                    "jersey_number": player.get("jerseyNum") or current.get("jersey_number", ""),
                    "position": player.get("position") or current.get("position", ""),
                    "height_inches": current.get("height_inches", 0),
                    "weight_lbs": current.get("weight_lbs", 0),
                    "birth_date": current.get("birth_date", ""),
                    "experience": current.get("experience", ""),
                    "current_team_id": int(team_id) if team_id else current.get("current_team_id", 0),
                    "season": current.get("season", boxscore_season),
                    "is_active": current.get("is_active", True),
                }
    return list(seen.values())

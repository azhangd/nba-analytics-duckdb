"""Pure transforms for player dimensions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from nba_duckdb.defaults import get_default_season

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


def _game_day(game_date: object) -> datetime:
    return datetime.strptime(str(game_date), "%m/%d/%Y %H:%M:%S")


def build_dim_player_rows(
    roster_rows: list[Mapping[str, Any]],
    boxscore_rows: list[Mapping[str, Any]],
) -> list[dict]:
    """One row per player.

    Roster fields win. Rosters are never pruned, so a traded player can have rows
    for an old team; the most recently refreshed row (season, then ingested_at)
    is the current one. Players on no roster take their team, name and jersey from
    their latest game. Box-score position is the slot a starter played, not the
    player's position, so it is never used.
    """
    default_season = get_default_season()
    seen = {}
    for row in sorted(roster_rows, key=lambda r: (str(r["season"]), str(r.get("ingested_at") or ""))):
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
    on_roster = set(seen)

    for row in sorted(boxscore_rows, key=lambda r: _game_day(r["game_date"])):
        traditional = row["traditional_json"]
        if isinstance(traditional, str):
            traditional = json.loads(traditional)
        game = traditional.get("game") or traditional.get("boxScoreTraditional") or {}
        for team_key in ("homeTeam", "awayTeam"):
            team = game.get(team_key, {}) or {}
            team_id = team.get("teamId")
            for player in team.get("players", []):
                player_id = player.get("personId")
                if not player_id or player_id in on_roster:
                    continue
                first_name = (player.get("firstName") or "").strip()
                family_name = (player.get("familyName") or "").strip()
                full_name = f"{first_name} {family_name}".strip() or player.get("nameI", "").strip()
                seen[player_id] = {
                    "player_id": int(player_id),
                    "full_name": full_name,
                    "jersey_number": player.get("jerseyNum") or "",
                    "position": "",
                    "height_inches": 0,
                    "weight_lbs": 0,
                    "birth_date": "",
                    "experience": "",
                    "current_team_id": int(team_id) if team_id else 0,
                    "season": row.get("season") or default_season,
                    "is_active": True,
                }
    return list(seen.values())

"""Pure transforms for bronze NBA play-by-play payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

FCT_PLAY_BY_PLAY = (
    "game_id",
    "action_id",
    "action_number",
    "period",
    "clock",
    "clock_seconds_remaining",
    "team_id",
    "player_id",
    "player_name",
    "action_type",
    "sub_type",
    "description",
    "score_home",
    "score_away",
    "shot_result",
    "is_field_goal",
    "pbp_source",
    "loc_x",
    "loc_y",
)


def parse_clock_seconds(clock: object) -> float:
    clock_value = str(clock)
    if "PT" in clock_value:
        match = re.search(r"PT(\d+)M([\d.]+)S", clock_value)
        if match:
            return float(match.group(1)) * 60 + float(match.group(2))
    elif ":" in clock_value:
        parts = clock_value.split(":")
        try:
            return float(parts[0]) * 60 + float(parts[1])
        except (ValueError, IndexError):
            pass
    return 0.0


def build_fct_play_by_play_rows(bronze_rows: list[Mapping[str, Any]]) -> list[dict]:
    output = []
    for bronze_row in bronze_rows:
        game_id = str(bronze_row["game_id"])
        pbp_source = str(bronze_row.get("source") or "unknown")
        raw = bronze_row["pbp_json"]
        if isinstance(raw, str):
            raw = json.loads(raw)

        for action in raw.get("game", {}).get("actions", []):
            loc_x = action.get("x") if pbp_source != "stats_v3" else None
            loc_y = action.get("y") if pbp_source != "stats_v3" else None
            team_id = action.get("teamId")
            player_id = action.get("personId")
            action_id = action.get("actionId")
            if action_id is None:
                action_id = action.get("orderNumber")
            output.append({
                "game_id": game_id,
                "action_id": int(action_id) if action_id is not None else None,
                "action_number": int(action.get("actionNumber") or 0),
                "period": int(action.get("period") or 0),
                "clock": str(action.get("clock", "")),
                "clock_seconds_remaining": parse_clock_seconds(action.get("clock", "")),
                "team_id": int(team_id) if team_id else None,
                "player_id": int(player_id) if player_id else None,
                "player_name": str(action.get("playerNameI", "")),
                "action_type": str(action.get("actionType", "")),
                "sub_type": str(action.get("subType", "")),
                "description": str(action.get("description", "")),
                "score_home": str(action.get("scoreHome", "")),
                "score_away": str(action.get("scoreAway", "")),
                "shot_result": str(action.get("shotResult", "")),
                "is_field_goal": action.get("isFieldGoal", 0) == 1,
                "pbp_source": pbp_source,
                "loc_x": float(loc_x) if loc_x is not None else None,
                "loc_y": float(loc_y) if loc_y is not None else None,
            })
    return output

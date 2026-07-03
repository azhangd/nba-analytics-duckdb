"""Pure transforms for bronze shot-chart payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

PULL_UP_KEYWORDS = ("pullup", "pull-up", "step back", "turnaround", "fadeaway", "fade away")
OFF_DRIBBLE_KEYWORDS = ("driving", "dunk", "layup", "tip", "floating", "running", "reverse", "alley")

FCT_SHOTS = (
    "game_id",
    "player_id",
    "player_name",
    "team_id",
    "period",
    "minutes_remaining",
    "seconds_remaining",
    "action_type",
    "shot_type",
    "shot_zone_basic",
    "shot_zone_area",
    "shot_zone_range",
    "shot_distance_ft",
    "loc_x",
    "loc_y",
    "shot_made",
    "game_date",
    "season",
    "shot_context",
)


def safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def shot_context(action_type: str) -> str:
    value = action_type.lower()
    if any(keyword in value for keyword in PULL_UP_KEYWORDS):
        return "pull_up"
    if any(keyword in value for keyword in OFF_DRIBBLE_KEYWORDS):
        return "off_dribble"
    if "jump shot" in value:
        return "catch_and_shoot"
    return "other"


def season_from_game_date(game_date: str) -> str:
    if not game_date:
        return ""
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(game_date, fmt)
            start_year = parsed.year if parsed.month >= 10 else parsed.year - 1
            return f"{start_year}-{str(start_year + 1)[-2:]}"
        except ValueError:
            continue
    return ""


def build_fct_shot_rows(bronze_rows: list[Mapping[str, Any]]) -> list[dict]:
    output = []
    for bronze_row in bronze_rows:
        game_id = str(bronze_row["game_id"])
        bronze_team_id = safe_int(bronze_row.get("team_id"))
        raw = bronze_row["shot_chart_json"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        for result_set in raw.get("resultSets", []):
            if result_set.get("name") != "Shot_Chart_Detail":
                continue
            headers = result_set.get("headers", [])
            for raw_row in result_set.get("rowSet", []):
                shot = dict(zip(headers, raw_row, strict=False))
                shot_team_id = safe_int(shot.get("TEAM_ID"))
                if bronze_team_id is not None and shot_team_id is not None and shot_team_id != bronze_team_id:
                    continue
                action = shot.get("ACTION_TYPE", "")
                output.append({
                    "game_id": game_id,
                    "player_id": safe_int(shot.get("PLAYER_ID")),
                    "player_name": shot.get("PLAYER_NAME", ""),
                    "team_id": shot_team_id,
                    "period": safe_int(shot.get("PERIOD")),
                    "minutes_remaining": safe_int(shot.get("MINUTES_REMAINING")),
                    "seconds_remaining": safe_int(shot.get("SECONDS_REMAINING")),
                    "action_type": action,
                    "shot_type": shot.get("SHOT_TYPE", ""),
                    "shot_zone_basic": shot.get("SHOT_ZONE_BASIC", ""),
                    "shot_zone_area": shot.get("SHOT_ZONE_AREA", ""),
                    "shot_zone_range": shot.get("SHOT_ZONE_RANGE", ""),
                    "shot_distance_ft": safe_int(shot.get("SHOT_DISTANCE")),
                    "loc_x": safe_int(shot.get("LOC_X")),
                    "loc_y": safe_int(shot.get("LOC_Y")),
                    "shot_made": shot.get("SHOT_MADE_FLAG") == 1,
                    "game_date": shot.get("GAME_DATE", ""),
                    "season": season_from_game_date(shot.get("GAME_DATE", "")),
                    "shot_context": shot_context(action),
                })
    return output

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


# Team ids are 10 digits (1610612737); player ids are far smaller. stats_v3 puts the
# team id in personId for team rebounds, turnovers and timeouts.
_MIN_TEAM_ID = 1_000_000_000


def _action_order(action: Mapping[str, Any]) -> int:
    # stats_v3 has a unique actionId; the live CDN feed's event order is orderNumber.
    value = action.get("actionId")
    if value is None:
        value = action.get("orderNumber")
    return int(value)


def _v3_action(action: Mapping[str, Any]) -> tuple[str, str, str]:
    """Map a stats_v3 action to the live CDN vocabulary: (action_type, sub_type, shot_result)."""
    action_type = str(action.get("actionType", ""))
    sub_type = str(action.get("subType", ""))
    shot_result = str(action.get("shotResult", ""))
    description = str(action.get("description", ""))
    if action_type in ("Made Shot", "Missed Shot"):
        return ("3pt" if action.get("shotValue") == 3 else "2pt"), sub_type, shot_result
    if action_type == "Free Throw":
        result = "Missed" if description.upper().startswith("MISS") else "Made"
        return "freethrow", sub_type.removeprefix("Free Throw ").strip(), result
    if action_type == "":
        upper = description.upper()
        if " STEAL " in f" {upper} ":
            return "steal", sub_type, shot_result
        if " BLOCK " in f" {upper} ":
            return "block", sub_type, shot_result
    return action_type.lower().replace(" ", ""), sub_type, shot_result


def build_fct_play_by_play_rows(bronze_rows: list[Mapping[str, Any]]) -> list[dict]:
    """One row per action, in event order, with both sources in the live CDN vocabulary.

    stats_v3 only reports the score on scoring plays, so the score is carried forward:
    every row holds the score at that moment.
    """
    output = []
    for bronze_row in bronze_rows:
        game_id = str(bronze_row["game_id"])
        pbp_source = str(bronze_row.get("source") or "unknown")
        raw = bronze_row["pbp_json"]
        if isinstance(raw, str):
            raw = json.loads(raw)

        actions = sorted(
            raw.get("game", {}).get("actions", []),
            key=lambda action: (int(action.get("period") or 0), _action_order(action)),
        )
        score_home, score_away = "0", "0"
        for action in actions:
            loc_x = action.get("x") if pbp_source != "stats_v3" else None
            loc_y = action.get("y") if pbp_source != "stats_v3" else None
            team_id = action.get("teamId")
            player_id = action.get("personId")
            if not team_id and player_id and int(player_id) >= _MIN_TEAM_ID:
                team_id, player_id = player_id, None
            if pbp_source == "stats_v3":
                action_type, sub_type, shot_result = _v3_action(action)
            else:
                action_type = str(action.get("actionType", ""))
                sub_type = str(action.get("subType", ""))
                shot_result = str(action.get("shotResult", ""))
            if str(action.get("scoreHome", "")).strip() and str(action.get("scoreAway", "")).strip():
                score_home = str(action["scoreHome"]).strip()
                score_away = str(action["scoreAway"]).strip()
            output.append({
                "game_id": game_id,
                "action_id": _action_order(action),
                "action_number": int(action.get("actionNumber") or 0),
                "period": int(action.get("period") or 0),
                "clock": str(action.get("clock", "")),
                "clock_seconds_remaining": parse_clock_seconds(action.get("clock", "")),
                "team_id": int(team_id) if team_id else None,
                "player_id": int(player_id) if player_id else None,
                "player_name": str(action.get("playerNameI", "")),
                "action_type": action_type,
                "sub_type": sub_type,
                "description": str(action.get("description", "")),
                "score_home": score_home,
                "score_away": score_away,
                "shot_result": shot_result,
                "is_field_goal": action.get("isFieldGoal", 0) == 1,
                "pbp_source": pbp_source,
                "loc_x": float(loc_x) if loc_x is not None else None,
                "loc_y": float(loc_y) if loc_y is not None else None,
            })
    return output

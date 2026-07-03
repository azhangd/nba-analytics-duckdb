"""Pure transforms for bronze NBA boxscore payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

FCT_BOXSCORES = (
    "game_id",
    "player_id",
    "team_id",
    "player_name",
    "started",
    "counts_as_gp",
    "minutes",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
    "oreb",
    "dreb",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "pts",
    "plus_minus",
    "off_rating",
    "def_rating",
    "net_rating",
    "usg_pct",
    "ts_pct",
    "pace",
)


def safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_minutes(minutes_raw: object) -> float:
    """Parse NBA minutes strings like ``31:55`` or ``PT31M55.00S``."""
    if not minutes_raw:
        return 0.0
    value = str(minutes_raw)
    if "PT" in value:
        match = re.search(r"PT(\d+)M([\d.]+)S", value)
        if match:
            return float(match.group(1)) + float(match.group(2)) / 60
    elif ":" in value:
        parts = value.split(":")
        try:
            return float(parts[0]) + float(parts[1]) / 60
        except (ValueError, IndexError):
            pass
    try:
        return float(value)
    except ValueError:
        return 0.0


def counts_as_game_played(player: Mapping[str, Any]) -> bool:
    stats = player.get("statistics", {})
    minutes_raw = stats.get("minutes") if isinstance(stats, Mapping) else None
    if minutes_raw is None or player.get("comment"):
        return False
    played = player.get("played")
    if played is not None:
        return str(played).strip().lower() in {"1", "true", "t", "yes", "y"} and bool(
            str(minutes_raw).strip()
        )
    if player.get("notPlayingReason") or player.get("notWithTeamReason"):
        return False
    status = str(player.get("status") or "").strip().upper()
    if status in {"INACTIVE", "DNP", "NOT_WITH_TEAM"}:
        return False
    return bool(str(minutes_raw).strip())


def derive_true_shooting_pct(stats: Mapping[str, Any]) -> float | None:
    pts = safe_float(stats.get("points"))
    fga = safe_float(stats.get("fieldGoalsAttempted"))
    fta = safe_float(stats.get("freeThrowsAttempted"))
    if pts is None or fga is None or fta is None:
        return None
    attempts = fga + (0.44 * fta)
    if attempts <= 0:
        return None
    return round(pts / (2 * attempts), 3)


def extract_players(team: Mapping[str, Any], game_id: str, adv_lookup: Mapping[int, Mapping[str, Any]]) -> list[dict]:
    team_id = team.get("teamId", 0)
    players = team.get("players", [])
    starters = {
        player.get("personId")
        for player in players
        if str(player.get("starter", "")).strip() in {"1", "true", "True"}
    }

    if not starters:
        raw_starters = team.get("starters", [])
        if isinstance(raw_starters, list):
            for starter in raw_starters:
                starters.add(starter.get("personId") if isinstance(starter, dict) else starter)

    if not starters and players:
        for index, player in enumerate(players):
            if index < 5:
                starters.add(player.get("personId", 0))

    rows = []
    for player in players:
        player_id = player.get("personId", 0)
        stats = player.get("statistics", {})
        adv = adv_lookup.get(player_id, {})
        ts_pct = safe_float(adv.get("trueShootingPercentage"))
        if ts_pct is None:
            ts_pct = derive_true_shooting_pct(stats)
        first_name = (player.get("firstName") or "").strip()
        family_name = (player.get("familyName") or "").strip()
        full_name = f"{first_name} {family_name}".strip()

        rows.append({
            "game_id": game_id,
            "player_id": safe_int(player_id),
            "team_id": safe_int(team_id),
            "player_name": full_name or player.get("nameI", "").strip(),
            "started": player_id in starters,
            "counts_as_gp": counts_as_game_played(player),
            "minutes": parse_minutes(stats.get("minutes")),
            "fgm": safe_int(stats.get("fieldGoalsMade")),
            "fga": safe_int(stats.get("fieldGoalsAttempted")),
            "fg3m": safe_int(stats.get("threePointersMade")),
            "fg3a": safe_int(stats.get("threePointersAttempted")),
            "ftm": safe_int(stats.get("freeThrowsMade")),
            "fta": safe_int(stats.get("freeThrowsAttempted")),
            "oreb": safe_int(stats.get("reboundsOffensive")),
            "dreb": safe_int(stats.get("reboundsDefensive")),
            "reb": safe_int(stats.get("reboundsTotal")),
            "ast": safe_int(stats.get("assists")),
            "stl": safe_int(stats.get("steals")),
            "blk": safe_int(stats.get("blocks")),
            "tov": safe_int(stats.get("turnovers")),
            "pf": safe_int(stats.get("foulsPersonal")),
            "pts": safe_int(stats.get("points")),
            "plus_minus": safe_int(stats.get("plusMinusPoints")),
            "off_rating": safe_float(adv.get("offensiveRating")),
            "def_rating": safe_float(adv.get("defensiveRating")),
            "net_rating": safe_float(adv.get("netRating")),
            "usg_pct": safe_float(adv.get("usagePercentage")),
            "ts_pct": ts_pct,
            "pace": safe_float(adv.get("estimatedPace", adv.get("pace"))),
        })
    return rows


def build_fct_boxscore_rows(bronze_rows: list[Mapping[str, Any]]) -> list[dict]:
    output = []
    for bronze_row in bronze_rows:
        game_id = str(bronze_row["game_id"])
        traditional = bronze_row["traditional_json"]
        if isinstance(traditional, str):
            traditional = json.loads(traditional)
        advanced = bronze_row["advanced_json"]
        if isinstance(advanced, str):
            advanced = json.loads(advanced)
        elif advanced is None:
            advanced = {}

        boxscore = traditional.get("game") or traditional.get("boxScoreTraditional")
        if not boxscore:
            continue

        advanced_payload = advanced.get("boxScoreAdvanced", {})
        adv_lookup = {}
        for team_key in ("homeTeam", "awayTeam"):
            for player in advanced_payload.get(team_key, {}).get("players", []):
                adv_lookup[player.get("personId")] = player.get("statistics", {})

        for team_key in ("homeTeam", "awayTeam"):
            output.extend(extract_players(boxscore.get(team_key, {}), game_id, adv_lookup))
    return output

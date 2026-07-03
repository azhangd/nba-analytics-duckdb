"""Pure transforms for optional NBA enrichment payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from nba_duckdb.transforms.silver._parsing import load_json, parse_minutes, result_rows

FCT_HUSTLE = (
    "season",
    "player_id",
    "player_name",
    "team_id",
    "minutes",
    "contested_shots",
    "contested_shots_2pt",
    "contested_shots_3pt",
    "deflections",
    "charges_drawn",
    "screen_assists",
    "screen_ast_pts",
    "off_loose_balls_recovered",
    "def_loose_balls_recovered",
    "loose_balls_recovered",
    "off_boxouts",
    "def_boxouts",
    "box_outs",
)

FCT_TRACKING = ("season", "category", "player_id", "player_name", "team_id", "gp", "stats")

FCT_MATCHUPS = (
    "season",
    "off_player_id",
    "off_player_name",
    "def_player_id",
    "def_player_name",
    "off_team_id",
    "def_team_id",
    "matchup_min",
    "partial_poss",
    "player_pts",
    "matchup_fgm",
    "matchup_fga",
    "matchup_fg_pct",
    "matchup_fg3m",
    "matchup_fg3a",
)

FCT_DEFENSE_PLAY_TYPES = (
    "season",
    "player_or_team",
    "type_grouping",
    "play_type",
    "player_id",
    "player_name",
    "team_id",
    "team_abbreviation",
    "gp",
    "poss",
    "pts",
    "ppp",
    "sfpct",
    "fgpct",
    "ft_pct",
    "to_pct",
    "score_pct",
    "freq_pct",
    "percentile",
)


def build_fct_hustle_rows(hustle_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in hustle_rows:
        if row.get("level") and row["level"] != "player":
            continue
        raw = load_json(row.get("hustle_json"))
        for parsed in result_rows(raw):
            if not parsed.get("player_id"):
                continue
            rows.append({
                "season": row.get("season"),
                "player_id": parsed.get("player_id"),
                "player_name": parsed.get("player_name", ""),
                "team_id": parsed.get("team_id"),
                "minutes": parsed.get("min"),
                "contested_shots": parsed.get("contested_shots"),
                "contested_shots_2pt": parsed.get("contested_shots_2pt"),
                "contested_shots_3pt": parsed.get("contested_shots_3pt"),
                "deflections": parsed.get("deflections"),
                "charges_drawn": parsed.get("charges_drawn"),
                "screen_assists": parsed.get("screen_assists"),
                "screen_ast_pts": parsed.get("screen_ast_pts"),
                "off_loose_balls_recovered": parsed.get("off_loose_balls_recovered"),
                "def_loose_balls_recovered": parsed.get("def_loose_balls_recovered"),
                "loose_balls_recovered": parsed.get("loose_balls_recovered"),
                "off_boxouts": parsed.get("off_boxouts"),
                "def_boxouts": parsed.get("def_boxouts"),
                "box_outs": parsed.get("box_outs"),
            })
    return rows


def build_fct_tracking_rows(tracking_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in tracking_rows:
        if row.get("level") and row["level"] != "player":
            continue
        category = row.get("category")
        raw = load_json(row.get("tracking_json"))
        for parsed in result_rows(raw):
            player_id = parsed.pop("player_id", None)
            player_name = parsed.pop("player_name", "")
            team_id = parsed.pop("team_id", None)
            gp = parsed.pop("gp", None)
            for key in ("player_name_last_first", "team_abbreviation", "age"):
                parsed.pop(key, None)
            rows.append({
                "season": row.get("season"),
                "category": category,
                "player_id": player_id,
                "player_name": player_name,
                "team_id": team_id,
                "gp": gp,
                "stats": json.dumps(parsed, sort_keys=True),
            })
    return rows


def build_fct_matchup_rows(matchup_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in matchup_rows:
        raw = load_json(row.get("matchup_json"))
        for parsed in result_rows(raw):
            rows.append({
                "season": row.get("season"),
                "off_player_id": parsed.get("off_player_id"),
                "off_player_name": parsed.get("off_player_name", ""),
                "def_player_id": parsed.get("def_player_id"),
                "def_player_name": parsed.get("def_player_name", ""),
                "off_team_id": parsed.get("off_team_id"),
                "def_team_id": parsed.get("def_team_id"),
                "matchup_min": parse_minutes(parsed.get("matchup_min")),
                "partial_poss": parsed.get("partial_poss"),
                "player_pts": parsed.get("player_pts"),
                "matchup_fgm": parsed.get("matchup_fgm"),
                "matchup_fga": parsed.get("matchup_fga"),
                "matchup_fg_pct": parsed.get("matchup_fg_pct"),
                "matchup_fg3m": parsed.get("matchup_fg3m"),
                "matchup_fg3a": parsed.get("matchup_fg3a"),
            })
    return rows


def build_fct_defense_play_type_rows(defense_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in defense_rows:
        raw = load_json(row.get("defense_json"))
        player_or_team = row.get("player_or_team")
        for parsed in result_rows(raw):
            player_id = parsed.get("player_id")
            team_id = parsed.get("team_id")
            if player_or_team == "P" and not player_id:
                continue
            if player_or_team == "T" and not team_id:
                continue
            rows.append({
                "season": row.get("season"),
                "player_or_team": player_or_team,
                "type_grouping": row.get("type_grouping"),
                "play_type": row.get("play_type"),
                "player_id": player_id,
                "player_name": parsed.get("player_name") or parsed.get("team_name") or "",
                "team_id": team_id,
                "team_abbreviation": parsed.get("team_abbreviation", ""),
                "gp": parsed.get("gp"),
                "poss": parsed.get("poss"),
                "pts": parsed.get("pts"),
                "ppp": parsed.get("ppp"),
                "sfpct": parsed.get("sf_pct"),
                "fgpct": parsed.get("fg_pct"),
                "ft_pct": parsed.get("ft_poss_pct"),
                "to_pct": parsed.get("to_poss_pct"),
                "score_pct": parsed.get("score_pct"),
                "freq_pct": parsed.get("poss_pct"),
                "percentile": parsed.get("percentile"),
            })
    return rows

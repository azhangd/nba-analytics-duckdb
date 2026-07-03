"""Pure transforms for injury report dimensions."""

from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

from nba_duckdb.transforms.silver._parsing import load_json

DIM_INJURIES = (
    "athlete_espn_id",
    "athlete_name",
    "player_id",
    "team_id",
    "team_abbr",
    "position",
    "status",
    "injury_type",
    "injury_detail",
    "injury_side",
    "return_date",
    "report_date",
    "updated_at",
)


def parse_injury_reason(reason: str) -> tuple[str, str, str]:
    injury_type, injury_detail, injury_side = "", "", ""
    if reason.startswith("Injury/Illness-"):
        body_and_detail = reason[len("Injury/Illness-"):]
        if ";" in body_and_detail:
            body_part, injury_detail = body_and_detail.split(";", 1)
            injury_detail = injury_detail.strip()
        else:
            body_part = body_and_detail
        for side in ("Right", "Left", "Bilateral"):
            if body_part.startswith(side):
                injury_side = side
                body_part = body_part[len(side):]
                break
        injury_type = body_part.strip()
    else:
        injury_type = reason
    return injury_type.strip(), injury_detail.strip(), injury_side


def build_dim_injury_rows(
    injuries: pl.DataFrame,
    teams: pl.DataFrame,
    players: pl.DataFrame,
    *,
    updated_at: str | None = None,
) -> list[dict]:
    if injuries.is_empty():
        return []
    row = injuries.sort("fetched_date", descending=True).row(0, named=True)
    raw = load_json(row.get("injuries_json"))
    report_date = row.get("fetched_date")
    team_lookup = {
        str(item["abbreviation"]): item["team_id"]
        for item in teams.iter_rows(named=True)
        if item.get("abbreviation")
    }
    player_lookup = {
        str(item["full_name"]).lower(): item["player_id"]
        for item in players.iter_rows(named=True)
        if item.get("full_name")
    }
    timestamp = updated_at or datetime.now(timezone.utc).isoformat()
    seen = set()
    output = []
    for raw_row in raw.get("rows", []):
        player_name = str(raw_row.get("player_name") or "").strip()
        team_abbr = str(raw_row.get("team_abbr") or "").strip()
        if not player_name or not team_abbr:
            continue
        key = (player_name.lower(), team_abbr)
        if key in seen:
            continue
        seen.add(key)
        if "," in player_name:
            last, first = player_name.split(",", 1)
            display_name = f"{first.strip()} {last.strip()}"
        else:
            display_name = player_name
        injury_type, injury_detail, injury_side = parse_injury_reason(str(raw_row.get("reason") or ""))
        output.append({
            "athlete_espn_id": f"{player_name.lower().replace(' ', '_')}_{team_abbr.lower()}",
            "athlete_name": display_name,
            "player_id": player_lookup.get(display_name.lower()),
            "team_id": team_lookup.get(team_abbr),
            "team_abbr": team_abbr,
            "position": None,
            "status": raw_row.get("status", ""),
            "injury_type": injury_type,
            "injury_detail": injury_detail,
            "injury_side": injury_side,
            "return_date": None,
            "report_date": report_date,
            "updated_at": timestamp,
        })
    return output

"""Shared parsing helpers for silver transforms."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import polars as pl


def load_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def result_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for result_set in raw.get("resultSets", []):
        headers = [str(header).lower() for header in result_set.get("headers", [])]
        for raw_row in result_set.get("rowSet", []):
            rows.append(dict(zip(headers, raw_row, strict=False)))
    return rows


def parse_minutes(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        parts = str(value).split(":")
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFD", name or "")
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower().replace(".", "").strip()


def title_from_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    return cleaned.replace(" ", "_")


def build_roster_name_map(boxscores_df: pl.DataFrame) -> dict[int, dict[str, int]]:
    roster_name_map: dict[int, dict[str, int]] = {}
    for row in boxscores_df.iter_rows(named=True):
        team_id = row.get("team_id")
        player_id = row.get("player_id")
        player_name = str(row.get("player_name") or "").strip()
        if not team_id or not player_id or not player_name:
            continue
        team_names = roster_name_map.setdefault(int(team_id), {})
        full_norm = normalize_name(player_name)
        if full_norm:
            team_names[full_norm] = int(player_id)
        parts = [part for part in player_name.split() if part]
        if parts:
            team_names[normalize_name(parts[-1])] = int(player_id)
            if len(parts) >= 2:
                team_names[normalize_name(" ".join(parts[-2:]))] = int(player_id)
    return roster_name_map

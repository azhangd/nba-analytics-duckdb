"""Pure transform for gold.player_combo_season_stats."""

from __future__ import annotations

import itertools
import re

import polars as pl

PLAYER_COMBO_SEASON_STATS = (
    "team_id",
    "season",
    "combo_type",
    "player_ids",
    "player_names",
    "stints",
    "total_minutes",
    "pts_for",
    "pts_against",
    "net_points",
    "net_rating_per_48",
)


def _canonical_player_ids(value: object) -> str:
    tokens = [token for token in re.split(r"[-,]", str(value or "").strip("-,")) if token]
    return ",".join(sorted(tokens, key=int))


def _player_map(dim_players: pl.DataFrame, boxscores: pl.DataFrame) -> dict[str, str]:
    names: dict[str, str] = {}
    if not boxscores.is_empty() and {"player_id", "player_name"} <= set(boxscores.columns):
        for row in boxscores.select("player_id", "player_name").unique().iter_rows(named=True):
            player_id = row.get("player_id")
            if player_id is not None and row.get("player_name"):
                names.setdefault(str(player_id), str(row["player_name"]))
    if not dim_players.is_empty() and {"player_id", "full_name"} <= set(dim_players.columns):
        for row in dim_players.iter_rows(named=True):
            player_id = row.get("player_id")
            if player_id is not None and row.get("full_name"):
                names[str(player_id)] = str(row["full_name"])
    return names


def _contains_player(player_ids_str: object, player_id: str) -> bool:
    return player_id in {token.strip() for token in str(player_ids_str or "").split(",") if token.strip()}


def _combo_row(
    *,
    team_id: int,
    season: str,
    combo_type: str,
    players: tuple[str, ...],
    stints: list[dict[str, object]],
    player_names: dict[str, str],
) -> dict[str, object] | None:
    together = [
        stint
        for stint in stints
        if all(_contains_player(stint.get("player_ids_str"), player_id) for player_id in players)
    ]
    minutes = sum(float(stint.get("duration_seconds") or 0.0) for stint in together) / 60.0
    if minutes < 5.0:
        return None

    pts_for = int(sum(float(stint.get("points_for") or 0.0) for stint in together))
    pts_against = int(sum(float(stint.get("points_against") or 0.0) for stint in together))
    net = pts_for - pts_against
    rounded_minutes = round(minutes, 1)
    return {
        "team_id": team_id,
        "season": season,
        "combo_type": combo_type,
        "player_ids": ",".join(players),
        "player_names": ",".join(player_names.get(player_id, player_id) for player_id in players),
        "stints": len(together),
        "total_minutes": rounded_minutes,
        "pts_for": pts_for,
        "pts_against": pts_against,
        "net_points": net,
        "net_rating_per_48": round(net / rounded_minutes * 48.0, 1),
    }


def build_player_combo_season_stat_rows(
    lineups: pl.DataFrame,
    dim_players: pl.DataFrame,
    games: pl.DataFrame,
    boxscores: pl.DataFrame,
) -> list[dict[str, object]]:
    required_lineup_cols = {"game_id", "team_id", "player_ids_str", "player_count", "duration_seconds"}
    if lineups.is_empty() or games.is_empty() or not required_lineup_cols <= set(lineups.columns):
        return []

    game_seasons = games.select(["game_id", "season", "game_type"]).unique(subset=["game_id"])
    stints = (
        lineups.join(game_seasons, on="game_id", how="left")
        .filter(
            (pl.col("player_count") >= 5)
            & (pl.col("duration_seconds") > 0)
            & (pl.col("game_type") == "regular_season")
        )
        .with_columns(
            pl.col("player_ids_str")
            .map_elements(_canonical_player_ids, return_dtype=pl.String)
            .alias("player_ids_str")
        )
    )
    if stints.is_empty():
        return []

    player_names = _player_map(dim_players, boxscores)
    team_players: dict[tuple[str, int], set[str]] = {}
    stint_rows = stints.to_dicts()
    for row in stint_rows:
        key = (str(row.get("season") or ""), int(row["team_id"]))
        team_players.setdefault(key, set())
        team_players[key].update(
            token.strip() for token in str(row.get("player_ids_str") or "").split(",") if token.strip()
        )

    rows: list[dict[str, object]] = []
    for (season, team_id), players in team_players.items():
        team_stints = [
            row
            for row in stint_rows
            if int(row["team_id"]) == team_id and str(row.get("season") or "") == season
        ]
        player_list = sorted(players, key=int)

        for combo in itertools.combinations(player_list, 2):
            row = _combo_row(
                team_id=team_id,
                season=season,
                combo_type="2-man",
                players=combo,
                stints=team_stints,
                player_names=player_names,
            )
            if row:
                rows.append(row)

        frequent_players = [
            player_id
            for player_id in player_list
            if sum(
                float(row.get("duration_seconds") or 0.0)
                for row in team_stints
                if _contains_player(row.get("player_ids_str"), player_id)
            )
            / 60.0
            >= 30.0
        ]
        for combo in itertools.combinations(frequent_players, 3):
            row = _combo_row(
                team_id=team_id,
                season=season,
                combo_type="3-man",
                players=combo,
                stints=team_stints,
                player_names=player_names,
            )
            if row:
                rows.append(row)

    return sorted(
        rows,
        key=lambda row: (
            str(row.get("season") or ""),
            str(row.get("combo_type") or ""),
            -(float(row.get("net_rating_per_48") or 0.0)),
        ),
    )

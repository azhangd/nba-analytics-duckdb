"""Bronze: load deterministic synthetic source payloads into raw tables."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nba_duckdb import db
from nba_duckdb.sources import get_source_adapter


def _result_set(name: str, headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"resultSets": [{"name": name, "headers": headers, "rowSet": rows}]}


def _players_for_team(players: list[dict[str, Any]], team_id: int) -> list[dict[str, Any]]:
    return [player for player in players if int(player["team_id"]) == int(team_id)]


def _coach_rows(teams: list[dict[str, Any]], season: str, now_iso: str) -> list[dict[str, Any]]:
    rows = []
    for index, team in enumerate(teams):
        first = f"Coach{index + 1}"
        last = team["abbreviation"]
        rows.append(
            {
                "coach_id": f"SYN-COACH-{team['team_id']}",
                "team_id": team["team_id"],
                "season": season,
                "first_name": first,
                "last_name": last,
                "coach_name": f"{first} {last}",
                "is_assistant": 0,
                "coach_type": "Head Coach",
                "sort_sequence": 1,
                "school": "Synthetic University",
                "birth_date": "2070-01-01",
                "raw_json": {"source": "synthetic_fixture"},
                "ingested_at": now_iso,
            }
        )
    return rows


def _tracking_payload(players: list[dict[str, Any]], category: str) -> dict[str, Any]:
    headers = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "MIN", "AVG_SPEED", "DIST_MILES"]
    rows = [
        [
            player["player_id"],
            player["full_name"],
            player["team_id"],
            22,
            28.0,
            round(3.7 + (index % 5) * 0.1, 2),
            round(1.8 + (index % 4) * 0.2, 2),
        ]
        for index, player in enumerate(players)
    ]
    return _result_set(category, headers, rows)


def _hustle_payload(players: list[dict[str, Any]]) -> dict[str, Any]:
    headers = [
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "MIN",
        "CONTESTED_SHOTS",
        "CONTESTED_SHOTS_2PT",
        "CONTESTED_SHOTS_3PT",
        "DEFLECTIONS",
        "CHARGES_DRAWN",
        "SCREEN_ASSISTS",
        "SCREEN_AST_PTS",
        "OFF_LOOSE_BALLS_RECOVERED",
        "DEF_LOOSE_BALLS_RECOVERED",
        "LOOSE_BALLS_RECOVERED",
        "OFF_BOXOUTS",
        "DEF_BOXOUTS",
        "BOX_OUTS",
    ]
    rows = []
    for index, player in enumerate(players):
        rows.append(
            [
                player["player_id"],
                player["full_name"],
                player["team_id"],
                28.0,
                3 + index % 4,
                2 + index % 3,
                1 + index % 2,
                2 + index % 5,
                index % 2,
                1 + index % 3,
                2 + index % 4,
                index % 2,
                1 + index % 2,
                1 + index % 3,
                index % 2,
                1 + index % 2,
                1 + index % 3,
            ]
        )
    return _result_set("HustleStatsPlayer", headers, rows)


def _matchup_payload(players: list[dict[str, Any]], team_id: int, opponent_id: int) -> dict[str, Any]:
    off_players = _players_for_team(players, team_id)[:5]
    def_players = _players_for_team(players, opponent_id)[:5]
    headers = [
        "OFF_PLAYER_ID",
        "OFF_PLAYER_NAME",
        "DEF_PLAYER_ID",
        "DEF_PLAYER_NAME",
        "OFF_TEAM_ID",
        "DEF_TEAM_ID",
        "MATCHUP_MIN",
        "PARTIAL_POSS",
        "PLAYER_PTS",
        "MATCHUP_FGM",
        "MATCHUP_FGA",
        "MATCHUP_FG_PCT",
        "MATCHUP_FG3M",
        "MATCHUP_FG3A",
    ]
    rows = []
    for index, (off_player, def_player) in enumerate(zip(off_players, def_players, strict=False)):
        rows.append(
            [
                off_player["player_id"],
                off_player["full_name"],
                def_player["player_id"],
                def_player["full_name"],
                team_id,
                opponent_id,
                f"{8 + index}:00",
                12.0 + index,
                4 + index,
                2,
                4,
                50.0,
                1,
                2,
            ]
        )
    return _result_set("Matchups", headers, rows)


def _defense_payload(players: list[dict[str, Any]], *, player_or_team: str) -> dict[str, Any]:
    headers = [
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "GP",
        "POSS",
        "PTS",
        "PPP",
        "SF_PCT",
        "FG_PCT",
        "FT_POSS_PCT",
        "TO_POSS_PCT",
        "SCORE_PCT",
        "POSS_PCT",
        "PERCENTILE",
    ]
    if player_or_team == "T":
        seen: dict[int, dict[str, Any]] = {}
        for player in players:
            seen.setdefault(player["team_id"], player)
        source_rows = list(seen.values())
    else:
        source_rows = players
    rows = []
    for index, item in enumerate(source_rows):
        rows.append(
            [
                item["player_id"] if player_or_team == "P" else None,
                item["full_name"] if player_or_team == "P" else f"Team {item['team_id']}",
                item["team_id"],
                "",
                22,
                30.0 + index,
                28.0 + index,
                0.9 + (index % 4) * 0.02,
                8.0,
                44.0,
                10.0,
                12.0,
                45.0,
                15.0,
                55.0,
            ]
        )
    return _result_set("Synergy", headers, rows)


def _rotation_payload(game: dict[str, Any], players: list[dict[str, Any]]) -> dict[str, Any]:
    headers = ["TEAM_ID", "PERSON_ID", "IN_TIME_REAL", "OUT_TIME_REAL"]
    result_sets = []
    for label, team_key in (("HomeTeam", "homeTeam"), ("AwayTeam", "awayTeam")):
        team_id = int(game[team_key]["teamId"])
        rows = [
            [team_id, player["player_id"], 0, 28800]
            for player in _players_for_team(players, team_id)[:5]
        ]
        result_sets.append({"name": label, "headers": headers, "rowSet": rows})
    return {"resultSets": result_sets}


def _game_detail_payload(game: dict[str, Any], players: list[dict[str, Any]]) -> dict[str, Any]:
    misc = {"boxScoreMisc": {}}
    for team_key in ("homeTeam", "awayTeam"):
        team = game[team_key]
        misc["boxScoreMisc"][team_key] = {
            "teamId": team["teamId"],
            "teamTricode": team["teamTricode"],
            "statistics": {
                "pointsOffTurnovers": 12,
                "pointsSecondChance": 10,
                "pointsFastBreak": 14,
                "pointsPaint": 44,
                "oppPointsOffTurnovers": 9,
                "oppPointsSecondChance": 8,
                "oppPointsFastBreak": 11,
                "oppPointsPaint": 40,
            },
        }
    return {"misc": misc, "rotation": _rotation_payload(game, players)}


def run(
    fixtures_dir: str | Path | None = None,
    source_name: str = "fixtures",
    **_: Any,
) -> dict[str, int]:
    source = get_source_adapter(
        source_name,
        fixtures_dir=str(fixtures_dir) if fixtures_dir else None,
    )
    payload = source.read()
    now_iso = datetime.now(timezone.utc).isoformat()
    season = payload.schedule[0]["season"]

    counts = {
        "schedule": db.upsert_rows(
            "bronze",
            "schedule",
            [
                {
                    "game_id": game["gameId"],
                    "game_date": game["gameDate"],
                    "home_team_id": game["homeTeam"]["teamId"],
                    "away_team_id": game["awayTeam"]["teamId"],
                    "home_team_abbr": game["homeTeam"]["teamTricode"],
                    "away_team_abbr": game["awayTeam"]["teamTricode"],
                    "game_status": game["gameStatus"],
                    "game_status_text": game["gameStatusText"],
                    "season": game["season"],
                    "raw_json": game,
                    "ingested_at": now_iso,
                }
                for game in payload.schedule
            ],
            conflict_cols=["game_id"],
        ),
        "rosters": db.upsert_rows(
            "bronze",
            "rosters",
            [
                {
                    "player_id": player["player_id"],
                    "team_id": player["team_id"],
                    "player_name": player["full_name"],
                    "jersey_number": player["jersey_number"],
                    "position": player["position"],
                    "height": player["height"],
                    "weight": player["weight"],
                    "birth_date": "2075-01-01",
                    "experience": "1",
                    "season": season,
                    "raw_json": player,
                    "ingested_at": now_iso,
                }
                for player in payload.players
            ],
            conflict_cols=["player_id", "team_id", "season"],
        ),
        "boxscores": db.upsert_rows(
            "bronze",
            "boxscores",
            [
                {
                    "game_id": boxscore["game_id"],
                    "traditional_json": {"game": boxscore["game"]},
                    "advanced_json": boxscore.get("advanced", {}),
                    "ingested_at": now_iso,
                }
                for boxscore in payload.boxscores
            ],
            conflict_cols=["game_id"],
        ),
        "play_by_play": db.upsert_rows(
            "bronze",
            "play_by_play",
            [
                {
                    "game_id": game_events["game"]["gameId"],
                    "pbp_json": game_events,
                    "source": "fixture",
                    "ingested_at": now_iso,
                }
                for game_events in payload.play_by_play
            ],
            conflict_cols=["game_id"],
        ),
        "shot_charts": db.upsert_rows(
            "bronze",
            "shot_charts",
            [
                {
                    "game_id": shot_chart["game_id"],
                    "team_id": shot_chart["team_id"],
                    "shot_chart_json": shot_chart["shot_chart"],
                    "ingested_at": now_iso,
                }
                for shot_chart in payload.shot_charts
            ],
            conflict_cols=["game_id", "team_id"],
        ),
        "coaches": db.upsert_rows(
            "bronze",
            "coaches",
            _coach_rows(payload.teams, season, now_iso),
            conflict_cols=["coach_id", "team_id", "season"],
        ),
        "standings": db.upsert_rows(
            "bronze",
            "standings",
            [
                {
                    "season": season,
                    "standings_json": {
                        "teams": [
                            {
                                "team_id": team["team_id"],
                                "wins": 22 - index,
                                "losses": 22 + index,
                            }
                            for index, team in enumerate(payload.teams)
                        ]
                    },
                    "ingested_at": now_iso,
                }
            ],
            conflict_cols=["season"],
        ),
        "tracking_stats": db.upsert_rows(
            "bronze",
            "tracking_stats",
            [
                {
                    "season": season,
                    "category": category,
                    "level": "player",
                    "tracking_json": _tracking_payload(payload.players, category),
                    "ingested_at": now_iso,
                }
                for category in ("SpeedDistance", "Defense", "Efficiency")
            ],
            conflict_cols=["season", "category", "level"],
        ),
        "hustle": db.upsert_rows(
            "bronze",
            "hustle",
            [
                {
                    "season": season,
                    "level": "player",
                    "hustle_json": _hustle_payload(payload.players),
                    "ingested_at": now_iso,
                }
            ],
            conflict_cols=["season", "level"],
        ),
        "matchups": db.upsert_rows(
            "bronze",
            "matchups",
            [
                {
                    "season": season,
                    "team_id": team["team_id"],
                    "direction": direction,
                    "matchup_json": _matchup_payload(
                        payload.players,
                        team["team_id"],
                        payload.teams[(index + 1) % len(payload.teams)]["team_id"],
                    ),
                    "ingested_at": now_iso,
                }
                for index, team in enumerate(payload.teams)
                for direction in ("offense", "defense")
            ],
            conflict_cols=["season", "team_id", "direction"],
        ),
        "defense": db.upsert_rows(
            "bronze",
            "defense",
            [
                {
                    "season": season,
                    "play_type": play_type,
                    "type_grouping": grouping,
                    "player_or_team": player_or_team,
                    "defense_json": _defense_payload(payload.players, player_or_team=player_or_team),
                    "ingested_at": now_iso,
                }
                for play_type in ("Isolation", "Transition", "Spotup")
                for grouping in ("offensive", "defensive")
                for player_or_team in ("P", "T")
            ],
            conflict_cols=["season", "play_type", "type_grouping", "player_or_team"],
        ),
        "game_detail": db.upsert_rows(
            "bronze",
            "game_detail",
            [
                {
                    "game_id": game["gameId"],
                    "detail_json": _game_detail_payload(game, payload.players),
                    "ingested_at": now_iso,
                }
                for game in payload.schedule
            ],
            conflict_cols=["game_id"],
        ),
        "tracking": db.upsert_rows(
            "bronze",
            "tracking",
            [
                {
                    "season": season,
                    "tracking_json": _tracking_payload(payload.players, "Shooting"),
                    "ingested_at": now_iso,
                }
            ],
            conflict_cols=["season"],
        ),
        "injuries": db.upsert_rows(
            "bronze",
            "injuries",
            [
                {
                    "fetched_date": "2100-01-01",
                    "injuries_json": {
                        "source_url": "synthetic-fixture",
                        "fetched_date": "2100-01-01",
                        "rows": [
                            {
                                "team_abbr": payload.teams[0]["abbreviation"],
                                "player_name": payload.players[0]["full_name"],
                                "status": "Out",
                                "reason": "Injury/Illness-Left Ankle;Soreness",
                            }
                        ],
                    },
                    "ingested_at": now_iso,
                }
            ],
            conflict_cols=["fetched_date"],
        ),
    }
    counts["teams"] = len(payload.teams)
    return counts

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'fixture',
 'task_type': 'fixture',
 'inputs': (),
 'optional_inputs': (),
 'outputs': ('bronze.schedule',
             'bronze.rosters',
             'bronze.coaches',
             'bronze.boxscores',
             'bronze.play_by_play',
             'bronze.shot_charts',
             'bronze.standings',
             'bronze.tracking_stats',
             'bronze.hustle',
             'bronze.matchups',
             'bronze.defense',
             'bronze.game_detail',
             'bronze.tracking',
             'bronze.injuries'),
 'mutates': (),
 'graphs': ('default', 'quick'),
 'modes': ('fixture',),
 'required': True,
 'quality_outputs': ('bronze.schedule',
                     'bronze.rosters',
                     'bronze.coaches',
                     'bronze.boxscores',
                     'bronze.play_by_play',
                     'bronze.shot_charts',
                     'bronze.standings',
                     'bronze.tracking_stats',
                     'bronze.hustle',
                     'bronze.matchups',
                     'bronze.defense',
                     'bronze.game_detail',
                     'bronze.tracking',
                     'bronze.injuries'),
 'regular_season_only': True,
 'live_order': None,
 'fixture_order': 10}

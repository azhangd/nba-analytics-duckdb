"""Generate deterministic synthetic fixtures for tests and offline smoke checks."""

from __future__ import annotations

import json
from pathlib import Path

SEASON = "2099-00"
# Use NBA-shaped franchise IDs so scoped quality checks exercise the same
# filtering path as live runs. Names, players, games, and stats are synthetic.
TEAM_IDS = [1610612737, 1610612738, 1610612739, 1610612740]
TEAM_ABBRS = ["MET", "HRB", "RID", "BAY"]
TEAM_NAMES = ["Metro Meteors", "Harbor Tides", "Ridge Peaks", "Bay Bears"]
GAME_ID = "002SYN0001"
SECOND_GAME_ID = "002SYN0002"
HOME_TEAM_ID = TEAM_IDS[0]
AWAY_TEAM_ID = TEAM_IDS[1]
GAME_COUNT = 44
# One game is played at a neutral site, like an NBA Cup semifinal.
NEUTRAL_GAME_INDEX = GAME_COUNT - 1
PLAYERS_PER_TEAM = 8


TEAMS = [
    {
        "team_id": team_id,
        "abbreviation": abbr,
        "full_name": name,
        "city": name.rsplit(" ", 1)[0],
        "nickname": name.rsplit(" ", 1)[1],
    }
    for team_id, abbr, name in zip(TEAM_IDS, TEAM_ABBRS, TEAM_NAMES, strict=True)
]


def _player(team_index: int, roster_index: int) -> dict:
    player_id = 910000 + team_index * 100 + roster_index + 1
    first_names = [
        "Avery",
        "Blair",
        "Casey",
        "Devin",
        "Ellis",
        "Finley",
        "Gray",
        "Harper",
    ]
    last_names = ["Arc", "Beam", "Cove", "Drift"]
    positions = ["G", "G", "F", "F", "C", "G", "F", "C"]
    return {
        "player_id": player_id,
        "full_name": f"{first_names[roster_index]} {last_names[team_index]}",
        "team_id": TEAM_IDS[team_index],
        "position": positions[roster_index],
        "jersey_number": str(roster_index + 1),
        "height": f"6-{2 + roster_index % 8}",
        "weight": str(185 + roster_index * 8),
    }


PLAYERS = [
    _player(team_index, roster_index)
    for team_index in range(len(TEAMS))
    for roster_index in range(PLAYERS_PER_TEAM)
]


def _team_payload(team: dict, score: int) -> dict:
    return {
        "teamId": team["team_id"],
        "teamTricode": team["abbreviation"],
        "teamCity": team["city"],
        "teamName": team["nickname"],
        "score": score,
    }


def _game_id(index: int) -> str:
    return f"002SYN{index + 1:04d}"


def _schedule_game(index: int) -> dict:
    home_index = index % len(TEAMS)
    away_index = (index * 2 + 1) % len(TEAMS)
    if away_index == home_index:
        away_index = (away_index + 1) % len(TEAMS)
    home_score = 96 + (index % 15)
    away_score = 91 + ((index * 3) % 14)
    return {
        "gameId": _game_id(index),
        "gameDate": f"01/{(index % 28) + 1:02d}/2100 00:00:00",
        "gameStatus": 3,
        "gameStatusText": "Final",
        "season": SEASON,
        "isNeutral": index == NEUTRAL_GAME_INDEX,
        "homeTeam": _team_payload(TEAMS[home_index], home_score),
        "awayTeam": _team_payload(TEAMS[away_index], away_score),
    }


SCHEDULE = [_schedule_game(index) for index in range(GAME_COUNT)]
# Every fifth game the away team also has a team turnover (no player), which the
# box score leaves out.
TEAM_TURNOVER_EVERY = 5
TURNOVER_SUB_TYPES = ["bad pass", "lost ball", "traveling", "offensive foul"]


def _team_players(team_id: int) -> list[dict]:
    return [player for player in PLAYERS if player["team_id"] == team_id]


def _player_turnovers(roster_index: int) -> int:
    return 1 + (roster_index % 3)


def _boxscore_player(player: dict, *, roster_index: int, game_index: int, is_home: bool) -> dict:
    first_name, family_name = player["full_name"].split(" ", 1)
    starter = roster_index < 5
    minutes = 30 + (roster_index % 3) if starter else 18 + (roster_index % 3)
    points = 8 + roster_index * 2 + (game_index % 5) + (2 if is_home else 0)
    fgm = max(points // 3, 1)
    fg3m = 1 + (roster_index % 2)
    ftm = max(points - fgm * 2 - fg3m * 3, 0)
    rebounds = 3 + (roster_index % 5)
    assists = 2 + ((roster_index + game_index) % 6)
    return {
        "personId": player["player_id"],
        "firstName": first_name,
        "familyName": family_name,
        "nameI": f"{first_name[0]}. {family_name}",
        "jerseyNum": player["jersey_number"],
        "position": player["position"],
        "starter": "1" if starter else "0",
        "played": "1",
        "statistics": {
            "minutes": f"{minutes}:00",
            "fieldGoalsMade": fgm,
            "fieldGoalsAttempted": fgm + 5,
            "threePointersMade": fg3m,
            "threePointersAttempted": fg3m + 3,
            "freeThrowsMade": ftm,
            "freeThrowsAttempted": ftm + (roster_index % 2),
            "reboundsOffensive": 1,
            "reboundsDefensive": max(rebounds - 1, 0),
            "reboundsTotal": rebounds,
            "assists": assists,
            "steals": 1 if roster_index % 3 == 0 else 0,
            "blocks": 1 if player["position"] == "C" else 0,
            "turnovers": _player_turnovers(roster_index),
            "foulsPersonal": 2,
            "points": points,
            "plusMinusPoints": 4 if is_home else -4,
        },
    }


def _advanced_player(player: dict, roster_index: int) -> dict:
    return {
        "personId": player["player_id"],
        "statistics": {
            "offensiveRating": 104.0 + roster_index,
            "defensiveRating": 101.0 - (roster_index % 4),
            "netRating": 3.0 + roster_index / 2,
            "usagePercentage": 18.0 + roster_index,
            "trueShootingPercentage": 0.54 + roster_index * 0.005,
            "estimatedPace": 99.0,
        },
    }


def _boxscore_game(index: int, game: dict) -> dict:
    home_team_id = game["homeTeam"]["teamId"]
    away_team_id = game["awayTeam"]["teamId"]
    home_players = _team_players(home_team_id)
    away_players = _team_players(away_team_id)
    return {
        "game_id": game["gameId"],
        "game": {
            "gameId": game["gameId"],
            "homeTeam": {
                "teamId": home_team_id,
                "teamTricode": game["homeTeam"]["teamTricode"],
                "players": [
                    _boxscore_player(player, roster_index=i, game_index=index, is_home=True)
                    for i, player in enumerate(home_players)
                ],
            },
            "awayTeam": {
                "teamId": away_team_id,
                "teamTricode": game["awayTeam"]["teamTricode"],
                "players": [
                    _boxscore_player(player, roster_index=i, game_index=index, is_home=False)
                    for i, player in enumerate(away_players)
                ],
            },
        },
        "advanced": {
            "boxScoreAdvanced": {
                "homeTeam": {
                    "players": [
                        _advanced_player(player, i) for i, player in enumerate(home_players)
                    ]
                },
                "awayTeam": {
                    "players": [
                        _advanced_player(player, i) for i, player in enumerate(away_players)
                    ]
                },
            }
        },
    }


BOXSCORES = [_boxscore_game(index, game) for index, game in enumerate(SCHEDULE)]


def _action(
    *,
    period: int,
    clock: str,
    team_id: int | None,
    player: dict | None,
    action_type: str,
    sub_type: str,
    description: str,
    score_home: int,
    score_away: int,
    shot_result: str = "",
    is_field_goal: int = 0,
    x: int | None = None,
    y: int | None = None,
) -> dict:
    return {
        "period": period,
        "clock": clock,
        "teamId": team_id,
        "personId": player["player_id"] if player else None,
        "playerNameI": player["full_name"] if player else "",
        "actionType": action_type,
        "subType": sub_type,
        "description": description,
        "scoreHome": str(score_home),
        "scoreAway": str(score_away),
        "shotResult": shot_result,
        "isFieldGoal": is_field_goal,
        "x": x,
        "y": y,
    }


def _turnover_order(players: list[dict], skip: dict | None = None) -> list[dict]:
    """Each player once per round until they reach their box-score turnovers, less `skip` once."""
    remaining = [_player_turnovers(i) - (player is skip) for i, player in enumerate(players)]
    order = []
    while any(remaining):
        for i, player in enumerate(players):
            if remaining[i]:
                order.append(player)
                remaining[i] -= 1
    return order


def _clock(seconds: int) -> str:
    return f"PT{seconds // 60:02d}M{seconds % 60:02d}.00S"


def _pbp_game(index: int, game: dict) -> dict:
    home_team_id = game["homeTeam"]["teamId"]
    away_team_id = game["awayTeam"]["teamId"]
    home_players = _team_players(home_team_id)
    away_players = _team_players(away_team_id)
    home_base = int(game["homeTeam"]["score"]) - 9
    away_base = int(game["awayTeam"]["score"]) - 7
    opening = [
        _action(
            period=1,
            clock="PT12M00.00S",
            team_id=None,
            player=None,
            action_type="period",
            sub_type="start",
            description="Period Start",
            score_home=0,
            score_away=0,
        ),
        _action(
            period=1,
            clock="PT11M30.00S",
            team_id=home_team_id,
            player=home_players[0],
            action_type="2pt",
            sub_type="Jump Shot",
            description=f"{home_players[0]['full_name']} makes jumper",
            score_home=2,
            score_away=0,
            shot_result="Made",
            is_field_goal=1,
            x=8,
            y=12,
        ),
        _action(
            period=1,
            clock="PT11M00.00S",
            team_id=away_team_id,
            player=away_players[1],
            action_type="3pt",
            sub_type="Jump Shot",
            description=f"{away_players[1]['full_name']} misses three",
            score_home=2,
            score_away=0,
            shot_result="Missed",
            is_field_goal=1,
            x=22,
            y=24,
        ),
        _action(
            period=1,
            clock="PT10M58.00S",
            team_id=home_team_id,
            player=home_players[4],
            action_type="rebound",
            sub_type="Defensive",
            description=f"{home_players[4]['full_name']} defensive rebound",
            score_home=2,
            score_away=0,
        ),
    ]
    # The home team has the ball after the defensive rebound. The teams trade
    # turnovers for the rest of the first period, so each team's play-by-play
    # turnovers match its box score (the away team's last one comes in the 4th).
    # That leaves the away team with the ball, and it gives it back with a team
    # turnover or a missed shot.
    home_turnovers = _turnover_order(home_players)
    away_turnovers = _turnover_order(away_players, skip=away_players[2])
    sequence = [(home_team_id, player) for player in home_turnovers]
    for position, player in enumerate(away_turnovers):
        sequence.insert(2 * position + 1, (away_team_id, player))
    if index % TEAM_TURNOVER_EVERY == TEAM_TURNOVER_EVERY - 1:
        sequence.append((away_team_id, None))
    clock = 640
    exchange = []
    for position, (team_id, player) in enumerate(sequence):
        if player is None:
            sub_type, description = "shot clock", "Team shot clock turnover"
        else:
            sub_type = TURNOVER_SUB_TYPES[position % len(TURNOVER_SUB_TYPES)]
            description = f"{player['full_name']} {sub_type} turnover"
        exchange.append(
            _action(
                period=1,
                clock=_clock(clock),
                team_id=team_id,
                player=player,
                action_type="turnover",
                sub_type=sub_type,
                description=description,
                score_home=2,
                score_away=0,
            )
        )
        clock -= 20
    if sequence[-1][0] == home_team_id:
        exchange += [
            _action(
                period=1,
                clock=_clock(clock),
                team_id=away_team_id,
                player=away_players[3],
                action_type="2pt",
                sub_type="Jump Shot",
                description=f"{away_players[3]['full_name']} misses jumper",
                score_home=2,
                score_away=0,
                shot_result="Missed",
                is_field_goal=1,
                x=-10,
                y=15,
            ),
            _action(
                period=1,
                clock=_clock(clock - 2),
                team_id=home_team_id,
                player=home_players[4],
                action_type="rebound",
                sub_type="Defensive",
                description=f"{home_players[4]['full_name']} defensive rebound",
                score_home=2,
                score_away=0,
            ),
        ]

    late = [
        _action(
            period=4,
            clock="PT04M30.00S",
            team_id=home_team_id,
            player=None,
            action_type="timeout",
            sub_type="regular",
            description="Synthetic timeout",
            score_home=home_base,
            score_away=away_base,
        ),
        _action(
            period=4,
            clock="PT04M15.00S",
            team_id=home_team_id,
            player=home_players[0],
            action_type="2pt",
            sub_type="Jump Shot",
            description=f"{home_players[0]['full_name']} makes jumper",
            score_home=home_base + 2,
            score_away=away_base,
            shot_result="Made",
            is_field_goal=1,
            x=9,
            y=14,
        ),
        _action(
            period=4,
            clock="PT04M00.00S",
            team_id=away_team_id,
            player=away_players[2],
            action_type="turnover",
            sub_type="bad pass",
            description=f"{away_players[2]['full_name']} turnover",
            score_home=home_base + 2,
            score_away=away_base,
        ),
        _action(
            period=4,
            clock="PT03M45.00S",
            team_id=home_team_id,
            player=home_players[0],
            action_type="freethrow",
            sub_type="Free Throw 1 of 1",
            description=f"{home_players[0]['full_name']} makes free throw",
            score_home=home_base + 3,
            score_away=away_base,
            shot_result="Made",
        ),
        _action(
            period=4,
            clock="PT00M00.00S",
            team_id=None,
            player=None,
            action_type="period",
            sub_type="end",
            description="Period End",
            score_home=int(game["homeTeam"]["score"]),
            score_away=int(game["awayTeam"]["score"]),
        ),
    ]
    actions = opening + exchange + late
    for number, action in enumerate(actions, start=1):
        action["actionId"] = action["actionNumber"] = number
    return {"game": {"gameId": game["gameId"], "actions": actions}}


PLAY_BY_PLAY = [_pbp_game(index, game) for index, game in enumerate(SCHEDULE)]


def _shot_chart_row(game: dict, player: dict, index: int) -> list:
    is_three = index % 3 == 0
    zone = "Above the Break 3" if is_three else ("Restricted Area" if index % 2 == 0 else "Mid-Range")
    team_offset = 0 if player["team_id"] == game["homeTeam"]["teamId"] else 100
    return [
        game["gameId"],
        team_offset + index + 1,
        player["player_id"],
        player["full_name"],
        player["team_id"],
        4,
        4,
        15,
        "Jump Shot" if is_three else "Driving Layup Shot",
        "3PT Field Goal" if is_three else "2PT Field Goal",
        zone,
        "Center(C)",
        "24+ ft." if is_three else "Less Than 8 ft.",
        25 if is_three else 3,
        12 + index,
        240 - index,
        1 if index % 4 != 1 else 0,
        "21000103",
    ]


def _shot_chart(game: dict, team_id: int) -> dict:
    players = _team_players(team_id)
    return {
        "game_id": game["gameId"],
        "team_id": team_id,
        "shot_chart": {
            "resultSets": [
                {
                    "name": "Shot_Chart_Detail",
                    "headers": [
                        "GAME_ID",
                        "GAME_EVENT_ID",
                        "PLAYER_ID",
                        "PLAYER_NAME",
                        "TEAM_ID",
                        "PERIOD",
                        "MINUTES_REMAINING",
                        "SECONDS_REMAINING",
                        "ACTION_TYPE",
                        "SHOT_TYPE",
                        "SHOT_ZONE_BASIC",
                        "SHOT_ZONE_AREA",
                        "SHOT_ZONE_RANGE",
                        "SHOT_DISTANCE",
                        "LOC_X",
                        "LOC_Y",
                        "SHOT_MADE_FLAG",
                        "GAME_DATE",
                    ],
                    "rowSet": [
                        _shot_chart_row(game, player, index)
                        for index, player in enumerate(players[:6])
                    ],
                }
            ]
        },
    }


SHOT_CHARTS = [
    _shot_chart(game, team_id)
    for game in SCHEDULE
    for team_id in (game["homeTeam"]["teamId"], game["awayTeam"]["teamId"])
]


def generate_fixtures(output_dir: str | Path) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    files = {
        "synthetic_teams.json": TEAMS,
        "synthetic_players.json": PLAYERS,
        "synthetic_schedule.json": SCHEDULE,
        "synthetic_boxscore.json": BOXSCORES,
        "synthetic_play_by_play.json": PLAY_BY_PLAY,
        "synthetic_shot_charts.json": SHOT_CHARTS,
    }
    written = []
    for filename, payload in files.items():
        path = output / filename
        path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    generate_fixtures(Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "generated")

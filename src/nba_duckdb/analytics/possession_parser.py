"""Possession parser.

Parses play-by-play events into possessions. Each possession represents
one continuous offensive opportunity for a team, ending when:
- A made field goal (possession changes unless offensive rebound)
- A defensive rebound
- A turnover
- End of period
- A made free throw that is the last of the set (non-technical)

Columns added:
- possession_context: "transition" | "half_court" (garbage_time is an overlay)
- is_garbage_time: bool (Cleaning the Glass sliding-scale methodology)
- score_margin: score differential at start of possession (positive = offense leading)
"""

import re

import polars as pl


def _is_garbage_time(period: int, clock_seconds: float, margin: int) -> bool:
    """Cleaning the Glass garbage time definition.

    4th quarter only (not OT — those are competitive by nature):
    - 12:00-9:00 remaining: |margin| >= 25
    - 9:00-6:00 remaining:  |margin| >= 20
    - 6:00-0:00 remaining:  |margin| >= 15
    """
    if period != 4:
        return False
    abs_margin = abs(margin)
    if clock_seconds > 540:  # 9:00-12:00
        return abs_margin >= 25
    if clock_seconds > 360:  # 6:00-9:00
        return abs_margin >= 20
    return abs_margin >= 15  # 0:00-6:00


def _parse_score(score_str: str) -> int | None:
    """Parse score string like '108' or '' to int."""
    try:
        return int(str(score_str).strip())
    except (ValueError, TypeError):
        return None


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _is_period_end(action_type: str, sub_type: str) -> bool:
    return action_type == "period" and sub_type == "end"


def _is_final_free_throw(sub_type: str) -> bool:
    match = re.search(r"(\d+)\s+(?:of|/)\s+(\d+)", sub_type)
    return bool(match and match.group(1) == match.group(2))


def _is_technical_free_throw(sub_type: str, description: str) -> bool:
    return "technical" in f"{sub_type} {description}"


def parse_possessions(
    pbp_df: pl.DataFrame,
    game_id: str,
    *,
    home_team_id: int,
    away_team_id: int,
) -> pl.DataFrame:
    """Parse a game's play-by-play (silver.fct_play_by_play rows) into possessions.

    Expects the silver vocabulary: action_type 2pt/3pt/freethrow/rebound/turnover/period,
    shot_result Made/Missed, and the score carried forward on every row.

    The offense is set only by offensive actions (shots, free throws, turnovers); after a
    possession ends the other team has the ball. Rebounds are offensive or defensive by
    comparing the rebounding team to the offense. Every made free throw counts; one taken
    by the team that just scored (an and-one) is credited to that team's last possession.
    """
    if pbp_df.is_empty():
        return pl.DataFrame()

    other_team = {home_team_id: away_team_id, away_team_id: home_team_id}
    events = pbp_df.sort(["period", "action_id"])

    possessions: list[dict] = []
    current: dict | None = None
    possession_number = 0
    score_home = 0
    score_away = 0

    def open_possession(
        period: int, clock: float, offense: int | None, start_type: str, prev_end: str | None, margin: int
    ) -> dict:
        nonlocal possession_number
        possession_number += 1
        return {
            "game_id": game_id,
            "possession_number": possession_number,
            "period": period,
            "offense_team_id": offense,
            "start_clock_seconds": clock,
            "start_type": start_type,
            "possession_context": "transition" if prev_end in ("defensive_rebound", "turnover") else "half_court",
            "raw_margin_at_start": margin,
            "events": [],
            "points_scored": 0,
            "has_offense_action": False,
        }

    def close_possession(possession: dict, clock: float, end_type: str) -> None:
        possession["end_clock_seconds"] = clock
        possession["end_type"] = end_type
        possession["duration_seconds"] = max(0.0, possession["start_clock_seconds"] - clock)
        possession["event_count"] = len(possession["events"])
        possession["events"] = "; ".join(possession["events"][-5:])
        raw_margin = possession.pop("raw_margin_at_start")
        possession.pop("has_offense_action")
        offense = possession["offense_team_id"]
        possession["score_margin"] = -raw_margin if offense == away_team_id else raw_margin
        possession["is_garbage_time"] = _is_garbage_time(
            possession["period"], possession["start_clock_seconds"], raw_margin
        )
        possessions.append(possession)

    for row in events.iter_rows(named=True):
        action_type = _norm(row.get("action_type"))
        sub_type = _norm(row.get("sub_type"))
        description = str(row.get("description") or "")
        team_id = row.get("team_id")
        period = int(row.get("period") or 0)
        clock = float(row.get("clock_seconds_remaining") or 0.0)
        made = _norm(row.get("shot_result")) == "made"
        parsed_home = _parse_score(row.get("score_home"))
        parsed_away = _parse_score(row.get("score_away"))
        # A row's score includes its own points.
        margin_before_row = score_home - score_away
        if parsed_home is not None and parsed_away is not None:
            score_home, score_away = parsed_home, parsed_away

        if action_type == "period" and sub_type == "start":
            # Technical free throws between periods come before the period start; the
            # substitutions there are not a possession.
            if current is not None and current["has_offense_action"]:
                close_possession(current, clock, "end_period")
            current = None
            continue
        if current is None:
            current = open_possession(period, clock, None, "dead_ball", None, score_home - score_away)
        if description:
            current["events"].append(description)

        if _is_period_end(action_type, sub_type):
            close_possession(current, clock, "end_period")
            current = None
            continue

        is_free_throw = action_type == "freethrow"
        is_offense_action = action_type in ("2pt", "3pt", "turnover") or is_free_throw
        if (
            is_free_throw
            and current["offense_team_id"] is not None
            and team_id != current["offense_team_id"]
            and not current["has_offense_action"]
        ):
            # A free throw by the team that just lost the ball: an and-one, a technical or
            # a flagrant. Credit the point to that team's last possession.
            if made:
                for previous in reversed(possessions):
                    if previous["offense_team_id"] == team_id:
                        previous["points_scored"] += 1
                        break
            continue
        if is_offense_action and team_id:
            if current["offense_team_id"] is None or not current["has_offense_action"]:
                current["offense_team_id"] = team_id
            elif team_id != current["offense_team_id"]:
                # The other team acted without a recorded change of possession. Its
                # possession starts before this row, so before this row's points.
                close_possession(current, clock, "change")
                current = open_possession(period, clock, team_id, "dead_ball", "change", margin_before_row)
            current["has_offense_action"] = True

        end_type = None
        if action_type in ("2pt", "3pt") and made:
            current["points_scored"] += 3 if action_type == "3pt" else 2
            end_type = f"made_{action_type[0]}"
        elif action_type == "turnover":
            end_type = "turnover"
        elif is_free_throw and made:
            current["points_scored"] += 1
            if _is_final_free_throw(sub_type) and not _is_technical_free_throw(sub_type, description.lower()):
                end_type = "free_throw"
        elif action_type == "rebound" and team_id and current["offense_team_id"] and team_id != current["offense_team_id"]:
            end_type = "defensive_rebound"

        if end_type:
            offense = current["offense_team_id"]
            close_possession(current, clock, end_type)
            start_type = "live_ball" if end_type in ("defensive_rebound", "made_2", "made_3") else "dead_ball"
            current = open_possession(
                period, clock, other_team.get(offense), start_type, end_type, score_home - score_away
            )

    if current is not None and current["events"]:
        close_possession(current, 0.0, "end_period")

    if not possessions:
        return pl.DataFrame()
    return pl.DataFrame(possessions)

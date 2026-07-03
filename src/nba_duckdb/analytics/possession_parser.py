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


def _is_period_end(action_type: str, sub_type: str, description: str) -> bool:
    if "end period" in action_type or "end of period" in description:
        return True
    if action_type == "period":
        return not sub_type or "end" in sub_type or "end" in description
    return False


def _is_turnover(action_type: str) -> bool:
    return action_type == "turnover" or "turnover" in action_type


def _field_goal_points(action_type: str, sub_type: str, description: str) -> int:
    if "3pt" in action_type or "3pt" in sub_type or "3-" in description:
        return 3
    return 2


def _is_free_throw(action_type: str) -> bool:
    return action_type in {"freethrow", "free throw"} or "free throw" in action_type


def _is_final_free_throw(sub_type: str, description: str) -> bool:
    text = f"{sub_type} {description}"
    ft_match = re.search(r"(\d+)\s+(?:of|/)\s+(\d+)", text)
    return bool(ft_match and ft_match.group(1) == ft_match.group(2))


def _is_technical_free_throw(sub_type: str, description: str) -> bool:
    return "technical" in f"{sub_type} {description}"


def parse_possessions(
    pbp_df: pl.DataFrame,
    game_id: str,
    home_team_id: int | None = None,
) -> pl.DataFrame:
    """Parse a game's play-by-play into possessions.

    Args:
        pbp_df: Play-by-play DataFrame for a single game
        game_id: The game ID
        home_team_id: Home team ID, used to sign score_margin correctly

    Returns:
        DataFrame with one row per possession, columns:
        - game_id, possession_number, period
        - offense_team_id, defense_team_id
        - start_clock_seconds, end_clock_seconds, duration_seconds
        - start_type (dead_ball, live_ball)
        - end_type (made_2, made_3, miss, turnover, end_period, foul)
        - possession_context (half_court, transition)
        - is_garbage_time (Cleaning the Glass sliding scale: Q4 only, 25/20/15pt thresholds)
        - score_margin (at start of possession; positive = offense team leading)
        - points_scored
        - events (list of action descriptions)
    """
    if pbp_df.is_empty():
        return pl.DataFrame()

    # Sort by period and clock (descending clock = forward in time)
    events = pbp_df.sort(["period", "clock_seconds_remaining"], descending=[False, True])

    possessions = []
    current_possession = None
    possession_number = 0
    prev_end_type = None

    # Track running score from PBP score fields
    last_score_home: int = 0
    last_score_away: int = 0

    for row in events.iter_rows(named=True):
        action_type_raw = str(row.get("action_type", ""))
        sub_type_raw = str(row.get("sub_type", ""))
        action_type = _norm(action_type_raw)
        sub_type = _norm(sub_type_raw)
        team_id = row.get("team_id")
        period = row.get("period", 0)
        clock = row.get("clock_seconds_remaining", 0.0)
        description = row.get("description", "")
        description_norm = _norm(description)
        shot_result = _norm(row.get("shot_result", ""))
        is_fg = row.get("is_field_goal", False)

        # Update running score from PBP score fields
        sh = _parse_score(row.get("score_home", ""))
        sa = _parse_score(row.get("score_away", ""))
        if sh is not None:
            last_score_home = sh
        if sa is not None:
            last_score_away = sa

        # Start a new possession if we don't have one
        if current_possession is None:
            possession_number += 1

            # Determine possession context based on how previous possession ended
            if prev_end_type in ("defensive_rebound", "turnover"):
                possession_context = "transition"
            else:
                possession_context = "half_court"

            # Score margin at start of this possession
            # Positive = home team leading (we'll sign from offense perspective after)
            raw_margin = last_score_home - last_score_away

            current_possession = {
                "game_id": game_id,
                "possession_number": possession_number,
                "period": period,
                "offense_team_id": team_id,
                "start_clock_seconds": clock,
                "start_type": "dead_ball",
                "possession_context": possession_context,
                "score_home_at_start": last_score_home,
                "score_away_at_start": last_score_away,
                "raw_margin_at_start": raw_margin,  # home - away, to be signed later
                "events": [],
                "points_scored": 0,
            }

        if current_possession.get("offense_team_id") is None and team_id:
            current_possession["offense_team_id"] = team_id

        # Track events in this possession
        if description:
            current_possession["events"].append(description)

        # Detect possession-ending events
        should_end = False
        end_type = ""

        if _is_period_end(action_type, sub_type, description_norm):
            should_end = True
            end_type = "end_period"

        elif _is_turnover(action_type):
            should_end = True
            end_type = "turnover"

        elif is_fg and shot_result in {"made", "made shot"}:
            points = _field_goal_points(action_type, sub_type, description_norm)
            current_possession["points_scored"] = points
            should_end = True
            end_type = f"made_{points}"

        elif "rebound" in action_type and team_id:
            offense_id = current_possession.get("offense_team_id")
            is_offensive = "offensive" in sub_type or "offensive" in description_norm
            is_defensive = "defensive" in sub_type or "defensive" in description_norm
            if is_defensive or (offense_id is not None and team_id != offense_id and not is_offensive):
                should_end = True
                end_type = "defensive_rebound"

        elif (
            _is_free_throw(action_type)
            and _is_final_free_throw(sub_type, description_norm)
            and not _is_technical_free_throw(sub_type, description_norm)
            and shot_result == "made"
        ):
            current_possession["points_scored"] += 1
            should_end = True
            end_type = "free_throw"

        if should_end and current_possession:
            current_possession["end_clock_seconds"] = clock
            current_possession["end_type"] = end_type
            duration = current_possession["start_clock_seconds"] - clock
            current_possession["duration_seconds"] = max(0, duration)
            current_possession["event_count"] = len(current_possession["events"])
            current_possession["events"] = "; ".join(current_possession["events"][-5:])  # Keep last 5

            # Compute score_margin from offense team's perspective
            offense_id = current_possession.get("offense_team_id")
            raw_margin = current_possession.pop("raw_margin_at_start")
            current_possession.pop("score_home_at_start")
            current_possession.pop("score_away_at_start")
            if home_team_id and offense_id == home_team_id:
                score_margin = raw_margin  # home leading = positive for home offense
            elif home_team_id and offense_id != home_team_id:
                score_margin = -raw_margin  # away offense: flip sign
            else:
                score_margin = raw_margin  # unknown, keep as-is

            current_possession["score_margin"] = score_margin

            current_possession["is_garbage_time"] = _is_garbage_time(
                period, clock, last_score_home - last_score_away
            )

            possessions.append(current_possession)

            # Start next possession
            next_offense = team_id if end_type == "defensive_rebound" else None
            start_type = "live_ball" if end_type in ("defensive_rebound", "made_2", "made_3") else "dead_ball"
            prev_end_type = end_type

            current_possession = None
            if end_type != "end_period":
                possession_number += 1

                # Context for next possession
                if end_type in ("defensive_rebound", "turnover"):
                    next_context = "transition"
                else:
                    next_context = "half_court"

                raw_margin = last_score_home - last_score_away

                current_possession = {
                    "game_id": game_id,
                    "possession_number": possession_number,
                    "period": period,
                    "offense_team_id": next_offense,
                    "start_clock_seconds": clock,
                    "start_type": start_type,
                    "possession_context": next_context,
                    "score_home_at_start": last_score_home,
                    "score_away_at_start": last_score_away,
                    "raw_margin_at_start": raw_margin,
                    "events": [],
                    "points_scored": 0,
                }

    # Handle any remaining possession at end of game
    if current_possession and current_possession.get("events"):
        current_possession["end_clock_seconds"] = 0.0
        current_possession["end_type"] = "end_period"
        duration = current_possession["start_clock_seconds"]
        current_possession["duration_seconds"] = max(0, duration)
        current_possession["event_count"] = len(current_possession["events"])
        current_possession["events"] = "; ".join(current_possession["events"][-5:])

        raw_margin = current_possession.pop("raw_margin_at_start")
        current_possession.pop("score_home_at_start")
        current_possession.pop("score_away_at_start")
        offense_id = current_possession.get("offense_team_id")
        if home_team_id and offense_id == home_team_id:
            score_margin = raw_margin
        elif home_team_id and offense_id != home_team_id:
            score_margin = -raw_margin
        else:
            score_margin = raw_margin

        current_possession["score_margin"] = score_margin
        current_possession["is_garbage_time"] = _is_garbage_time(
            current_possession["period"], 0.0, last_score_home - last_score_away
        )
        possessions.append(current_possession)

    if not possessions:
        return pl.DataFrame()

    return pl.DataFrame(possessions)

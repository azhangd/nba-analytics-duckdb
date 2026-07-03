"""Lineup tracker.

Reconstructs 5-man lineups from play-by-play substitution events.
Tracks which 5 players are on the court for each team at every point in the game.
"""

import re
import unicodedata

import polars as pl


def _normalize(s: str) -> str:
    """Normalize string: lowercase, strip diacritics, remove periods."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().replace(".", "").strip()


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _add_name_variants(team_names: dict[str, int], player_name: str, player_id: int) -> None:
    """Index common normalized name variants for substitution lookup."""
    pname = str(player_name or "").strip()
    if not pname or not player_id:
        return

    full_norm = _normalize(pname)
    if full_norm:
        team_names[full_norm] = player_id

    parts = [part for part in pname.split() if part]
    if not parts:
        return

    last = _normalize(parts[-1])
    if last:
        team_names[last] = player_id

    if len(parts) >= 2 and _normalize(parts[-1]) in SUFFIXES:
        last_with_suffix = _normalize(" ".join(parts[-2:]))
        if last_with_suffix:
            team_names[last_with_suffix] = player_id
        penultimate = _normalize(parts[-2])
        if penultimate:
            team_names[penultimate] = player_id


def _build_name_map(
    pbp_df: pl.DataFrame,
    *,
    roster_name_map: dict[int, dict[str, int]] | None = None,
) -> dict[int, dict[str, int]]:
    """Build team_id -> {name_fragment -> player_id} maps from all PBP events.

    Substitution descriptions say "SUB: Portis FOR Turner" — we need to map
    "Portis" to a player_id. We do this by extracting the last name from every
    player_name seen in the PBP (for example, first-initial last-name formats) and
    storing team_id -> {last_name -> player_id}.
    """
    name_map: dict[int, dict[str, int]] = {}
    for row in pbp_df.iter_rows(named=True):
        tid = row.get("team_id")
        pid = row.get("player_id")
        pname = str(row.get("player_name") or "")
        if not tid or not pid or not pname or pid in (0, None):
            continue
        if tid not in name_map:
            name_map[tid] = {}
        _add_name_variants(name_map[tid], pname, int(pid))

    for tid, team_names in (roster_name_map or {}).items():
        merged = name_map.setdefault(int(tid), {})
        merged.update(team_names)
    return name_map


def _parse_sub_in_name(description: str) -> str:
    """Parse 'SUB: X FOR Y' → 'X' (the player coming IN)."""
    m = re.match(r"SUB:\s+(.+?)\s+FOR\s+", description, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _parse_sub_out_name(description: str) -> str:
    """Parse 'SUB: X FOR Y' -> 'Y' (the player going OUT)."""
    m = re.match(r"SUB:\s+.+?\s+FOR\s+(.+)", description, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def _lookup_sub_in(sub_in_name: str, team_id: int, name_map: dict) -> int | None:
    """Look up player_id for the sub-in player by name fragment."""
    team_names = name_map.get(team_id, {})
    if not sub_in_name or not team_names:
        return None
    # Try normalized last name match first
    parts = sub_in_name.strip().split()
    last = _normalize(parts[-1]) if parts else ""
    if last in team_names:
        return team_names[last]
    # Try normalized full name
    full = _normalize(sub_in_name)
    if full in team_names:
        return team_names[full]
    # Partial match
    for key, pid in team_names.items():
        if full in key or key in full:
            return pid
    return None


def _parse_sub_batch(
    sub_rows: list[dict],
    *,
    team_id: int,
    name_map: dict[int, dict[str, int]],
) -> tuple[set[int], set[int]]:
    """Resolve a same-clock substitution batch into outgoing and incoming ids."""
    outgoing_ids: set[int] = set()
    incoming_ids: set[int] = set()

    for sub_row in sub_rows:
        description = str(sub_row.get("description", "")).strip()
        description_lower = description.lower()
        player_id = sub_row.get("player_id")
        player_name = str(sub_row.get("player_name", "") or "").strip()

        if description_lower.startswith("sub out:"):
            if player_id:
                outgoing_ids.add(int(player_id))
            elif player_name:
                looked_up = _lookup_sub_in(player_name, team_id, name_map)
                if looked_up:
                    outgoing_ids.add(looked_up)
            continue

        if description_lower.startswith("sub in:"):
            if player_id:
                incoming_ids.add(int(player_id))
            else:
                incoming_name = description.split(":", 1)[1].strip() if ":" in description else ""
                looked_up = _lookup_sub_in(incoming_name, team_id, name_map)
                if looked_up:
                    incoming_ids.add(looked_up)
            continue

        incoming_name = _parse_sub_in_name(description)
        if incoming_name:
            incoming_id = _lookup_sub_in(incoming_name, team_id, name_map)
            if incoming_id:
                incoming_ids.add(incoming_id)

        if player_id:
            outgoing_ids.add(int(player_id))
            continue

        outgoing_name = _parse_sub_out_name(description)
        if outgoing_name:
            outgoing_id = _lookup_sub_in(outgoing_name, team_id, name_map)
            if outgoing_id:
                outgoing_ids.add(outgoing_id)

    return outgoing_ids, incoming_ids


def _period_length(period: int) -> float:
    return 720.0 if period <= 4 else 300.0


def _start_stint(
    current_stints: dict[int, dict],
    current_lineups: dict[int, set[int]],
    *,
    game_id: str,
    team_id: int,
    period: int,
    start_clock: float,
    score_home: int,
    score_away: int,
    stint_number: int,
) -> int:
    lineup = current_lineups.get(team_id, set())
    if len(lineup) != 5:
        return stint_number
    stint_number += 1
    current_stints[team_id] = {
        "game_id": game_id,
        "stint_number": stint_number,
        "period": period,
        "team_id": team_id,
        "player_ids": sorted(list(lineup)),
        "start_clock_seconds": start_clock,
        "start_home_score": score_home,
        "start_away_score": score_away,
    }
    return stint_number


def track_lineups(
    pbp_df: pl.DataFrame,
    game_id: str,
    *,
    starters_by_team: dict[int, set[int]] | None = None,
    roster_name_map: dict[int, dict[str, int]] | None = None,
) -> pl.DataFrame:
    """Track lineup stints from play-by-play data.

    A stint is a continuous period where the same 5 players are on court for a team.
    A substitution creates a new stint.

    Args:
        pbp_df: Play-by-play DataFrame for a single game
        game_id: The game ID

    Returns:
        DataFrame with columns:
        - game_id, stint_number, period
        - team_id
        - player_ids (sorted list of 5 player IDs)
        - start_clock_seconds, end_clock_seconds, duration_seconds
        - points_for, points_against
    """
    if pbp_df.is_empty():
        return pl.DataFrame()

    events = pbp_df.sort(["period", "clock_seconds_remaining"], descending=[False, True])
    rows = list(events.iter_rows(named=True))

    # Build name->player_id map for substitution parsing
    name_map = _build_name_map(pbp_df, roster_name_map=roster_name_map)
    starters_by_team = {
        int(team_id): set(int(player_id) for player_id in player_ids)
        for team_id, player_ids in (starters_by_team or {}).items()
        if player_ids
    }

    # Track current lineups per team
    stints: list[dict] = []
    current_lineups: dict[int, set[int]] = {
        team_id: set(player_ids) for team_id, player_ids in starters_by_team.items()
    }
    current_stints: dict[int, dict] = {}  # team_id -> current stint info
    pending_start_clock: dict[int, float] = {
        team_id: _period_length(1) for team_id in starters_by_team
    }
    pending_start_scores: dict[int, tuple[int, int]] = {
        team_id: (0, 0) for team_id in starters_by_team
    }
    stint_number = 0
    known_team_ids: set[int] = set(starters_by_team)

    # Track scores for points_for/against
    last_home_score = 0
    last_away_score = 0
    home_team_id = None
    away_team_id = None

    idx = 0
    while idx < len(rows):
        row = rows[idx]
        action_type = str(row.get("action_type", ""))
        team_id = row.get("team_id")
        player_id = row.get("player_id")
        period = int(row.get("period", 0) or 0)
        clock = float(row.get("clock_seconds_remaining", 0.0) or 0.0)
        description = str(row.get("description", ""))

        # Update running score only when event has actual score values.
        raw_home = row.get("score_home") or ""
        raw_away = row.get("score_away") or ""
        if raw_home and raw_away:
            try:
                last_home_score = int(str(raw_home).strip())
                last_away_score = int(str(raw_away).strip())
            except (ValueError, TypeError):
                pass
        score_home = last_home_score
        score_away = last_away_score

        # Detect period start/end — action_type is lowercase "period" from NBA API v3
        is_period_event = action_type.lower() == "period"
        if is_period_event:
            desc_lower = description.lower()
            if "start" in desc_lower:
                # Close any open stints from previous period
                for tid in list(current_stints.keys()):
                    _close_stint(stints, current_stints, tid, 0.0, last_home_score,
                                 last_away_score, home_team_id)
                current_stints.clear()
                opening_clock = _period_length(period)
                for tid in set(known_team_ids) | set(starters_by_team):
                    if period == 1 and tid in starters_by_team:
                        current_lineups[tid] = set(starters_by_team[tid])
                    pending_start_clock[tid] = opening_clock
                    pending_start_scores[tid] = (last_home_score, last_away_score)
            # Skip period events — don't process further
            idx += 1
            continue

        # Track team IDs (first two teams seen)
        if team_id and not home_team_id:
            home_team_id = team_id
        elif team_id and team_id != home_team_id and not away_team_id:
            away_team_id = team_id
        if team_id:
            known_team_ids.add(int(team_id))
            current_lineups.setdefault(int(team_id), set())
            pending_start_clock.setdefault(int(team_id), _period_length(period))
            pending_start_scores.setdefault(int(team_id), (last_home_score, last_away_score))

        # Handle substitutions — the key fix: parse sub-in from description
        if "Substitution" in action_type or "substitution" in action_type.lower():
            sub_rows = [row]
            next_idx = idx + 1
            while next_idx < len(rows):
                next_row = rows[next_idx]
                next_action = str(next_row.get("action_type", ""))
                next_team = next_row.get("team_id")
                next_period = int(next_row.get("period", 0) or 0)
                next_clock = float(next_row.get("clock_seconds_remaining", 0.0) or 0.0)
                if (
                    "substitution" not in next_action.lower()
                    or next_team != team_id
                    or next_period != period
                    or next_clock != clock
                ):
                    break
                sub_rows.append(next_row)
                next_idx += 1

            if team_id and team_id in current_lineups:
                # Close current stint
                if team_id in current_stints:
                    _close_stint(stints, current_stints, team_id, clock,
                                 score_home, score_away, home_team_id)
                pending_start_clock[team_id] = clock
                pending_start_scores[team_id] = (score_home, score_away)

                lineup = current_lineups[team_id]
                outgoing_ids, incoming_ids = _parse_sub_batch(
                    sub_rows,
                    team_id=int(team_id),
                    name_map=name_map,
                )
                lineup.difference_update(outgoing_ids)
                lineup.update(incoming_ids)

                # Start new stint immediately if we have exactly 5 players
                if len(lineup) == 5:
                    start_home, start_away = pending_start_scores.get(team_id, (score_home, score_away))
                    stint_number = _start_stint(
                        current_stints,
                        current_lineups,
                        game_id=game_id,
                        team_id=team_id,
                        period=period,
                        start_clock=pending_start_clock.get(team_id, clock),
                        score_home=start_home,
                        score_away=start_away,
                        stint_number=stint_number,
                    )
                elif len(lineup) > 5:
                    # More than 5 — likely a sub parsing issue; remove the
                    # subbed-out player if identifiable, otherwise keep last 5
                    # Still >5? Trim to most recent 5 (best effort)
                    trimmed = set(sorted(list(lineup))[-5:])
                    current_lineups[team_id] = trimmed
                    start_home, start_away = pending_start_scores.get(team_id, (score_home, score_away))
                    stint_number = _start_stint(
                        current_stints,
                        current_lineups,
                        game_id=game_id,
                        team_id=team_id,
                        period=period,
                        start_clock=pending_start_clock.get(team_id, clock),
                        score_home=start_home,
                        score_away=start_away,
                        stint_number=stint_number,
                    )
            idx = next_idx
            continue

        # Add players to lineups as we see them act (for initial lineup detection)
        if team_id and player_id and player_id not in (0, None):
            current_lineups.setdefault(team_id, set()).add(player_id)

            # Start a stint if we have 5 players and no active stint
            if team_id not in current_stints and len(current_lineups.get(team_id, set())) == 5:
                start_home, start_away = pending_start_scores.get(team_id, (score_home, score_away))
                stint_number = _start_stint(
                    current_stints,
                    current_lineups,
                    game_id=game_id,
                    team_id=team_id,
                    period=period,
                    start_clock=pending_start_clock.get(team_id, clock),
                    score_home=start_home,
                    score_away=start_away,
                    stint_number=stint_number,
                )
        idx += 1

    # Close any remaining stints
    for tid in list(current_stints.keys()):
        _close_stint(stints, current_stints, tid, 0.0,
                     last_home_score, last_away_score, home_team_id)

    if not stints:
        return pl.DataFrame()

    return pl.DataFrame(stints)


def _close_stint(
    stints: list[dict],
    current_stints: dict[int, dict],
    team_id: int,
    clock: float,
    score_home: int,
    score_away: int,
    home_team_id: int | None,
) -> None:
    """Close the current stint for a team and add it to the stints list."""
    if team_id not in current_stints:
        return

    stint = current_stints.pop(team_id)
    stint["end_clock_seconds"] = clock
    stint["duration_seconds"] = max(0, stint["start_clock_seconds"] - clock)

    # Calculate points for/against
    home_diff = score_home - stint["start_home_score"]
    away_diff = score_away - stint["start_away_score"]

    if team_id == home_team_id:
        stint["points_for"] = home_diff
        stint["points_against"] = away_diff
    else:
        stint["points_for"] = away_diff
        stint["points_against"] = home_diff

    # Convert player_ids list to string for Parquet storage
    stint["player_ids_str"] = ",".join(str(p) for p in stint["player_ids"])
    stint["player_count"] = len(stint["player_ids"])
    del stint["player_ids"]
    del stint["start_home_score"]
    del stint["start_away_score"]

    stints.append(stint)

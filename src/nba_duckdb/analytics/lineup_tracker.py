"""Lineup tracker.

Reconstructs 5-man lineups from play-by-play substitution events.
Tracks which 5 players are on the court for each team at every point in the game.
"""

import logging
import re
import unicodedata

import polars as pl

logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    """Normalize string: lowercase, strip diacritics, remove periods."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().replace(".", "").strip()


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _add_name_key(team_names: dict[str, int | None], key: str, player_id: int | None) -> None:
    """Map a name key to a player. A key two players share maps to None, so it never resolves."""
    if not key:
        return
    if key in team_names and team_names[key] != player_id:
        team_names[key] = None
    else:
        team_names[key] = player_id


def _add_name_variants(team_names: dict[str, int | None], player_name: str, player_id: int) -> None:
    """Index the full name and the surname, with its suffix if there is one ("jackson jr").

    A bare suffix such as "jr" is never a key: every Jr. on a team would share it.
    """
    pname = str(player_name or "").strip()
    if not pname or not player_id:
        return

    # "Schröder" is indexed as "schroder" and "schroeder", the two ways the feeds spell it.
    for spelling in {pname, pname.translate(_UMLAUTS)}:
        _add_name_key(team_names, _normalize(spelling), player_id)

        parts = [_normalize(part) for part in spelling.split() if _normalize(part)]
        if not parts:
            continue
        if parts[-1] in SUFFIXES:
            if len(parts) >= 2:
                _add_name_key(team_names, f"{parts[-2]} {parts[-1]}", player_id)
        else:
            _add_name_key(team_names, parts[-1], player_id)


def _merge_name_maps(into: dict[int, dict[str, int | None]], other: dict[int, dict[str, int | None]]) -> None:
    for team_id, names in other.items():
        team_names = into.setdefault(int(team_id), {})
        for key, player_id in names.items():
            _add_name_key(team_names, key, player_id)


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

    _merge_name_maps(name_map, roster_name_map or {})
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
    """Find the player a substitution names, such as "Jackson Jr.", "L. James" or "Jay. Williams".

    The full name is tried first, then the surname, then a first name or initial against
    the start of each teammate's first name, then the last word ("da Silva"). A bare surname prefers the player without a
    suffix ("Jackson" over "Jackson Jr."). A name that matches no player, or more than
    one, gives None.

    When the surname appears nowhere on the team, the name is tried again the way the roster
    may spell it: with umlauts spelt out ("Pöltl" for "Jakob Poeltl") or without a suffix the
    roster leaves off ("Martin Jr." for "KJ Martin").
    """
    team_names = name_map.get(team_id, {})
    full = _normalize(sub_in_name or "")
    if not full or not team_names:
        return None
    player_id = _resolve_name(full, team_names)
    if player_id is not None or _surname_on_team(full, team_names):
        return player_id
    words = full.split()
    alternatives = [_normalize(sub_in_name.translate(_UMLAUTS))]
    if len(words) > 1 and words[-1] in SUFFIXES:
        alternatives.append(" ".join(words[:-1]))
    for alternative in alternatives:
        if alternative != full:
            player_id = _resolve_name(alternative, team_names)
            if player_id is not None:
                return player_id
    return None


def _surname_on_team(full: str, team_names: dict[str, int | None]) -> bool:
    """Whether the surname of a normalized name, with its suffix if it has one, is part of any key."""
    words = full.split()
    surname = " ".join(words[-2:] if len(words) > 1 and words[-1] in SUFFIXES else words[-1:])
    return any(f" {surname} " in f" {key} " for key in team_names)


def _resolve_name(full: str, team_names: dict[str, int | None]) -> int | None:
    if full in team_names:
        return team_names[full]
    words = full.split()
    if len(words) == 1:
        matches = {team_names.get(f"{full} {suffix}") for suffix in SUFFIXES} - {None}
        if not matches:
            # One word of a teammate's name, such as "Hansen" for the box score's "Hansen Yang".
            matches = {player_id for key, player_id in team_names.items() if player_id and full in key.split()}
    else:
        first, surname = words[0], " ".join(words[1:])
        matches = {
            player_id
            for key, player_id in team_names.items()
            if player_id is not None
            and " " in key
            and key.split(" ", 1)[0].startswith(first)
            and key.split(" ", 1)[1] in (surname, *(f"{surname} {suffix}" for suffix in SUFFIXES))
        }
        if not matches and words[-1] not in SUFFIXES:
            # A two-word surname with no first name, such as "da Silva".
            return team_names.get(words[-1])
    if len(matches) == 1:
        return matches.pop()
    return None


def _sub_moves(sub_row: dict, *, team_id: int, name_map: dict[int, dict[str, int]]) -> list[tuple[str, int | None]]:
    """The players a substitution row takes out and sends in, as ("out" | "in", player id).

    The id is None when the row names a player who matches no one.
    """
    description = str(sub_row.get("description", "")).strip()
    player_id = sub_row.get("player_id")

    def resolve(player_id: object, name: str) -> int | None:
        if player_id:
            return int(player_id)
        return _lookup_sub_in(name, team_id, name_map) if name else None

    if description.lower().startswith("sub out:"):
        return [("out", resolve(player_id, str(sub_row.get("player_name", "") or "").strip()))]
    if description.lower().startswith("sub in:"):
        return [("in", resolve(player_id, description.split(":", 1)[1].strip()))]
    # "SUB: X FOR Y", whose player is Y.
    return [
        ("out", resolve(player_id, _parse_sub_out_name(description))),
        ("in", resolve(None, _parse_sub_in_name(description))),
    ]


def _period_length(period: int) -> float:
    return 720.0 if period <= 4 else 300.0


_PERIOD_MARKERS = {"period", "game"}
# Plays that don't show a player is on the court: bench technicals, ejections, coach's challenges.
_OFF_COURT_ACTIONS = {"substitution", "timeout", "ejection", "instantreplay", *_PERIOD_MARKERS}


def _is_court_action(row: dict) -> bool:
    action_type = str(row.get("action_type") or "").lower().replace(" ", "")
    if action_type in _OFF_COURT_ACTIONS:
        return False
    return not (action_type == "foul" and "tech" in str(row.get("sub_type") or "").lower())


SubMove = tuple[int, str, int | None]  # (index of the row in the period, "out" | "in", player id)


def _team_sub_runs(
    period_rows: list[dict], team_id: int, name_map: dict[int, dict[str, int]]
) -> list[tuple[float, list[SubMove]]]:
    """A team's substitutions in one period, in order, grouped into runs at the same clock.

    Other plays can come between the substitutions of a run, such as a free throw a player
    is sent in for and taken out after.
    """
    runs: list[tuple[float, list[SubMove]]] = []
    for index, row in enumerate(period_rows):
        if row.get("team_id") != team_id or "substitution" not in str(row.get("action_type", "")).lower():
            continue
        clock = float(row.get("clock_seconds_remaining") or 0.0)
        if not runs or runs[-1][0] != clock:
            runs.append((clock, []))
        runs[-1][1].extend((index, direction, player_id) for direction, player_id in _sub_moves(
            row, team_id=team_id, name_map=name_map))
    return runs


def _period_start_lineup(
    period_rows: list[dict],
    team_id: int,
    runs: list[tuple[float, list[SubMove]]],
    previous_lineup: set[int],
) -> set[int]:
    """Who is on the floor when a period starts.

    A player is on if his first substitution in the period takes him out, or he makes a play
    before his first substitution. The stats_v3 feed leaves out substitutions made between
    periods, so the previous period's last lineup only fills in players with no substitution
    in this period, and only when that makes exactly five.
    """
    first_move: dict[int, tuple[int, str]] = {}
    for _clock, moves in runs:
        for index, direction, player_id in moves:
            if player_id is not None:
                first_move.setdefault(player_id, (index, direction))
    on_court = {player_id for player_id, (_index, direction) in first_move.items() if direction == "out"}
    for index, row in enumerate(period_rows):
        player_id = row.get("player_id")
        if (
            row.get("team_id") == team_id
            and player_id
            and _is_court_action(row)
            and index < first_move.get(int(player_id), (len(period_rows), ""))[0]
        ):
            on_court.add(int(player_id))
    if len(on_court) < 5:
        carried = {player_id for player_id in previous_lineup if player_id not in first_move} - on_court
        if len(on_court | carried) == 5:
            on_court |= carried
    return on_court


def _apply_run(lineup: set[int], clock: float, moves: list[SubMove]) -> tuple[set[int], str | None]:
    """The lineup after a run of substitutions, and what's wrong with them if they don't fit it."""
    lineup = set(lineup)
    for _index, direction, player_id in moves:
        if player_id is None:
            return lineup, f"a substitution at {clock:g}s names a player who matches no one"
        if direction == "out":
            if player_id not in lineup:
                return lineup, f"a substitution at {clock:g}s takes out player {player_id}, who isn't on the floor"
            lineup.discard(player_id)
        else:
            if player_id in lineup:
                return lineup, f"a substitution at {clock:g}s sends in player {player_id}, who is already on the floor"
            lineup.add(player_id)
    if len(lineup) != 5:
        return lineup, f"the substitutions at {clock:g}s leave {len(lineup)} on the floor"
    return lineup, None


def track_lineups(
    pbp_df: pl.DataFrame,
    game_id: str,
    *,
    home_team_id: int,
    starters_by_team: dict[int, set[int]] | None = None,
    roster_name_map: dict[int, dict[str, int]] | None = None,
) -> pl.DataFrame:
    """Track lineup stints from play-by-play data.

    A stint is a stretch of a period where the same 5 players are on court for a team; each
    run of substitutions starts a new one. Each period's opening lineup comes from
    _period_start_lineup (period 1 starts from the box score starters). When the lineup can't
    be told, or a substitution doesn't fit it (a player taken out who isn't on, one sent in who
    already is, or a name that matches no one), that team gets no stints for the rest of the
    period, and a warning says where.

    Returns a DataFrame with game_id, stint_number, period, team_id, player_ids_str,
    player_count, start_clock_seconds, end_clock_seconds, duration_seconds, points_for and
    points_against.
    """
    if pbp_df.is_empty():
        return pl.DataFrame()

    rows = list(pbp_df.sort(["period", "action_id"]).iter_rows(named=True))
    name_map = _build_name_map(pbp_df, roster_name_map=roster_name_map)
    previous_lineups: dict[int, set[int]] = {
        int(team_id): {int(player_id) for player_id in player_ids}
        for team_id, player_ids in (starters_by_team or {}).items()
        if player_ids
    }
    team_ids = sorted(set(previous_lineups) | {int(row["team_id"]) for row in rows if row.get("team_id")})

    # The score after each row, carried forward over rows without one.
    scores: list[tuple[int, int]] = []
    score = (0, 0)
    for row in rows:
        raw_home, raw_away = row.get("score_home") or "", row.get("score_away") or ""
        if raw_home and raw_away:
            score = (int(str(raw_home).strip()), int(str(raw_away).strip()))
        scores.append(score)

    stints: list[dict] = []
    start = 0
    while start < len(rows):
        period = int(rows[start].get("period") or 0)
        end = start
        while end < len(rows) and int(rows[end].get("period") or 0) == period:
            end += 1
        period_rows = rows[start:end]
        # A period with nothing but start and end markers wasn't played: the live feed can file
        # "Game End" under a fifth period after a game decided in regulation.
        played = any(str(row.get("action_type", "")).lower() not in _PERIOD_MARKERS for row in period_rows)
        for team_id in team_ids if played else []:
            runs = _team_sub_runs(period_rows, team_id, name_map)
            previous_lineup = previous_lineups.get(team_id, set())
            if period == 1 and len(previous_lineup) == 5:
                lineup = set(previous_lineup)  # the box score starters
            else:
                lineup = _period_start_lineup(period_rows, team_id, runs, previous_lineup)
            stint_start = (_period_length(period), scores[start - 1] if start else (0, 0))
            problem = None if len(lineup) == 5 else f"{len(lineup)} players found on the floor at the start"
            for clock, moves in runs if problem is None else []:
                first_row = start + moves[0][0]
                at_clock = (clock, scores[first_row - 1] if first_row else (0, 0))
                _add_stint(stints, game_id, period, team_id, home_team_id, lineup, stint_start, at_clock)
                lineup, problem = _apply_run(lineup, clock, moves)
                if problem:
                    break
                stint_start = at_clock
            if problem is None:
                _add_stint(stints, game_id, period, team_id, home_team_id, lineup, stint_start, (0.0, scores[end - 1]))
                previous_lineups[team_id] = lineup
            else:
                logger.warning(
                    "Can't tell who is on the floor for team %s in period %s of game %s: %s; "
                    "its lineups stop there for the period",
                    team_id, period, game_id, problem,
                )
                previous_lineups[team_id] = set()
        start = end

    if not stints:
        return pl.DataFrame()
    stints.sort(key=lambda stint: (stint["period"], -stint["start_clock_seconds"], stint["team_id"]))
    for number, stint in enumerate(stints, start=1):
        stint["stint_number"] = number
    return pl.DataFrame(stints)


def _add_stint(
    stints: list[dict],
    game_id: str,
    period: int,
    team_id: int,
    home_team_id: int,
    lineup: set[int],
    start: tuple[float, tuple[int, int]],
    end: tuple[float, tuple[int, int]],
) -> None:
    """Add the stint from start to end, each a (clock, (home score, away score)) pair, if it lasts."""
    (start_clock, (start_home, start_away)), (end_clock, (end_home, end_away)) = start, end
    if start_clock <= end_clock:
        return
    home_points, away_points = end_home - start_home, end_away - start_away
    is_home = team_id == home_team_id
    stints.append({
        "game_id": game_id,
        "period": period,
        "team_id": team_id,
        "player_ids_str": ",".join(str(player_id) for player_id in sorted(lineup)),
        "player_count": len(lineup),
        "start_clock_seconds": start_clock,
        "end_clock_seconds": end_clock,
        "duration_seconds": start_clock - end_clock,
        "points_for": home_points if is_home else away_points,
        "points_against": away_points if is_home else home_points,
    })

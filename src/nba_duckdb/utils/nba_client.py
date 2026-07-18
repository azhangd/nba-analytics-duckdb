"""Abstraction layer over nba_api with rate limiting and error handling.

This wraps nba_api so we can swap it out if needed without changing
the rest of the codebase. All NBA data access goes through this module.
"""

import os
import time
from typing import Any

import httpx

# Patch nba_api headers before any endpoint imports.
# - Referer must be www.nba.com (not stats.nba.com) as of 2025.
# - The stats endpoints expect browser-compatible request metadata.
# - Client hints match the public web app requests that return JSON payloads.
# - The live endpoints (cdn.nba.com) use a *different* headers constant living
#   under nba_api.live.nba.library.http; without patching it the CDN returns
#   403 Access Denied for play-by-play and live box scores, which surface as
#   "Expecting value: line 1 column 1 (char 0)" JSONDecodeErrors downstream.
import nba_api.stats.library.http as _nba_http
import nba_api.live.nba.library.http as _nba_live_http

_nba_http.STATS_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

_LIVE_HEADERS = {
    "Host": "cdn.nba.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}
_nba_live_http.STATS_HEADERS = _LIVE_HEADERS
_nba_live_http.NBALiveHTTP.headers = _LIVE_HEADERS

from nba_api.stats.endpoints import (
    BoxScoreAdvancedV3,
    BoxScoreMiscV3,
    BoxScoreScoringV3,
    BoxScoreTraditionalV3,
    CommonTeamRoster,
    GameRotation,
    LeagueDashLineups,
    LeagueDashPlayerPtShot,
    LeagueDashPtStats,
    LeagueHustleStatsPlayer,
    LeagueHustleStatsTeam,
    LeagueSeasonMatchups,
    PlayByPlayV3,
    LeagueStandingsV3,
    PlayerDashPtPass,
    PlayerDashPtReb,
    PlayerIndex,
    ScoreboardV3,
    ScheduleLeagueV2,
    ShotChartDetail,
    SynergyPlayTypes,
    WinProbabilityPBP,
)
from nba_api.stats.static import teams as static_teams

from nba_duckdb.utils.rate_limiter import nba_api_limiter
from nba_duckdb.utils.env import positive_int
from nba_duckdb.exceptions import LiveEndpointUnavailableError

# nba_api live endpoints
from nba_api.live.nba.endpoints import BoxScore as LiveBoxScore
from nba_api.live.nba.endpoints import PlayByPlay as LivePlayByPlay
from nba_api.live.nba.endpoints import ScoreBoard as LiveScoreBoard


_TIMEOUT = 60  # seconds; default 30s is too low for heavy endpoints
_LIVE_TIMEOUT = positive_int("NBA_DUCKDB_LIVE_TIMEOUT_SECONDS", 30)
_CURRENT_SCHEDULE_URLS = (
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
)
_SYNERGY_PLAY_TYPE_ALIASES = {
    "Putbacks": "OffRebound",
}
_TRANSIENT_STATS_ERROR_MARKERS = (
    "Empty resultSets",
    "Expecting value",
    "Incomplete response from",
    "'resultSet'",
    "'resultSets'",
    "Read timed out",
    "RemoteDisconnected",
    "Remote end closed connection without response",
    "Connection reset by peer",
    "Connection aborted",
)


def _ensure_live_fetch_allowed() -> None:
    if os.environ.get("NBA_DUCKDB_OFFLINE_SMOKE") == "1":
        raise RuntimeError("Live NBA API calls are disabled during offline smoke runs")


def _has_stats_payload(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    if result.get("resultSets"):
        return True
    return bool(result.get("resultSet"))


def _has_v3_boxscore_payload(result: dict[str, Any] | None, payload_key: str) -> bool:
    if not result:
        return False
    payload = result.get(payload_key, {})
    return bool(payload.get("homeTeam")) and bool(payload.get("awayTeam"))


def _has_schedule_payload(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    schedule = result.get("leagueSchedule", result.get("LeagueSchedule", {}))
    game_dates = schedule.get("gameDates", schedule.get("GameDates"))
    return isinstance(game_dates, list) and bool(game_dates)


def _is_transient_stats_error(exc: Exception) -> bool:
    message = str(exc)
    if exc.__class__.__name__ == "JSONDecodeError":
        return True
    return any(marker in message for marker in _TRANSIENT_STATS_ERROR_MARKERS)


def _call_with_rate_limit(
    endpoint_cls: type,
    max_retries: int = 5,
    timeout: int = _TIMEOUT,
    result_validator: Any | None = None,
    **kwargs: Any,
) -> dict:
    """Call an nba_api endpoint with rate limiting and retries.

    Handles two failure modes:
    - Empty body (HTTP 200 + empty JSON): stats.nba.com rate-limit signal.
      Backs off longer before retrying.
    - Exception (timeout, connection error, parse error): standard backoff.
    """
    _ensure_live_fetch_allowed()
    for attempt in range(max_retries):
        nba_api_limiter.acquire()
        try:
            endpoint = endpoint_cls(timeout=timeout, **kwargs)
            result = endpoint.get_dict()
            if result_validator:
                if not result_validator(result):
                    raise ValueError(f"Incomplete response from {endpoint_cls.__name__}")
            # Empty resultSets list = rate-limit signal (HTTP 200 with no data)
            elif not _has_stats_payload(result):
                raise ValueError("Empty resultSets — likely rate-limited")
            return result
        except TypeError:
            # Wrong kwargs / endpoint misuse — no point retrying
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            # Longer backoff for empty-body responses (rate limit signal)
            transient = _is_transient_stats_error(e)
            wait = (15 if transient else 2) * (2 ** attempt)
            time.sleep(min(wait, 120))  # cap at 2 min
    return {}


def _call_live_endpoint(
    endpoint_cls: type,
    max_retries: int = 3,
    timeout: int = _LIVE_TIMEOUT,
    result_validator: Any | None = None,
    **kwargs: Any,
) -> dict:
    """Call an nba_api live endpoint with rate limiting and light retries."""
    _ensure_live_fetch_allowed()
    for attempt in range(max_retries):
        nba_api_limiter.acquire()
        try:
            endpoint = endpoint_cls(timeout=timeout, **kwargs)
            result = endpoint.get_dict()
            if result_validator and not result_validator(result):
                raise ValueError(f"Incomplete live response from {endpoint_cls.__name__}")
            return result
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(min(2 ** attempt, 10))
    return {}


def get_schedule(
    season: str,
    league_id: str = "00",
    max_retries: int = 5,
) -> dict:
    """Fetch and validate one official NBA-operated league schedule."""
    result = _call_with_rate_limit(
        ScheduleLeagueV2,
        season=season,
        league_id=str(league_id),
        max_retries=max_retries,
        result_validator=_has_schedule_payload,
    )
    schedule = result.get("leagueSchedule", result.get("LeagueSchedule", {}))
    response_season = schedule.get("seasonYear", schedule.get("SeasonYear"))
    response_league_id = str(schedule.get("leagueId", schedule.get("LeagueID", "")))
    if response_season != season:
        raise ValueError(
            f"NBA schedule response is for {response_season!r}, not requested season {season!r}"
        )
    if response_league_id != str(league_id):
        raise ValueError(
            "NBA schedule response is for league "
            f"{response_league_id!r}, not requested league {str(league_id)!r}"
        )
    return result


def get_current_schedule_from_cdn(season: str) -> dict:
    """Fetch the current season schedule from the NBA website's CDN feed.

    The CDN resource only represents the current season, so validate its
    season before returning it. The alternate URL keeps this path resilient to
    the filename used by different versions of the NBA schedule page.
    """
    _ensure_live_fetch_allowed()
    errors: list[str] = []
    for url in _CURRENT_SCHEDULE_URLS:
        nba_api_limiter.acquire()
        try:
            response = httpx.get(
                url,
                headers=_LIVE_HEADERS,
                timeout=_LIVE_TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()
            result = response.json()
            league_schedule = result.get("leagueSchedule", {})
            response_season = league_schedule.get("seasonYear")
            game_dates = league_schedule.get("gameDates")
            if response_season != season:
                raise ValueError(
                    f"NBA CDN schedule is for {response_season!r}, not requested season {season!r}"
                )
            if not game_dates:
                raise ValueError("NBA CDN schedule has no gameDates")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"{url}: {exc}")

    raise ValueError("NBA CDN schedule unavailable; " + "; ".join(errors))


def get_scoreboard_for_date(game_date: str, max_retries: int = 3) -> dict:
    """Fetch the NBA scoreboard for a specific date (YYYY-MM-DD)."""
    _ensure_live_fetch_allowed()
    for attempt in range(max_retries):
        nba_api_limiter.acquire()
        try:
            endpoint = ScoreboardV3(game_date=game_date, timeout=_TIMEOUT)
            result = endpoint.get_dict()
            if result.get("scoreboard", {}).get("games") is None:
                raise ValueError("Missing scoreboard.games payload")
            return result
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(min(2 ** attempt, 10))
    return {}


def get_boxscore(game_id: str, max_retries: int = 3) -> dict:
    """Fetch a completed-game box score.

    Prefer the official stats V3 endpoint for completed games because the live
    feed can drift from the finalized historical box score. Fall back to the
    live endpoint if V3 is temporarily unavailable.
    """
    _ensure_live_fetch_allowed()
    for attempt in range(max_retries):
        nba_api_limiter.acquire()
        try:
            endpoint = BoxScoreTraditionalV3(game_id=game_id, timeout=_TIMEOUT)
            result = endpoint.get_dict()
            boxscore = result.get("boxScoreTraditional", {})
            if (
                boxscore.get("homeTeam", {}).get("players")
                and boxscore.get("awayTeam", {}).get("players")
            ):
                return result
            raise ValueError("Incomplete BoxScoreTraditionalV3 payload")
        except Exception:
            if attempt == max_retries - 1:
                break
            time.sleep(min(2 ** attempt, 10))

    return _call_live_endpoint(
        LiveBoxScore,
        game_id=game_id,
        max_retries=1,
        result_validator=lambda result: bool(
            result.get("game", {}).get("homeTeam", {}).get("players")
        )
        and bool(result.get("game", {}).get("awayTeam", {}).get("players")),
    )


def get_boxscore_advanced(game_id: str, max_retries: int = 5) -> dict:
    """Fetch advanced box score for a game."""
    return _call_with_rate_limit(
        BoxScoreAdvancedV3,
        game_id=game_id,
        max_retries=max_retries,
        result_validator=lambda result: _has_v3_boxscore_payload(result, "boxScoreAdvanced"),
    )


def get_play_by_play(
    game_id: str,
    max_retries: int = 5,
    timeout: int = _LIVE_TIMEOUT,
) -> dict:
    """Fetch completed-game play-by-play data."""
    payload, _source = get_play_by_play_with_source(
        game_id=game_id,
        max_retries=max_retries,
        timeout=timeout,
    )
    return payload


def get_play_by_play_with_source(
    game_id: str,
    max_retries: int = 5,
    timeout: int = _LIVE_TIMEOUT,
) -> tuple[dict, str]:
    """Fetch completed-game play-by-play data.

    Prefer the live CDN payload because it is the shape downstream transforms
    were built around. Fall back to stats PlayByPlayV3 when the CDN blocks or
    returns non-JSON during larger historical backfills. The returned source is
    intentionally stored separately from the payload so bronze keeps the API
    response intact.
    """
    def validator(result: dict[str, Any]) -> bool:
        return bool(result.get("game", {}).get("actions"))

    live_error: Exception | None = None
    try:
        return _call_live_endpoint(
            LivePlayByPlay,
            game_id=game_id,
            max_retries=max_retries,
            timeout=timeout,
            result_validator=validator,
        ), "live_cdn"
    except Exception as exc:
        live_error = exc

    try:
        return _call_with_rate_limit(
            PlayByPlayV3,
            game_id=game_id,
            max_retries=max(1, max_retries),
            timeout=_TIMEOUT,
            result_validator=validator,
        ), "stats_v3"
    except Exception as stats_error:
        raise LiveEndpointUnavailableError(
            "Play-by-play unavailable from live CDN and stats PlayByPlayV3 "
            f"for game {game_id}: live={live_error}; stats={stats_error}"
        ) from stats_error


def get_shot_chart(
    game_id: str = "",
    team_id: int = 0,
    player_id: int = 0,
    season: str = "",
    season_type: str = "Regular Season",
    max_retries: int = 5,
) -> dict:
    """Fetch shot chart detail."""
    return _call_with_rate_limit(
        ShotChartDetail,
        max_retries=max_retries,
        game_id_nullable=game_id,
        team_id=team_id,
        player_id=player_id,
        season_nullable=season,
        season_type_all_star=season_type,
        context_measure_simple="FGA",
    )


def get_roster(team_id: int, season: str) -> dict:
    """Fetch team roster."""
    return _call_with_rate_limit(CommonTeamRoster, team_id=team_id, season=season)


def get_player_index(season: str) -> dict:
    """Fetch all players for a season."""
    return _call_with_rate_limit(PlayerIndex, season=season)


def get_standings(season: str) -> dict:
    """Fetch league standings."""
    return _call_with_rate_limit(LeagueStandingsV3, season=season)


def get_lineups(
    team_id: int,
    season: str,
    group_quantity: int = 5,
    measure_type: str = "Advanced",
) -> dict:
    """Fetch lineup stats."""
    return _call_with_rate_limit(
        LeagueDashLineups,
        team_id_nullable=team_id,
        season=season,
        group_quantity=group_quantity,
        measure_type_detailed_defense=measure_type,
    )


def get_player_shooting(season: str) -> dict:
    """Fetch league-wide player shooting dashboard (tracking data)."""
    return _call_with_rate_limit(
        LeagueDashPlayerPtShot,
        season=season,
    )


def get_synergy_play_types(
    season: str,
    play_type: str = "Isolation",
    player_or_team: str = "P",
    type_grouping: str = "offensive",
) -> dict:
    """Fetch Synergy play type data."""
    play_type = _SYNERGY_PLAY_TYPE_ALIASES.get(play_type, play_type)
    return _call_with_rate_limit(
        SynergyPlayTypes,
        season=season,
        play_type_nullable=play_type,
        player_or_team_abbreviation=player_or_team,
        type_grouping_nullable=type_grouping,
    )


# --- Hustle stats ---


def get_hustle_stats_player(season: str, per_mode: str = "PerGame") -> dict:
    """Fetch league-wide hustle stats (deflections, contested shots, loose balls, etc.)."""
    return _call_with_rate_limit(
        LeagueHustleStatsPlayer,
        season=season,
        per_mode_time=per_mode,
    )


def get_hustle_stats_team(season: str, per_mode: str = "PerGame") -> dict:
    """Fetch team-level hustle stats."""
    return _call_with_rate_limit(
        LeagueHustleStatsTeam,
        season=season,
        per_mode_time=per_mode,
    )


# --- Tracking stats (12 categories) ---


def get_tracking_stats(
    season: str,
    pt_measure_type: str = "SpeedDistance",
    player_or_team: str = "Player",
    per_mode: str = "PerGame",
) -> dict:
    """Fetch player tracking stats. pt_measure_type options:
    SpeedDistance, Rebounding, Possessions, CatchShoot, PullUpShot,
    Defense, Drives, Passing, ElbowTouch, PostTouch, PaintTouch, Efficiency
    """
    return _call_with_rate_limit(
        LeagueDashPtStats,
        season=season,
        pt_measure_type=pt_measure_type,
        player_or_team=player_or_team,
        per_mode_simple=per_mode,
    )


# --- Passing ---


def get_player_passing(player_id: int, season: str) -> dict:
    """Fetch passing dashboard for a player (who they pass to, assist combos)."""
    return _call_with_rate_limit(
        PlayerDashPtPass,
        player_id=player_id,
        season=season,
    )


# --- Rebounds (contested/uncontested) ---


def get_player_rebounds(player_id: int, season: str) -> dict:
    """Fetch rebound detail (contested vs uncontested, by distance)."""
    return _call_with_rate_limit(
        PlayerDashPtReb,
        player_id=player_id,
        season=season,
    )


# --- Matchups ---


def get_season_matchups(
    season: str,
    off_player_id: int | None = None,
    def_player_id: int | None = None,
    off_team_id: int | None = None,
    def_team_id: int | None = None,
) -> dict:
    """Fetch player-vs-player matchup data for the season."""
    kwargs: dict[str, Any] = {"season": season}
    if off_player_id:
        kwargs["off_player_id_nullable"] = off_player_id
    if def_player_id:
        kwargs["def_player_id_nullable"] = def_player_id
    if off_team_id:
        kwargs["off_team_id_nullable"] = off_team_id
    if def_team_id:
        kwargs["def_team_id_nullable"] = def_team_id
    return _call_with_rate_limit(LeagueSeasonMatchups, **kwargs)


# --- Misc & Scoring box scores ---


def get_boxscore_misc(game_id: str, max_retries: int = 1) -> dict:
    """Fetch misc box score: fast break pts, pts off TOV, 2nd chance pts, paint pts."""
    return _call_with_rate_limit(
        BoxScoreMiscV3,
        max_retries=max_retries,
        timeout=10,
        game_id=game_id,
        result_validator=lambda result: _has_v3_boxscore_payload(result, "boxScoreMisc"),
    )


def get_boxscore_scoring(game_id: str, max_retries: int = 1) -> dict:
    """Fetch scoring box score: assisted/unassisted FG%, pct of points by type."""
    return _call_with_rate_limit(
        BoxScoreScoringV3,
        max_retries=max_retries,
        timeout=10,
        game_id=game_id,
        result_validator=lambda result: _has_v3_boxscore_payload(result, "boxScoreScoring"),
    )


# --- Win probability ---


def get_win_probability(game_id: str, max_retries: int = 1) -> dict:
    """Fetch NBA-computed win probability for every PBP event."""
    return _call_with_rate_limit(WinProbabilityPBP, max_retries=max_retries, timeout=10, game_id=game_id)


# --- Game rotations ---


def get_game_rotation(
    game_id: str,
    max_retries: int = 5,
    timeout: int = 30,
) -> dict:
    """Fetch official rotation data (stint times, player pts, +/-, USG%)."""
    return _call_with_rate_limit(
        GameRotation,
        max_retries=max_retries,
        timeout=timeout,
        game_id=game_id,
    )


# --- Shot detail with filters ---


def get_shooting_by_defender_distance(season: str, close_def_dist: str = "") -> dict:
    """Fetch shooting splits by closest defender distance.
    close_def_dist options: '', '0-2 Feet - Very Tight', '2-4 Feet - Tight',
    '4-6 Feet - Open', '6+ Feet - Wide Open'
    """
    kwargs: dict[str, Any] = {"season": season}
    if close_def_dist:
        kwargs["close_def_dist_range_nullable"] = close_def_dist
    return _call_with_rate_limit(LeagueDashPlayerPtShot, **kwargs)


# --- Live game endpoints ---


def get_live_scoreboard() -> dict:
    """Fetch today's live scoreboard."""
    _ensure_live_fetch_allowed()
    nba_api_limiter.acquire()
    return LiveScoreBoard().get_dict()


def get_live_boxscore(game_id: str) -> dict:
    """Fetch a box score from the live endpoint."""
    return get_boxscore(game_id=game_id, max_retries=1)


def get_live_play_by_play(game_id: str) -> dict:
    """Fetch play-by-play from the live endpoint."""
    return get_play_by_play(game_id=game_id, max_retries=1)


# --- Static data ---


def get_all_teams() -> list[dict]:
    """Get static team data (no API call needed)."""
    return static_teams.get_teams()


def get_team_by_id(team_id: int) -> dict | None:
    """Get static team info by ID."""
    results = [t for t in static_teams.get_teams() if t["id"] == team_id]
    return results[0] if results else None

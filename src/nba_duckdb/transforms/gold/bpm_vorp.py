"""Box Plus/Minus 2.0 and VORP, following Basketball-Reference.

The method and every coefficient below come from Daniel Myers, "About Box
Plus/Minus (BPM)", https://www.basketball-reference.com/about/bpm2.html
(fetched 2026-11-16), including its section "Doing this at the Game Level",
which is how Basketball-Reference publishes BPM from 1985 on.

Season level, for each player-team stint:

1. Box score stats are put per 100 team possessions played.
2. Position (1 = PG, 5 = C) and offensive role (1 = creator, 5 = receiver)
   are estimated from the player's share of team stats while on the floor,
   then shifted per team so the minutes-weighted average is 3.0, clamped to
   1..5 (page appendix).
3. Coefficients are interpolated between their position-1 and position-5
   values (FGA and FTA by offensive role instead), plus the position and role
   constants.
4. Points are adjusted for team shooting context: every player on a team gets
   the same points per true shot attempt shift, from the team's rate to 1.00.
   The page doesn't print the 1.00 baseline. Its 2017 worked example (34.9
   points on 28.2 TSA adjusted to 30.4) puts it 0.16 below that team's rate,
   and on 2022-23 to 2025-26 1.00 matches Basketball-Reference best (mean gap
   0.19-0.24 against 0.27-0.34 for 0.95 or 1.05).
5. A team adjustment is added so the team's players, weighted by share of
   minutes, sum to the team's net rating per 100 possessions, adjusted for
   strength of schedule and for playing with a lead: teams play about 0.35
   points per 100 worse per point of lead, and half of that is credited back
   to the team (+0.175 x average lead). OBPM does the same with the team's
   offensive rating and half of the lead correction.

   There is no 1.2 multiplier on the team rating (BPM 1.0 had one; the 2.0
   page doesn't).

Game level, which gives the published numbers:

6. The season position and role are kept. Each game's box score is rated the
   same way: per 100 of the game's possessions the player was on for, with
   points adjusted for the team's shooting in that game.
7. Each team's players sum, weighted by share of the game's minutes, to a
   target built from who actually played: the lineup quality is the players'
   season BPMs from step 5 (pulled toward an estimate for players under 450
   minutes) weighted by share of the game's minutes. Both teams start from
   the average of the two qualities and split the game's efficiency margin,
   plus 0.175 x the team's average lead in that game. So strength of
   schedule enters through the season BPMs of the opponents who played.
8. A player's season BPM is his game BPMs averaged by minutes. On 2022-23 to
   2025-26 minutes match Basketball-Reference better than possessions played
   (mean BPM gap 0.04-0.05 against 0.05-0.06 for 500+ minutes), and so does
   the game's shooting context against the season's (0.04-0.05 against
   0.08-0.10).

The page gives the game targets for BPM only. OBPM's are built the same way
from offense: half of the team's offensive quality (season OBPMs, not pulled
toward an estimate, since the page gives that estimate for BPM only) plus the
opponent's defensive quality (BPM - OBPM) plus the team's offensive rating
above league average in that game, and half the lead correction. DBPM is
BPM - OBPM.

Because every game's shares add up to 5, a team's players, weighted by share
of the team's season minutes, sum to the minutes-weighted average of its game
targets (per stint; a traded player's season BPM averages his stints).

Differences from Basketball-Reference: they blend 50 minutes of the player's
listed position (PG..C) into the position estimate. The NBA lists G, F or C,
and turning those into 1..5 (G = 1.5, F = 3.5, ...) didn't move the match
either way on 2022-23 to 2025-26, so the position estimate comes from the box
score alone. A season with any game lacking possessions or an average lead (no
play-by-play) gives its players no BPM, as does a partial load whose games
can't separate each team's offense from its defense (for example two teams
that only play each other). Only games between two loaded teams are rated.
"""

from __future__ import annotations

import numpy as np
import polars as pl

# Coefficient per 100 team possessions: (position 1, position 5). FGA and FTA
# are (role 1 creator, role 5 receiver). Single values are the same for both.
_BPM_COEFFICIENTS = {
    "pts": (0.860, 0.860),
    "fg3m": (0.389, 0.389),
    "ast": (0.580, 1.034),
    "tov": (-0.964, -0.964),
    "oreb": (0.613, 0.181),
    "dreb": (0.116, 0.181),
    "stl": (1.369, 1.008),
    "blk": (1.327, 0.703),
    "pf": (-0.367, -0.367),
    "fga": (-0.560, -0.780),
    "fta": (-0.246, -0.343),
}
_OBPM_COEFFICIENTS = {
    "pts": (0.605, 0.605),
    "fg3m": (0.477, 0.477),
    "ast": (0.476, 0.476),
    "tov": (-0.579, -0.882),
    "oreb": (0.606, 0.422),
    "dreb": (-0.112, 0.103),
    "stl": (0.177, 0.294),
    "blk": (0.725, 0.097),
    "pf": (-0.439, -0.439),
    "fga": (-0.330, -0.472),
    "fta": (-0.145, -0.208),
}
_ROLE_COEFFICIENTS = ("fga", "fta")
# Position constant at position 1, rising linearly to 0 at position 3 and
# staying 0 above; offensive role constant at role 1, linear through 0 at 3.
_BPM_POSITION_CONSTANT = -0.818
_BPM_ROLE_CONSTANT = -2.774
_OBPM_POSITION_CONSTANT = -1.698
_OBPM_ROLE_CONSTANT = -0.860

# Position and offensive role regressions on % of team stats while on court.
_POSITION_INTERCEPT = 2.130
_POSITION_WEIGHTS = {"reb": 8.668, "stl": -2.486, "pf": 0.992, "ast": -3.536, "blk": 1.667}
_ROLE_INTERCEPT = 6.00
_ROLE_AST = -6.642
_ROLE_THRESHOLD_PTS = -8.544
_ROLE_THRESHOLD_BELOW_TEAM = 0.33  # points per TSA below the team's rate
_ROLE_PRIOR_MINUTES = 50.0
_ROLE_PRIOR = 4.0

# Season BPMs that rate a game's lineups are pulled toward an estimate of
# -4.75 + 0.175 x minutes / (games + 4), weighted (450 - minutes) / 3, so the
# estimate fades out at 450 minutes.
_LOW_MINUTES_INTERCEPT = -4.75
_LOW_MINUTES_SLOPE = 0.175
_LOW_MINUTES_EXTRA_GAMES = 4
_LOW_MINUTES_FADE = 450.0
_LOW_MINUTES_DIVISOR = 3.0

_TSA_FTA_WEIGHT = 0.44
_BASELINE_PTS_PER_TSA = 1.00
_LEAD_CORRECTION = 0.35 / 2  # points per 100 per point of average lead
_REPLACEMENT_BPM = -2.0
_SEASON_MINUTES = 48.0 * 82.0

_STATS = ["pts", "fga", "fta", "fg3m", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf"]
_PER_100_STATS = ["fg3m", "ast", "tov", "oreb", "dreb", "stl", "blk", "pf", "fga", "fta"]


def empty_bpm_vorp() -> pl.DataFrame:
    return pl.DataFrame({
        "player_id": pl.Series([], dtype=pl.Int64),
        "season": pl.Series([], dtype=pl.Utf8),
        "obpm": pl.Series([], dtype=pl.Float64),
        "dbpm": pl.Series([], dtype=pl.Float64),
        "bpm_approx": pl.Series([], dtype=pl.Float64),
        "vorp_approx": pl.Series([], dtype=pl.Float64),
    })


def build_bpm_vorp(*, player_games: pl.DataFrame, team_games: pl.DataFrame) -> pl.DataFrame:
    """BPM 2.0, OBPM, DBPM and VORP per player-season, rated game by game.

    `player_games` is gold.player_game_stats and `team_games` is
    gold.team_game_stats (regular-season games with possessions). Player games
    outside `team_games` are ignored, and so are games whose opponent has no
    player rows.
    """
    if player_games.is_empty() or team_games.is_empty():
        return empty_bpm_vorp()

    games = team_games.select(["game_id", "team_id", "season", "pts", "opp_pts", "possessions", "avg_lead"]).with_columns(
        pl.col("team_id").cast(pl.Int64)
    )
    pgs = player_games.filter(pl.col("minutes") > 0).join(
        games.select(["game_id", "team_id", "season"]), on=["game_id", "team_id"], how="inner"
    )
    stints = _season_stints(pgs, _team_targets(games))

    quality = stints.group_by(["player_id", "season"]).agg(
        ((pl.col("bpm") * pl.col("minutes")).sum() / pl.col("minutes").sum()).alias("season_bpm"),
        ((pl.col("obpm") * pl.col("minutes")).sum() / pl.col("minutes").sum()).alias("quality_obpm"),
        pl.col("minutes").sum().alias("season_minutes"),
    ).join(pgs.group_by(["player_id", "season"]).agg(pl.len().alias("season_games")), on=["player_id", "season"])
    estimate = _LOW_MINUTES_INTERCEPT + _LOW_MINUTES_SLOPE * pl.col("season_minutes") / (
        pl.col("season_games") + _LOW_MINUTES_EXTRA_GAMES
    )
    estimate_weight = ((_LOW_MINUTES_FADE - pl.col("season_minutes")) / _LOW_MINUTES_DIVISOR).clip(lower_bound=0)
    quality = quality.select(
        "player_id",
        "season",
        (
            (pl.col("season_bpm") * pl.col("season_minutes") + estimate * estimate_weight)
            / (pl.col("season_minutes") + estimate_weight)
        ).alias("quality_bpm"),
        "quality_obpm",
    )

    game_teams = pgs.group_by(["game_id", "team_id"]).agg(
        pl.col("minutes").sum().alias("game_team_minutes"),
        pl.col("pts").sum().alias("game_team_pts"),
        (pl.col("fga").sum() + _TSA_FTA_WEIGHT * pl.col("fta").sum()).alias("game_team_tsa"),
    )
    rated = (
        pgs.join(game_teams, on=["game_id", "team_id"])
        .join(games.select("game_id", "team_id", "possessions"), on=["game_id", "team_id"])
        .join(stints.select("player_id", "season", "team_id", "position", "role"), on=["player_id", "season", "team_id"])
        .join(quality, on=["player_id", "season"])
        .with_columns((pl.col("minutes") / (pl.col("game_team_minutes") / 5)).alias("share"))
    )
    per_100 = 100 / (pl.col("share") * pl.col("possessions"))
    tsa = pl.col("fga") + _TSA_FTA_WEIGHT * pl.col("fta")
    team_pts_per_tsa = pl.col("game_team_pts") / pl.col("game_team_tsa")
    rated = rated.with_columns(
        [((pl.col("pts") + (_BASELINE_PTS_PER_TSA - team_pts_per_tsa) * tsa) * per_100).alias("pts_100")]
        + [(pl.col(stat).cast(pl.Float64) * per_100).alias(f"{stat}_100") for stat in _PER_100_STATS]
    ).with_columns(
        _raw_bpm(_BPM_COEFFICIENTS, _BPM_POSITION_CONSTANT, _BPM_ROLE_CONSTANT).alias("raw_bpm"),
        _raw_bpm(_OBPM_COEFFICIENTS, _OBPM_POSITION_CONSTANT, _OBPM_ROLE_CONSTANT).alias("raw_obpm"),
    )
    # Team adjustment per game: one constant per team so that sum(share x
    # BPM), where the shares add up to 5, equals that game's target.
    rated = rated.join(_game_targets(rated, games), on=["game_id", "team_id"]).with_columns(
        (
            pl.col(f"raw_{metric}")
            + (pl.col(f"{metric}_target") - (pl.col("share") * pl.col(f"raw_{metric}")).sum().over(["game_id", "team_id"]))
            / 5
        ).alias(metric)
        for metric in ("bpm", "obpm")
    )

    players = rated.group_by(["player_id", "season"]).agg(
        ((pl.col("bpm") * pl.col("minutes")).sum() / pl.col("minutes").sum()).alias("bpm"),
        ((pl.col("obpm") * pl.col("minutes")).sum() / pl.col("minutes").sum()).alias("obpm"),
        pl.col("minutes").sum().alias("total_minutes"),
    )
    return players.select(
        "player_id",
        "season",
        pl.col("obpm").round(1),
        (pl.col("bpm") - pl.col("obpm")).round(1).alias("dbpm"),
        pl.col("bpm").round(1).alias("bpm_approx"),
        ((pl.col("bpm") - _REPLACEMENT_BPM) * pl.col("total_minutes") / _SEASON_MINUTES).round(2).alias(
            "vorp_approx"
        ),
    )


def _season_stints(pgs: pl.DataFrame, targets: pl.DataFrame) -> pl.DataFrame:
    """Steps 1-5: season position, offensive role, BPM and OBPM per
    player-team stint, with one team adjustment for the whole season."""
    stints = pgs.group_by(["player_id", "season", "team_id"]).agg(
        [pl.col("minutes").sum()] + [pl.col(stat).sum().cast(pl.Float64) for stat in _STATS]
    )
    teams = stints.group_by(["team_id", "season"]).agg(
        [pl.col("minutes").sum().alias("team_minutes")]
        + [pl.col(stat).sum().alias(f"team_{stat}") for stat in _STATS]
    ).join(targets, on=["team_id", "season"], how="inner")

    stints = stints.join(teams, on=["team_id", "season"], how="inner")
    share = pl.col("minutes") / (pl.col("team_minutes") / 5)
    team_pts_per_tsa = pl.col("team_pts") / (pl.col("team_fga") + _TSA_FTA_WEIGHT * pl.col("team_fta"))
    tsa = pl.col("fga") + _TSA_FTA_WEIGHT * pl.col("fta")
    stints = stints.with_columns(
        share.alias("share"),
        (pl.col("pts") + (_BASELINE_PTS_PER_TSA - team_pts_per_tsa) * tsa).alias("pts_adj"),
        (pl.col("pts") - (team_pts_per_tsa - _ROLE_THRESHOLD_BELOW_TEAM) * tsa).alias("threshold_pts"),
        (_ROLE_THRESHOLD_BELOW_TEAM * (pl.col("team_fga") + _TSA_FTA_WEIGHT * pl.col("team_fta"))).alias(
            "team_threshold_pts"
        ),
    )

    def team_share(stat: str, team_stat: str) -> pl.Expr:
        # A team total of 0 (possible only in tiny samples) means every player had 0% of it.
        return (
            pl.when(pl.col(team_stat) == 0)
            .then(0.0)
            .otherwise(pl.col(stat) / (pl.col("share") * pl.col(team_stat)))
        )

    position_raw = pl.lit(_POSITION_INTERCEPT)
    for stat, weight in _POSITION_WEIGHTS.items():
        position_raw = position_raw + weight * team_share(stat, f"team_{stat}")
    role_fit = (
        _ROLE_INTERCEPT
        + _ROLE_AST * team_share("ast", "team_ast")
        + _ROLE_THRESHOLD_PTS * team_share("threshold_pts", "team_threshold_pts")
    )
    role_raw = (role_fit * pl.col("minutes") + _ROLE_PRIOR * _ROLE_PRIOR_MINUTES) / (
        pl.col("minutes") + _ROLE_PRIOR_MINUTES
    )
    stints = stints.with_columns(position_raw.alias("position_raw"), role_raw.alias("role_raw"))
    stints = _center_on_team(stints, "position_raw", "position")
    stints = _center_on_team(stints, "role_raw", "role")

    per_100 = 100 / (pl.col("share") * pl.col("team_possessions"))
    stints = stints.with_columns(
        [(pl.col("pts_adj") * per_100).alias("pts_100")]
        + [(pl.col(stat) * per_100).alias(f"{stat}_100") for stat in _PER_100_STATS]
    )
    stints = stints.with_columns(
        _raw_bpm(_BPM_COEFFICIENTS, _BPM_POSITION_CONSTANT, _BPM_ROLE_CONSTANT).alias("raw_bpm"),
        _raw_bpm(_OBPM_COEFFICIENTS, _OBPM_POSITION_CONSTANT, _OBPM_ROLE_CONSTANT).alias("raw_obpm"),
    )
    return stints.with_columns(
        (
            pl.col(f"raw_{metric}")
            + (pl.col(f"{metric}_target") - (pl.col("share") * pl.col(f"raw_{metric}")).sum().over(["team_id", "season"]))
            / 5
        ).alias(metric)
        for metric in ("bpm", "obpm")
    )


def _game_targets(rated: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    """Step 7: what each team's players sum to in each game (BPM and OBPM).

    BPM: (own lineup quality + opponent's + efficiency margin) / 2 + 0.175 x
    average lead, so a team that wins by exactly what its lineup predicts gets
    its own quality. OBPM: (own offense + opponent's defense + offensive
    rating above league) / 2 + half that lead correction.
    """
    league = games.group_by("season").agg(
        (100 * pl.col("pts").sum() / pl.col("possessions").sum()).alias("league_ortg")
    )
    lineups = rated.group_by(["game_id", "team_id"]).agg(
        (pl.col("share") * pl.col("quality_bpm")).sum().alias("quality"),
        (pl.col("share") * pl.col("quality_obpm")).sum().alias("offense"),
    )
    opponents = lineups.select(
        "game_id",
        pl.col("team_id").alias("opp_id"),
        pl.col("quality").alias("opp_quality"),
        (pl.col("quality") - pl.col("offense")).alias("opp_defense"),
    )
    margin = 100 * (pl.col("pts") - pl.col("opp_pts")) / pl.col("possessions")
    offense_above_league = 100 * pl.col("pts") / pl.col("possessions") - pl.col("league_ortg")
    return (
        lineups.join(opponents, on="game_id")
        .filter(pl.col("team_id") != pl.col("opp_id"))
        .join(games, on=["game_id", "team_id"])
        .join(league, on="season")
        .select(
            "game_id",
            "team_id",
            ((pl.col("quality") + pl.col("opp_quality") + margin) / 2 + _LEAD_CORRECTION * pl.col("avg_lead")).alias(
                "bpm_target"
            ),
            (
                (pl.col("offense") + pl.col("opp_defense") + offense_above_league) / 2
                + _LEAD_CORRECTION / 2 * pl.col("avg_lead")
            ).alias("obpm_target"),
        )
    )


def _raw_bpm(coefficients: dict[str, tuple[float, float]], position_constant: float, role_constant: float) -> pl.Expr:
    position_t = (pl.col("position") - 1) / 4
    role_t = (pl.col("role") - 1) / 4
    total = pl.lit(0.0)
    for stat, (at_1, at_5) in coefficients.items():
        t = role_t if stat in _ROLE_COEFFICIENTS else position_t
        total = total + (at_1 + (at_5 - at_1) * t) * pl.col(f"{stat}_100")
    position_adj = pl.when(pl.col("position") < 3).then(position_constant * (3 - pl.col("position")) / 2).otherwise(0.0)
    role_adj = role_constant * (3 - pl.col("role")) / 2
    return total + position_adj + role_adj


def _center_on_team(stints: pl.DataFrame, raw: str, out: str) -> pl.DataFrame:
    """Add one constant per team to `raw`, then clamp to 1..5, so the team's
    minutes-weighted average is exactly 3.0.

    The weighted average of the clamped values rises monotonically with the
    constant, from 1 to 5 over [1 - max raw, 5 - min raw], so bisection to
    float precision finds it.
    """
    parts = []
    for team in stints.partition_by(["team_id", "season"], maintain_order=True):
        values = team[raw].to_numpy()
        weights = team["minutes"].to_numpy()
        low, high = 1.0 - values.max(), 5.0 - values.min()
        while True:
            mid = (low + high) / 2
            if mid in (low, high):
                break
            if np.average(np.clip(values + mid, 1.0, 5.0), weights=weights) < 3.0:
                low = mid
            else:
                high = mid
        parts.append(team.with_columns(pl.Series(out, np.clip(values + mid, 1.0, 5.0))))
    return pl.concat(parts)


def _team_targets(games: pl.DataFrame) -> pl.DataFrame:
    """Step 5's season targets: net rating (BPM) and offensive rating (OBPM)
    per 100 possessions relative to the league, adjusted for strength of
    schedule and average lead.

    Each team's adjusted offense o and defense d (points per 100 kept off the
    board, above league) satisfy, over its games against opponents j:
        o_i = (ORtg_i - league) + mean_j d_j
        d_i = (league - DRtg_i) + mean_j o_j
    with league-average adjusted offense fixed at 0. A season with any game
    lacking possessions or average lead, or whose games don't pin down every
    team's offense and defense, is left out.
    """
    rows = []
    for season_games in games.partition_by("season"):
        if season_games["possessions"].null_count() or season_games["avg_lead"].null_count():
            continue
        season = season_games["season"][0]
        opponents = season_games.join(
            season_games.select("game_id", pl.col("team_id").alias("opp_id")), on="game_id"
        ).filter(pl.col("team_id") != pl.col("opp_id"))
        totals = season_games.group_by("team_id").agg(
            pl.col("pts").sum(), pl.col("opp_pts").sum(), pl.col("possessions").sum(), pl.col("avg_lead").mean(),
            pl.len().alias("games"),
        ).sort("team_id")
        team_ids = totals["team_id"].to_list()
        index = {team_id: i for i, team_id in enumerate(team_ids)}
        n = len(team_ids)
        league = 100 * totals["pts"].sum() / totals["possessions"].sum()
        off_rel = (100 * totals["pts"] / totals["possessions"] - league).to_numpy()
        def_rel = (league - 100 * totals["opp_pts"] / totals["possessions"]).to_numpy()
        schedule = np.zeros((n, n))
        for team_id, opp_id in opponents.select("team_id", "opp_id").iter_rows():
            schedule[index[team_id], index[opp_id]] += 1
        schedule /= totals["games"].to_numpy()[:, None]
        identity = np.eye(n)
        system = np.block([[identity, -schedule], [-schedule, identity], [np.ones((1, n)), np.zeros((1, n))]])
        target = np.concatenate([off_rel, def_rel, [0.0]])
        solution, _, rank, _ = np.linalg.lstsq(system, target, rcond=None)
        if rank < 2 * n:
            # Only with a few loaded teams (say two that only play each other):
            # their games can't separate offense from defense.
            continue
        rows.append(
            pl.DataFrame({
                "team_id": team_ids,
                "season": [season] * n,
                "obpm_target": solution[:n] + _LEAD_CORRECTION / 2 * totals["avg_lead"].to_numpy(),
                "bpm_target": solution[:n] + solution[n:] + _LEAD_CORRECTION * totals["avg_lead"].to_numpy(),
                "team_possessions": totals["possessions"],
            })
        )
    if not rows:
        return pl.DataFrame(schema={
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "obpm_target": pl.Float64,
            "bpm_target": pl.Float64,
            "team_possessions": pl.Float64,
        })
    return pl.concat(rows)

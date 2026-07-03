"""Player archetype classifier.

Classifies players into offensive archetypes based on box score and shot
profile data. Rather than hard labels, each player gets a probability
distribution across archetypes — e.g., "60% Primary Ball Handler,
25% Shot Creator, 15% Spotup."

Archetypes:
1. Primary Creator  — high USG, high AST, handles the ball
2. Secondary Creator — moderate USG+AST, versatile scorer
3. Stretch Shooter   — high 3PA rate, low USG, floor spacer
4. Slasher          — high paint FGA, drives, finishes at rim
5. Post Scorer      — high mid-range/post, rebounds, lower 3PA
6. 3-and-D Wing     — high 3PA rate + high STL/BLK rate
7. Athletic Big     — high REB, BLK, paint finisher, low perimeter
8. Role Player      — limited usage, does a bit of everything

Uses a soft-max scoring approach: compute affinity scores for each archetype,
then normalize to probabilities. This keeps role labels probabilistic instead
of forcing players into one box.
"""

import polars as pl


def classify_archetypes(season_stats: pl.DataFrame) -> pl.DataFrame:
    """Classify each player into probabilistic archetypes.

    Args:
        season_stats: Gold player_season_stats DataFrame with per-game avgs

    Returns:
        DataFrame with player_id, player_name, primary_archetype,
        and probability columns for each archetype.
    """
    if season_stats.is_empty():
        return pl.DataFrame()

    rows = []
    for p in season_stats.iter_rows(named=True):
        mpg = p.get("mpg", 0) or 0
        if mpg < 5:
            continue  # Skip garbage-time-only players

        ppg = p.get("ppg", 0) or 0
        apg = p.get("apg", 0) or 0
        rpg = p.get("rpg", 0) or 0
        spg = p.get("spg", 0) or 0
        bpg = p.get("bpg", 0) or 0
        topg = p.get("topg", 0) or 0
        usg = (p.get("avg_usg_pct", 0) or 0) * 100  # Convert to %
        fg3_pct = p.get("fg3_pct", 0) or 0
        fg_pct = p.get("fg_pct", 0) or 0

        # Per-36 rates for position-neutral comparison
        scale = 36.0 / mpg if mpg > 0 else 0
        ppg36 = ppg * scale
        apg36 = apg * scale
        rpg36 = rpg * scale
        spg36 = spg * scale
        bpg36 = bpg * scale
        topg36 = topg * scale

        # Assist-to-turnover ratio (creation efficiency)
        ast_tov = apg / max(topg, 0.5)

        # ── Affinity scores (higher = stronger match) ────────────────

        # Primary Creator: high assists, high usage, handles ball
        primary_creator = (
            min(apg36 / 3.0, 2.0)  # Assist volume (6+ per 36 = max)
            + min(usg / 15.0, 2.0)  # Usage rate (30%+ = max)
            + min(topg36 / 2.0, 1.0)  # Turnovers indicate ball-handling
            + (0.5 if ast_tov > 2.0 else 0)
        )

        # Secondary Creator: moderate usage + assists, versatile
        secondary_creator = (
            min(apg36 / 4.0, 1.5)  # 6 ast/36 = 1.5
            + min(ppg36 / 10.0, 1.5)  # 15 pts/36 = 1.5
            + min(usg / 20.0, 1.0)  # 20% USG = 1.0
            + (0.5 if 15 < usg < 28 else 0)  # Sweet spot usage
        )

        # Stretch Shooter: high 3PT rate, floor spacer
        stretch_shooter = (
            min(fg3_pct / 0.15, 2.0)  # 30%+ 3P = 2.0
            + (1.5 if usg < 20 else 0.5 if usg < 25 else 0)  # Lower usage
            + (0.5 if rpg36 < 5 else 0)  # Not a rebounder
        )

        # Slasher: drives, finishes at rim, high FG%
        slasher = (
            min(ppg36 / 10.0, 1.5)  # Scoring
            + (1.5 if fg_pct > 0.55 else 0.75 if fg_pct > 0.48 else 0)
            + (0.5 if fg3_pct < 0.30 else 0)  # Not a shooter
            + min(spg36 / 2.0, 0.5)  # Some steals (quick hands)
        )

        # Post Scorer: mid-range, rebounds, traditional big
        post_scorer = (
            min(rpg36 / 5.0, 1.5)  # Rebounding
            + min(ppg36 / 10.0, 1.0)  # Scoring
            + (1.0 if bpg36 > 1.0 else 0.3)  # Shot blocking
            + (0.5 if fg3_pct < 0.25 else 0)  # Not a shooter
            + (0.5 if usg > 20 else 0)
        )

        # 3-and-D Wing: shoots threes + defensive stats
        three_and_d = (
            min(fg3_pct / 0.15, 1.5)  # 3PT shooting
            + min((spg36 + bpg36) / 1.5, 1.5)  # Defensive activity
            + (1.0 if usg < 22 else 0)  # Not a primary option
            + (0.5 if rpg36 > 4 else 0)  # Boards
        )

        # Athletic Big: rebounds, blocks, paint finisher
        athletic_big = (
            min(rpg36 / 4.0, 2.0)  # Rebounding
            + min(bpg36 / 0.8, 1.5)  # Shot blocking
            + (1.0 if fg_pct > 0.55 else 0.3)  # Efficient finisher
            + (0.5 if fg3_pct < 0.20 else 0)  # Not a shooter
        )

        # Role Player: limited usage, does a bit of everything
        role_player = (
            (2.0 if usg < 15 else 1.0 if usg < 18 else 0)
            + (0.5 if mpg < 20 else 0)
            + (0.5 if ppg36 < 10 else 0)
        )

        scores = {
            "Primary Creator": max(0, primary_creator),
            "Secondary Creator": max(0, secondary_creator),
            "Stretch Shooter": max(0, stretch_shooter),
            "Slasher": max(0, slasher),
            "Post Scorer": max(0, post_scorer),
            "3-and-D Wing": max(0, three_and_d),
            "Athletic Big": max(0, athletic_big),
            "Role Player": max(0, role_player),
        }

        # Softmax normalization to probabilities
        total = sum(scores.values())
        if total == 0:
            total = 1

        probs = {k: round(v / total, 3) for k, v in scores.items()}

        # Primary archetype = highest probability
        primary = max(probs, key=probs.get)

        # Secondary = second highest
        sorted_archetypes = sorted(probs.items(), key=lambda x: -x[1])
        secondary = sorted_archetypes[1][0] if len(sorted_archetypes) > 1 else primary

        rows.append({
            "player_id": p["player_id"],
            "player_name": p["player_name"],
            "team_id": p["team_id"],
            "primary_archetype": primary,
            "secondary_archetype": secondary,
            "archetype_confidence": probs[primary],
            **{f"prob_{k.lower().replace(' ', '_').replace('-', '_')}": v
               for k, v in probs.items()},
        })

    if not rows:
        return pl.DataFrame()

    df = pl.DataFrame(rows)

    # ── Gravity estimate ─────────────────────────────────────────────
    # Approximation of NBA's official Gravity stat using available data.
    # True gravity requires tracking data (defender positions). We proxy
    # using: 3PT accuracy × 3PT volume + scoring volume × efficiency.
    # Players who shoot well from 3 at volume force closeouts = gravity.
    # Normalized to 0-100 scale within the sample.
    gravity_data = []
    for p in season_stats.iter_rows(named=True):
        mpg = p.get("mpg", 0) or 0
        if mpg < 5:
            continue
        fg3_pct = (p.get("fg3_pct", 0) or 0)
        ppg = p.get("ppg", 0) or 0
        ts = (p.get("avg_ts_pct", 0) or 0)
        usg = (p.get("avg_usg_pct", 0) or 0) * 100

        # Raw gravity score components:
        # 1. 3PT threat (accuracy × implied volume)
        three_threat = fg3_pct * (usg / 20)  # Scaled by usage
        # 2. Scoring threat (PPG × efficiency)
        score_threat = (ppg / 30) * ts  # Normalize PPG to 0-1ish
        # 3. Usage premium (high-usage = more attention)
        usage_premium = max(0, (usg - 15) / 20)

        raw_gravity = three_threat * 0.45 + score_threat * 0.35 + usage_premium * 0.20
        gravity_data.append({
            "player_id": p["player_id"],
            "raw_gravity": raw_gravity,
        })

    if gravity_data:
        gdf = pl.DataFrame(gravity_data)
        # Normalize to 0-100
        g_min = gdf["raw_gravity"].min()
        g_max = gdf["raw_gravity"].max()
        g_range = max(g_max - g_min, 0.001)
        gdf = gdf.with_columns(
            ((pl.col("raw_gravity") - g_min) / g_range * 100).round(0).cast(pl.Int32).alias("gravity_score")
        ).drop("raw_gravity")
        df = df.join(gdf, on="player_id", how="left")

    return df.sort("player_name")

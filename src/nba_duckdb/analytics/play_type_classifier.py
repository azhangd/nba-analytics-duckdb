"""Play type classifier.

Classifies possessions into play types based on PBP event sequences.
Rule-based engine that analyzes action patterns within each possession.

Play types (Synergy-style rule-based categories):
- Transition: fast break after turnover/defensive rebound (<7s possession)
- Isolation: single player creates, minimal passing, no screens
- PRBallHandler: pick-and-roll, ball handler action
- PRRollMan: pick-and-roll, roll/pop man action
- Postup: back-to-basket play
- Spotup: catch-and-shoot or one-dribble pull-up
- Cut: basket cut for layup/dunk
- Handoff: dribble handoff action
- OffScreen: coming off screens for shot (non-PnR screen)
- Putback: offensive rebound put-back
- Miscellaneous: unclassifiable

v2: Uses possession_context from parser, improved keyword matching,
    multi-signal scoring instead of first-match.
"""

from collections import defaultdict

import polars as pl

# ─── Keyword banks ──────────────────────────────────────────────────────────
TRANSITION_KEYWORDS = {"fast break", "transition", "fastbreak", "breakaway", "running layup", "running jump", "running dunk", "running finger roll"}
POSTUP_KEYWORDS = {"post up", "hook shot", "turnaround hook", "fadeaway", "turnaround fadeaway", "turnaround jump", "back down", "drop step"}
CUT_KEYWORDS = {"cutting", "cut ", "alley oop", "alley-oop", "lob pass", "cutting layup", "cutting dunk"}
PUTBACK_KEYWORDS = {"putback", "put-back", "tip shot", "tip-in", "tip layup", "tip dunk"}
SCREEN_KEYWORDS = {"screen", "pick and roll", "pick-and-roll", "pnr"}
HANDOFF_KEYWORDS = {"handoff", "hand off", "dribble hand"}
OFF_SCREEN_KEYWORDS = {"off screen", "off-screen", "curl", "flare", "pin down"}
ISO_KEYWORDS = {"step back", "stepback", "crossover", "between the legs", "hesitation"}
CATCH_SHOOT_KEYWORDS = {"catch and shoot", "c&s", "catch-and-shoot", "spot up"}
DUNK_KEYWORDS = {"dunk", "slam", "jam"}
LAYUP_KEYWORDS = {"layup", "lay-up", "driving", "finger roll", "reverse lay"}
PULLUP_KEYWORDS = {"pull-up", "pullup", "pullup jump", "step back jump", "stepback jump"}
DRIVING_KEYWORDS = {"driving layup", "driving dunk", "driving finger roll", "driving floating", "driving hook", "driving reverse"}

TRANSITION_THRESHOLD_SECONDS = 7.0


def classify_possessions(
    possessions_df: pl.DataFrame,
    pbp_df: pl.DataFrame,
) -> pl.DataFrame:
    """Classify each possession into a play type.

    Args:
        possessions_df: Possession DataFrame (from possession_parser)
        pbp_df: Full PBP DataFrame for the same games

    Returns:
        DataFrame with added columns: play_type, play_type_confidence
    """
    if possessions_df.is_empty():
        return possessions_df.with_columns(
            pl.lit("").alias("play_type"),
            pl.lit(0.0).alias("play_type_confidence"),
        )

    # Build PBP events lookup: (game_id, period) -> sorted list of (clock, text)
    pbp_lookup: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    if not pbp_df.is_empty():
        desc_col = "description" if "description" in pbp_df.columns else None
        sub_col = "sub_type" if "sub_type" in pbp_df.columns else None
        for row in pbp_df.iter_rows(named=True):
            gid = row.get("game_id")
            period = row.get("period")
            clock = row.get("clock_seconds_remaining", 0.0) or 0.0
            parts = []
            if desc_col and row.get(desc_col):
                parts.append(str(row[desc_col]))
            if sub_col and row.get(sub_col):
                parts.append(str(row[sub_col]))
            if parts:
                pbp_lookup[(gid, period)].append((clock, " ".join(parts)))
        # Sort each group by clock descending (possessions go start_clock -> end_clock)
        for key in pbp_lookup:
            pbp_lookup[key].sort(key=lambda x: x[0], reverse=True)

    classifications = []

    for row in possessions_df.iter_rows(named=True):
        # Build events_str from PBP data if not already present
        events_str = row.get("events") or ""
        if not events_str and pbp_lookup:
            gid = row.get("game_id")
            period = row.get("period")
            start_clock = row.get("start_clock_seconds", 720.0) or 720.0
            end_clock = row.get("end_clock_seconds", 0.0) or 0.0
            key = (gid, period)
            if key in pbp_lookup:
                matched = [
                    text for clock, text in pbp_lookup[key]
                    if end_clock <= clock <= start_clock
                ]
                events_str = "; ".join(matched[-5:])  # last 5 events
            row = {**row, "events": events_str}

        play_type, confidence = _classify_single(row)
        classifications.append({
            "play_type": play_type,
            "play_type_confidence": confidence,
        })

    class_df = pl.DataFrame(classifications)
    return pl.concat([possessions_df, class_df], how="horizontal_extend")


def _has_any(text: str, keywords: set[str]) -> bool:
    return any(kw in text for kw in keywords)


def _classify_single(possession: dict) -> tuple[str, float]:
    """Classify a single possession using multi-signal scoring."""
    events_str = str(possession.get("events", "")).lower()
    duration = possession.get("duration_seconds", 0.0)
    event_count = possession.get("event_count", 0)
    context = possession.get("possession_context", "half_court")

    # ── 1. Putback — highest priority, very distinct ───────────────────────
    if _has_any(events_str, PUTBACK_KEYWORDS):
        return "Putback", 0.9

    # ── 2. Transition — keyword-based detection only ───────────────────────
    # Note: possession_context="transition" is too broad (set after every defensive
    # rebound, which is ~50% of possessions). Rely on actual PBP keywords instead.
    if _has_any(events_str, TRANSITION_KEYWORDS):
        return "Transition", 0.85
    # Very fast possession after transition opportunity = fast break even without keyword
    if context == "transition" and duration <= 4.0 and event_count <= 2:
        return "Transition", 0.65

    # ── 3. Handoff — dribble handoff action ────────────────────────────────
    if _has_any(events_str, HANDOFF_KEYWORDS):
        return "Handoff", 0.7

    # ── 4. Off-screen — non-PnR screen actions ────────────────────────────
    if _has_any(events_str, OFF_SCREEN_KEYWORDS):
        # If there's a 3PT or jump shot, it's off-screen
        if "3pt" in events_str or "jump shot" in events_str:
            return "OffScreen", 0.7

    # ── 5. Pick-and-Roll — screen + roll/pop ──────────────────────────────
    if _has_any(events_str, SCREEN_KEYWORDS):
        has_rim = _has_any(events_str, LAYUP_KEYWORDS | DUNK_KEYWORDS)
        if has_rim:
            return "PRRollMan", 0.7  # Screen + finish at rim = roll man
        return "PRBallHandler", 0.65  # Screen + perimeter shot = ball handler

    # ── 6. Cut — basket cut for rim finish ────────────────────────────────
    if _has_any(events_str, CUT_KEYWORDS):
        if _has_any(events_str, DUNK_KEYWORDS | LAYUP_KEYWORDS):
            return "Cut", 0.75

    # ── 7. Post-up — back-to-basket ──────────────────────────────────────
    if _has_any(events_str, POSTUP_KEYWORDS):
        return "Postup", 0.7

    # ── 8. Spot-up — catch and shoot ─────────────────────────────────────
    if _has_any(events_str, CATCH_SHOOT_KEYWORDS):
        return "Spotup", 0.8

    # ── 9. Isolation — single-player creation ────────────────────────────
    if _has_any(events_str, ISO_KEYWORDS):
        return "Isolation", 0.7

    # Pull-up with short possession → isolation
    if _has_any(events_str, PULLUP_KEYWORDS):
        if duration <= 10.0 and event_count <= 4:
            return "Isolation", 0.55
        return "Spotup", 0.45

    # Driving plays = isolation/penetration
    if _has_any(events_str, DRIVING_KEYWORDS):
        return "Isolation", 0.55

    # Low event count + longer duration = likely ISO
    if event_count <= 3 and duration > 6.0:
        return "Isolation", 0.35

    # ── 10. Default heuristics ───────────────────────────────────────────
    if "3pt" in events_str:
        return "Spotup", 0.3

    # Note: do NOT default layup/dunk to "Cut" — drives and non-cut rim finishes
    # are far more common than actual cuts, and 0.25 confidence pollutes the data.
    # Let these fall through to Miscellaneous.

    return "Miscellaneous", 0.2

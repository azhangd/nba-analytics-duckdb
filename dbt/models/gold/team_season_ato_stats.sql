{{ config(materialized='table', schema='gold', alias='team_season_ato_stats', tags=['gold_mart']) }}

SELECT *
FROM (
WITH timeouts AS (
    SELECT
        pbp.game_id,
        fg.season,
        pbp.action_number AS timeout_action_number,
        pbp.period,
        pbp.clock_seconds_remaining AS timeout_clock,
        pbp.team_id AS timeout_team_id,
        ABS(
            COALESCE(NULLIF(REGEXP_REPLACE(CAST(pbp.score_home AS TEXT), '[^0-9-]', '', 'g'), '')::INTEGER, 0)
            - COALESCE(NULLIF(REGEXP_REPLACE(CAST(pbp.score_away AS TEXT), '[^0-9-]', '', 'g'), '')::INTEGER, 0)
        ) AS score_margin,
        CASE
            WHEN pbp.period > 4 THEN 1
            WHEN pbp.period = 4
              AND COALESCE(pbp.clock_seconds_remaining, 9999) <= 300
              AND ABS(
                    COALESCE(NULLIF(REGEXP_REPLACE(CAST(pbp.score_home AS TEXT), '[^0-9-]', '', 'g'), '')::INTEGER, 0)
                    - COALESCE(NULLIF(REGEXP_REPLACE(CAST(pbp.score_away AS TEXT), '[^0-9-]', '', 'g'), '')::INTEGER, 0)
                  ) <= 5
            THEN 1
            ELSE 0
        END AS is_clutch_ato
    FROM {{ ref('fct_play_by_play') }} pbp
    JOIN {{ ref('fct_games') }} fg ON fg.game_id = pbp.game_id
    WHERE LOWER(CAST(pbp.action_type AS TEXT)) LIKE '%timeout%'
      AND pbp.team_id IS NOT NULL
      AND pbp.clock_seconds_remaining IS NOT NULL
      AND fg.game_type = 'regular_season'
),
raw_candidate_possessions AS (
    SELECT
        t.*,
        p.possession_number,
        p.start_clock_seconds,
        p.end_clock_seconds,
        p.end_type
    FROM timeouts t
    JOIN {{ ref('fct_possessions') }} p
      ON p.game_id = t.game_id
     AND p.period = t.period
     AND COALESCE(p.is_garbage_time, FALSE) = FALSE
     AND (
          (p.start_clock_seconds <= t.timeout_clock + 0.1 AND p.start_clock_seconds >= t.timeout_clock - 120)
          OR (p.start_clock_seconds >= t.timeout_clock - 0.1 AND p.end_clock_seconds <= t.timeout_clock + 0.1)
     )
),
event_rollup AS (
    SELECT
        r.game_id,
        r.timeout_action_number,
        r.possession_number,
        (ARRAY_AGG(e.team_id ORDER BY e.action_number) FILTER (
            WHERE e.team_id IS NOT NULL
              AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) IN ('2pt', '3pt', 'freethrow', 'turnover', 'steal')
        ))[1] AS first_team_id,
        (ARRAY_AGG(LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) ORDER BY e.action_number) FILTER (
            WHERE e.team_id IS NOT NULL
              AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) IN ('2pt', '3pt', 'freethrow', 'turnover', 'steal')
        ))[1] AS first_action_type,
        SUM(
            CASE
                WHEN e.team_id = r.timeout_team_id
                 AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = '3pt'
                 AND LOWER(COALESCE(CAST(e.shot_result AS TEXT), '')) = 'made' THEN 3
                WHEN e.team_id = r.timeout_team_id
                 AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = '2pt'
                 AND LOWER(COALESCE(CAST(e.shot_result AS TEXT), '')) = 'made' THEN 2
                WHEN e.team_id = r.timeout_team_id
                 AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = 'freethrow'
                 AND LOWER(COALESCE(CAST(e.shot_result AS TEXT), '')) = 'made' THEN 1
                ELSE 0
            END
        ) AS timeout_team_points,
        SUM(
            CASE
                WHEN e.team_id IS NOT NULL
                 AND e.team_id <> r.timeout_team_id
                 AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = '3pt'
                 AND LOWER(COALESCE(CAST(e.shot_result AS TEXT), '')) = 'made' THEN 3
                WHEN e.team_id IS NOT NULL
                 AND e.team_id <> r.timeout_team_id
                 AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = '2pt'
                 AND LOWER(COALESCE(CAST(e.shot_result AS TEXT), '')) = 'made' THEN 2
                WHEN e.team_id IS NOT NULL
                 AND e.team_id <> r.timeout_team_id
                 AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = 'freethrow'
                 AND LOWER(COALESCE(CAST(e.shot_result AS TEXT), '')) = 'made' THEN 1
                ELSE 0
            END
        ) AS opponent_points,
        COUNT(*) FILTER (
            WHERE e.team_id = r.timeout_team_id
              AND LOWER(COALESCE(CAST(e.action_type AS TEXT), '')) = 'turnover'
        ) AS timeout_team_turnovers
    FROM raw_candidate_possessions r
    JOIN {{ ref('fct_play_by_play') }} e
      ON e.game_id = r.game_id
     AND e.period = r.period
     AND e.action_number > r.timeout_action_number
     AND e.clock_seconds_remaining <= LEAST(r.start_clock_seconds, r.timeout_clock) + 0.1
     AND e.clock_seconds_remaining >= r.end_clock_seconds - 0.1
    GROUP BY r.game_id, r.timeout_action_number, r.possession_number
),
candidate_possessions AS (
    SELECT
        r.*,
        ev.first_team_id,
        ev.first_action_type,
        COALESCE(ev.timeout_team_points, 0) AS timeout_team_points,
        COALESCE(ev.opponent_points, 0) AS opponent_points,
        COALESCE(ev.timeout_team_turnovers, 0) AS timeout_team_turnovers,
        ROW_NUMBER() OVER (
            PARTITION BY r.game_id, r.timeout_action_number
            ORDER BY
                CASE WHEN r.start_clock_seconds <= r.timeout_clock + 0.1 THEN 0 ELSE 1 END,
                ABS(r.start_clock_seconds - r.timeout_clock),
                r.possession_number
        ) AS rn
    FROM raw_candidate_possessions r
    JOIN event_rollup ev
      ON ev.game_id = r.game_id
     AND ev.timeout_action_number = r.timeout_action_number
     AND ev.possession_number = r.possession_number
    WHERE ev.first_team_id IS NOT NULL
),
ato_possessions AS (
    SELECT
        *,
        CASE
            WHEN first_action_type = 'steal' AND first_team_id = timeout_team_id THEN 0
            WHEN first_action_type = 'steal' AND first_team_id <> timeout_team_id THEN 1
            WHEN first_team_id = timeout_team_id THEN 1
            ELSE 0
        END AS is_offensive_ato,
        CASE
            WHEN first_action_type = 'steal' AND first_team_id <> timeout_team_id THEN 1
            WHEN timeout_team_turnovers > 0 THEN 1
            ELSE 0
        END AS is_timeout_team_turnover
    FROM candidate_possessions
    WHERE rn = 1
),
team_base AS (
    SELECT
        timeout_team_id AS team_id,
        season,
        COUNT(*)::INTEGER AS timeout_count,
        COUNT(*) FILTER (WHERE is_offensive_ato = 1)::INTEGER AS offensive_ato_possessions,
        COALESCE(SUM(timeout_team_points) FILTER (WHERE is_offensive_ato = 1), 0)::INTEGER AS offensive_ato_points,
        ROUND(
            COALESCE(SUM(timeout_team_points) FILTER (WHERE is_offensive_ato = 1), 0)::NUMERIC
            / NULLIF(COUNT(*) FILTER (WHERE is_offensive_ato = 1), 0),
            3
        )::REAL AS ato_ppp,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE is_offensive_ato = 1 AND timeout_team_points > 0)
            / NULLIF(COUNT(*) FILTER (WHERE is_offensive_ato = 1), 0),
            1
        )::REAL AS ato_score_pct,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE is_offensive_ato = 1 AND is_timeout_team_turnover = 1)
            / NULLIF(COUNT(*) FILTER (WHERE is_offensive_ato = 1), 0),
            1
        )::REAL AS ato_turnover_pct,
        COUNT(*) FILTER (WHERE is_offensive_ato = 1 AND is_clutch_ato = 1)::INTEGER AS clutch_ato_possessions,
        ROUND(
            COALESCE(SUM(timeout_team_points) FILTER (WHERE is_offensive_ato = 1 AND is_clutch_ato = 1), 0)::NUMERIC
            / NULLIF(COUNT(*) FILTER (WHERE is_offensive_ato = 1 AND is_clutch_ato = 1), 0),
            3
        )::REAL AS clutch_ato_ppp,
        COUNT(*) FILTER (WHERE is_offensive_ato = 0)::INTEGER AS defensive_ato_possessions,
        COALESCE(SUM(opponent_points) FILTER (WHERE is_offensive_ato = 0), 0)::INTEGER AS defensive_ato_points_allowed,
        ROUND(
            COALESCE(SUM(opponent_points) FILTER (WHERE is_offensive_ato = 0), 0)::NUMERIC
            / NULLIF(COUNT(*) FILTER (WHERE is_offensive_ato = 0), 0),
            3
        )::REAL AS ato_def_ppp,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE is_offensive_ato = 0 AND opponent_points = 0)
            / NULLIF(COUNT(*) FILTER (WHERE is_offensive_ato = 0), 0),
            1
        )::REAL AS ato_stop_pct
    FROM ato_possessions
    GROUP BY timeout_team_id, season
),
rank_inputs AS (
    SELECT
        team_base.*,
        COUNT(*) FILTER (WHERE offensive_ato_possessions >= 15) OVER (PARTITION BY season) AS qualifying_offense_teams,
        COUNT(*) FILTER (WHERE defensive_ato_possessions >= 15) OVER (PARTITION BY season) AS qualifying_defense_teams,
        CASE
            WHEN offensive_ato_possessions >= 15 THEN RANK() OVER (
                PARTITION BY season
                ORDER BY CASE WHEN offensive_ato_possessions >= 15 THEN ato_ppp END DESC NULLS LAST
            )
        END AS raw_offense_rank,
        CASE
            WHEN defensive_ato_possessions >= 15 THEN RANK() OVER (
                PARTITION BY season
                ORDER BY CASE WHEN defensive_ato_possessions >= 15 THEN ato_def_ppp END ASC NULLS LAST
            )
        END AS raw_defense_rank
    FROM team_base
)
SELECT
    team_id,
    season,
    timeout_count,
    offensive_ato_possessions,
    offensive_ato_points,
    ato_ppp,
    ato_score_pct,
    ato_turnover_pct,
    clutch_ato_possessions,
    clutch_ato_ppp,
    defensive_ato_possessions,
    defensive_ato_points_allowed,
    ato_def_ppp,
    ato_stop_pct,
    raw_offense_rank::INTEGER AS league_ato_ppp_rank,
    raw_defense_rank::INTEGER AS league_ato_def_ppp_rank,
    CASE
        WHEN raw_offense_rank IS NULL OR qualifying_offense_teams <= 1 THEN NULL
        ELSE ROUND(
            (1 - ((raw_offense_rank - 1)::NUMERIC / NULLIF(qualifying_offense_teams - 1, 0))) * 100
        )::INTEGER
    END AS league_ato_ppp_percentile,
    CASE
        WHEN offensive_ato_possessions < 10 THEN 'small offensive ATO sample'
        WHEN defensive_ato_possessions < 10 THEN 'small defensive ATO sample'
        ELSE 'tracked after-timeout possessions'
    END AS sample_note
FROM rank_inputs
) AS model(
    team_id,
    season,
    timeout_count,
    offensive_ato_possessions,
    offensive_ato_points,
    ato_ppp,
    ato_score_pct,
    ato_turnover_pct,
    clutch_ato_possessions,
    clutch_ato_ppp,
    defensive_ato_possessions,
    defensive_ato_points_allowed,
    ato_def_ppp,
    ato_stop_pct,
    league_ato_ppp_rank,
    league_ato_def_ppp_rank,
    league_ato_ppp_percentile,
    sample_note
)

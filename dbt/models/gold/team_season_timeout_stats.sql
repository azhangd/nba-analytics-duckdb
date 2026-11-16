{{ config(materialized='table', schema='gold', alias='team_season_timeout_stats', tags=['gold_mart']) }}

WITH timeouts AS (
    SELECT
        pbp.team_id,
        fg.season,
        period,
        clock_seconds_remaining,
        -- Clutch, as in the other clutch models: the last 5 minutes of the 4th or any
        -- overtime with a margin of 5 or less. A timeout scores no points, so its
        -- row's score is the score before it.
        CASE
            WHEN period >= 4
              AND clock_seconds_remaining <= 300
              AND ABS(CAST(pbp.score_home AS INTEGER) - CAST(pbp.score_away AS INTEGER)) <= 5
            THEN 1
            ELSE 0
        END AS is_clutch_timeout,
        CASE WHEN period = 4 THEN clock_seconds_remaining ELSE NULL END AS q4_clock
    FROM {{ ref('fct_play_by_play') }} pbp
    JOIN {{ ref('fct_games') }} fg ON pbp.game_id = fg.game_id
    WHERE LOWER(CAST(action_type AS TEXT)) LIKE '%timeout%'
      -- A coach's challenge is charged as a timeout but isn't one.
      AND LOWER(COALESCE(pbp.sub_type, '')) NOT LIKE '%challenge%'
      AND pbp.team_id IS NOT NULL
      AND fg.game_type = 'regular_season'
)
SELECT
    team_id,
    season,
    COUNT(*) AS total_timeouts,
    SUM(CASE WHEN period = 1 THEN 1 ELSE 0 END) AS q1_timeouts,
    SUM(CASE WHEN period = 2 THEN 1 ELSE 0 END) AS q2_timeouts,
    SUM(CASE WHEN period = 3 THEN 1 ELSE 0 END) AS q3_timeouts,
    SUM(CASE WHEN period = 4 THEN 1 ELSE 0 END) AS q4_timeouts,
    SUM(CASE WHEN period > 4 THEN 1 ELSE 0 END) AS ot_timeouts,
    SUM(is_clutch_timeout) AS clutch_timeouts,
    ROUND(AVG(q4_clock)::NUMERIC, 1) AS avg_clock_when_called_q4,
    ROUND(
        100.0 * SUM(is_clutch_timeout) / NULLIF(SUM(CASE WHEN period >= 4 THEN 1 ELSE 0 END), 0),
        1
    ) AS clutch_timeout_pct
FROM timeouts
GROUP BY team_id, season

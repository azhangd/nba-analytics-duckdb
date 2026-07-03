{{ config(materialized='table', schema='gold', alias='player_season_clutch_stats', tags=['gold_mart']) }}

SELECT *
FROM (
WITH clutch_events AS (
    SELECT
        pbp.game_id,
        g.season,
        pbp.period,
        pbp.player_id,
        CAST(pbp.player_name AS TEXT) AS player_name,
        pbp.team_id,
        CAST(pbp.action_type AS TEXT) AS action_type,
        CAST(pbp.sub_type AS TEXT) AS sub_type,
        CAST(pbp.description AS TEXT) AS description,
        CAST(pbp.shot_result AS TEXT) AS shot_result,
        pbp.is_field_goal
    FROM {{ ref('fct_play_by_play') }} pbp
    JOIN {{ ref('fct_games') }} g ON pbp.game_id = g.game_id
    WHERE g.game_type = 'regular_season'
      AND pbp.period >= 4
      AND pbp.clock_seconds_remaining <= 300
      AND pbp.player_id IS NOT NULL
      AND NULLIF(CAST(pbp.score_home AS TEXT), '') IS NOT NULL
      AND NULLIF(CAST(pbp.score_away AS TEXT), '') IS NOT NULL
      AND ABS(
            CAST(NULLIF(CAST(pbp.score_home AS TEXT), '') AS INTEGER)
            - CAST(NULLIF(CAST(pbp.score_away AS TEXT), '') AS INTEGER)
          ) <= 5
),
player_agg AS (
    SELECT
        player_id,
        season,
        -- Most recent player_name (by taking max — deterministic tie-break)
        MAX(player_name) AS player_name,
        -- Use the most common team_id for the player
        MODE() WITHIN GROUP (ORDER BY team_id) AS team_id,
        COUNT(DISTINCT game_id) AS clutch_games,
        -- Field goal attempts & makes
        COUNT(*) FILTER (WHERE is_field_goal = true) AS fga,
        COUNT(*) FILTER (WHERE is_field_goal = true AND shot_result = 'Made') AS fgm,
        -- 3-point attempts & makes
        COUNT(*) FILTER (
            WHERE is_field_goal = true
              AND (sub_type ILIKE '%3pt%' OR sub_type ILIKE '%3-pt%' OR sub_type ILIKE '%3 pt%'
                   OR description ILIKE '%3PT%')
        ) AS fg3a,
        COUNT(*) FILTER (
            WHERE is_field_goal = true AND shot_result = 'Made'
              AND (sub_type ILIKE '%3pt%' OR sub_type ILIKE '%3-pt%' OR sub_type ILIKE '%3 pt%'
                   OR description ILIKE '%3PT%')
        ) AS fg3m,
        -- Free throw attempts & makes
        COUNT(*) FILTER (
            WHERE action_type ILIKE '%free%throw%' OR action_type ILIKE '%freethrow%'
        ) AS fta,
        COUNT(*) FILTER (
            WHERE (action_type ILIKE '%free%throw%' OR action_type ILIKE '%freethrow%')
              AND shot_result = 'Made'
        ) AS ftm,
        -- Turnovers
        COUNT(*) FILTER (WHERE action_type ILIKE '%turnover%') AS turnovers
    FROM clutch_events
    GROUP BY player_id, season
    HAVING COUNT(DISTINCT game_id) >= 2
)
SELECT
    player_id,
    season,
    player_name,
    team_id,
    clutch_games,
    fga,
    fgm,
    fg3a,
    fg3m,
    fta,
    ftm,
    turnovers,
    -- Points: 2pt made = (fgm - fg3m)*2, 3pt made = fg3m*3, ft made = ftm*1
    (fgm - fg3m) * 2 + fg3m * 3 + ftm AS points,
    -- Derived percentages
    ROUND(fgm::NUMERIC / NULLIF(fga, 0), 3)::REAL AS fg_pct,
    ROUND(fg3m::NUMERIC / NULLIF(fg3a, 0), 3)::REAL AS fg3_pct,
    ROUND(ftm::NUMERIC / NULLIF(fta, 0), 3)::REAL AS ft_pct,
    -- Clutch PPG
    ROUND(((fgm - fg3m) * 2 + fg3m * 3 + ftm)::NUMERIC / NULLIF(clutch_games, 0), 2)::REAL AS clutch_ppg,
    -- True shooting percentage: pts / (2 * (fga + 0.44 * fta))
    ROUND(
        ((fgm - fg3m) * 2 + fg3m * 3 + ftm)::NUMERIC
        / NULLIF(2.0 * (fga + 0.44 * fta), 0),
        3
    )::REAL AS clutch_ts_pct
FROM player_agg
ORDER BY season, ((fgm - fg3m) * 2 + fg3m * 3 + ftm)::NUMERIC / NULLIF(clutch_games, 0) DESC
) AS model(
    player_id,
    season,
    player_name,
    team_id,
    clutch_games,
    fga,
    fgm,
    fg3a,
    fg3m,
    fta,
    ftm,
    turnovers,
    points,
    fg_pct,
    fg3_pct,
    ft_pct,
    clutch_ppg,
    clutch_ts_pct
)

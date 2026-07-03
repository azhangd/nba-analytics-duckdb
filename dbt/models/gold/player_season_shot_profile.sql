{{ config(materialized='table', schema='gold', alias='player_season_shot_profile', tags=['gold_mart']) }}

SELECT *
FROM (
WITH classified AS (
    SELECT *,
        CASE
            WHEN CAST(shot_zone_basic AS TEXT) IN ('Restricted Area', 'In The Paint (Non-RA)') THEN 'paint_2'
            WHEN CAST(shot_type AS TEXT) LIKE '%3PT%' THEN 'three'
            ELSE 'non_paint_2'
        END AS shot_bucket
    FROM {{ ref('fct_shots') }}
),
player_agg AS (
    SELECT team_id, season, player_id,
        MAX(player_name) AS player_name,
        shot_bucket,
        COUNT(*) AS attempts,
        SUM(shot_made::INT) AS makes
    FROM classified
    WHERE team_id IS NOT NULL AND player_id IS NOT NULL
    GROUP BY team_id, season, player_id, shot_bucket
),
player_total AS (
    SELECT team_id, season, player_id, SUM(attempts) AS total
    FROM player_agg GROUP BY team_id, season, player_id
)
SELECT a.team_id, a.season, a.player_id, a.player_name, a.shot_bucket, a.attempts, a.makes,
    CASE WHEN a.attempts > 0 THEN ROUND(a.makes::NUMERIC / a.attempts * 100, 1) END,
    ROUND(a.attempts::NUMERIC / t.total * 100, 1)
FROM player_agg a
JOIN player_total t ON a.team_id = t.team_id AND a.season = t.season AND a.player_id = t.player_id
) AS model(
    team_id,
    season,
    player_id,
    player_name,
    shot_bucket,
    attempts,
    makes,
    fg_pct,
    freq_pct
)

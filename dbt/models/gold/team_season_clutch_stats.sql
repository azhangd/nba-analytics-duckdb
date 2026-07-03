{{ config(materialized='table', schema='gold', alias='team_season_clutch_stats', tags=['gold_mart']) }}

SELECT *
FROM (
SELECT
    offense_team_id,
    fg.season,
    COUNT(*) AS clutch_possessions,
    SUM(points_scored) AS clutch_points,
    ROUND(AVG(points_scored)::NUMERIC, 3) AS clutch_ppp,
    SUM(CASE WHEN end_type = 'turnover' THEN 1 ELSE 0 END) AS clutch_turnovers
FROM {{ ref('fct_possessions') }} fp
JOIN {{ ref('fct_games') }} fg ON fp.game_id = fg.game_id
WHERE offense_team_id IS NOT NULL
  AND fg.game_type = 'regular_season'
  AND period >= 4
  AND start_clock_seconds <= 300
  AND ABS(score_margin) <= 5
  AND NOT is_garbage_time
GROUP BY offense_team_id, fg.season
) AS model(
    offense_team_id,
    season,
    clutch_possessions,
    clutch_points,
    clutch_ppp,
    clutch_turnovers
)

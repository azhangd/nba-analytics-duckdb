{{ config(materialized='table', schema='gold', alias='player_season_load_management', tags=['gold_mart']) }}

SELECT *
FROM (
SELECT
    player_id,
    fg.season,
    mode() WITHIN GROUP (ORDER BY player_name) AS player_name,
    mode() WITHIN GROUP (ORDER BY team_id) AS team_id,
    COUNT(*) AS games_played,
    ROUND(SUM(minutes)::NUMERIC, 0) AS total_minutes,
    ROUND(AVG(minutes)::NUMERIC, 1) AS avg_minutes,
    ROUND(MAX(minutes)::NUMERIC, 1) AS max_minutes,
    ROUND(MIN(minutes)::NUMERIC, 1) AS min_minutes,
    ROUND(STDDEV(minutes)::NUMERIC, 1) AS minutes_stddev,
    SUM(CASE WHEN minutes > 36 THEN 1 ELSE 0 END) AS high_minute_games,
    AVG(minutes) > 34.0 AS high_workload_flag
FROM {{ ref('fct_boxscores') }} fb
JOIN {{ ref('fct_games') }} fg ON fb.game_id = fg.game_id
WHERE fb.minutes > 0
  AND fg.game_type = 'regular_season'
GROUP BY player_id, fg.season
ORDER BY fg.season, total_minutes DESC
) AS model(
    player_id,
    season,
    player_name,
    team_id,
    games_played,
    total_minutes,
    avg_minutes,
    max_minutes,
    min_minutes,
    minutes_stddev,
    high_minute_games,
    high_workload_flag
)

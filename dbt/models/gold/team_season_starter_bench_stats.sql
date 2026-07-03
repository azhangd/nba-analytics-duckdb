{{ config(materialized='table', schema='gold', alias='team_season_starter_bench_stats', tags=['gold_mart']) }}

SELECT *
FROM (
SELECT
    fb.team_id,
    fg.season,
    CASE WHEN fb.started THEN 'starter' ELSE 'bench' END AS role,
    COUNT(DISTINCT fb.game_id) AS games,
    ROUND(AVG(fb.pts)::NUMERIC, 1),
    ROUND(AVG(fb.reb)::NUMERIC, 1),
    ROUND(AVG(fb.ast)::NUMERIC, 1),
    ROUND(AVG(fb.minutes)::NUMERIC, 1),
    CASE WHEN SUM(fb.fga) > 0 THEN ROUND(SUM(fb.fgm)::NUMERIC / SUM(fb.fga) * 100, 1) END,
    CASE WHEN SUM(fb.fga) + SUM(fb.fta) > 0 THEN
        ROUND(SUM(fb.pts)::NUMERIC / (2.0 * (SUM(fb.fga) + 0.44 * SUM(fb.fta))) * 100, 1)
    END,
    ROUND(AVG(fb.plus_minus)::NUMERIC, 1)
FROM {{ ref('fct_boxscores') }} fb
JOIN {{ ref('fct_games') }} fg ON fb.game_id = fg.game_id
WHERE fb.minutes > 0
  AND fg.game_type = 'regular_season'
GROUP BY fb.team_id, fg.season, fb.started
ORDER BY fg.season, fb.team_id, fb.started DESC
) AS model(
    team_id,
    season,
    role,
    games,
    ppg,
    rpg,
    apg,
    mpg,
    fg_pct,
    ts_pct,
    plus_minus
)

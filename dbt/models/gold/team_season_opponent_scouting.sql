{{ config(materialized='table', schema='gold', alias='team_season_opponent_scouting', tags=['gold_mart']) }}

SELECT *
FROM (
WITH game_rows AS (
    -- Home perspective
    SELECT
        home_team_id AS team_id,
        season,
        away_team_id AS opponent_id,
        home_score AS our_score,
        away_score AS opp_score,
        (home_score > away_score)::INT AS won
    FROM {{ ref('fct_games') }}
    WHERE status = 'Final' AND game_type = 'regular_season'
    UNION ALL
    -- Away perspective
    SELECT
        away_team_id, season, home_team_id,
        away_score, home_score,
        (away_score > home_score)::INT
    FROM {{ ref('fct_games') }}
    WHERE status = 'Final' AND game_type = 'regular_season'
)
SELECT
    g.team_id, g.season, g.opponent_id,
    COUNT(*) AS games_played,
    SUM(g.won) AS wins,
    COUNT(*) - SUM(g.won) AS losses,
    ROUND(AVG(g.our_score)::NUMERIC, 1),
    ROUND(AVG(g.opp_score)::NUMERIC, 1),
    ROUND(AVG(g.our_score - g.opp_score)::NUMERIC, 1),
    t.abbreviation,
    t.full_name
FROM game_rows g
JOIN {{ ref('dim_teams') }} t ON g.opponent_id = t.team_id
WHERE g.team_id BETWEEN 1610612737 AND 1610612766
  AND g.opponent_id BETWEEN 1610612737 AND 1610612766
GROUP BY g.team_id, g.season, g.opponent_id, t.abbreviation, t.full_name
ORDER BY g.season, games_played DESC
) AS model(
    team_id,
    season,
    opponent_id,
    games_played,
    wins,
    losses,
    avg_pts_for,
    avg_pts_against,
    avg_margin,
    opp_abbr,
    opp_name
)

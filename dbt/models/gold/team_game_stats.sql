{{ config(materialized='table', schema='gold', alias='team_game_stats', tags=['gold']) }}

WITH team_boxscores AS (
    SELECT
        CAST(game_id AS TEXT) AS game_id,
        team_id,
        SUM(COALESCE(pts, 0)) AS pts,
        SUM(COALESCE(fga, 0)) AS fga,
        SUM(COALESCE(fta, 0)) AS fta,
        SUM(COALESCE(oreb, 0)) AS oreb,
        SUM(COALESCE(tov, 0)) AS tov
    FROM {{ ref('fct_boxscores') }}
    WHERE minutes > 0
      AND COALESCE(CAST(game_id AS TEXT), '') NOT LIKE '001%'
    GROUP BY CAST(game_id AS TEXT), team_id
),
valid_games AS (
    SELECT game_id
    FROM team_boxscores
    GROUP BY game_id
    HAVING COUNT(*) = 2
),
team_with_opponent AS (
    SELECT
        team_boxscores.game_id,
        team_boxscores.team_id,
        team_boxscores.pts,
        opponent.pts AS opp_pts,
        GREATEST(
            team_boxscores.fga - team_boxscores.oreb + team_boxscores.tov + 0.44 * team_boxscores.fta,
            1.0
        ) AS possessions,
        GREATEST(
            opponent.fga - opponent.oreb + opponent.tov + 0.44 * opponent.fta,
            1.0
        ) AS opponent_possessions
    FROM team_boxscores
    JOIN valid_games
        ON team_boxscores.game_id = valid_games.game_id
    JOIN team_boxscores AS opponent
        ON team_boxscores.game_id = opponent.game_id
       AND team_boxscores.team_id <> opponent.team_id
)
SELECT
    team_with_opponent.game_id,
    CAST(team_with_opponent.team_id AS INTEGER) AS team_id,
    COALESCE(CAST(games.season AS TEXT), '') AS season,
    COALESCE(CAST(games.game_date AS TEXT), '') AS game_date,
    COALESCE(CAST(games.game_type AS TEXT), 'regular_season') AS game_type,
    CAST(team_with_opponent.pts AS INTEGER) AS pts,
    CAST(team_with_opponent.opp_pts AS INTEGER) AS opp_pts,
    CAST(team_with_opponent.pts - team_with_opponent.opp_pts AS INTEGER) AS margin,
    team_with_opponent.pts > team_with_opponent.opp_pts AS is_win,
    ROUND(team_with_opponent.pts / team_with_opponent.possessions * 100, 1) AS off_rtg,
    ROUND(team_with_opponent.opp_pts / team_with_opponent.opponent_possessions * 100, 1) AS def_rtg,
    ROUND(
        (
            team_with_opponent.pts / team_with_opponent.possessions
            - team_with_opponent.opp_pts / team_with_opponent.opponent_possessions
        ) * 100,
        1
    ) AS net_rtg
FROM team_with_opponent
JOIN {{ ref('fct_games') }} AS games
    ON team_with_opponent.game_id = games.game_id

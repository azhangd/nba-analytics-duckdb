{{ config(materialized='table', schema='gold', alias='team_game_stats', tags=['gold']) }}

WITH team_boxscores AS (
    SELECT
        CAST(game_id AS TEXT) AS game_id,
        team_id,
        SUM(COALESCE(pts, 0)) AS pts,
        SUM(COALESCE(fgm, 0)) AS fgm,
        SUM(COALESCE(fga, 0)) AS fga,
        SUM(COALESCE(fg3m, 0)) AS fg3m,
        SUM(COALESCE(ftm, 0)) AS ftm,
        SUM(COALESCE(fta, 0)) AS fta,
        SUM(COALESCE(oreb, 0)) AS oreb,
        SUM(COALESCE(dreb, 0)) AS dreb,
        SUM(minutes) AS minutes
    FROM {{ ref('fct_boxscores') }}
    WHERE minutes > 0
      AND CAST(game_id AS TEXT) LIKE '002%'
    GROUP BY CAST(game_id AS TEXT), team_id
),
valid_games AS (
    SELECT game_id
    FROM team_boxscores
    GROUP BY game_id
    HAVING COUNT(*) = 2
),
-- Player box scores leave out team turnovers (shot clock, 8 seconds and so
-- on), so team turnovers are counted from the play-by-play. A game without
-- play-by-play gets NULL turnovers rather than zero.
games_with_plays AS (
    SELECT DISTINCT CAST(game_id AS TEXT) AS game_id
    FROM {{ ref('fct_play_by_play') }}
),
play_turnovers AS (
    SELECT CAST(game_id AS TEXT) AS game_id, team_id, COUNT(*) AS tov
    FROM {{ ref('fct_play_by_play') }}
    WHERE action_type = 'turnover'
    GROUP BY CAST(game_id AS TEXT), team_id
),
team_totals AS (
    SELECT
        team_boxscores.*,
        CASE
            WHEN games_with_plays.game_id IS NOT NULL THEN COALESCE(play_turnovers.tov, 0)
        END AS tov
    FROM team_boxscores
    JOIN valid_games
        ON team_boxscores.game_id = valid_games.game_id
    LEFT JOIN games_with_plays
        ON team_boxscores.game_id = games_with_plays.game_id
    LEFT JOIN play_turnovers
        ON team_boxscores.game_id = play_turnovers.game_id
       AND team_boxscores.team_id = play_turnovers.team_id
),
team_with_opponent AS (
    SELECT
        team.*,
        opponent.pts AS opp_pts,
        -- Basketball-Reference's estimate: the average of both teams' possessions.
        0.5 * (
            (
                team.fga + 0.4 * team.fta
                - 1.07 * (team.oreb / NULLIF(team.oreb + opponent.dreb, 0)) * (team.fga - team.fgm)
                + team.tov
            )
            + (
                opponent.fga + 0.4 * opponent.fta
                - 1.07 * (opponent.oreb / NULLIF(opponent.oreb + team.dreb, 0)) * (opponent.fga - opponent.fgm)
                + opponent.tov
            )
        ) AS possessions
    FROM team_totals AS team
    JOIN team_totals AS opponent
        ON team.game_id = opponent.game_id
       AND team.team_id <> opponent.team_id
)
SELECT
    team_with_opponent.game_id,
    CAST(team_with_opponent.team_id AS INTEGER) AS team_id,
    COALESCE(CAST(games.season AS TEXT), '') AS season,
    games.game_date,
    CAST(team_with_opponent.pts AS INTEGER) AS pts,
    CAST(team_with_opponent.opp_pts AS INTEGER) AS opp_pts,
    CAST(team_with_opponent.pts - team_with_opponent.opp_pts AS INTEGER) AS margin,
    team_with_opponent.pts > team_with_opponent.opp_pts AS is_win,
    ROUND(team_with_opponent.pts / team_with_opponent.possessions * 100, 1) AS off_rtg,
    ROUND(team_with_opponent.opp_pts / team_with_opponent.possessions * 100, 1) AS def_rtg,
    ROUND((team_with_opponent.pts - team_with_opponent.opp_pts) / team_with_opponent.possessions * 100, 1) AS net_rtg,
    team_with_opponent.possessions,
    team_with_opponent.minutes,
    CAST(team_with_opponent.fgm AS INTEGER) AS fgm,
    CAST(team_with_opponent.fga AS INTEGER) AS fga,
    CAST(team_with_opponent.fg3m AS INTEGER) AS fg3m,
    CAST(team_with_opponent.ftm AS INTEGER) AS ftm,
    CAST(team_with_opponent.fta AS INTEGER) AS fta,
    CAST(team_with_opponent.oreb AS INTEGER) AS oreb,
    CAST(team_with_opponent.dreb AS INTEGER) AS dreb,
    CAST(team_with_opponent.tov AS INTEGER) AS tov
FROM team_with_opponent
JOIN {{ ref('fct_games') }} AS games
    ON team_with_opponent.game_id = games.game_id

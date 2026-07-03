{{ config(materialized='table', schema='gold', alias='lineup_season_stats', tags=['gold']) }}

WITH stints AS (
    SELECT
        lineups.team_id,
        games.season,
        (
            SELECT string_agg(token, ',' ORDER BY TRY_CAST(token AS INTEGER))
            FROM unnest(
                regexp_split_to_array(
                    regexp_replace(TRIM(BOTH '-,' FROM CAST(lineups.player_ids_str AS TEXT)), '-', ',', 'g'),
                    ','
                )
            ) AS split(token)
            WHERE token <> ''
        ) AS player_ids_str,
        CAST(lineups.duration_seconds AS DOUBLE) AS duration_seconds,
        CAST(COALESCE(lineups.points_for, 0) AS INTEGER) AS points_for,
        CAST(COALESCE(lineups.points_against, 0) AS INTEGER) AS points_against
    FROM {{ ref('fct_lineups') }} AS lineups
    JOIN {{ ref('fct_games') }} AS games
        ON lineups.game_id = games.game_id
    WHERE lineups.player_count >= 5
      AND lineups.duration_seconds > 0
      AND games.game_type = 'regular_season'
)
SELECT
    team_id,
    season,
    player_ids_str,
    COUNT(*) AS stints,
    ROUND(SUM(duration_seconds) / 60.0, 1) AS total_minutes,
    CAST(SUM(points_for) AS INTEGER) AS total_pts_for,
    CAST(SUM(points_against) AS INTEGER) AS total_pts_against,
    CAST(SUM(points_for) - SUM(points_against) AS INTEGER) AS net_points,
    CASE
        WHEN ROUND(SUM(duration_seconds) / 60.0, 1) > 0
            THEN ROUND(
                (SUM(points_for) - SUM(points_against))
                / ROUND(SUM(duration_seconds) / 60.0, 1)
                * 48.0,
                1
            )
    END AS net_rating_per_48
FROM stints
GROUP BY team_id, season, player_ids_str
ORDER BY season, team_id, net_rating_per_48 DESC

{{ config(materialized='table', schema='gold', alias='player_game_stats', tags=['gold']) }}

WITH shot_splits AS (
    SELECT
        CAST(game_id AS TEXT) AS game_id,
        player_id,
        SUM(CASE WHEN CAST(shot_zone_basic AS TEXT) IN ('Restricted Area', 'In The Paint (Non-RA)') THEN 1 ELSE 0 END) AS paint_attempts,
        SUM(CASE WHEN CAST(shot_zone_basic AS TEXT) IN ('Restricted Area', 'In The Paint (Non-RA)') AND COALESCE(shot_made, FALSE) THEN 1 ELSE 0 END) AS paint_makes,
        SUM(CASE WHEN CAST(shot_type AS TEXT) LIKE '%3PT%' THEN 1 ELSE 0 END) AS three_attempts,
        SUM(CASE WHEN CAST(shot_type AS TEXT) LIKE '%3PT%' AND COALESCE(shot_made, FALSE) THEN 1 ELSE 0 END) AS three_makes,
        SUM(CASE WHEN CAST(shot_zone_basic AS TEXT) = 'Mid-Range' THEN 1 ELSE 0 END) AS midrange_attempts,
        SUM(CASE WHEN CAST(shot_zone_basic AS TEXT) = 'Mid-Range' AND COALESCE(shot_made, FALSE) THEN 1 ELSE 0 END) AS midrange_makes
    FROM {{ ref('fct_shots') }}
    WHERE CAST(game_id AS TEXT) LIKE '002%'
      AND player_id IS NOT NULL
    GROUP BY CAST(game_id AS TEXT), player_id
)
SELECT
    CAST(boxscores.game_id AS TEXT) AS game_id,
    boxscores.player_id,
    boxscores.team_id,
    boxscores.player_name,
    boxscores.started,
    boxscores.counts_as_gp,
    boxscores.minutes,
    boxscores.fgm,
    boxscores.fga,
    boxscores.fg3m,
    boxscores.fg3a,
    boxscores.ftm,
    boxscores.fta,
    boxscores.oreb,
    boxscores.dreb,
    boxscores.reb,
    boxscores.ast,
    boxscores.stl,
    boxscores.blk,
    boxscores.tov,
    boxscores.pf,
    boxscores.pts,
    boxscores.plus_minus,
    boxscores.off_rating,
    boxscores.def_rating,
    boxscores.net_rating,
    boxscores.usg_pct,
    boxscores.ts_pct,
    boxscores.pace,
    COALESCE(shot_splits.paint_makes, 0) AS paint_makes,
    COALESCE(shot_splits.paint_attempts, 0) AS paint_attempts,
    COALESCE(shot_splits.three_makes, 0) AS three_makes,
    COALESCE(shot_splits.three_attempts, 0) AS three_attempts,
    COALESCE(shot_splits.midrange_makes, 0) AS midrange_makes,
    COALESCE(shot_splits.midrange_attempts, 0) AS midrange_attempts,
    ROUND(
        COALESCE(boxscores.pts, 0)
        + 0.4 * COALESCE(boxscores.fgm, 0)
        - 0.7 * COALESCE(boxscores.fga, 0)
        - 0.4 * (COALESCE(boxscores.fta, 0) - COALESCE(boxscores.ftm, 0))
        + 0.7 * COALESCE(boxscores.oreb, 0)
        + 0.3 * COALESCE(boxscores.dreb, 0)
        + COALESCE(boxscores.stl, 0)
        + 0.7 * COALESCE(boxscores.ast, 0)
        + 0.7 * COALESCE(boxscores.blk, 0)
        - 0.4 * COALESCE(boxscores.pf, 0)
        - COALESCE(boxscores.tov, 0),
        1
    ) AS game_score
FROM {{ ref('fct_boxscores') }} AS boxscores
LEFT JOIN shot_splits
    ON CAST(boxscores.game_id AS TEXT) = shot_splits.game_id
   AND boxscores.player_id = shot_splits.player_id
WHERE CAST(boxscores.game_id AS TEXT) LIKE '002%'
  AND boxscores.player_id IS NOT NULL

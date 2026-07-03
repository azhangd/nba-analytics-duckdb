{{ config(materialized='table', schema='gold', alias='player_season_split_stats', tags=['gold']) }}

WITH base AS (
    SELECT
        stats.player_id,
        games.season,
        stats.player_name,
        stats.team_id,
        stats.game_id,
        CAST(stats.minutes AS DOUBLE) AS minutes,
        CAST(COALESCE(stats.pts, 0) AS DOUBLE) AS pts,
        CAST(COALESCE(stats.reb, 0) AS DOUBLE) AS reb,
        CAST(COALESCE(stats.ast, 0) AS DOUBLE) AS ast,
        CAST(COALESCE(stats.stl, 0) AS DOUBLE) AS stl,
        CAST(COALESCE(stats.blk, 0) AS DOUBLE) AS blk,
        CAST(COALESCE(stats.tov, 0) AS DOUBLE) AS tov,
        CAST(COALESCE(stats.fgm, 0) AS DOUBLE) AS fgm,
        CAST(COALESCE(stats.fga, 0) AS DOUBLE) AS fga,
        CAST(COALESCE(stats.fg3m, 0) AS DOUBLE) AS fg3m,
        CAST(COALESCE(stats.fg3a, 0) AS DOUBLE) AS fg3a,
        CAST(COALESCE(stats.ftm, 0) AS DOUBLE) AS ftm,
        CAST(COALESCE(stats.fta, 0) AS DOUBLE) AS fta,
        CAST(COALESCE(stats.usg_pct, 0) AS DOUBLE) AS usg_pct,
        CAST(COALESCE(stats.plus_minus, 0) AS DOUBLE) AS plus_minus,
        CAST(COALESCE(stats.net_rating, 0) AS DOUBLE) AS net_rating,
        CAST(COALESCE(stats.game_score, 0) AS DOUBLE) AS game_score,
        games.home_team_id,
        games.away_team_id,
        games.home_score,
        games.away_score,
        try_strptime(
            CAST(games.game_date AS TEXT),
            ['%m/%d/%Y %H:%M:%S', '%m/%d/%Y', '%Y-%m-%d', '%Y%m%d']
        ) AS game_date_parsed
    FROM {{ ref('player_game_stats') }} AS stats
    JOIN {{ ref('fct_games') }} AS games
        ON stats.game_id = games.game_id
    WHERE games.game_type = 'regular_season'
),
with_context AS (
    SELECT
        *,
        CASE WHEN team_id = home_team_id THEN 'Home' ELSE 'Away' END AS home_away,
        CASE
            WHEN (
                (team_id = home_team_id AND home_score > away_score)
                OR (team_id <> home_team_id AND away_score > home_score)
            ) THEN 'Win'
            ELSE 'Loss'
        END AS win_loss,
        CASE
            WHEN ABS(
                CASE
                    WHEN team_id = home_team_id THEN home_score - away_score
                    ELSE away_score - home_score
                END
            ) <= 5 THEN 'Close'
            WHEN (
                CASE
                    WHEN team_id = home_team_id THEN home_score - away_score
                    ELSE away_score - home_score
                END
            ) > 5 THEN 'Won Big'
            ELSE 'Lost Big'
        END AS score_context,
        CASE strftime(game_date_parsed, '%m')
            WHEN '01' THEN 'Jan'
            WHEN '02' THEN 'Feb'
            WHEN '03' THEN 'Mar'
            WHEN '04' THEN 'Apr'
            WHEN '05' THEN 'May'
            WHEN '06' THEN 'Jun'
            WHEN '10' THEN 'Oct'
            WHEN '11' THEN 'Nov'
            WHEN '12' THEN 'Dec'
            ELSE 'Other'
        END AS month,
        LAG(game_date_parsed) OVER (
            PARTITION BY player_id, season
            ORDER BY game_date_parsed, game_id
        ) AS prev_game_date
    FROM base
),
with_rest AS (
    SELECT
        *,
        CASE
            WHEN prev_game_date IS NULL THEN 'First Game'
            WHEN date_diff('day', prev_game_date, game_date_parsed) <= 1 THEN 'B2B'
            ELSE 'Rested'
        END AS rest_category
    FROM with_context
),
split_rows AS (
    SELECT *, 'home_away' AS split_type, home_away AS split_value FROM with_rest
    UNION ALL
    SELECT *, 'win_loss' AS split_type, win_loss AS split_value FROM with_rest
    UNION ALL
    SELECT *, 'score_context' AS split_type, score_context AS split_value FROM with_rest
    UNION ALL
    SELECT *, 'month' AS split_type, month AS split_value FROM with_rest
    UNION ALL
    SELECT *, 'rest_days' AS split_type, rest_category AS split_value FROM with_rest
)
SELECT
    player_id,
    season,
    MAX(player_name) AS player_name,
    team_id,
    split_type,
    CAST(split_value AS TEXT) AS split_value,
    COUNT(*) AS games,
    ROUND(AVG(minutes), 1) AS minutes,
    ROUND(AVG(pts), 1) AS ppg,
    ROUND(AVG(reb), 1) AS rpg,
    ROUND(AVG(ast), 1) AS apg,
    ROUND(AVG(stl), 1) AS spg,
    ROUND(AVG(blk), 1) AS bpg,
    ROUND(AVG(tov), 1) AS topg,
    ROUND(SUM(fgm) / NULLIF(SUM(fga), 0), 3) AS fg_pct,
    ROUND(SUM(fg3m) / NULLIF(SUM(fg3a), 0), 3) AS fg3_pct,
    ROUND(SUM(ftm) / NULLIF(SUM(fta), 0), 3) AS ft_pct,
    ROUND(SUM(pts) / NULLIF(2.0 * (SUM(fga) + 0.44 * SUM(fta)), 0), 3) AS ts_pct,
    ROUND(AVG(usg_pct), 3) AS usg_pct,
    ROUND(AVG(plus_minus), 1) AS plus_minus,
    ROUND(AVG(net_rating), 1) AS net_rating,
    ROUND(AVG(game_score), 1) AS game_score
FROM split_rows
WHERE split_value IS NOT NULL
GROUP BY player_id, season, team_id, split_type, split_value

{{ config(materialized='table', schema='gold', alias='player_game_rolling_stats', tags=['gold']) }}

WITH base AS (
    SELECT
        stats.player_id,
        games.season,
        stats.game_id,
        games.game_date,
        stats.team_id,
        ROW_NUMBER() OVER (
            PARTITION BY stats.player_id, games.season
            ORDER BY games.game_date, stats.game_id
        ) AS game_number,
        CAST(COALESCE(stats.pts, 0) AS DOUBLE) AS pts,
        CAST(COALESCE(stats.reb, 0) AS DOUBLE) AS reb,
        CAST(COALESCE(stats.ast, 0) AS DOUBLE) AS ast,
        CAST(COALESCE(stats.stl, 0) AS DOUBLE) AS stl,
        CAST(COALESCE(stats.blk, 0) AS DOUBLE) AS blk,
        CAST(COALESCE(stats.fgm, 0) AS DOUBLE) AS fgm,
        CAST(COALESCE(stats.fga, 0) AS DOUBLE) AS fga,
        CAST(COALESCE(stats.fg3m, 0) AS DOUBLE) AS fg3m,
        CAST(COALESCE(stats.fg3a, 0) AS DOUBLE) AS fg3a,
        CAST(COALESCE(stats.ftm, 0) AS DOUBLE) AS ftm,
        CAST(COALESCE(stats.fta, 0) AS DOUBLE) AS fta,
        CAST(COALESCE(stats.plus_minus, 0) AS DOUBLE) AS plus_minus,
        CAST(COALESCE(stats.minutes, 0) AS DOUBLE) AS minutes,
        CAST(stats.usg_pct AS DOUBLE) AS usg_pct,
        CAST(stats.net_rating AS DOUBLE) AS net_rating,
        CAST(stats.game_score AS DOUBLE) AS game_score,
        CAST(COALESCE(stats.fga, 0) AS DOUBLE) + 0.44 * CAST(COALESCE(stats.fta, 0) AS DOUBLE) AS tsa
    FROM {{ ref('player_game_stats') }} AS stats
    JOIN {{ ref('fct_games') }} AS games
        ON stats.game_id = games.game_id
    WHERE games.game_type = 'regular_season'
),
rolled AS (
    SELECT
        *,
        AVG(pts) OVER w3 AS l3_ppg,
        AVG(reb) OVER w3 AS l3_rpg,
        AVG(ast) OVER w3 AS l3_apg,
        AVG(stl) OVER w3 AS l3_spg,
        AVG(blk) OVER w3 AS l3_bpg,
        SUM(fgm) OVER w3 / NULLIF(SUM(fga) OVER w3, 0) AS l3_fg_pct,
        SUM(fg3m) OVER w3 / NULLIF(SUM(fg3a) OVER w3, 0) AS l3_fg3_pct,
        SUM(ftm) OVER w3 / NULLIF(SUM(fta) OVER w3, 0) AS l3_ft_pct,
        SUM(pts) OVER w3 / NULLIF(2.0 * SUM(tsa) OVER w3, 0) AS l3_ts_pct,
        AVG(usg_pct) OVER w3 AS l3_usg_pct,
        AVG(plus_minus) OVER w3 AS l3_plus_minus,
        AVG(net_rating) OVER w3 AS l3_net_rtg,
        AVG(game_score) OVER w3 AS l3_game_score,
        AVG(minutes) OVER w3 AS l3_minutes,

        AVG(pts) OVER w5 AS l5_ppg,
        AVG(reb) OVER w5 AS l5_rpg,
        AVG(ast) OVER w5 AS l5_apg,
        AVG(stl) OVER w5 AS l5_spg,
        AVG(blk) OVER w5 AS l5_bpg,
        SUM(fgm) OVER w5 / NULLIF(SUM(fga) OVER w5, 0) AS l5_fg_pct,
        SUM(fg3m) OVER w5 / NULLIF(SUM(fg3a) OVER w5, 0) AS l5_fg3_pct,
        SUM(ftm) OVER w5 / NULLIF(SUM(fta) OVER w5, 0) AS l5_ft_pct,
        SUM(pts) OVER w5 / NULLIF(2.0 * SUM(tsa) OVER w5, 0) AS l5_ts_pct,
        AVG(usg_pct) OVER w5 AS l5_usg_pct,
        AVG(plus_minus) OVER w5 AS l5_plus_minus,
        AVG(net_rating) OVER w5 AS l5_net_rtg,
        AVG(game_score) OVER w5 AS l5_game_score,
        AVG(minutes) OVER w5 AS l5_minutes,

        AVG(pts) OVER w10 AS l10_ppg,
        AVG(reb) OVER w10 AS l10_rpg,
        AVG(ast) OVER w10 AS l10_apg,
        AVG(stl) OVER w10 AS l10_spg,
        AVG(blk) OVER w10 AS l10_bpg,
        SUM(fgm) OVER w10 / NULLIF(SUM(fga) OVER w10, 0) AS l10_fg_pct,
        SUM(fg3m) OVER w10 / NULLIF(SUM(fg3a) OVER w10, 0) AS l10_fg3_pct,
        SUM(ftm) OVER w10 / NULLIF(SUM(fta) OVER w10, 0) AS l10_ft_pct,
        SUM(pts) OVER w10 / NULLIF(2.0 * SUM(tsa) OVER w10, 0) AS l10_ts_pct,
        AVG(usg_pct) OVER w10 AS l10_usg_pct,
        AVG(plus_minus) OVER w10 AS l10_plus_minus,
        AVG(net_rating) OVER w10 AS l10_net_rtg,
        AVG(game_score) OVER w10 AS l10_game_score,
        AVG(minutes) OVER w10 AS l10_minutes,

        AVG(pts) OVER w15 AS l15_ppg,
        AVG(reb) OVER w15 AS l15_rpg,
        AVG(ast) OVER w15 AS l15_apg,
        AVG(stl) OVER w15 AS l15_spg,
        AVG(blk) OVER w15 AS l15_bpg,
        SUM(fgm) OVER w15 / NULLIF(SUM(fga) OVER w15, 0) AS l15_fg_pct,
        SUM(fg3m) OVER w15 / NULLIF(SUM(fg3a) OVER w15, 0) AS l15_fg3_pct,
        SUM(ftm) OVER w15 / NULLIF(SUM(fta) OVER w15, 0) AS l15_ft_pct,
        SUM(pts) OVER w15 / NULLIF(2.0 * SUM(tsa) OVER w15, 0) AS l15_ts_pct,
        AVG(usg_pct) OVER w15 AS l15_usg_pct,
        AVG(plus_minus) OVER w15 AS l15_plus_minus,
        AVG(net_rating) OVER w15 AS l15_net_rtg,
        AVG(game_score) OVER w15 AS l15_game_score,
        AVG(minutes) OVER w15 AS l15_minutes,

        AVG(pts) OVER w20 AS l20_ppg,
        AVG(reb) OVER w20 AS l20_rpg,
        AVG(ast) OVER w20 AS l20_apg,
        AVG(stl) OVER w20 AS l20_spg,
        AVG(blk) OVER w20 AS l20_bpg,
        SUM(fgm) OVER w20 / NULLIF(SUM(fga) OVER w20, 0) AS l20_fg_pct,
        SUM(fg3m) OVER w20 / NULLIF(SUM(fg3a) OVER w20, 0) AS l20_fg3_pct,
        SUM(ftm) OVER w20 / NULLIF(SUM(fta) OVER w20, 0) AS l20_ft_pct,
        SUM(pts) OVER w20 / NULLIF(2.0 * SUM(tsa) OVER w20, 0) AS l20_ts_pct,
        AVG(usg_pct) OVER w20 AS l20_usg_pct,
        AVG(plus_minus) OVER w20 AS l20_plus_minus,
        AVG(net_rating) OVER w20 AS l20_net_rtg,
        AVG(game_score) OVER w20 AS l20_game_score,
        AVG(minutes) OVER w20 AS l20_minutes,

        AVG(pts) OVER wseason AS season_ppg,
        AVG(reb) OVER wseason AS season_rpg,
        AVG(ast) OVER wseason AS season_apg,
        AVG(stl) OVER wseason AS season_spg,
        AVG(blk) OVER wseason AS season_bpg,
        SUM(fgm) OVER wseason / NULLIF(SUM(fga) OVER wseason, 0) AS season_fg_pct,
        SUM(fg3m) OVER wseason / NULLIF(SUM(fg3a) OVER wseason, 0) AS season_fg3_pct,
        SUM(ftm) OVER wseason / NULLIF(SUM(fta) OVER wseason, 0) AS season_ft_pct,
        SUM(pts) OVER wseason / NULLIF(2.0 * SUM(tsa) OVER wseason, 0) AS season_ts_pct,
        AVG(usg_pct) OVER wseason AS season_usg_pct,
        AVG(plus_minus) OVER wseason AS season_plus_minus,
        AVG(net_rating) OVER wseason AS season_net_rtg,
        AVG(game_score) OVER wseason AS season_game_score,
        AVG(minutes) OVER wseason AS season_minutes,
        STDDEV_SAMP(game_score) OVER (
            PARTITION BY player_id, season
        ) AS gs_std
    FROM base
    WINDOW
        w3 AS (
            PARTITION BY player_id, season
            ORDER BY game_date, game_id
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ),
        w5 AS (
            PARTITION BY player_id, season
            ORDER BY game_date, game_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ),
        w10 AS (
            PARTITION BY player_id, season
            ORDER BY game_date, game_id
            ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
        ),
        w15 AS (
            PARTITION BY player_id, season
            ORDER BY game_date, game_id
            ROWS BETWEEN 14 PRECEDING AND CURRENT ROW
        ),
        w20 AS (
            PARTITION BY player_id, season
            ORDER BY game_date, game_id
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ),
        wseason AS (
            PARTITION BY player_id, season
            ORDER BY game_date, game_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
),
trends AS (
    SELECT
        *,
        ROUND(l5_ppg - l20_ppg, 2) AS trend_ppg,
        ROUND(l5_game_score - l20_game_score, 2) AS trend_game_score,
        ROUND(l5_ts_pct - l20_ts_pct, 3) AS trend_ts_pct
    FROM rolled
)
SELECT
    player_id,
    season,
    game_id,
    game_date,
    team_id,
    game_number,
    ROUND(l3_ppg, 2) AS l3_ppg,
    ROUND(l3_rpg, 2) AS l3_rpg,
    ROUND(l3_apg, 2) AS l3_apg,
    ROUND(l3_spg, 2) AS l3_spg,
    ROUND(l3_bpg, 2) AS l3_bpg,
    ROUND(l3_fg_pct, 3) AS l3_fg_pct,
    ROUND(l3_fg3_pct, 3) AS l3_fg3_pct,
    ROUND(l3_ft_pct, 3) AS l3_ft_pct,
    ROUND(l3_ts_pct, 3) AS l3_ts_pct,
    ROUND(l3_usg_pct, 3) AS l3_usg_pct,
    ROUND(l3_plus_minus, 2) AS l3_plus_minus,
    ROUND(l3_net_rtg, 2) AS l3_net_rtg,
    ROUND(l3_game_score, 2) AS l3_game_score,
    ROUND(l3_minutes, 2) AS l3_minutes,
    ROUND(l5_ppg, 2) AS l5_ppg,
    ROUND(l5_rpg, 2) AS l5_rpg,
    ROUND(l5_apg, 2) AS l5_apg,
    ROUND(l5_spg, 2) AS l5_spg,
    ROUND(l5_bpg, 2) AS l5_bpg,
    ROUND(l5_fg_pct, 3) AS l5_fg_pct,
    ROUND(l5_fg3_pct, 3) AS l5_fg3_pct,
    ROUND(l5_ft_pct, 3) AS l5_ft_pct,
    ROUND(l5_ts_pct, 3) AS l5_ts_pct,
    ROUND(l5_usg_pct, 3) AS l5_usg_pct,
    ROUND(l5_plus_minus, 2) AS l5_plus_minus,
    ROUND(l5_net_rtg, 2) AS l5_net_rtg,
    ROUND(l5_game_score, 2) AS l5_game_score,
    ROUND(l5_minutes, 2) AS l5_minutes,
    ROUND(l10_ppg, 2) AS l10_ppg,
    ROUND(l10_rpg, 2) AS l10_rpg,
    ROUND(l10_apg, 2) AS l10_apg,
    ROUND(l10_spg, 2) AS l10_spg,
    ROUND(l10_bpg, 2) AS l10_bpg,
    ROUND(l10_fg_pct, 3) AS l10_fg_pct,
    ROUND(l10_fg3_pct, 3) AS l10_fg3_pct,
    ROUND(l10_ft_pct, 3) AS l10_ft_pct,
    ROUND(l10_ts_pct, 3) AS l10_ts_pct,
    ROUND(l10_usg_pct, 3) AS l10_usg_pct,
    ROUND(l10_plus_minus, 2) AS l10_plus_minus,
    ROUND(l10_net_rtg, 2) AS l10_net_rtg,
    ROUND(l10_game_score, 2) AS l10_game_score,
    ROUND(l10_minutes, 2) AS l10_minutes,
    ROUND(l15_ppg, 2) AS l15_ppg,
    ROUND(l15_rpg, 2) AS l15_rpg,
    ROUND(l15_apg, 2) AS l15_apg,
    ROUND(l15_spg, 2) AS l15_spg,
    ROUND(l15_bpg, 2) AS l15_bpg,
    ROUND(l15_fg_pct, 3) AS l15_fg_pct,
    ROUND(l15_fg3_pct, 3) AS l15_fg3_pct,
    ROUND(l15_ft_pct, 3) AS l15_ft_pct,
    ROUND(l15_ts_pct, 3) AS l15_ts_pct,
    ROUND(l15_usg_pct, 3) AS l15_usg_pct,
    ROUND(l15_plus_minus, 2) AS l15_plus_minus,
    ROUND(l15_net_rtg, 2) AS l15_net_rtg,
    ROUND(l15_game_score, 2) AS l15_game_score,
    ROUND(l15_minutes, 2) AS l15_minutes,
    ROUND(l20_ppg, 2) AS l20_ppg,
    ROUND(l20_rpg, 2) AS l20_rpg,
    ROUND(l20_apg, 2) AS l20_apg,
    ROUND(l20_spg, 2) AS l20_spg,
    ROUND(l20_bpg, 2) AS l20_bpg,
    ROUND(l20_fg_pct, 3) AS l20_fg_pct,
    ROUND(l20_fg3_pct, 3) AS l20_fg3_pct,
    ROUND(l20_ft_pct, 3) AS l20_ft_pct,
    ROUND(l20_ts_pct, 3) AS l20_ts_pct,
    ROUND(l20_usg_pct, 3) AS l20_usg_pct,
    ROUND(l20_plus_minus, 2) AS l20_plus_minus,
    ROUND(l20_net_rtg, 2) AS l20_net_rtg,
    ROUND(l20_game_score, 2) AS l20_game_score,
    ROUND(l20_minutes, 2) AS l20_minutes,
    ROUND(season_ppg, 2) AS season_ppg,
    ROUND(season_rpg, 2) AS season_rpg,
    ROUND(season_apg, 2) AS season_apg,
    ROUND(season_spg, 2) AS season_spg,
    ROUND(season_bpg, 2) AS season_bpg,
    ROUND(season_fg_pct, 3) AS season_fg_pct,
    ROUND(season_fg3_pct, 3) AS season_fg3_pct,
    ROUND(season_ft_pct, 3) AS season_ft_pct,
    ROUND(season_ts_pct, 3) AS season_ts_pct,
    ROUND(season_usg_pct, 3) AS season_usg_pct,
    ROUND(season_plus_minus, 2) AS season_plus_minus,
    ROUND(season_net_rtg, 2) AS season_net_rtg,
    ROUND(season_game_score, 2) AS season_game_score,
    ROUND(season_minutes, 2) AS season_minutes,
    trend_ppg,
    trend_game_score,
    trend_ts_pct,
    trend_game_score > gs_std AS is_hot,
    trend_game_score < -gs_std AS is_cold
FROM trends

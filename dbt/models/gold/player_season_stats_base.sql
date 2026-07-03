{{ config(materialized='table', schema='gold', alias='player_season_stats_base', tags=['gold_mart']) }}

SELECT *
FROM (
WITH base AS (
    SELECT
        pgs.player_id,
        COALESCE(fg.season, '2025-26') AS season,
        mode() WITHIN GROUP (ORDER BY pgs.player_name) AS player_name,
        mode() WITHIN GROUP (ORDER BY pgs.team_id) AS team_id,
        SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END) AS games_played,
        ROUND(
            SUM(COALESCE(pgs.minutes, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS mpg,
        ROUND(
            SUM(COALESCE(pgs.pts, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS ppg,
        ROUND(
            SUM(COALESCE(pgs.reb, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS rpg,
        ROUND(
            SUM(COALESCE(pgs.ast, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS apg,
        ROUND(
            SUM(COALESCE(pgs.stl, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS spg,
        ROUND(
            SUM(COALESCE(pgs.blk, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS bpg,
        ROUND(
            SUM(COALESCE(pgs.tov, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS topg,
        COALESCE(ROUND(SUM(pgs.fgm)::NUMERIC / NULLIF(SUM(pgs.fga), 0), 3), 0.000) AS fg_pct,
        COALESCE(ROUND(SUM(pgs.fg3m)::NUMERIC / NULLIF(SUM(pgs.fg3a), 0), 3), 0.000) AS fg3_pct,
        COALESCE(ROUND(SUM(pgs.ftm)::NUMERIC / NULLIF(SUM(pgs.fta), 0), 3), 0.000) AS ft_pct,
        ROUND(
            SUM(COALESCE(pgs.plus_minus, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS plus_minus_avg,
        ROUND(AVG(pgs.game_score) FILTER (WHERE COALESCE(pgs.counts_as_gp, pgs.minutes > 0))::NUMERIC, 1) AS avg_game_score,
        ROUND(AVG(pgs.off_rating) FILTER (WHERE COALESCE(pgs.counts_as_gp, pgs.minutes > 0))::NUMERIC, 1) AS avg_off_rating,
        ROUND(AVG(pgs.def_rating) FILTER (WHERE COALESCE(pgs.counts_as_gp, pgs.minutes > 0))::NUMERIC, 1) AS avg_def_rating,
        ROUND(AVG(pgs.usg_pct) FILTER (WHERE COALESCE(pgs.counts_as_gp, pgs.minutes > 0))::NUMERIC, 3) AS avg_usg_pct,
        CASE WHEN SUM(pgs.fga) + SUM(pgs.fta) >= 20 THEN
            LEAST(ROUND(SUM(pgs.pts)::NUMERIC / (2.0 * (SUM(pgs.fga) + 0.44 * SUM(pgs.fta))), 3), 1.0)
        END AS avg_ts_pct
    FROM {{ ref('player_game_stats') }} pgs
    LEFT JOIN {{ ref('fct_games') }} fg ON pgs.game_id = fg.game_id
    GROUP BY pgs.player_id, COALESCE(fg.season, '2025-26')
    HAVING SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END) > 0
),
with_advanced AS (
    SELECT *,
        -- Simple box-score impact approximation, not the Basketball-Reference metric.
        CASE WHEN mpg > 0 THEN ROUND((
            0.123 * (ppg / mpg * 36)
            + 0.168 * (apg / mpg * 36)
            - 0.155 * (topg / mpg * 36)
            + 0.025 * (rpg / mpg * 36)
            + 0.153 * (spg / mpg * 36)
            + 0.195 * (bpg / mpg * 36)
            - 2.4
        )::NUMERIC, 1) END AS bpm_approx,
        -- Value-over-replacement approximation derived from bpm_approx.
        CASE WHEN mpg > 0 AND games_played > 0 THEN ROUND(((
            0.123 * (ppg / mpg * 36)
            + 0.168 * (apg / mpg * 36)
            - 0.155 * (topg / mpg * 36)
            + 0.025 * (rpg / mpg * 36)
            + 0.153 * (spg / mpg * 36)
            + 0.195 * (bpg / mpg * 36)
            - 2.4
            + 2.0
        ) * (mpg::NUMERIC / 48) * (games_played::NUMERIC / 82))::NUMERIC, 2) END AS vorp_approx,
        CASE WHEN mpg > 0 THEN ROUND((ppg / mpg * 36)::NUMERIC, 1) END AS pts_per_36,
        CASE WHEN mpg > 0 THEN ROUND((apg / mpg * 36)::NUMERIC, 1) END AS ast_per_36,
        CASE WHEN mpg > 0 THEN ROUND((rpg / mpg * 36)::NUMERIC, 1) END AS reb_per_36
    FROM base
),
with_info AS (
    SELECT
        b.*,
        COALESCE(p.full_name, b.player_name) AS full_name,
        p.position,
        p.jersey_number
    FROM with_advanced b
    LEFT JOIN {{ ref('dim_players') }} p ON b.player_id = p.player_id
),
season_scope AS (
    SELECT
        season,
        COUNT(DISTINCT team_id) AS comparison_team_count,
        COUNT(DISTINCT player_id) AS comparison_player_count,
        CASE
            WHEN COUNT(DISTINCT team_id) = 30 THEN 'full_league'
            ELSE 'loaded_sample'
        END AS comparison_scope
    FROM with_info
    GROUP BY season
)
SELECT
    w.player_id, w.season, w.full_name AS player_name, w.team_id, w.position, w.jersey_number,
    games_played, mpg, ppg, rpg, apg, spg, bpg, topg,
    fg_pct, fg3_pct, ft_pct, plus_minus_avg, avg_game_score,
    avg_off_rating, avg_def_rating, avg_usg_pct, avg_ts_pct,
    NULL::REAL AS obpm, NULL::REAL AS dbpm,
    bpm_approx, vorp_approx, pts_per_36, ast_per_36, reb_per_36,
    NULL::REAL AS adj_ppg,
    NULL::REAL AS adj_ts_pct,
    NULL::REAL AS adj_net_rtg,
    s.comparison_scope,
    s.comparison_player_count,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY ppg) * 100)::INT AS ppg_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY rpg) * 100)::INT AS rpg_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY apg) * 100)::INT AS apg_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY spg) * 100)::INT AS spg_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY bpg) * 100)::INT AS bpg_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY mpg) * 100)::INT AS mpg_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY fg_pct) * 100)::INT AS fg_shoot_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY fg3_pct) * 100)::INT AS fg3_shoot_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY avg_ts_pct) * 100)::INT AS ts_pct_rank,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY avg_usg_pct) * 100)::INT AS usg_pct_rank,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY avg_game_score) * 100)::INT AS game_score_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY bpm_approx) * 100)::INT AS bpm_approx_pct,
    (PERCENT_RANK() OVER (PARTITION BY w.season ORDER BY vorp_approx) * 100)::INT AS vorp_approx_pct
FROM with_info w
LEFT JOIN season_scope s ON s.season = w.season
) AS model(
    player_id,
    season,
    player_name,
    team_id,
    position,
    jersey_number,
    games_played,
    mpg,
    ppg,
    rpg,
    apg,
    spg,
    bpg,
    topg,
    fg_pct,
    fg3_pct,
    ft_pct,
    plus_minus_avg,
    avg_game_score,
    avg_off_rating,
    avg_def_rating,
    avg_usg_pct,
    avg_ts_pct,
    obpm,
    dbpm,
    bpm_approx,
    vorp_approx,
    pts_per_36,
    ast_per_36,
    reb_per_36,
    adj_ppg,
    adj_ts_pct,
    adj_net_rtg,
    comparison_scope,
    comparison_player_count,
    ppg_pct,
    rpg_pct,
    apg_pct,
    spg_pct,
    bpg_pct,
    mpg_pct,
    fg_shoot_pct,
    fg3_shoot_pct,
    ts_pct_rank,
    usg_pct_rank,
    game_score_pct,
    bpm_approx_pct,
    vorp_approx_pct
)

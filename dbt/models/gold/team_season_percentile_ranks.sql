{{ config(materialized='table', schema='gold', alias='team_season_percentile_ranks', tags=['gold_mart']) }}

WITH season_scope AS (
    SELECT
        season,
        COUNT(DISTINCT team_id) AS comparison_team_count,
        CASE
            WHEN COUNT(DISTINCT team_id) = 30 THEN 'full_league'
            ELSE 'loaded_sample'
        END AS comparison_scope
    FROM {{ ref('team_season_four_factors') }}
    GROUP BY season
)
SELECT
    f.team_id,
    f.season,
    f.team_abbreviation,
    s.comparison_scope,
    s.comparison_team_count,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY off_efg_pct) * 100)::INT AS off_efg_pct_pct,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY off_tov_pct DESC) * 100)::INT AS off_tov_pct_pct,  -- lower TOV% = better
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY off_oreb_pct) * 100)::INT AS off_oreb_pct_pct,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY off_ft_rate) * 100)::INT AS off_ft_rate_pct,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY def_efg_pct DESC) * 100)::INT AS def_efg_pct_pct,  -- lower def eFG% = better
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY def_tov_pct) * 100)::INT AS def_tov_pct_pct,       -- higher forced TOV% = better
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY def_oreb_pct DESC) * 100)::INT AS def_oreb_pct_pct,  -- lower opp OREB% = better
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY def_ft_rate DESC) * 100)::INT AS def_ft_rate_pct,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY pace) * 100)::INT AS pace_pct,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY ppg) * 100)::INT AS ppg_pct,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY opp_ppg DESC) * 100)::INT AS opp_ppg_pct,      -- lower opp PPG = better
    ppg - opp_ppg AS point_diff,
    (PERCENT_RANK() OVER (PARTITION BY f.season ORDER BY ppg - opp_ppg) * 100)::INT AS point_diff_pct
FROM {{ ref('team_season_four_factors') }} f
LEFT JOIN season_scope s ON s.season = f.season

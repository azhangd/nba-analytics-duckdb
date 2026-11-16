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
    {{ season_percentile('off_efg_pct', 'f.season') }} AS off_efg_pct_pct,
    {{ season_percentile('off_tov_pct', 'f.season', descending=true) }} AS off_tov_pct_pct,  -- lower TOV% = better
    {{ season_percentile('off_oreb_pct', 'f.season') }} AS off_oreb_pct_pct,
    {{ season_percentile('off_ft_rate', 'f.season') }} AS off_ft_rate_pct,
    {{ season_percentile('def_efg_pct', 'f.season', descending=true) }} AS def_efg_pct_pct,  -- lower def eFG% = better
    {{ season_percentile('def_tov_pct', 'f.season') }} AS def_tov_pct_pct,       -- higher forced TOV% = better
    {{ season_percentile('def_oreb_pct', 'f.season', descending=true) }} AS def_oreb_pct_pct,  -- lower opp OREB% = better
    {{ season_percentile('def_ft_rate', 'f.season', descending=true) }} AS def_ft_rate_pct,
    {{ season_percentile('pace', 'f.season') }} AS pace_pct,
    {{ season_percentile('ppg', 'f.season') }} AS ppg_pct,
    {{ season_percentile('opp_ppg', 'f.season', descending=true) }} AS opp_ppg_pct,      -- lower opp PPG = better
    ppg - opp_ppg AS point_diff,
    {{ season_percentile('ppg - opp_ppg', 'f.season') }} AS point_diff_pct
FROM {{ ref('team_season_four_factors') }} f
LEFT JOIN season_scope s ON s.season = f.season

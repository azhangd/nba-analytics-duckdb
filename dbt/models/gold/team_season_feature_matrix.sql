{{ config(materialized='table', schema='gold', alias='team_season_feature_matrix', tags=['gold']) }}

WITH base AS (
    SELECT
        factors.team_id,
        factors.season,
        teams.abbreviation AS team_abbreviation,
        factors.pace,
        factors.ppg,
        factors.opp_ppg,
        factors.off_efg_pct,
        factors.off_tov_pct,
        factors.off_oreb_pct,
        factors.off_ft_rate,
        factors.def_efg_pct,
        factors.def_tov_pct,
        factors.def_oreb_pct,
        factors.def_ft_rate,
        factors.pyth_win_pct
    FROM {{ ref('team_season_four_factors') }} AS factors
    LEFT JOIN {{ ref('dim_teams') }} AS teams
        ON factors.team_id = teams.team_id
),
elo AS (
    SELECT
        team_id,
        season,
        elo_rating,
        current_wins,
        current_losses,
        win_pct
    FROM {{ ref('team_season_elo') }}
),
team_games_ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY team_id, season
            ORDER BY game_date DESC, game_id DESC
        ) AS game_recency
    FROM {{ ref('team_game_stats') }}
),
recent_form AS (
    SELECT
        team_id,
        season,
        SUM(CASE WHEN game_recency <= 5 AND margin > 0 THEN 1 ELSE 0 END) AS l5_wins,
        SUM(CASE WHEN game_recency <= 5 AND margin <= 0 THEN 1 ELSE 0 END) AS l5_losses,
        ROUND(AVG(CASE WHEN game_recency <= 5 THEN margin END), 1) AS l5_net_rtg,
        SUM(CASE WHEN game_recency <= 10 AND margin > 0 THEN 1 ELSE 0 END) AS l10_wins,
        SUM(CASE WHEN game_recency <= 10 AND margin <= 0 THEN 1 ELSE 0 END) AS l10_losses,
        ROUND(AVG(CASE WHEN game_recency <= 10 THEN margin END), 1) AS l10_net_rtg
    FROM team_games_ranked
    GROUP BY team_id, season
),
shot_diet AS (
    SELECT
        team_id,
        season,
        SUM(
            CASE
                WHEN LOWER(shot_bucket) LIKE '%paint%' OR LOWER(shot_bucket) LIKE '%restricted%'
                    THEN COALESCE(freq_pct, 0)
                ELSE 0
            END
        ) AS paint_freq,
        SUM(
            CASE
                WHEN LOWER(shot_bucket) LIKE '%3pt%' OR LOWER(shot_bucket) LIKE '%three%'
                    THEN COALESCE(freq_pct, 0)
                ELSE 0
            END
        ) AS three_freq,
        SUM(
            CASE
                WHEN NOT (
                    LOWER(shot_bucket) LIKE '%paint%'
                    OR LOWER(shot_bucket) LIKE '%restricted%'
                    OR LOWER(shot_bucket) LIKE '%3pt%'
                    OR LOWER(shot_bucket) LIKE '%three%'
                )
                    THEN COALESCE(freq_pct, 0)
                ELSE 0
            END
        ) AS mid_freq
    FROM {{ ref('team_season_shot_profile') }}
    GROUP BY team_id, season
),
play_type_mix AS (
    SELECT
        offense_team_id AS team_id,
        season,
        MAX(CASE WHEN play_type = 'Transition' THEN ROUND(frequency_pct, 3) END) AS transition_freq,
        MAX(CASE WHEN play_type = 'Isolation' THEN ROUND(frequency_pct, 3) END) AS isolation_freq,
        MAX(CASE WHEN play_type = 'PRBallHandler' THEN ROUND(frequency_pct, 3) END) AS pnr_freq,
        MAX(CASE WHEN play_type = 'Spotup' THEN ROUND(frequency_pct, 3) END) AS spot_up_freq,
        MAX(CASE WHEN play_type = 'Postup' THEN ROUND(frequency_pct, 3) END) AS post_up_freq
    FROM {{ ref('team_season_play_type_stats') }}
    GROUP BY offense_team_id, season
),
starter_bench AS (
    SELECT
        team_id,
        season,
        ROUND(SUM(CASE WHEN LOWER(role) LIKE '%start%' THEN COALESCE(ppg, 0) ELSE 0 END), 1) AS starter_ppg,
        ROUND(SUM(CASE WHEN LOWER(role) LIKE '%bench%' THEN COALESCE(ppg, 0) ELSE 0 END), 1) AS bench_ppg
    FROM {{ ref('team_season_starter_bench_stats') }}
    GROUP BY team_id, season
),
clutch AS (
    SELECT
        offense_team_id AS team_id,
        season,
        clutch_ppp
    FROM {{ ref('team_season_clutch_stats') }}
)
SELECT
    base.team_id,
    base.season,
    base.team_abbreviation,
    base.pace,
    base.ppg,
    base.opp_ppg,
    base.off_efg_pct,
    base.off_tov_pct,
    base.off_oreb_pct,
    base.off_ft_rate,
    base.def_efg_pct,
    base.def_tov_pct,
    base.def_oreb_pct,
    base.def_ft_rate,
    base.pyth_win_pct,
    elo.elo_rating,
    elo.current_wins,
    elo.current_losses,
    elo.win_pct,
    recent_form.l5_wins,
    recent_form.l5_losses,
    recent_form.l5_net_rtg,
    recent_form.l10_wins,
    recent_form.l10_losses,
    recent_form.l10_net_rtg,
    shot_diet.paint_freq,
    shot_diet.three_freq,
    shot_diet.mid_freq,
    play_type_mix.transition_freq,
    play_type_mix.isolation_freq,
    play_type_mix.pnr_freq,
    play_type_mix.spot_up_freq,
    play_type_mix.post_up_freq,
    starter_bench.starter_ppg,
    starter_bench.bench_ppg,
    clutch.clutch_ppp
FROM base
LEFT JOIN elo
    ON base.team_id = elo.team_id
   AND base.season = elo.season
LEFT JOIN recent_form
    ON base.team_id = recent_form.team_id
   AND base.season = recent_form.season
LEFT JOIN shot_diet
    ON base.team_id = shot_diet.team_id
   AND base.season = shot_diet.season
LEFT JOIN play_type_mix
    ON base.team_id = play_type_mix.team_id
   AND base.season = play_type_mix.season
LEFT JOIN starter_bench
    ON base.team_id = starter_bench.team_id
   AND base.season = starter_bench.season
LEFT JOIN clutch
    ON base.team_id = clutch.team_id
   AND base.season = clutch.season

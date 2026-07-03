{{ config(materialized='table', schema='gold', alias='player_season_feature_matrix', tags=['gold', 'requires_gold_runtime']) }}

WITH base AS (
    SELECT
        player_id,
        season,
        player_name,
        team_id,
        position,
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
        avg_ts_pct AS ts_pct,
        avg_usg_pct AS usg_pct,
        plus_minus_avg,
        avg_game_score AS game_score_avg,
        avg_off_rating AS off_rating,
        avg_def_rating AS def_rating,
        ROUND(CAST(avg_off_rating AS DOUBLE) - CAST(avg_def_rating AS DOUBLE), 1) AS net_rating,
        pts_per_36,
        reb_per_36,
        ast_per_36,
        ppg_pct,
        rpg_pct,
        apg_pct,
        spg_pct,
        bpg_pct,
        bpm_approx,
        vorp_approx
    FROM {{ ref('player_season_stats') }}
),
rolling_ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY player_id, season
            ORDER BY game_number DESC, game_id DESC
        ) AS rn
    FROM {{ ref('player_game_rolling_stats') }}
),
rolling_latest AS (
    SELECT
        player_id,
        season,
        l5_ppg,
        l5_ts_pct,
        l5_game_score,
        l10_ppg,
        l10_ts_pct,
        l10_game_score,
        trend_ppg,
        trend_game_score,
        is_hot,
        is_cold
    FROM rolling_ranked
    WHERE rn = 1
),
shot_diet AS (
    SELECT
        player_id,
        season,
        SUM(
            CASE
                WHEN LOWER(shot_bucket) LIKE '%paint%' OR LOWER(shot_bucket) LIKE '%restricted%' OR LOWER(shot_bucket) LIKE '%0-3%'
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
                    OR LOWER(shot_bucket) LIKE '%0-3%'
                    OR LOWER(shot_bucket) LIKE '%3pt%'
                    OR LOWER(shot_bucket) LIKE '%three%'
                )
                    THEN COALESCE(freq_pct, 0)
                ELSE 0
            END
        ) AS mid_freq
    FROM {{ ref('player_season_shot_profile') }}
    GROUP BY player_id, season
),
archetypes AS (
    SELECT
        player_id,
        season,
        primary_archetype AS archetype,
        archetype_confidence
    FROM {{ ref('player_season_archetypes') }}
),
embeddings AS (
    SELECT
        player_id,
        season,
        cluster_id,
        cluster_label
    FROM {{ source('gold_runtime', 'player_season_embeddings') }}
),
rapm AS (
    SELECT
        player_id,
        season,
        rapm,
        rapm_blended
    FROM {{ source('gold_runtime', 'player_season_rapm') }}
),
hustle AS (
    SELECT
        player_id,
        season,
        AVG(CAST(deflections AS DOUBLE)) AS deflections,
        AVG(CAST(contested_shots AS DOUBLE)) AS contested_shots
    FROM {{ ref('fct_hustle') }}
    GROUP BY player_id, season
),
clutch AS (
    SELECT
        player_id,
        season,
        clutch_ppg,
        clutch_ts_pct
    FROM {{ ref('player_season_clutch_stats') }}
),
consistency AS (
    SELECT
        stats.player_id,
        games.season,
        ROUND(STDDEV_SAMP(CAST(stats.game_score AS DOUBLE)), 2) AS game_score_stddev
    FROM {{ ref('player_game_stats') }} AS stats
    JOIN {{ ref('fct_games') }} AS games
        ON stats.game_id = games.game_id
    WHERE games.game_type = 'regular_season'
    GROUP BY stats.player_id, games.season
)
SELECT
    base.player_id,
    base.season,
    base.player_name,
    base.team_id,
    base.position,
    base.games_played,
    base.mpg,
    base.ppg,
    base.rpg,
    base.apg,
    base.spg,
    base.bpg,
    base.topg,
    base.fg_pct,
    base.fg3_pct,
    base.ft_pct,
    base.ts_pct,
    base.usg_pct,
    base.plus_minus_avg,
    base.game_score_avg,
    base.off_rating,
    base.def_rating,
    base.net_rating,
    base.pts_per_36,
    base.reb_per_36,
    base.ast_per_36,
    base.ppg_pct,
    base.rpg_pct,
    base.apg_pct,
    base.spg_pct,
    base.bpg_pct,
    rolling_latest.l5_ppg,
    rolling_latest.l5_ts_pct,
    rolling_latest.l5_game_score,
    rolling_latest.l10_ppg,
    rolling_latest.l10_ts_pct,
    rolling_latest.l10_game_score,
    rolling_latest.trend_ppg,
    rolling_latest.trend_game_score,
    rolling_latest.is_hot,
    rolling_latest.is_cold,
    shot_diet.paint_freq,
    shot_diet.three_freq,
    shot_diet.mid_freq,
    archetypes.archetype,
    archetypes.archetype_confidence,
    embeddings.cluster_id,
    embeddings.cluster_label,
    rapm.rapm,
    rapm.rapm_blended,
    base.bpm_approx,
    base.vorp_approx,
    hustle.deflections,
    hustle.contested_shots,
    clutch.clutch_ppg,
    clutch.clutch_ts_pct,
    consistency.game_score_stddev,
    CASE
        WHEN consistency.game_score_stddev > 0
            THEN ROUND(base.game_score_avg / consistency.game_score_stddev, 2)
    END AS consistency_score
FROM base
LEFT JOIN rolling_latest
    ON base.player_id = rolling_latest.player_id
   AND base.season = rolling_latest.season
LEFT JOIN shot_diet
    ON base.player_id = shot_diet.player_id
   AND base.season = shot_diet.season
LEFT JOIN archetypes
    ON base.player_id = archetypes.player_id
   AND base.season = archetypes.season
LEFT JOIN embeddings
    ON base.player_id = embeddings.player_id
   AND base.season = embeddings.season
LEFT JOIN rapm
    ON base.player_id = rapm.player_id
   AND base.season = rapm.season
LEFT JOIN hustle
    ON base.player_id = hustle.player_id
   AND base.season = hustle.season
LEFT JOIN clutch
    ON base.player_id = clutch.player_id
   AND base.season = clutch.season
LEFT JOIN consistency
    ON base.player_id = consistency.player_id
   AND base.season = consistency.season

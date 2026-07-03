{{ config(materialized='table', schema='gold', alias='player_season_mvp_ladder', tags=['gold']) }}

WITH stats AS (
    SELECT
        player_id,
        season,
        player_name,
        team_id,
        position,
        CAST(games_played AS DOUBLE) AS games_played,
        CAST(mpg AS DOUBLE) AS mpg,
        CAST(ppg AS DOUBLE) AS ppg,
        CAST(rpg AS DOUBLE) AS rpg,
        CAST(apg AS DOUBLE) AS apg,
        CAST(bpm_approx AS DOUBLE) AS bpm_approx,
        CAST(vorp_approx AS DOUBLE) AS vorp_approx,
        CAST(avg_ts_pct AS DOUBLE) AS avg_ts_pct,
        CAST(avg_game_score AS DOUBLE) AS avg_game_score,
        CAST(plus_minus_avg AS DOUBLE) AS plus_minus_avg
    FROM {{ ref('player_season_stats') }}
),
team_wins AS (
    SELECT
        team_id,
        season,
        team_abbreviation AS team_abbr,
        CAST(win_pct AS DOUBLE) AS team_win_pct,
        CAST(current_wins AS INTEGER) AS current_wins,
        CAST(current_losses AS INTEGER) AS current_losses,
        CAST(games_played AS DOUBLE) AS team_gp
    FROM {{ ref('team_season_elo') }}
),
on_off AS (
    SELECT
        player_id,
        team_id,
        season,
        CAST(on_off_differential AS DOUBLE) AS on_off_diff
    FROM {{ ref('player_season_on_off_stats') }}
),
joined AS (
    SELECT
        stats.player_id,
        stats.season,
        stats.player_name,
        stats.team_id,
        team_wins.team_abbr,
        stats.position,
        COALESCE(stats.games_played, 0) AS games_played,
        COALESCE(stats.mpg, 0) AS mpg,
        COALESCE(stats.ppg, 0) AS ppg,
        COALESCE(stats.rpg, 0) AS rpg,
        COALESCE(stats.apg, 0) AS apg,
        COALESCE(stats.bpm_approx, 0) AS bpm_approx,
        COALESCE(stats.vorp_approx, 0) AS vorp_approx,
        COALESCE(stats.avg_ts_pct, 0) AS avg_ts_pct,
        COALESCE(stats.avg_game_score, 0) AS avg_game_score,
        COALESCE(stats.plus_minus_avg, 0) AS plus_minus_avg,
        COALESCE(team_wins.team_win_pct, 0) AS team_win_pct,
        COALESCE(on_off.on_off_diff, 0) AS on_off_diff,
        CASE
            WHEN team_wins.team_gp > 0 THEN stats.games_played / team_wins.team_gp
            ELSE stats.games_played / 82.0
        END AS gp_pct
    FROM stats
    LEFT JOIN team_wins
        ON stats.team_id = team_wins.team_id
       AND stats.season = team_wins.season
    LEFT JOIN on_off
        ON stats.player_id = on_off.player_id
       AND stats.team_id = on_off.team_id
       AND stats.season = on_off.season
),
eligible AS (
    SELECT *
    FROM joined
    WHERE games_played >= 20
      AND mpg >= 25.0
      AND gp_pct >= 0.30
),
team_ranks AS (
    SELECT
        season,
        team_id,
        ROW_NUMBER() OVER (
            PARTITION BY season
            ORDER BY team_win_pct DESC, team_id
        ) AS team_rank
    FROM (
        SELECT DISTINCT season, team_id, team_win_pct
        FROM eligible
    )
),
with_seed AS (
    SELECT
        eligible.*,
        CASE
            WHEN team_ranks.team_rank <= 3 THEN 0.5
            WHEN team_ranks.team_rank <= 5 THEN 0.25
            ELSE 0.0
        END AS seed_bonus
    FROM eligible
    LEFT JOIN team_ranks
        ON eligible.season = team_ranks.season
       AND eligible.team_id = team_ranks.team_id
),
z_scores AS (
    SELECT
        *,
        (team_win_pct - AVG(team_win_pct) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(team_win_pct) OVER season_pool > 0
                THEN STDDEV_SAMP(team_win_pct) OVER season_pool ELSE 1.0 END AS team_win_pct_z,
        (bpm_approx - AVG(bpm_approx) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(bpm_approx) OVER season_pool > 0
                THEN STDDEV_SAMP(bpm_approx) OVER season_pool ELSE 1.0 END AS bpm_approx_z,
        (ppg - AVG(ppg) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(ppg) OVER season_pool > 0
                THEN STDDEV_SAMP(ppg) OVER season_pool ELSE 1.0 END AS ppg_z,
        (avg_game_score - AVG(avg_game_score) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(avg_game_score) OVER season_pool > 0
                THEN STDDEV_SAMP(avg_game_score) OVER season_pool ELSE 1.0 END AS avg_game_score_z,
        (on_off_diff - AVG(on_off_diff) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(on_off_diff) OVER season_pool > 0
                THEN STDDEV_SAMP(on_off_diff) OVER season_pool ELSE 1.0 END AS on_off_diff_z,
        (plus_minus_avg - AVG(plus_minus_avg) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(plus_minus_avg) OVER season_pool > 0
                THEN STDDEV_SAMP(plus_minus_avg) OVER season_pool ELSE 1.0 END AS plus_minus_avg_z,
        (avg_ts_pct - AVG(avg_ts_pct) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(avg_ts_pct) OVER season_pool > 0
                THEN STDDEV_SAMP(avg_ts_pct) OVER season_pool ELSE 1.0 END AS avg_ts_pct_z,
        (vorp_approx - AVG(vorp_approx) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(vorp_approx) OVER season_pool > 0
                THEN STDDEV_SAMP(vorp_approx) OVER season_pool ELSE 1.0 END AS vorp_approx_z,
        (gp_pct - AVG(gp_pct) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(gp_pct) OVER season_pool > 0
                THEN STDDEV_SAMP(gp_pct) OVER season_pool ELSE 1.0 END AS gp_pct_z,
        (apg - AVG(apg) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(apg) OVER season_pool > 0
                THEN STDDEV_SAMP(apg) OVER season_pool ELSE 1.0 END AS apg_z,
        (rpg - AVG(rpg) OVER season_pool)
            / CASE WHEN STDDEV_SAMP(rpg) OVER season_pool > 0
                THEN STDDEV_SAMP(rpg) OVER season_pool ELSE 1.0 END AS rpg_z
    FROM with_seed
    WINDOW season_pool AS (PARTITION BY season)
),
pillars AS (
    SELECT
        *,
        team_win_pct_z + seed_bonus AS team_success_z,
        0.50 * bpm_approx_z + 0.33 * ppg_z + 0.17 * avg_game_score_z AS stat_dominance_z,
        0.70 * on_off_diff_z + 0.30 * plus_minus_avg_z AS on_court_impact_z,
        avg_ts_pct_z AS efficiency_z,
        0.60 * vorp_approx_z + 0.40 * gp_pct_z AS volume_durability_z,
        0.50 * apg_z + 0.50 * rpg_z AS counting_z
    FROM z_scores
),
raw_scores AS (
    SELECT
        *,
        0.25 * team_success_z
        + 0.30 * stat_dominance_z
        + 0.20 * on_court_impact_z
        + 0.10 * efficiency_z
        + 0.10 * volume_durability_z
        + 0.05 * counting_z AS raw_mvp_score
    FROM pillars
),
scored AS (
    SELECT
        *,
        CASE
            WHEN MAX(raw_mvp_score) OVER (PARTITION BY season) > MIN(raw_mvp_score) OVER (PARTITION BY season)
                THEN ROUND(
                    (
                        (raw_mvp_score - MIN(raw_mvp_score) OVER (PARTITION BY season))
                        / (
                            MAX(raw_mvp_score) OVER (PARTITION BY season)
                            - MIN(raw_mvp_score) OVER (PARTITION BY season)
                        )
                    ) * 100.0,
                    1
                )
            ELSE 50.0
        END AS mvp_score
    FROM raw_scores
)
SELECT
    player_id,
    season,
    player_name,
    team_id,
    team_abbr,
    position,
    CAST(games_played AS INTEGER) AS games_played,
    mpg,
    ppg,
    rpg,
    apg,
    bpm_approx,
    vorp_approx,
    avg_ts_pct,
    avg_game_score,
    plus_minus_avg,
    team_win_pct,
    on_off_diff,
    ROUND(team_success_z, 2) AS team_success_z,
    ROUND(stat_dominance_z, 2) AS stat_dominance_z,
    ROUND(on_court_impact_z, 2) AS on_court_impact_z,
    ROUND(efficiency_z, 2) AS efficiency_z,
    ROUND(volume_durability_z, 2) AS volume_durability_z,
    ROUND(counting_z, 2) AS counting_z,
    mvp_score,
    ROW_NUMBER() OVER (
        PARTITION BY season
        ORDER BY mvp_score DESC, player_id
    ) AS mvp_rank
FROM scored

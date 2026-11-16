{{ config(materialized='table', schema='gold', alias='player_season_stats_base', tags=['gold_mart']) }}

WITH team_games_played AS (
    SELECT
        pgs.player_id,
        fg.season,
        pgs.team_id,
        SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END) AS games_played,
        MAX(fg.game_date) AS last_game_date
    FROM {{ ref('player_game_stats') }} pgs
    LEFT JOIN {{ ref('fct_games') }} fg ON pgs.game_id = fg.game_id
    GROUP BY pgs.player_id, fg.season, pgs.team_id
),
-- A traded player is listed under the team they played the most games for;
-- a tie goes to the team they played for last.
primary_team AS (
    SELECT player_id, season, team_id
    FROM team_games_played
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_id, season
        ORDER BY games_played DESC, last_game_date DESC
    ) = 1
),
-- Team minutes, shots and free throws in each game, for season usage.
team_game_totals AS (
    SELECT
        game_id,
        team_id,
        SUM(COALESCE(minutes, 0)) AS minutes,
        SUM(COALESCE(fga, 0)) AS fga,
        SUM(COALESCE(fta, 0)) AS fta
    FROM {{ ref('player_game_stats') }}
    GROUP BY game_id, team_id
),
-- Team turnovers come from play-by-play, because the box score only has the
-- players' turnovers and leaves out team ones (shot clock, 8 seconds).
play_by_play_games AS (
    SELECT DISTINCT CAST(game_id AS TEXT) AS game_id
    FROM {{ ref('fct_play_by_play') }}
),
team_game_turnovers AS (
    SELECT CAST(game_id AS TEXT) AS game_id, team_id, COUNT(*) AS tov
    FROM {{ ref('fct_play_by_play') }}
    WHERE action_type = 'turnover'
      AND team_id IS NOT NULL
    GROUP BY CAST(game_id AS TEXT), team_id
),
-- Season usage from season totals over the games the player played, as
-- Basketball-Reference computes it. NULL if any of those games has no play-by-play.
season_usage AS (
    SELECT
        pgs.player_id,
        fg.season,
        CASE WHEN COUNT(pbp.game_id) = COUNT(*) THEN
            SUM(COALESCE(pgs.fga, 0) + 0.44 * COALESCE(pgs.fta, 0) + COALESCE(pgs.tov, 0))
            * SUM(team.minutes) / 5
            / NULLIF(
                SUM(pgs.minutes)
                * SUM(team.fga + 0.44 * team.fta + COALESCE(tov.tov, 0)),
                0
            )
        END AS usg_pct
    FROM {{ ref('player_game_stats') }} pgs
    LEFT JOIN {{ ref('fct_games') }} fg ON pgs.game_id = fg.game_id
    JOIN team_game_totals team
        ON pgs.game_id = team.game_id
       AND pgs.team_id = team.team_id
    LEFT JOIN play_by_play_games pbp ON pgs.game_id = pbp.game_id
    LEFT JOIN team_game_turnovers tov
        ON pgs.game_id = tov.game_id
       AND pgs.team_id = tov.team_id
    WHERE pgs.minutes > 0
    GROUP BY pgs.player_id, fg.season
),
base AS (
    SELECT
        pgs.player_id,
        fg.season AS season,
        mode() WITHIN GROUP (ORDER BY pgs.player_name) AS player_name,
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
        ROUND(SUM(pgs.fgm)::NUMERIC / NULLIF(SUM(pgs.fga), 0), 3) AS fg_pct,
        ROUND(SUM(pgs.fg3m)::NUMERIC / NULLIF(SUM(pgs.fg3a), 0), 3) AS fg3_pct,
        ROUND(SUM(pgs.ftm)::NUMERIC / NULLIF(SUM(pgs.fta), 0), 3) AS ft_pct,
        ROUND(
            SUM(COALESCE(pgs.plus_minus, 0))::NUMERIC
            / NULLIF(SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END), 0),
            1
        ) AS plus_minus_avg,
        ROUND(AVG(pgs.game_score) FILTER (WHERE COALESCE(pgs.counts_as_gp, pgs.minutes > 0))::NUMERIC, 1) AS avg_game_score,
        ROUND(({{ minutes_weighted('pgs.off_rating', minutes='pgs.minutes') }})::NUMERIC, 1) AS avg_off_rating,
        ROUND(({{ minutes_weighted('pgs.def_rating', minutes='pgs.minutes') }})::NUMERIC, 1) AS avg_def_rating,
        SUM(pgs.fga) AS fga_total,
        SUM(pgs.fg3a) AS fg3a_total,
        CASE WHEN SUM(pgs.fga) + SUM(pgs.fta) >= 20 THEN
            LEAST(ROUND(SUM(pgs.pts)::NUMERIC / (2.0 * (SUM(pgs.fga) + 0.44 * SUM(pgs.fta))), 3), 1.0)
        END AS avg_ts_pct
    FROM {{ ref('player_game_stats') }} pgs
    LEFT JOIN {{ ref('fct_games') }} fg ON pgs.game_id = fg.game_id
    GROUP BY pgs.player_id, fg.season
    HAVING SUM(CASE WHEN COALESCE(pgs.counts_as_gp, pgs.minutes > 0) THEN 1 ELSE 0 END) > 0
),
with_advanced AS (
    SELECT base.*,
        primary_team.team_id,
        ROUND(season_usage.usg_pct::NUMERIC, 3) AS avg_usg_pct,
        CASE WHEN mpg > 0 THEN ROUND((ppg / mpg * 36)::NUMERIC, 1) END AS pts_per_36,
        CASE WHEN mpg > 0 THEN ROUND((apg / mpg * 36)::NUMERIC, 1) END AS ast_per_36,
        CASE WHEN mpg > 0 THEN ROUND((rpg / mpg * 36)::NUMERIC, 1) END AS reb_per_36
    FROM base
    JOIN primary_team USING (player_id, season)
    LEFT JOIN season_usage USING (player_id, season)
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
    pts_per_36, ast_per_36, reb_per_36,
    s.comparison_scope,
    s.comparison_player_count,
    {{ season_percentile('ppg', 'w.season') }} AS ppg_pct,
    {{ season_percentile('rpg', 'w.season') }} AS rpg_pct,
    {{ season_percentile('apg', 'w.season') }} AS apg_pct,
    {{ season_percentile('spg', 'w.season') }} AS spg_pct,
    {{ season_percentile('bpg', 'w.season') }} AS bpg_pct,
    {{ season_percentile('mpg', 'w.season') }} AS mpg_pct,
    {{ season_percentile('CASE WHEN w.fga_total >= 100 THEN w.fg_pct END', 'w.season') }} AS fg_shoot_pct,
    {{ season_percentile('CASE WHEN w.fg3a_total >= 100 THEN w.fg3_pct END', 'w.season') }} AS fg3_shoot_pct,
    {{ season_percentile('avg_ts_pct', 'w.season') }} AS ts_pct_rank,
    {{ season_percentile('avg_usg_pct', 'w.season') }} AS usg_pct_rank,
    {{ season_percentile('avg_game_score', 'w.season') }} AS game_score_pct
FROM with_info w
LEFT JOIN season_scope s ON s.season = w.season

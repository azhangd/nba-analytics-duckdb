{{ config(materialized='table', schema='gold', alias='team_season_four_factors', tags=['gold_mart']) }}

WITH with_opp AS (
    SELECT t.*,
        o.dreb AS opp_dreb, o.oreb AS opp_oreb,
        o.fgm AS opp_fgm, o.fga AS opp_fga, o.fg3m AS opp_fg3m,
        o.ftm AS opp_ftm, o.fta AS opp_fta, o.tov AS opp_tov
    FROM {{ ref('team_game_stats') }} t
    JOIN {{ ref('team_game_stats') }} o ON t.game_id = o.game_id AND t.team_id != o.team_id
),
season AS (
    SELECT team_id, season, COUNT(*) AS games,
        SUM(pts) AS pts, SUM(opp_pts) AS opp_pts, SUM(minutes) AS minutes,
        SUM(fgm) AS fgm, SUM(fga) AS fga, SUM(fg3m) AS fg3m,
        SUM(ftm) AS ftm, SUM(fta) AS fta,
        SUM(oreb) AS oreb, SUM(dreb) AS dreb,
        -- Turnovers are NULL for a game without play-by-play; a season missing
        -- any of them gets NULL rather than an undercount.
        CASE WHEN COUNT(tov) = COUNT(*) THEN SUM(tov) END AS tov,
        SUM(opp_dreb) AS opp_dreb, SUM(opp_oreb) AS opp_oreb,
        SUM(opp_fgm) AS opp_fgm, SUM(opp_fga) AS opp_fga, SUM(opp_fg3m) AS opp_fg3m,
        SUM(opp_ftm) AS opp_ftm, SUM(opp_fta) AS opp_fta,
        CASE WHEN COUNT(opp_tov) = COUNT(*) THEN SUM(opp_tov) END AS opp_tov
    FROM with_opp GROUP BY team_id, season
),
-- Basketball-Reference's season possessions: the same estimate as a game's,
-- applied to season totals.
season_possessions AS (
    SELECT *,
        0.5 * (
            (fga + 0.4 * fta - 1.07 * (oreb / NULLIF(oreb + opp_dreb, 0)) * (fga - fgm) + tov)
            + (opp_fga + 0.4 * opp_fta - 1.07 * (opp_oreb / NULLIF(opp_oreb + dreb, 0)) * (opp_fga - opp_fgm) + opp_tov)
        ) AS possessions
    FROM season
)
SELECT
    s.team_id,
    s.season,
    t.abbreviation AS team_abbreviation,
    s.games, s.pts, s.opp_pts,
    -- Possessions per 48 minutes; team minutes / 5 counts overtime.
    ROUND((48 * s.possessions / (s.minutes / 5))::NUMERIC, 1) AS pace,
    ROUND((s.pts / s.possessions * 100)::NUMERIC, 1) AS off_rtg,
    ROUND((s.opp_pts / s.possessions * 100)::NUMERIC, 1) AS def_rtg,
    ROUND(((s.pts - s.opp_pts) / s.possessions * 100)::NUMERIC, 1) AS net_rtg,
    ROUND(s.pts::NUMERIC / s.games, 1) AS ppg,
    ROUND(s.opp_pts::NUMERIC / s.games, 1) AS opp_ppg,
    -- Offensive
    CASE WHEN fga > 0 THEN ROUND(((fgm + 0.5*fg3m)::NUMERIC / fga * 100), 1) END AS off_efg_pct,
    CASE WHEN fga+fta+tov > 0 THEN ROUND((tov::NUMERIC / (fga + 0.44*fta + tov) * 100), 1) END AS off_tov_pct,
    CASE WHEN oreb+opp_dreb > 0 THEN ROUND((oreb::NUMERIC / (oreb+opp_dreb) * 100), 1) END AS off_oreb_pct,
    CASE WHEN fga > 0 THEN ROUND((ftm::NUMERIC / fga * 100), 1) END AS off_ft_rate,
    -- Defensive
    CASE WHEN opp_fga > 0 THEN ROUND(((opp_fgm + 0.5*opp_fg3m)::NUMERIC / opp_fga * 100), 1) END AS def_efg_pct,
    CASE WHEN opp_fga+opp_fta+opp_tov > 0 THEN ROUND((opp_tov::NUMERIC / (opp_fga + 0.44*opp_fta + opp_tov) * 100), 1) END AS def_tov_pct,
    CASE WHEN opp_oreb+dreb > 0 THEN ROUND((opp_oreb::NUMERIC / (opp_oreb+dreb) * 100), 1) END AS def_oreb_pct,
    CASE WHEN opp_fga > 0 THEN ROUND((opp_ftm::NUMERIC / opp_fga * 100), 1) END AS def_ft_rate,
    -- Pythagorean
    CASE WHEN pts+opp_pts > 0 THEN
        ROUND((POWER(pts::NUMERIC, 13.91) / (POWER(pts::NUMERIC, 13.91) + POWER(opp_pts::NUMERIC, 13.91))), 3)
    ELSE 0.5 END AS pyth_win_pct,
    CASE WHEN pts+opp_pts > 0 THEN
        ROUND((POWER(pts::NUMERIC, 13.91) / (POWER(pts::NUMERIC, 13.91) + POWER(opp_pts::NUMERIC, 13.91)) * games)::NUMERIC, 1)
    END AS pyth_wins,
    CASE WHEN pts+opp_pts > 0 THEN
        ROUND(((1.0 - POWER(pts::NUMERIC, 13.91) / (POWER(pts::NUMERIC, 13.91) + POWER(opp_pts::NUMERIC, 13.91))) * games)::NUMERIC, 1)
    END AS pyth_losses,
    -- Possession battle
    ROUND(tov::NUMERIC / games, 1) AS tov_per_game,
    ROUND(opp_tov::NUMERIC / games, 1) AS tov_forced_per_game,
    ROUND((opp_tov - tov)::NUMERIC / games, 1) AS tov_diff_per_game,
    ROUND(oreb::NUMERIC / games, 1) AS oreb_per_game,
    ROUND(opp_oreb::NUMERIC / games, 1) AS opp_oreb_per_game,
    ROUND((oreb - opp_oreb)::NUMERIC / games, 1) AS oreb_diff_per_game,
    ROUND((opp_tov - tov + oreb - opp_oreb)::NUMERIC / games, 1) AS possession_battle_per_game
FROM season_possessions s
LEFT JOIN {{ ref('dim_teams') }} t ON s.team_id = t.team_id

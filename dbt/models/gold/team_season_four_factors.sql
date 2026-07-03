{{ config(materialized='table', schema='gold', alias='team_season_four_factors', tags=['gold_mart']) }}

SELECT *
FROM (
WITH team_games AS (
    SELECT fb.game_id, fb.team_id, fg.season,
        SUM(fgm) AS fgm, SUM(fga) AS fga, SUM(fg3m) AS fg3m,
        SUM(ftm) AS ftm, SUM(fta) AS fta,
        SUM(oreb) AS oreb, SUM(dreb) AS dreb, SUM(tov) AS tov,
        SUM(pts) AS pts, AVG(pace) AS pace
    FROM {{ ref('fct_boxscores') }} fb
    JOIN {{ ref('fct_games') }} fg ON fb.game_id = fg.game_id
    WHERE fb.minutes > 0
      AND fg.game_type = 'regular_season'
    GROUP BY fb.game_id, fb.team_id, fg.season
),
with_opp AS (
    SELECT t.*,
        o.dreb AS opp_dreb, o.oreb AS opp_oreb, o.pts AS opp_pts,
        o.fgm AS opp_fgm, o.fga AS opp_fga, o.fg3m AS opp_fg3m,
        o.ftm AS opp_ftm, o.fta AS opp_fta, o.tov AS opp_tov
    FROM team_games t
    JOIN team_games o ON t.game_id = o.game_id AND t.team_id != o.team_id AND t.season = o.season
),
season AS (
    SELECT team_id, season, COUNT(*) AS games,
        SUM(pts) AS pts, SUM(opp_pts) AS opp_pts,
        ROUND(AVG(pace)::NUMERIC, 1) AS pace,
        SUM(fgm) AS fgm, SUM(fga) AS fga, SUM(fg3m) AS fg3m,
        SUM(ftm) AS ftm, SUM(fta) AS fta,
        SUM(oreb) AS oreb, SUM(dreb) AS dreb, SUM(tov) AS tov,
        SUM(opp_dreb) AS opp_dreb, SUM(opp_oreb) AS opp_oreb,
        SUM(opp_fgm) AS opp_fgm, SUM(opp_fga) AS opp_fga, SUM(opp_fg3m) AS opp_fg3m,
        SUM(opp_ftm) AS opp_ftm, SUM(opp_fta) AS opp_fta, SUM(opp_tov) AS opp_tov
    FROM with_opp GROUP BY team_id, season
)
SELECT
    s.team_id,
    s.season,
    t.abbreviation AS team_abbreviation,
    s.games, s.pts, s.opp_pts, s.pace,
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
FROM season s
LEFT JOIN {{ ref('dim_teams') }} t ON s.team_id = t.team_id
) AS model(
    team_id,
    season,
    team_abbreviation,
    games,
    pts,
    opp_pts,
    pace,
    ppg,
    opp_ppg,
    off_efg_pct,
    off_tov_pct,
    off_oreb_pct,
    off_ft_rate,
    def_efg_pct,
    def_tov_pct,
    def_oreb_pct,
    def_ft_rate,
    pyth_win_pct,
    pyth_wins,
    pyth_losses,
    tov_per_game,
    tov_forced_per_game,
    tov_diff_per_game,
    oreb_per_game,
    opp_oreb_per_game,
    oreb_diff_per_game,
    possession_battle_per_game
)

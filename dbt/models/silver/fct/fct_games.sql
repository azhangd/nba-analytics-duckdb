{{ config(materialized='table', schema='silver', alias='fct_games', tags=['silver']) }}

SELECT
    CAST(game_id AS TEXT) AS game_id,
    season,
    COALESCE(league_id, '00') AS league_id,
    COALESCE(competition, 'nba') AS competition,
    {{ parse_game_date("game_date") }} AS game_date,
    CAST(home_team_id AS INTEGER) AS home_team_id,
    CAST(away_team_id AS INTEGER) AS away_team_id,
    home_team_abbr,
    away_team_abbr,
    COALESCE(TRY_CAST(json_extract_string(raw_json, '$.homeTeam.score') AS INTEGER), 0) AS home_score,
    COALESCE(TRY_CAST(json_extract_string(raw_json, '$.awayTeam.score') AS INTEGER), 0) AS away_score,
    -- True for games away from both teams' arenas, such as NBA Cup games in Las
    -- Vegas and games abroad. A missing flag gives NULL, which fails the not_null test.
    CAST(json_extract_string(raw_json, '$.isNeutral') AS BOOLEAN) AS is_neutral,
    CASE
        WHEN game_status = 3 THEN 'Final'
        WHEN game_status = 2 THEN 'In Progress'
        ELSE 'Scheduled'
    END AS status,
    -- The game id prefix is the game type. An unknown prefix gives NULL, which
    -- fails the not_null test instead of being counted as regular season.
    CASE LEFT(CAST(game_id AS TEXT), 3)
        WHEN '001' THEN 'preseason'
        WHEN '002' THEN 'regular_season'
        WHEN '003' THEN 'all_star'
        WHEN '004' THEN 'playoffs'
        WHEN '005' THEN 'play_in'
        WHEN '006' THEN 'nba_cup'
    END AS game_type
FROM {{ source('bronze', 'schedule') }}
WHERE COALESCE(competition, 'nba') = 'nba'

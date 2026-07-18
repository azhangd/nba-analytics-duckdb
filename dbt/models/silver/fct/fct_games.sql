{{ config(materialized='table', schema='silver', alias='fct_games', tags=['silver']) }}

SELECT
    CAST(game_id AS TEXT) AS game_id,
    season,
    COALESCE(league_id, '00') AS league_id,
    COALESCE(competition, 'nba') AS competition,
    game_date,
    CAST(home_team_id AS INTEGER) AS home_team_id,
    CAST(away_team_id AS INTEGER) AS away_team_id,
    home_team_abbr,
    away_team_abbr,
    COALESCE(TRY_CAST(json_extract_string(raw_json, '$.homeTeam.score') AS INTEGER), 0) AS home_score,
    COALESCE(TRY_CAST(json_extract_string(raw_json, '$.awayTeam.score') AS INTEGER), 0) AS away_score,
    CASE
        WHEN game_status = 3 THEN 'Final'
        WHEN game_status = 2 THEN 'In Progress'
        ELSE 'Scheduled'
    END AS status,
    CASE
        WHEN COALESCE(competition, 'nba') LIKE 'summer_league_%' THEN 'summer_league'
        WHEN CAST(game_id AS TEXT) LIKE '004%' THEN 'playoffs'
        WHEN CAST(game_id AS TEXT) LIKE '005%' THEN 'play_in'
        WHEN CAST(game_id AS TEXT) LIKE '006%' THEN 'nba_cup'
        WHEN CAST(game_id AS TEXT) LIKE '001%' THEN 'preseason'
        ELSE 'regular_season'
    END AS game_type
FROM {{ source('bronze', 'schedule') }}

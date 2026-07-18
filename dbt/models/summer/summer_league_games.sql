{{ config(materialized='table', schema='silver', alias='summer_league_games', tags=['summer_league']) }}

SELECT
    CAST(game_id AS TEXT) AS game_id,
    season,
    league_id,
    competition,
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
    'summer_league' AS game_type
FROM {{ source('bronze', 'schedule') }}
WHERE competition LIKE 'summer_league_%'

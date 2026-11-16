{{ config(materialized='table', schema='silver', alias='dim_teams', tags=['silver']) }}

WITH source_teams AS (
    SELECT
        game_id,
        {{ parse_game_date("game_date") }} AS game_date,
        home_team_id AS fallback_team_id,
        home_team_abbr AS fallback_abbreviation,
        json_extract_string(raw_json, '$.homeTeam.teamId') AS raw_team_id,
        json_extract_string(raw_json, '$.homeTeam.id') AS raw_id,
        json_extract_string(raw_json, '$.homeTeam.teamTricode') AS raw_team_tricode,
        json_extract_string(raw_json, '$.homeTeam.abbreviation') AS raw_abbreviation,
        json_extract_string(raw_json, '$.homeTeam.teamName') AS raw_team_name,
        json_extract_string(raw_json, '$.homeTeam.nickname') AS raw_nickname,
        json_extract_string(raw_json, '$.homeTeam.teamCity') AS raw_team_city,
        json_extract_string(raw_json, '$.homeTeam.city') AS raw_city,
        json_extract_string(raw_json, '$.homeTeam.full_name') AS raw_full_name,
        json_extract_string(raw_json, '$.homeTeam.fullName') AS raw_full_name_camel
    FROM {{ source('bronze', 'schedule') }}

    UNION ALL

    SELECT
        game_id,
        {{ parse_game_date("game_date") }} AS game_date,
        away_team_id AS fallback_team_id,
        away_team_abbr AS fallback_abbreviation,
        json_extract_string(raw_json, '$.awayTeam.teamId') AS raw_team_id,
        json_extract_string(raw_json, '$.awayTeam.id') AS raw_id,
        json_extract_string(raw_json, '$.awayTeam.teamTricode') AS raw_team_tricode,
        json_extract_string(raw_json, '$.awayTeam.abbreviation') AS raw_abbreviation,
        json_extract_string(raw_json, '$.awayTeam.teamName') AS raw_team_name,
        json_extract_string(raw_json, '$.awayTeam.nickname') AS raw_nickname,
        json_extract_string(raw_json, '$.awayTeam.teamCity') AS raw_team_city,
        json_extract_string(raw_json, '$.awayTeam.city') AS raw_city,
        json_extract_string(raw_json, '$.awayTeam.full_name') AS raw_full_name,
        json_extract_string(raw_json, '$.awayTeam.fullName') AS raw_full_name_camel
    FROM {{ source('bronze', 'schedule') }}
),
normalized AS (
    SELECT
        COALESCE(TRY_CAST(raw_team_id AS INTEGER), TRY_CAST(raw_id AS INTEGER), fallback_team_id) AS team_id,
        COALESCE(NULLIF(raw_team_tricode, ''), NULLIF(raw_abbreviation, ''), fallback_abbreviation, '') AS abbreviation,
        COALESCE(NULLIF(raw_team_city, ''), NULLIF(raw_city, ''), '') AS city,
        COALESCE(NULLIF(raw_team_name, ''), NULLIF(raw_nickname, ''), '') AS nickname,
        COALESCE(NULLIF(raw_full_name, ''), NULLIF(raw_full_name_camel, '')) AS full_name_from_payload,
        game_date,
        game_id
    FROM source_teams
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY team_id
            ORDER BY game_date DESC, game_id DESC
        ) AS team_row_number
    FROM normalized
    -- The 30 NBA franchises; leaves out All-Star and visiting international teams.
    WHERE team_id BETWEEN 1610612737 AND 1610612766
)
SELECT
    team_id,
    abbreviation,
    COALESCE(
        full_name_from_payload,
        NULLIF(TRIM(city || ' ' || nickname), ''),
        abbreviation
    ) AS full_name,
    city,
    nickname
FROM ranked
WHERE team_row_number = 1

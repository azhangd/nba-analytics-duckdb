{{ config(materialized='table', schema='silver', alias='fct_team_coach_seasons', tags=['silver']) }}

SELECT
    CAST(team_id AS INTEGER) AS team_id,
    season,
    CAST(coach_id AS TEXT) AS coach_id,
    CASE
        WHEN COALESCE(is_assistant, 0) = 0 THEN 'head'
        WHEN LOWER(COALESCE(CAST(coach_type AS TEXT), '')) LIKE '%head%' THEN 'head'
        ELSE 'assistant'
    END AS role,
    TRIM(COALESCE(CAST(coach_type AS TEXT), '')) AS coach_type,
    sort_sequence AS sort_seq
FROM {{ source('bronze', 'coaches') }}

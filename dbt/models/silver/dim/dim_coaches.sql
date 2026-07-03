{{ config(materialized='table', schema='silver', alias='dim_coaches', tags=['silver']) }}

WITH normalized AS (
    SELECT
        CAST(coach_id AS TEXT) AS coach_id,
        TRIM(COALESCE(CAST(first_name AS TEXT), '')) AS first_name,
        TRIM(COALESCE(CAST(last_name AS TEXT), '')) AS last_name,
        TRIM(
            COALESCE(
                NULLIF(CAST(coach_name AS TEXT), ''),
                TRIM(COALESCE(CAST(first_name AS TEXT), '') || ' ' || COALESCE(CAST(last_name AS TEXT), '')),
                ''
            )
        ) AS full_name,
        TRIM(COALESCE(CAST(school AS TEXT), '')) AS school,
        TRIM(COALESCE(CAST(birth_date AS TEXT), '')) AS birth_date,
        season,
        team_id,
        sort_sequence
    FROM {{ source('bronze', 'coaches') }}
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY coach_id
            ORDER BY
                CASE WHEN full_name <> '' THEN 0 ELSE 1 END,
                season,
                team_id,
                sort_sequence
        ) AS coach_row_number
    FROM normalized
)
SELECT
    coach_id,
    full_name,
    first_name,
    last_name,
    school,
    birth_date
FROM ranked
WHERE coach_row_number = 1

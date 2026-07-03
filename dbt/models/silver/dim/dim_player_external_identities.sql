{{ config(materialized='table', schema='silver', alias='dim_player_external_identities', tags=['silver']) }}

SELECT
    CAST(player_id AS INTEGER) AS player_id,
    '' AS wikidata_qid,
    REPLACE(REGEXP_REPLACE(TRIM(CAST(full_name AS TEXT)), '\s+', ' ', 'g'), ' ', '_') AS wikipedia_title,
    0.25 AS source_confidence,
    'Deterministic name-derived identity; verify before using externally' AS source_note,
    CAST(CURRENT_TIMESTAMP AS TEXT) AS updated_at
FROM {{ ref('dim_players') }}
WHERE player_id IS NOT NULL
  AND player_id <> 0
  AND COALESCE(CAST(full_name AS TEXT), '') <> ''

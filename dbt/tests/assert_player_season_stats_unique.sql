SELECT
    player_id,
    season,
    COUNT(*) AS row_count
FROM {{ ref('player_season_stats') }}
GROUP BY player_id, season
HAVING COUNT(*) > 1

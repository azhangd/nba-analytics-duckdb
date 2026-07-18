SELECT game_id, game_event_id
FROM {{ ref('summer_league_shots') }}
GROUP BY game_id, game_event_id
HAVING COUNT(*) > 1

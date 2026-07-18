SELECT game_id, action_id
FROM {{ ref('summer_league_play_by_play') }}
GROUP BY game_id, action_id
HAVING COUNT(*) > 1

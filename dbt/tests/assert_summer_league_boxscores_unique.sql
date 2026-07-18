SELECT game_id, player_id
FROM {{ ref('summer_league_boxscores') }}
GROUP BY game_id, player_id
HAVING COUNT(*) > 1

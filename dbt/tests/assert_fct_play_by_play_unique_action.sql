select game_id, action_id, count(*) as row_count
from {{ ref('fct_play_by_play') }}
group by game_id, action_id
having count(*) > 1

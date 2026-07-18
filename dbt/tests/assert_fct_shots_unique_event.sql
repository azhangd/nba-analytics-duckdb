select game_id, game_event_id, count(*) as row_count
from {{ ref('fct_shots') }}
group by game_id, game_event_id
having count(*) > 1

# Tables

Every table in the database, grouped by layer:

![All the tables, grouped by layer](assets/schema.png)

## Core tables

![The core tables and how they join](assets/er_core.png)

## All tables

All silver and gold tables with key columns. Bronze tables are excluded because they only contain raw API responses.

![All the tables and how they join](assets/er_full.png)

## Notes

- Silver tables include every game type (preseason, regular season, All-Star, playoffs, play-in and NBA Cup), which you can find in `fct_games.game_type`. Gold tables only count regular-season games.
- `player_season_stats` has one row per player per season, so a traded player is listed under the team they played the most games for.
- `fct_lineups.player_ids_str` holds the ids of the players on the floor, sorted and separated by commas.
- Summer League tables only join to `summer_league_games`, since their player and team ids haven't been checked against `dim_players` and `dim_teams` yet.

To redraw the diagrams, run `make smoke` and then `make diagrams`. CI will fail if they're out of date.

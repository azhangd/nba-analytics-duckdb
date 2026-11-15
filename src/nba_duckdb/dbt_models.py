"""dbt-owned warehouse model metadata."""

DBT_SUMMER_LEAGUE_MODEL_NAMES = (
    "summer_league_games",
    "summer_league_boxscores",
    "summer_league_play_by_play",
    "summer_league_shots",
)

DBT_SILVER_MODEL_NAMES = (
    "dim_teams",
    "dim_players",
    "dim_coaches",
    "dim_injuries",
    "fct_team_coach_seasons",
    "fct_games",
    "fct_boxscores",
    "fct_play_by_play",
    "fct_possessions",
    "fct_shots",
    "fct_lineups",
    "fct_hustle",
    "fct_tracking",
    "fct_matchups",
    "fct_defense_play_types",
    "fct_game_detail",
)

DBT_GOLD_MODEL_NAMES = (
    "player_game_stats",
    "team_game_stats",
    "team_season_elo",
    "team_game_elo_history",
    "player_season_stats_base",
    "player_season_stats",
    "player_game_rolling_stats",
    "player_season_split_stats",
    "player_season_on_off_stats",
    "lineup_season_stats",
    "player_combo_season_stats",
    "player_season_mvp_ladder",
    "team_season_four_factors",
    "team_season_percentile_ranks",
    "team_season_starter_bench_stats",
    "player_season_load_management",
    "team_season_clutch_stats",
    "team_season_opponent_scouting",
    "team_season_timeout_stats",
    "team_season_ato_stats",
    "player_season_clutch_stats",
    "team_season_shot_profile",
    "player_season_shot_profile",
    "player_zone_season_shot_quality",
    "team_season_play_type_stats",
    "team_season_play_type_splits",
    "team_season_feature_matrix",
    "player_season_feature_matrix",
)

DBT_MODEL_DATASETS = (
    *(f"silver.{model}" for model in DBT_SILVER_MODEL_NAMES),
    *(f"gold.{model}" for model in DBT_GOLD_MODEL_NAMES),
    *(f"silver.{model}" for model in DBT_SUMMER_LEAGUE_MODEL_NAMES),
)
DBT_MODEL_NAMES = (
    *DBT_SILVER_MODEL_NAMES,
    *DBT_GOLD_MODEL_NAMES,
    *DBT_SUMMER_LEAGUE_MODEL_NAMES,
)
DBT_CORE_MODEL_NAMES = (*DBT_SILVER_MODEL_NAMES, *DBT_GOLD_MODEL_NAMES)
DBT_CORE_MODEL_DATASETS = (
    *(f"silver.{model}" for model in DBT_SILVER_MODEL_NAMES),
    *(f"gold.{model}" for model in DBT_GOLD_MODEL_NAMES),
)
DBT_SUMMER_LEAGUE_MODEL_DATASETS = tuple(
    f"silver.{model}" for model in DBT_SUMMER_LEAGUE_MODEL_NAMES
)

DBT_TRANSFORM_SELECTOR = "tag:silver tag:gold"
DBT_SUMMER_LEAGUE_SELECTOR = "tag:summer_league"

DBT_TRANSFORM_INPUTS = (
    "bronze.schedule",
    "bronze.rosters",
    "bronze.coaches",
    "bronze.boxscores",
    "bronze.play_by_play",
    "bronze.shot_charts",
    "bronze.tracking_stats",
    "bronze.hustle",
    "bronze.matchups",
    "bronze.defense",
    "bronze.game_detail",
    "bronze.injuries",
)

# The CLI runs each dbt group as one task; Airflow/Cosmos splits it per model.
DBT_TRANSFORM_TASK_DEF = {
    "name": "dbt_build_warehouse",
    "dbt_selector": DBT_TRANSFORM_SELECTOR,
    "dbt_models": DBT_CORE_MODEL_NAMES,
    "inputs": DBT_TRANSFORM_INPUTS,
    "outputs": DBT_CORE_MODEL_DATASETS,
    "graphs": ("default",),
    "modes": ("live", "fixture"),
    "required": True,
    "live_order": 295,
    "fixture_order": 175,
}

DBT_SUMMER_LEAGUE_TASK_DEF = {
    "name": "dbt_build_summer_league",
    "dbt_selector": DBT_SUMMER_LEAGUE_SELECTOR,
    "dbt_models": DBT_SUMMER_LEAGUE_MODEL_NAMES,
    "inputs": (
        "bronze.schedule",
        "bronze.boxscores",
        "bronze.play_by_play",
        "bronze.shot_charts",
    ),
    "outputs": DBT_SUMMER_LEAGUE_MODEL_DATASETS,
    "graphs": ("summer_league",),
    "modes": ("live",),
    "required": True,
    "regular_season_only": False,
    "live_order": 100,
}

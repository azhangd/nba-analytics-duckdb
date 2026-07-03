"""dbt-owned warehouse model metadata."""

DBT_FEATURE_MODEL_NAMES = (
    "player_season_feature_matrix",
)

DBT_RUNTIME_DEPENDENT_SELECTOR = "tag:requires_gold_runtime"

DBT_SILVER_MODEL_NAMES = (
    "dim_teams",
    "dim_players",
    "dim_coaches",
    "dim_player_external_identities",
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
    "player_season_archetypes",
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
    "game_flow_snapshots",
    "team_season_feature_matrix",
    *DBT_FEATURE_MODEL_NAMES,
)

DBT_MODEL_DATASETS = (
    *(f"silver.{model}" for model in DBT_SILVER_MODEL_NAMES),
    *(f"gold.{model}" for model in DBT_GOLD_MODEL_NAMES),
)
DBT_MODEL_NAMES = (*DBT_SILVER_MODEL_NAMES, *DBT_GOLD_MODEL_NAMES)
DBT_CORE_MODEL_NAMES = (
    *DBT_SILVER_MODEL_NAMES,
    *(model for model in DBT_GOLD_MODEL_NAMES if model not in DBT_FEATURE_MODEL_NAMES),
)
DBT_CORE_MODEL_DATASETS = tuple(
    f"silver.{model}" if model in DBT_SILVER_MODEL_NAMES else f"gold.{model}"
    for model in DBT_CORE_MODEL_NAMES
)
DBT_FEATURE_MODEL_DATASETS = tuple(f"gold.{model}" for model in DBT_FEATURE_MODEL_NAMES)

DBT_TRANSFORM_SELECTOR = "tag:silver tag:gold"
# The core build exclude and the feature build selector are two sides of the
# same orchestration boundary: models that require runtime gold artifacts.
DBT_TRANSFORM_EXCLUDE = DBT_RUNTIME_DEPENDENT_SELECTOR
DBT_FEATURE_SELECTOR = DBT_RUNTIME_DEPENDENT_SELECTOR

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

# Compatibility metadata for the local run ledger while the CLI wraps dbt as one
# build phase. Model-level lineage is owned by the dbt manifest and Dagster.
DBT_TRANSFORM_TASK_DEF = {
    "name": "dbt_build_warehouse",
    "dbt_selector": DBT_TRANSFORM_SELECTOR,
    "dbt_exclude": DBT_TRANSFORM_EXCLUDE,
    "dbt_models": DBT_CORE_MODEL_NAMES,
    "inputs": DBT_TRANSFORM_INPUTS,
    "outputs": DBT_CORE_MODEL_DATASETS,
    "graphs": ("default",),
    "modes": ("live", "fixture"),
    "required": True,
    "quality_outputs": DBT_CORE_MODEL_DATASETS,
    "live_order": 295,
    "fixture_order": 175,
}

DBT_FEATURE_INPUTS = (
    "gold.player_season_stats",
    "gold.player_game_rolling_stats",
    "gold.player_season_shot_profile",
    "gold.player_season_archetypes",
    "gold.player_season_embeddings",
    "gold.player_season_rapm",
    "silver.fct_hustle",
    "gold.player_season_clutch_stats",
    "gold.player_game_stats",
    "silver.fct_games",
)

DBT_FEATURE_TASK_DEF = {
    "name": "dbt_build_feature_matrices",
    "dbt_selector": DBT_FEATURE_SELECTOR,
    "dbt_models": DBT_FEATURE_MODEL_NAMES,
    "inputs": DBT_FEATURE_INPUTS,
    "outputs": DBT_FEATURE_MODEL_DATASETS,
    "graphs": ("default",),
    "modes": ("live", "fixture"),
    "required": True,
    "quality_outputs": DBT_FEATURE_MODEL_DATASETS,
    "live_order": 700,
    "fixture_order": 560,
}

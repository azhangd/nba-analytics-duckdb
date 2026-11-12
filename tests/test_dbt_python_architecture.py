import ast
from pathlib import Path

EXPECTED_DBT_PYTHON_MODELS = {
    "dim_injuries",
    "dim_players",
    "fct_boxscores",
    "fct_defense_play_types",
    "fct_game_detail",
    "fct_hustle",
    "fct_lineups",
    "fct_matchups",
    "fct_play_by_play",
    "fct_possessions",
    "fct_shots",
    "fct_tracking",
    "game_flow_snapshots",
    "player_season_stats",
    "player_combo_season_stats",
    "player_season_archetypes",
    "player_zone_season_shot_quality",
    "summer_league_boxscores",
    "summer_league_play_by_play",
    "summer_league_shots",
    "team_game_elo_history",
    "team_season_elo",
    "team_season_play_type_splits",
    "team_season_play_type_stats",
}

RUNTIME_MODULE_PREFIXES = (
    "airflow",
    "cosmos",
    "dbt",
    "nba_duckdb.tasks",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dbt_python_models() -> list[Path]:
    return sorted((_repo_root() / "dbt" / "models").glob("**/*.py"))


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("**/*.py") if "__pycache__" not in path.parts)


def _imports_for(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports = [
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    imports += [
        node.module or ""
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    ]
    return imports


def test_remaining_dbt_python_models_are_explicitly_justified():
    actual = {path.stem for path in _dbt_python_models()}

    assert actual == EXPECTED_DBT_PYTHON_MODELS

    for path in _dbt_python_models():
        imports = _imports_for(path)
        assert all(
            module.startswith("nba_duckdb.transforms.")
            or module == "nba_duckdb.dbt_support"
            for module in imports
        ), path


def test_dbt_and_transforms_do_not_import_runtime_modules():
    root = _repo_root()
    checked = _dbt_python_models() + _python_sources(root / "src" / "nba_duckdb" / "transforms")

    for path in checked:
        imports = _imports_for(path)
        for module in imports:
            assert not module.startswith(RUNTIME_MODULE_PREFIXES), (path, module)

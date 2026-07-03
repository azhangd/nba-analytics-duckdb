import ast
from pathlib import Path

import pytest

CONVERTED_SQL_MODELS = {
    "dim_coaches",
    "dim_player_external_identities",
    "dim_teams",
    "fct_games",
    "fct_team_coach_seasons",
    "player_game_stats",
    "team_game_stats",
}

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
    "team_game_elo_history",
    "team_season_elo",
    "team_season_play_type_splits",
    "team_season_play_type_stats",
}

RUNTIME_MODULE_PREFIXES = (
    "dagster",
    "dagster_dbt",
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


def test_dbt_bridge_modules_were_removed():
    root = _repo_root()
    bridge_modules = [f"dbt_{layer}" for layer in ("silver", "gold")]

    for module in bridge_modules:
        assert not (root / "src" / "nba_duckdb" / f"{module}.py").exists()

    self_path = Path(__file__).resolve()
    for path in _python_sources(root / "src") + _python_sources(root / "tests") + _dbt_python_models():
        if path.resolve() == self_path:
            continue
        text = path.read_text()
        for module in bridge_modules:
            assert f"nba_duckdb.{module}" not in text, path


def test_simple_dbt_models_are_sql_not_python_adapters():
    models_root = _repo_root() / "dbt" / "models"

    for model in CONVERTED_SQL_MODELS:
        sql_path = next(models_root.glob(f"**/{model}.sql"), None)
        py_path = next(models_root.glob(f"**/{model}.py"), None)
        assert sql_path is not None, model
        assert py_path is None, model


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


@pytest.mark.parametrize(
    "module_path",
    [
        "src/nba_duckdb/transforms/silver/coaches.py",
        "src/nba_duckdb/transforms/silver/games.py",
        "src/nba_duckdb/transforms/silver/external_identities.py",
        "src/nba_duckdb/transforms/gold/player_game_stats.py",
        "src/nba_duckdb/transforms/gold/team_game_stats.py",
    ],
)
def test_over_abstracted_one_use_transform_modules_were_removed(module_path):
    assert not (_repo_root() / module_path).exists()


def test_dbt_and_transforms_do_not_import_runtime_modules():
    root = _repo_root()
    checked = _dbt_python_models() + _python_sources(root / "src" / "nba_duckdb" / "transforms")

    for path in checked:
        imports = _imports_for(path)
        for module in imports:
            assert not module.startswith(RUNTIME_MODULE_PREFIXES), (path, module)

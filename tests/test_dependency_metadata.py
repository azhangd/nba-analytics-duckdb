from __future__ import annotations

import re
import tomllib
from pathlib import Path


def _pyproject_optional_dependencies() -> dict[str, list[str]]:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text())["project"]["optional-dependencies"]


def _package_name(requirement: str) -> str:
    return re.split(r"[<>=!~;\\[]", requirement, maxsplit=1)[0].strip()


def _package_names(requirements: list[str]) -> set[str]:
    return {_package_name(requirement) for requirement in requirements}


def test_full_extra_is_exact_union_of_ml_and_live_extras():
    optional = _pyproject_optional_dependencies()

    assert sorted(optional["full"]) == sorted({*optional["ml"], *optional["live"]})


def test_optional_dependency_groups_match_pyproject_extras():
    from nba_duckdb.dependencies import OPTIONAL_GROUPS

    optional = _pyproject_optional_dependencies()

    assert set(OPTIONAL_GROUPS) == {"ml", "live"}
    for group_name, modules in OPTIONAL_GROUPS.items():
        assert set(modules.values()) == _package_names(optional[group_name])


def test_missing_optional_dependency_error_behaves_like_runtime_error():
    from nba_duckdb.dependencies import MissingOptionalDependencyError

    exc = MissingOptionalDependencyError(
        groups=("ml",),
        missing_modules=("sklearn",),
        missing_packages=("scikit-learn",),
        hint="Install ML dependencies.",
        install_command="uv sync --extra dev --extra ml",
        pip_install_command='python -m pip install -e ".[dev,ml]"',
    )

    assert isinstance(exc, RuntimeError)
    assert exc.args == (str(exc),)


def test_missing_required_dependency_error_behaves_like_runtime_error():
    from nba_duckdb.dependencies import MissingRequiredDependencyError

    exc = MissingRequiredDependencyError(
        missing_modules=("dbt",),
        missing_packages=("dbt-core",),
        hint="Install project dependencies.",
        install_command="uv sync --extra dev",
        pip_install_command='python -m pip install -e ".[dev]"',
    )

    assert isinstance(exc, RuntimeError)
    assert exc.args == (str(exc),)

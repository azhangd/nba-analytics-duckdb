from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_checker():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_artifacts.py"
    spec = importlib.util.spec_from_file_location("check_artifacts", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_artifact_checker_allows_committed_synthetic_fixture_json(tmp_path):
    checker = _load_checker()
    _write(tmp_path / "tests/fixtures/generated/synthetic_teams.json", "[]")

    violations = checker.check_paths(
        ["tests/fixtures/generated/synthetic_teams.json"],
        root=tmp_path,
    )

    assert violations == []


def test_artifact_checker_rejects_generated_data_and_notebooks(tmp_path):
    checker = _load_checker()
    paths = [
        "data/warehouse/nba.duckdb",
        "exports/team_summary.csv",
        "analysis.ipynb",
        "models/model.joblib",
        "artifacts/embeddings/model.joblib",
    ]
    for path in paths:
        _write(tmp_path / path, "artifact")

    violations = checker.check_paths(paths, root=tmp_path)

    assert {violation.path for violation in violations} == set(paths)


def test_artifact_checker_rejects_oversized_tracked_files(tmp_path):
    checker = _load_checker()
    _write(tmp_path / "README.md", "too large")

    violations = checker.check_paths(["README.md"], root=tmp_path, max_file_bytes=4)

    assert violations[0].path == "README.md"
    assert "larger" in violations[0].reason


def test_direct_dependencies_do_not_include_unused_heavy_packages():
    pyproject = Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text()
    src_text = "\n".join(
        path.read_text()
        for path in Path(__file__).resolve().parents[1].joinpath("src").rglob("*.py")
    )

    assert '"shap' not in pyproject
    assert '"numba' not in pyproject
    assert "import shap" not in src_text
    assert "from shap" not in src_text
    assert "import numba" not in src_text
    assert "from numba" not in src_text


def test_artifact_root_respects_env_changes_in_same_process(tmp_path, monkeypatch):
    from nba_duckdb.modeling.artifact_paths import artifact_root

    first = tmp_path / "artifacts-one"
    second = tmp_path / "artifacts-two"

    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(first))
    assert artifact_root() == str(first)

    monkeypatch.setenv("NBA_DUCKDB_ARTIFACT_ROOT", str(second))
    assert artifact_root() == str(second)

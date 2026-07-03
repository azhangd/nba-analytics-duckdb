import importlib.util
import os
from pathlib import Path

import pytest


def _load_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_wheel_smoke.py"
    spec = importlib.util.spec_from_file_location("check_wheel_smoke", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wheel_smoke_requires_a_built_wheel(tmp_path, monkeypatch):
    script = _load_script()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dist").mkdir()

    with pytest.raises(SystemExit, match="No wheel found"):
        script._latest_wheel()


def test_wheel_smoke_selects_latest_built_wheel(tmp_path, monkeypatch):
    script = _load_script()
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    old_wheel = dist / "nba_analytics_duckdb-0.0.1-py3-none-any.whl"
    new_wheel = dist / "nba_analytics_duckdb-0.0.2-py3-none-any.whl"
    old_wheel.write_text("old")
    new_wheel.write_text("new")
    os.utime(old_wheel, (1, 1))
    os.utime(new_wheel, (2, 2))

    assert script._latest_wheel().resolve() == new_wheel

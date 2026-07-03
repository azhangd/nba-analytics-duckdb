import importlib.util
import sys
from pathlib import Path

import duckdb


def _load_basic_team_summary_module():
    path = Path(__file__).parents[1] / "examples" / "basic_team_summary" / "analysis.py"
    spec = importlib.util.spec_from_file_location("basic_team_summary", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_team_summary_warehouse(path: Path, *, season: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as conn:
        conn.execute("CREATE SCHEMA gold")
        conn.execute(
            """
            CREATE TABLE gold.team_game_stats (
                season VARCHAR,
                team_id INTEGER,
                is_win BOOLEAN,
                pts DOUBLE,
                opp_pts DOUBLE,
                margin DOUBLE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE gold.team_season_elo (
                season VARCHAR,
                team_id INTEGER,
                team_abbreviation VARCHAR,
                elo_rating DOUBLE,
                comparison_scope VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE gold.team_season_four_factors (
                season VARCHAR,
                team_id INTEGER,
                off_efg_pct DOUBLE,
                def_efg_pct DOUBLE
            )
            """
        )
        conn.execute(
            "INSERT INTO gold.team_game_stats VALUES (?, ?, ?, ?, ?, ?)",
            [season, 1610612737, True, 101.0, 95.0, 6.0],
        )
        conn.execute(
            "INSERT INTO gold.team_season_elo VALUES (?, ?, ?, ?, ?)",
            [season, 1610612737, "MET", 1512.5, "loaded_sample"],
        )
        conn.execute(
            "INSERT INTO gold.team_season_four_factors VALUES (?, ?, ?, ?)",
            [season, 1610612737, 0.55, 0.51],
        )


def test_basic_team_summary_flags_mixed_synthetic_rows():
    module = _load_basic_team_summary_module()

    assert module._uses_synthetic_fixture_season(
        ["season", "team"],
        [("2025-26", "ATL"), ("2099-00", "MET")],
    )


def test_basic_team_summary_defaults_to_smoke_warehouse():
    module = _load_basic_team_summary_module()

    assert module.DEFAULT_WAREHOUSE == Path("data/warehouse/smoke.duckdb")


def test_basic_team_summary_prints_synthetic_warning_by_default(
    tmp_path,
    monkeypatch,
    capsys,
):
    module = _load_basic_team_summary_module()
    warehouse = tmp_path / "data" / "warehouse" / "smoke.duckdb"
    _write_team_summary_warehouse(warehouse, season="2099-00")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["analysis.py"])

    assert module.main() == 0

    output = capsys.readouterr().out
    assert "Synthetic smoke warehouse" in output
    assert "2099-00" in output
    assert "MET" in output


def test_basic_team_summary_omits_synthetic_warning_for_live_like_rows(
    tmp_path,
    monkeypatch,
    capsys,
):
    module = _load_basic_team_summary_module()
    warehouse = tmp_path / "nba.duckdb"
    _write_team_summary_warehouse(warehouse, season="2025-26")

    monkeypatch.delenv("NBA_DUCKDB_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["analysis.py", "--warehouse", str(warehouse)])

    assert module.main() == 0

    output = capsys.readouterr().out
    assert "Synthetic smoke warehouse" not in output
    assert "2025-26" in output

from pathlib import Path

from nba_duckdb.sql.schema import SCHEMA_FILES


def test_schema_init_creates_expected_tables(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    db.init_schema()

    rows = db.execute_sql(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('bronze', 'silver', 'gold', 'ops')
        """
    )
    tables = {(row["table_schema"], row["table_name"]) for row in rows}

    expected = {
        ("bronze", "schedule"),
        ("bronze", "boxscores"),
        ("gold", "model_artifacts"),
        ("ops", "pipeline_runs"),
        ("ops", "task_runs"),
        ("ops", "ingestion_items"),
    }
    assert expected.issubset(tables)


def test_schema_manifest_matches_files_on_disk():
    schema_dir = Path(__file__).resolve().parents[1] / "src" / "nba_duckdb" / "sql" / "schema"

    sql_files = {path.name for path in schema_dir.glob("*.sql")}

    assert len(SCHEMA_FILES) == len(set(SCHEMA_FILES))
    assert set(SCHEMA_FILES) == sql_files

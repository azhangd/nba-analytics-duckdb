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


def test_lightweight_migrations_do_not_touch_dbt_owned_tables():
    from nba_duckdb import db
    from nba_duckdb.dbt_models import DBT_MODEL_DATASETS

    migration_targets = {
        f"{schema}.{table}"
        for schema, table, _sql in db.LIGHTWEIGHT_MIGRATIONS
    }

    assert migration_targets.isdisjoint(DBT_MODEL_DATASETS)


def test_lightweight_migrations_add_competition_scope_to_existing_schedule(
    tmp_path,
    monkeypatch,
):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "legacy.duckdb"))
    db.execute_sql("CREATE SCHEMA bronze")
    db.execute_sql(
        """
        CREATE TABLE bronze.schedule (
            game_id TEXT PRIMARY KEY,
            season TEXT
        )
        """
    )
    db.execute_sql(
        "INSERT INTO bronze.schedule (game_id, season) VALUES ('0022500001', '2025-26')"
    )

    db.init_schema()

    assert db.execute_sql(
        "SELECT game_id, league_id, competition FROM bronze.schedule"
    ) == [
        {
            "game_id": "0022500001",
            "league_id": "00",
            "competition": "nba",
        }
    ]


def test_schema_manifest_matches_files_on_disk():
    schema_dir = Path(__file__).resolve().parents[1] / "src" / "nba_duckdb" / "sql" / "schema"

    sql_files = {path.name for path in schema_dir.glob("*.sql")}

    assert len(SCHEMA_FILES) == len(set(SCHEMA_FILES))
    assert set(SCHEMA_FILES) == sql_files

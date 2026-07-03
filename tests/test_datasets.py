import duckdb
import pytest


def _create_materialize_table(db):
    db.execute_sql("CREATE SCHEMA IF NOT EXISTS test_silver")
    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS test_silver.materialize_target (
            id INTEGER PRIMARY KEY,
            season TEXT,
            team_id INTEGER,
            value INTEGER NOT NULL
        )
        """
    )


def test_materialize_replaces_only_scoped_rows(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, materialize

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [
            {"id": 1, "season": "2024-25", "value": 10},
            {"id": 2, "season": "2025-26", "value": 20},
        ],
    )

    count = materialize(
        DatasetSpec("test_silver", "materialize_target", default_scope_col="season"),
        [{"id": 3, "season": "2025-26", "value": 30}],
        scope_values=["2025-26"],
    )

    rows = db.execute_sql(
        """
        SELECT id, season, value
        FROM test_silver.materialize_target
        ORDER BY id
        """
    )
    assert count == 1
    assert rows == [
        {"id": 1, "season": "2024-25", "value": 10},
        {"id": 3, "season": "2025-26", "value": 30},
    ]


def test_materialize_replaces_multi_column_scope(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, materialize

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [
            {"id": 1, "season": "2025-26", "team_id": 1, "value": 10},
            {"id": 2, "season": "2025-26", "team_id": 2, "value": 20},
            {"id": 3, "season": "2024-25", "team_id": 1, "value": 30},
        ],
    )

    count = materialize(
        DatasetSpec("test_silver", "materialize_target"),
        [{"id": 4, "season": "2025-26", "team_id": 1, "value": 40}],
        scope_filters={"season": ["2025-26"], "team_id": [1]},
    )

    rows = db.execute_sql(
        """
        SELECT id, season, team_id, value
        FROM test_silver.materialize_target
        ORDER BY id
        """
    )
    assert count == 1
    assert rows == [
        {"id": 2, "season": "2025-26", "team_id": 2, "value": 20},
        {"id": 3, "season": "2024-25", "team_id": 1, "value": 30},
        {"id": 4, "season": "2025-26", "team_id": 1, "value": 40},
    ]


def test_materialize_preserves_scope_on_insert_failure(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, materialize

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [{"id": 1, "season": "2025-26", "value": 10}],
    )

    with pytest.raises(duckdb.Error):
        materialize(
            DatasetSpec("test_silver", "materialize_target", default_scope_col="season"),
            [{"id": 2, "season": "2025-26", "value": "not-an-int"}],
            scope_values=["2025-26"],
        )

    rows = db.execute_sql(
        """
        SELECT id, season, value
        FROM test_silver.materialize_target
        ORDER BY id
        """
    )
    assert rows == [{"id": 1, "season": "2025-26", "value": 10}]


def test_materialize_empty_scope_behavior_is_explicit(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, materialize

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [{"id": 1, "season": "2025-26", "value": 10}],
    )

    preserved = materialize(
        DatasetSpec("test_silver", "materialize_target", default_scope_col="season"),
        [],
        scope_values=["2025-26"],
    )
    assert preserved == 0
    assert db.count_rows("test_silver", "materialize_target") == 1

    deleted = materialize(
        DatasetSpec(
            "test_silver",
            "materialize_target",
            default_scope_col="season",
            delete_scope_when_empty=True,
        ),
        [],
        scope_values=["2025-26"],
    )
    assert deleted == 0
    assert db.count_rows("test_silver", "materialize_target") == 0


def test_materialize_rejects_rows_outside_explicit_scope(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, materialize

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [{"id": 1, "season": "2025-26", "value": 10}],
    )

    with pytest.raises(ValueError, match="outside.*season scope|out-of-scope"):
        materialize(
            DatasetSpec("test_silver", "materialize_target", default_scope_col="season"),
            [{"id": 2, "season": "2024-25", "value": 20}],
            scope_values=["2025-26"],
        )

    rows = db.execute_sql(
        "SELECT id, season, value FROM test_silver.materialize_target ORDER BY id"
    )
    assert rows == [{"id": 1, "season": "2025-26", "value": 10}]


def test_materialize_derived_clears_empty_explicit_scope(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, materialize_derived

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [
            {"id": 1, "season": "2024-25", "value": 10},
            {"id": 2, "season": "2025-26", "value": 20},
        ],
    )

    count = materialize_derived(
        DatasetSpec("test_silver", "materialize_target", default_scope_col="season"),
        [],
        scope_values=["2025-26"],
    )

    rows = db.execute_sql(
        """
        SELECT id, season, value
        FROM test_silver.materialize_target
        ORDER BY id
        """
    )
    assert count == 0
    assert rows == [{"id": 1, "season": "2024-25", "value": 10}]


def test_materialize_expectations_fail_before_delete(tmp_path, monkeypatch):
    from nba_duckdb import db
    from nba_duckdb.datasets import DatasetSpec, NotNullExpectation, materialize

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [{"id": 1, "season": "2025-26", "value": 10}],
    )

    with pytest.raises(ValueError, match="null values"):
        materialize(
            DatasetSpec(
                "test_silver",
                "materialize_target",
                default_scope_col="season",
                expectations=(NotNullExpectation(("season",)),),
            ),
            [{"id": 2, "season": None, "value": 20}],
            scope_values=["2025-26"],
        )

    assert db.count_rows("test_silver", "materialize_target") == 1


def test_upsert_rows_rolls_back_delete_on_insert_failure(tmp_path, monkeypatch):
    from nba_duckdb import db

    monkeypatch.setenv("NBA_DUCKDB_PATH", str(tmp_path / "nba.duckdb"))
    _create_materialize_table(db)
    db.insert_rows(
        "test_silver",
        "materialize_target",
        [{"id": 1, "season": "2025-26", "value": 10}],
    )

    with pytest.raises(duckdb.Error):
        db.upsert_rows(
            "test_silver",
            "materialize_target",
            [
                {"id": 1, "season": "2025-26", "value": 20},
                {"id": 2, "season": "2025-26", "value": "not-an-int"},
            ],
            conflict_cols=["id"],
        )

    rows = db.execute_sql(
        "SELECT id, season, value FROM test_silver.materialize_target ORDER BY id"
    )
    assert rows == [{"id": 1, "season": "2025-26", "value": 10}]

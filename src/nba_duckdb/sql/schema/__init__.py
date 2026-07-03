"""Manifest-ordered warehouse schema SQL files."""

from __future__ import annotations

from importlib import resources

SCHEMA_FILES = (
    "schemas.sql",
    "ops.sql",
    "bronze.sql",
    "gold_player.sql",
    "gold_team.sql",
    "gold_play_model_signal.sql",
)


def schema_sql_parts() -> tuple[tuple[str, str], ...]:
    schema_package = resources.files(__package__)
    return tuple((filename, schema_package.joinpath(filename).read_text()) for filename in SCHEMA_FILES)


def schema_sql_text() -> str:
    return "\n\n".join(sql_text for _, sql_text in schema_sql_parts())

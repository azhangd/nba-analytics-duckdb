"""Helpers for resolving writable local artifact directories."""

from __future__ import annotations

import os
from pathlib import Path

from nba_duckdb import config


def artifact_root() -> str:
    explicit_root = (
        os.environ.get("NBA_DUCKDB_ARTIFACT_ROOT")
        or os.environ.get("NBA_DUCKDB_ARTIFACT_DIR")
    )
    if explicit_root:
        return explicit_root

    configured = config.get_settings().artifact_root
    if configured.is_absolute():
        return str(configured)
    return str(Path.cwd() / configured)


def artifact_dir(*parts: str) -> str:
    return os.path.join(artifact_root(), *parts)

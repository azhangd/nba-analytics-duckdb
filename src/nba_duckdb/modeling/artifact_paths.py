"""Helpers for resolving writable local artifact directories."""

from __future__ import annotations

import os
from pathlib import Path

from nba_duckdb import config


def artifact_root() -> str:
    root = config.artifact_root()
    return str(root if root.is_absolute() else Path.cwd() / root)


def artifact_dir(*parts: str) -> str:
    return os.path.join(artifact_root(), *parts)

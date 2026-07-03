"""Runtime configuration helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE_LOADED_VALUES: dict[str, str] = {}


def _read_env_file(path: str | Path = ".env") -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def load_env_file(path: str | Path = ".env") -> None:
    for key, value in _read_env_file(path).items():
        if key not in os.environ:
            os.environ[key] = value
            _ENV_FILE_LOADED_VALUES[key] = value


def env_value_loaded_from_file(key: str) -> bool:
    """Return whether the current environment value came from `.env` loading."""
    return os.environ.get(key) == _ENV_FILE_LOADED_VALUES.get(key)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NBA_DUCKDB_", env_file=".env")

    duckdb_path: Path = Field(
        default=Path("data/warehouse/nba.duckdb"),
        validation_alias="NBA_DUCKDB_PATH",
    )
    raw_root: Path = Path("data/raw")
    artifact_root: Path = Path("data/artifacts")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]


def fixtures_dir(value: str | None = None) -> Path:
    load_env_file()
    raw = value or os.environ.get("NBA_DUCKDB_FIXTURES_DIR")
    return Path(raw) if raw else Path("data") / "fixtures" / "generated"


def smoke_warehouse_path() -> Path:
    raw = os.environ.get("NBA_DUCKDB_SMOKE_PATH") or _read_env_file().get(
        "NBA_DUCKDB_SMOKE_PATH"
    )
    return Path(raw or "data/warehouse/smoke.duckdb")


def quick_smoke_warehouse_path() -> Path:
    raw = os.environ.get("NBA_DUCKDB_QUICK_SMOKE_PATH") or _read_env_file().get(
        "NBA_DUCKDB_QUICK_SMOKE_PATH"
    )
    return Path(raw or "data/warehouse/smoke-quick.duckdb")


@lru_cache
def get_settings() -> Settings:
    load_env_file()
    return Settings()

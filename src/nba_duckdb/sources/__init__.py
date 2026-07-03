"""Source adapters for bronze ingestion."""

from nba_duckdb.sources.base import SourceAdapter, SourcePayload
from nba_duckdb.sources.fixtures import FixtureSource


def get_source_adapter(source_name: str, *, fixtures_dir: str | None = None) -> SourceAdapter:
    if source_name == "fixtures":
        return FixtureSource(fixtures_dir=fixtures_dir)
    msg = f"Unsupported source adapter: {source_name}"
    raise ValueError(msg)


__all__ = ["FixtureSource", "SourceAdapter", "SourcePayload", "get_source_adapter"]

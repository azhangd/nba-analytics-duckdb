"""Common source adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SourcePayload:
    teams: list[dict[str, Any]]
    players: list[dict[str, Any]]
    schedule: list[dict[str, Any]]
    boxscores: list[dict[str, Any]]
    play_by_play: list[dict[str, Any]]
    shot_charts: list[dict[str, Any]]


class SourceAdapter(Protocol):
    def read(self) -> SourcePayload:
        """Return one coherent bronze source payload."""

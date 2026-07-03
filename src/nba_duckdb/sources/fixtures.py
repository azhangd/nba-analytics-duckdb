"""Synthetic fixture source adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nba_duckdb import config
from nba_duckdb.fixtures.generate_synthetic_fixtures import generate_fixtures
from nba_duckdb.sources.base import SourcePayload

REQUIRED_FILES = {
    "teams": "synthetic_teams.json",
    "players": "synthetic_players.json",
    "schedule": "synthetic_schedule.json",
    "boxscores": "synthetic_boxscore.json",
    "play_by_play": "synthetic_play_by_play.json",
    "shot_charts": "synthetic_shot_charts.json",
}


class FixtureSource:
    def __init__(self, fixtures_dir: str | Path | None = None) -> None:
        self.fixtures_dir = config.fixtures_dir(str(fixtures_dir) if fixtures_dir else None)

    def read(self) -> SourcePayload:
        if not self._has_required_files():
            generate_fixtures(self.fixtures_dir)

        return SourcePayload(
            teams=self._read_json("teams"),
            players=self._read_json("players"),
            schedule=self._read_json("schedule"),
            boxscores=self._read_json("boxscores"),
            play_by_play=self._read_json("play_by_play"),
            shot_charts=self._read_json("shot_charts"),
        )

    def _has_required_files(self) -> bool:
        return all((self.fixtures_dir / filename).exists() for filename in REQUIRED_FILES.values())

    def _read_json(self, key: str) -> Any:
        return json.loads((self.fixtures_dir / REQUIRED_FILES[key]).read_text())

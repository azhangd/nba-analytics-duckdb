import json

import polars as pl
import pytest


def _frames() -> dict[tuple[str, str], pl.DataFrame]:
    game_id = "1522600001"
    return {
        ("bronze", "schedule"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "season": "2026-27",
                    "competition": "summer_league_vegas",
                    "game_status": 3,
                }
            ]
        ),
        ("bronze", "boxscores"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "traditional_json": json.dumps(
                        {"boxScoreTraditional": {"gameId": game_id}}
                    ),
                }
            ]
        ),
        ("bronze", "play_by_play"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "pbp_json": json.dumps(
                        {"game": {"actions": [{"actionNumber": 1}]}}
                    ),
                }
            ]
        ),
        ("bronze", "shot_charts"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "shot_chart_json": json.dumps(
                        {
                            "resultSets": [
                                {"name": "Shot_Chart_Detail", "rowSet": [[1]]}
                            ]
                        }
                    ),
                }
            ]
        ),
        ("silver", "summer_league_games"): pl.DataFrame([{"game_id": game_id}]),
        ("silver", "summer_league_boxscores"): pl.DataFrame([{"game_id": game_id}]),
        ("silver", "summer_league_play_by_play"): pl.DataFrame([{"game_id": game_id}]),
        ("silver", "summer_league_shots"): pl.DataFrame([{"game_id": game_id}]),
    }


def test_summer_league_quality_gate_requires_end_to_end_coverage(monkeypatch):
    from nba_duckdb.tasks.quality import validate_summer_league

    frames = _frames()
    monkeypatch.setattr(
        validate_summer_league,
        "read_table",
        lambda schema, table: frames[(schema, table)],
    )

    result = validate_summer_league.run(
        season="2026-27",
        competitions=["summer_league_vegas"],
    )

    assert result["status"] == "success"
    assert result["competition_counts"] == {"summer_league_vegas": 1}
    assert result["schedule_games"] == 1
    assert result["completed_games"] == 1


def test_summer_league_quality_gate_fails_on_missing_completed_game_data(monkeypatch):
    from nba_duckdb.tasks.quality import validate_summer_league

    frames = _frames()
    frames[("bronze", "play_by_play")] = pl.DataFrame(
        schema={"game_id": pl.String, "pbp_json": pl.String}
    )
    monkeypatch.setattr(
        validate_summer_league,
        "read_table",
        lambda schema, table: frames[(schema, table)],
    )

    with pytest.raises(RuntimeError, match="bronze.play_by_play missing 1"):
        validate_summer_league.run(
            season="2026-27",
            competitions=["summer_league_vegas"],
        )

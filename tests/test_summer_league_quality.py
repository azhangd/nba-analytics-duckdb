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
                    "league_id": "15",
                    "competition": "summer_league_vegas",
                    "game_status": 3,
                    "raw_json": json.dumps(
                        {
                            "homeTeam": {"score": "80"},
                            "awayTeam": {"score": "70"},
                        }
                    ),
                    "ingested_at": "2026-07-10T00:00:00Z",
                }
            ]
        ),
        ("bronze", "boxscores"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "traditional_json": json.dumps(
                        {
                            "boxScoreTraditional": {
                                "gameId": game_id,
                                "homeTeam": {
                                    "statistics": {
                                        "freeThrowsAttempted": 2,
                                        "freeThrowsMade": 1,
                                        "points": 80,
                                    }
                                },
                                "awayTeam": {
                                    "statistics": {
                                        "freeThrowsAttempted": 0,
                                        "freeThrowsMade": 0,
                                        "points": 70,
                                    }
                                },
                            }
                        }
                    ),
                    "advanced_json": None,
                    "traditional_source": "stats_v3",
                    "advanced_source": "unknown",
                    "ingested_at": "2026-07-10T00:00:01Z",
                }
            ]
        ),
        ("bronze", "play_by_play"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "pbp_json": json.dumps(
                        {
                            "game": {
                                "actions": [
                                    {
                                        "actionNumber": 1,
                                        "actionType": "Free Throw",
                                        "description": "Player Free Throw 2PT",
                                    },
                                    {
                                        "actionNumber": 2,
                                        "actionType": "Free Throw",
                                        "description": "MISS Player Free Throw 1 of 2",
                                    },
                                ]
                            }
                        }
                    ),
                    "source": "stats_v3",
                    "ingested_at": "2026-07-10T00:00:02Z",
                }
            ]
        ),
        ("bronze", "shot_charts"): pl.DataFrame(
            [
                {
                    "game_id": game_id,
                    "team_id": 1,
                    "shot_chart_json": json.dumps(
                        {
                            "resultSets": [
                                {"name": "Shot_Chart_Detail", "rowSet": [[1]]}
                            ]
                        }
                    ),
                    "ingested_at": "2026-07-10T00:00:03Z",
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
        persist_manifest=False,
    )

    assert result["status"] == "success"
    assert result["competition_counts"] == {"summer_league_vegas": 1}
    assert result["schedule_games"] == 1
    assert result["completed_games"] == 1
    assert result["semantic_reconciliation"] == {
        "games_checked": 1,
        "free_throw_mismatches": 0,
        "final_score_mismatches": 0,
    }
    assert result["source_manifest"]["rows"] == 4
    assert len(result["source_manifest"]["sha256"]) == 64


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
            persist_manifest=False,
        )


def test_summer_league_quality_gate_fails_on_cross_source_ft_mismatch(monkeypatch):
    from nba_duckdb.tasks.quality import validate_summer_league

    frames = _frames()
    boxscore = json.loads(frames[("bronze", "boxscores")][0, "traditional_json"])
    boxscore["boxScoreTraditional"]["homeTeam"]["statistics"][
        "freeThrowsAttempted"
    ] = 3
    frames[("bronze", "boxscores")] = frames[("bronze", "boxscores")].with_columns(
        pl.lit(json.dumps(boxscore)).alias("traditional_json")
    )
    monkeypatch.setattr(
        validate_summer_league,
        "read_table",
        lambda schema, table: frames[(schema, table)],
    )

    with pytest.raises(RuntimeError, match="semantic reconciliation failed"):
        validate_summer_league.run(
            season="2026-27",
            competitions=["summer_league_vegas"],
            persist_manifest=False,
        )

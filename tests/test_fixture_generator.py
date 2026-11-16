import filecmp
from pathlib import Path

from nba_duckdb.fixtures.generate_synthetic_fixtures import (
    BOXSCORES,
    PLAY_BY_PLAY,
    generate_fixtures,
)


def test_fixture_generator_writes_expected_files(tmp_path):
    files = generate_fixtures(tmp_path)

    assert {path.name for path in files} == {
        "synthetic_teams.json",
        "synthetic_players.json",
        "synthetic_schedule.json",
        "synthetic_boxscore.json",
        "synthetic_play_by_play.json",
        "synthetic_shot_charts.json",
    }
    assert all(path.read_text().strip().startswith("[") for path in files)


def test_committed_fixtures_match_generator(tmp_path):
    generated_files = generate_fixtures(tmp_path)
    committed_dir = Path(__file__).parent / "fixtures" / "generated"

    for generated_file in generated_files:
        committed_file = committed_dir / generated_file.name
        assert filecmp.cmp(generated_file, committed_file, shallow=False)


def test_play_by_play_turnovers_match_box_scores():
    for box, pbp in zip(BOXSCORES, PLAY_BY_PLAY, strict=True):
        turnovers = [action for action in pbp["game"]["actions"] if action["actionType"] == "turnover"]
        for side in ("homeTeam", "awayTeam"):
            team = box["game"][side]
            for player in team["players"]:
                player_turnovers = [action for action in turnovers if action["personId"] == player["personId"]]
                assert len(player_turnovers) == player["statistics"]["turnovers"]
    team_turnovers = [
        action
        for pbp in PLAY_BY_PLAY
        for action in pbp["game"]["actions"]
        if action["actionType"] == "turnover" and action["personId"] is None
    ]
    assert team_turnovers

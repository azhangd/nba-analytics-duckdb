import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]

REAL_TEAM_MARKERS = {
    "76ers",
    "Bucks",
    "Bulls",
    "Celtics",
    "Clippers",
    "Grizzlies",
    "Hawks",
    "Heat",
    "Hornets",
    "Jazz",
    "Kings",
    "Knicks",
    "Lakers",
    "Magic",
    "Mavericks",
    "Nets",
    "Nuggets",
    "Pacers",
    "Pelicans",
    "Pistons",
    "Raptors",
    "Rockets",
    "Spurs",
    "Suns",
    "Thunder",
    "Timberwolves",
    "Trail Blazers",
    "Warriors",
    "Wizards",
}

REAL_PLAYER_MARKERS = {
    "Anthony Davis",
    "Anthony Edwards",
    "Damian Lillard",
    "Devin Booker",
    "Giannis",
    "Ja Morant",
    "Jalen Brunson",
    "James Harden",
    "Jayson Tatum",
    "Jimmy Butler",
    "Joel Embiid",
    "Kawhi Leonard",
    "Kevin Durant",
    "LeBron",
    "Luka Doncic",
    "Nikola Jokic",
    "Shai Gilgeous-Alexander",
    "Stephen Curry",
    "Victor Wembanyama",
}

REAL_MARKERS = REAL_TEAM_MARKERS | REAL_PLAYER_MARKERS
TEXT_SUFFIXES = {".py", ".sql", ".md", ".json", ".toml", ".yml", ".yaml"}
ALLOWED_OCCURRENCES = {
    ("src/nba_duckdb/tasks/bronze/ingest_injuries.py", "76ers"),
}


def _public_text_paths() -> list[Path]:
    roots = [
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "examples",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "CONTRIBUTING.md",
        PROJECT_ROOT / "VALIDATION.md",
        PROJECT_ROOT / ".env.example",
        PROJECT_ROOT / "tests" / "fixtures" / "README.md",
    ]
    paths = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        else:
            paths.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(path for path in paths if path.suffix in TEXT_SUFFIXES)


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def test_committed_fixture_payloads_are_synthetic():
    fixture_dir = Path(__file__).parent / "fixtures" / "generated"
    payloads = [json.loads(path.read_text()) for path in sorted(fixture_dir.glob("*.json"))]
    serialized = json.dumps(payloads)

    for marker in REAL_MARKERS:
        assert marker not in serialized

    assert "002SYN" in serialized
    assert "Metro Meteors" in serialized
    assert "Avery Arc" in serialized
    assert "2099-" in serialized


def test_public_text_does_not_embed_real_player_or_team_samples():
    failures = []
    for path in _public_text_paths():
        relative_path = _relative(path)
        text = path.read_text()
        for marker in REAL_MARKERS:
            if marker not in text:
                continue
            if (relative_path, marker) in ALLOWED_OCCURRENCES:
                continue
            failures.append(f"{relative_path}: {marker}")

    assert failures == []

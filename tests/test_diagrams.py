import importlib.util
import re
import struct
import sys
from pathlib import Path


def _load_diagram_script():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "generate_diagrams.py"
    spec = importlib.util.spec_from_file_location("generate_diagrams", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def _markdown_png_paths(path: Path) -> list[str]:
    return re.findall(r"!\[[^\]]+\]\(([^)]+\.png)\)", path.read_text())


def test_diagram_sources_are_current():
    diagrams = _load_diagram_script()

    expected = {
        diagram.dot_path: diagrams.render_domain_diagram_dot(diagram.key)
        for diagram in diagrams.DOMAIN_DIAGRAMS
    }
    for dot_path, content in expected.items():
        assert dot_path.read_text() == content
        assert dot_path.with_suffix(".png").exists()


def test_primary_diagram_assignments_cover_every_non_ops_table_once():
    diagrams = _load_diagram_script()

    schema_datasets = diagrams._schema_datasets()
    primary_datasets = [table.dataset for table in diagrams.TABLES]

    assert len(primary_datasets) == len(set(primary_datasets))
    assert set(primary_datasets) == schema_datasets
    assert diagrams.validate_diagram_specs() == []


def test_relationship_endpoints_exist():
    diagrams = _load_diagram_script()
    schema_datasets = diagrams._schema_datasets()

    for relationship in diagrams._all_relationships():
        assert relationship.source in schema_datasets
        assert relationship.target in schema_datasets


def test_diagram_relationships_are_backed_by_lineage_edges():
    diagrams = _load_diagram_script()

    for relationship in diagrams._all_relationships():
        assert diagrams._relationship_is_backed_by_lineage(relationship)


def test_dbt_relationships_require_manifest_lineage(monkeypatch):
    diagrams = _load_diagram_script()
    relationship = diagrams.RelationshipSpec(
        "player",
        "gold.fake_registry_only_source",
        "gold.player_season_feature_matrix",
        "fake",
    )

    monkeypatch.setattr(
        diagrams,
        "_registry_lineage_edges",
        lambda: {(relationship.source, relationship.target)},
    )
    monkeypatch.setattr(diagrams, "_dbt_manifest_lineage_edges", lambda: set())

    assert not diagrams._relationship_is_backed_by_lineage(relationship)


def test_python_asset_relationships_use_registry_lineage(monkeypatch):
    diagrams = _load_diagram_script()
    relationship = diagrams.RelationshipSpec(
        "play_model_signal",
        "silver.fct_play_by_play",
        "gold.model_artifacts",
        "model training",
    )

    monkeypatch.setattr(
        diagrams,
        "_registry_lineage_edges",
        lambda: {(relationship.source, relationship.target)},
    )
    monkeypatch.setattr(diagrams, "_dbt_manifest_lineage_edges", lambda: set())

    assert diagrams._relationship_is_backed_by_lineage(relationship)


def test_dbt_manifest_lineage_edges_cover_representative_models():
    diagrams = _load_diagram_script()
    manifest_edges = diagrams._dbt_manifest_lineage_edges()

    assert {
        ("gold.player_game_stats", "gold.player_season_stats_base"),
        ("silver.fct_games", "gold.player_season_stats_base"),
        ("silver.dim_players", "gold.player_season_stats_base"),
    } <= manifest_edges

    assert {
        ("gold.team_season_four_factors", "gold.team_season_feature_matrix"),
        ("gold.team_season_elo", "gold.team_season_feature_matrix"),
        ("gold.team_game_stats", "gold.team_season_feature_matrix"),
    } <= manifest_edges
    assert {
        ("gold.player_season_embeddings", "gold.team_season_feature_matrix"),
        ("gold.player_season_rapm", "gold.team_season_feature_matrix"),
    }.isdisjoint(manifest_edges)

    assert {
        ("gold.player_season_embeddings", "gold.player_season_feature_matrix"),
        ("gold.player_season_rapm", "gold.player_season_feature_matrix"),
    } <= manifest_edges


def test_readme_references_raw_to_silver_png():
    root = Path(__file__).resolve().parents[1]
    readme_paths = _markdown_png_paths(root / "README.md")

    assert readme_paths == ["docs/assets/core_tables.png"]
    assert (root / readme_paths[0]).exists()


def test_diagrams_doc_references_generated_domain_pngs():
    root = Path(__file__).resolve().parents[1]
    diagrams = _load_diagram_script()
    diagram_doc_paths = _markdown_png_paths(root / "docs" / "DIAGRAMS.md")

    expected = [f"assets/{diagram.png_path.name}" for diagram in diagrams.DOMAIN_DIAGRAMS]
    assert diagram_doc_paths == expected
    for image_path in diagram_doc_paths:
        assert (root / "docs" / image_path).exists()


def test_diagram_png_dimensions_are_doc_friendly():
    diagrams = _load_diagram_script()

    for diagram in diagrams.DOMAIN_DIAGRAMS:
        width, height = _png_dimensions(diagram.png_path)
        assert 900 <= width <= 2600, diagram.png_path.name
        assert height <= 1800, diagram.png_path.name


def test_diagram_check_allows_platform_specific_png_bytes(tmp_path, monkeypatch):
    diagrams = _load_diagram_script()
    dot_path = tmp_path / "diagram.dot"
    png_path = tmp_path / "diagram.png"
    dot_path.write_text("digraph test_diagram {}\n")
    png_path.write_bytes(b"stale")
    monkeypatch.setattr(
        diagrams,
        "_all_diagram_artifacts",
        lambda: [(dot_path, png_path, "digraph test_diagram {}\n")],
    )
    monkeypatch.setattr(diagrams, "validate_diagram_specs", lambda: [])
    monkeypatch.setattr(diagrams.shutil, "which", lambda _name: "/usr/bin/dot")
    monkeypatch.setattr(diagrams, "_render_png", lambda _dot, png: png.write_bytes(b"fresh"))

    assert diagrams.check_diagrams() == 0

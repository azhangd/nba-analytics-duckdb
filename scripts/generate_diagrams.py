#!/usr/bin/env python3
"""Generate readable warehouse diagrams from curated metadata plus live schema."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from nba_duckdb import registry
from nba_duckdb.dbt_manifest import dbt_manifest_edges, load_dbt_manifest
from nba_duckdb.dbt_models import DBT_MODEL_DATASETS
from nba_duckdb.sql.schema import schema_sql_text

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"


@dataclass(frozen=True)
class DiagramSpec:
    key: str
    title: str
    description: str
    dot_path: Path
    png_path: Path


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    fill: str
    border: str


@dataclass(frozen=True)
class TableSpec:
    dataset: str
    diagram: str
    section: str
    grain: str


@dataclass(frozen=True)
class RelationshipSpec:
    diagram: str
    source: str
    target: str
    key: str


DOMAIN_DIAGRAMS = (
    DiagramSpec(
        "core",
        "Bronze to silver",
        "Raw NBA source records and derived silver facts and dimensions.",
        ASSET_DIR / "core_tables.dot",
        ASSET_DIR / "core_tables.png",
    ),
    DiagramSpec(
        "player",
        "Player gold tables",
        "Player-level game logs, season summaries, splits, embeddings, and feature matrices.",
        ASSET_DIR / "player_tables.dot",
        ASSET_DIR / "player_tables.png",
    ),
    DiagramSpec(
        "team",
        "Team gold tables",
        "Team-level game logs, season summaries, Elo ratings, scouting, and feature matrices.",
        ASSET_DIR / "team_tables.dot",
        ASSET_DIR / "team_tables.png",
    ),
    DiagramSpec(
        "play_model_signal",
        "Play, model, and signal tables",
        "Play-level events, shot-quality estimates, model artifacts, and off-court covariates.",
        ASSET_DIR / "play_model_signal_tables.dot",
        ASSET_DIR / "play_model_signal_tables.png",
    ),
)

DOMAIN_DIAGRAM_BY_KEY = {diagram.key: diagram for diagram in DOMAIN_DIAGRAMS}

SECTIONS = (
    SectionSpec("bronze", "Bronze", "#fffdf8", "#9a6a16"),
    SectionSpec("silver_dim", "Silver dimensions", "#fbfdff", "#4b6f93"),
    SectionSpec("silver_fct", "Silver facts", "#fbfdff", "#4b6f93"),
    SectionSpec("gold_player", "Player gold", "#fbfffd", "#39715a"),
    SectionSpec("gold_team", "Team gold", "#fbfffd", "#39715a"),
    SectionSpec("gold_play", "Play gold", "#fbfffd", "#39715a"),
    SectionSpec("gold_model", "Models and signals", "#fbfffd", "#39715a"),
    SectionSpec("context", "Context", "#fafafa", "#8a8f98"),
)

SECTION_BY_KEY = {section.key: section for section in SECTIONS}

TABLES = (
    TableSpec("bronze.schedule", "core", "bronze", "game"),
    TableSpec("bronze.rosters", "core", "bronze", "player, team, season"),
    TableSpec("bronze.coaches", "core", "bronze", "coach, team, season"),
    TableSpec("bronze.boxscores", "core", "bronze", "game payload"),
    TableSpec("bronze.play_by_play", "core", "bronze", "game payload"),
    TableSpec("bronze.shot_charts", "core", "bronze", "game, team payload"),
    TableSpec("bronze.standings", "core", "bronze", "season payload"),
    TableSpec("bronze.tracking_stats", "core", "bronze", "season, category, level"),
    TableSpec("bronze.hustle", "core", "bronze", "season, level payload"),
    TableSpec("bronze.matchups", "core", "bronze", "season, team, direction"),
    TableSpec("bronze.defense", "core", "bronze", "season, play type, grouping"),
    TableSpec("bronze.game_detail", "core", "bronze", "game payload"),
    TableSpec("bronze.tracking", "core", "bronze", "season payload"),
    TableSpec("bronze.injuries", "core", "bronze", "fetch date payload"),
    TableSpec("silver.dim_teams", "core", "silver_dim", "team"),
    TableSpec("silver.dim_players", "core", "silver_dim", "player"),
    TableSpec("silver.dim_coaches", "core", "silver_dim", "coach"),
    TableSpec("silver.dim_player_external_identities", "core", "silver_dim", "player"),
    TableSpec("silver.dim_injuries", "core", "silver_dim", "injured athlete"),
    TableSpec("silver.fct_games", "core", "silver_fct", "game"),
    TableSpec("silver.fct_boxscores", "core", "silver_fct", "player, game"),
    TableSpec("silver.fct_shots", "core", "silver_fct", "shot attempt"),
    TableSpec("silver.fct_play_by_play", "core", "silver_fct", "play event"),
    TableSpec("silver.fct_possessions", "core", "silver_fct", "possession"),
    TableSpec("silver.fct_lineups", "core", "silver_fct", "lineup stint"),
    TableSpec("silver.fct_hustle", "core", "silver_fct", "player/team hustle row"),
    TableSpec("silver.fct_tracking", "core", "silver_fct", "tracking stat row"),
    TableSpec("silver.fct_matchups", "core", "silver_fct", "player matchup"),
    TableSpec("silver.fct_defense_play_types", "core", "silver_fct", "defense play-type row"),
    TableSpec("silver.fct_game_detail", "core", "silver_fct", "team, game detail"),
    TableSpec("silver.fct_team_coach_seasons", "core", "silver_fct", "team, season, coach"),
    TableSpec("gold.player_game_stats", "player", "gold_player", "player, game"),
    TableSpec("gold.player_season_stats_base", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_stats", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_clutch_stats", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_load_management", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_archetypes", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_rapm", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_mvp_ladder", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_embeddings", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_similarity", "player", "gold_player", "player pair, season"),
    TableSpec("gold.player_game_rolling_stats", "player", "gold_player", "player, game"),
    TableSpec("gold.player_season_split_stats", "player", "gold_player", "player, season, split"),
    TableSpec("gold.player_season_feature_matrix", "player", "gold_player", "player, season"),
    TableSpec("gold.player_season_shot_profile", "player", "gold_player", "player, season, shot bucket"),
    TableSpec("gold.team_game_stats", "team", "gold_team", "team, game"),
    TableSpec("gold.team_season_four_factors", "team", "gold_team", "team, season"),
    TableSpec("gold.team_season_percentile_ranks", "team", "gold_team", "team, season"),
    TableSpec("gold.team_season_starter_bench_stats", "team", "gold_team", "team, season, role"),
    TableSpec("gold.team_season_clutch_stats", "team", "gold_team", "team, season"),
    TableSpec("gold.team_season_opponent_scouting", "team", "gold_team", "team, opponent, season"),
    TableSpec("gold.team_season_timeout_stats", "team", "gold_team", "team, season"),
    TableSpec("gold.team_season_ato_stats", "team", "gold_team", "team, season"),
    TableSpec("gold.team_season_elo", "team", "gold_team", "team, season"),
    TableSpec("gold.team_game_elo_history", "team", "gold_team", "team, game"),
    TableSpec("gold.team_season_feature_matrix", "team", "gold_team", "team, season"),
    TableSpec("gold.team_season_shot_profile", "team", "gold_team", "team, season, shot bucket"),
    TableSpec("gold.lineup_season_stats", "play_model_signal", "gold_play", "lineup, season"),
    TableSpec("gold.player_season_on_off_stats", "play_model_signal", "gold_play", "player, team, season"),
    TableSpec("gold.player_zone_season_shot_quality", "play_model_signal", "gold_play", "player, zone, season"),
    TableSpec("gold.team_season_play_type_stats", "play_model_signal", "gold_play", "team, season, play type"),
    TableSpec("gold.team_season_play_type_splits", "play_model_signal", "gold_play", "team, play type, split"),
    TableSpec("gold.player_combo_season_stats", "play_model_signal", "gold_play", "player combo, season"),
    TableSpec("gold.game_flow_snapshots", "play_model_signal", "gold_play", "game, time snapshot"),
    TableSpec(
        "gold.player_zone_season_shot_quality_trained",
        "play_model_signal",
        "gold_model",
        "player, zone, season",
    ),
    TableSpec("gold.model_artifacts", "play_model_signal", "gold_model", "model, season"),
    TableSpec("gold.player_pageviews_daily", "play_model_signal", "gold_model", "player, date"),
    TableSpec("gold.player_media_mentions_daily", "play_model_signal", "gold_model", "player, date"),
    TableSpec("gold.player_jersey_rank_snapshots", "play_model_signal", "gold_model", "player, snapshot"),
)

RELATIONSHIPS = (
    RelationshipSpec("core", "bronze.schedule", "silver.dim_teams", "team_id"),
    RelationshipSpec("core", "bronze.rosters", "silver.dim_players", "player_id"),
    RelationshipSpec("core", "bronze.coaches", "silver.dim_coaches", "coach_id"),
    RelationshipSpec("core", "bronze.schedule", "silver.fct_games", "game_id"),
    RelationshipSpec("core", "bronze.boxscores", "silver.fct_boxscores", "game_id"),
    RelationshipSpec("core", "bronze.play_by_play", "silver.fct_play_by_play", "game_id"),
    RelationshipSpec("core", "bronze.shot_charts", "silver.fct_shots", "game_id, team_id"),
    RelationshipSpec("core", "bronze.game_detail", "silver.fct_game_detail", "game_id"),
    RelationshipSpec("core", "bronze.tracking_stats", "silver.fct_tracking", "season, category"),
    RelationshipSpec("core", "bronze.hustle", "silver.fct_hustle", "season"),
    RelationshipSpec("core", "bronze.matchups", "silver.fct_matchups", "season, team"),
    RelationshipSpec("core", "bronze.defense", "silver.fct_defense_play_types", "season, play type"),
    RelationshipSpec("core", "bronze.injuries", "silver.dim_injuries", "athlete"),
    RelationshipSpec("core", "silver.fct_games", "silver.fct_boxscores", "game_id"),
    RelationshipSpec("core", "silver.fct_games", "silver.fct_play_by_play", "game_id"),
    RelationshipSpec("core", "silver.fct_play_by_play", "silver.fct_possessions", "game_id"),
    RelationshipSpec("core", "silver.fct_play_by_play", "silver.fct_lineups", "game_id"),
    RelationshipSpec("core", "silver.dim_players", "silver.dim_player_external_identities", "player_id"),
    RelationshipSpec("core", "bronze.coaches", "silver.fct_team_coach_seasons", "coach_id"),
    RelationshipSpec("player", "silver.fct_boxscores", "gold.player_game_stats", "player_id, game_id"),
    RelationshipSpec("player", "gold.player_game_stats", "gold.player_season_stats_base", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_stats_base", "gold.player_season_stats", "player_id, season"),
    RelationshipSpec("player", "silver.fct_shots", "gold.player_season_shot_profile", "player_id, season"),
    RelationshipSpec("player", "silver.fct_play_by_play", "gold.player_season_clutch_stats", "player_id, season"),
    RelationshipSpec("player", "silver.fct_boxscores", "gold.player_season_load_management", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_stats", "gold.player_season_archetypes", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_stats", "gold.player_season_rapm", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_stats", "gold.player_season_mvp_ladder", "player_id, season"),
    RelationshipSpec("player", "gold.player_game_stats", "gold.player_game_rolling_stats", "player_id, game"),
    RelationshipSpec("player", "gold.player_game_stats", "gold.player_season_split_stats", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_shot_profile", "gold.player_season_embeddings", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_stats", "gold.player_season_similarity", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_embeddings", "gold.player_season_feature_matrix", "player_id, season"),
    RelationshipSpec("player", "gold.player_game_rolling_stats", "gold.player_season_feature_matrix", "player_id, season"),
    RelationshipSpec("player", "gold.player_season_rapm", "gold.player_season_feature_matrix", "player_id, season"),
    RelationshipSpec("team", "silver.fct_games", "gold.team_game_stats", "game_id"),
    RelationshipSpec("team", "silver.fct_boxscores", "gold.team_season_four_factors", "team_id, season"),
    RelationshipSpec("team", "silver.fct_games", "gold.team_game_elo_history", "team_id, game_id"),
    RelationshipSpec("team", "gold.team_season_four_factors", "gold.team_season_percentile_ranks", "team_id, season"),
    RelationshipSpec("team", "gold.team_season_four_factors", "gold.team_season_feature_matrix", "team_id, season"),
    RelationshipSpec("team", "silver.fct_shots", "gold.team_season_shot_profile", "team_id, season"),
    RelationshipSpec("team", "gold.team_season_shot_profile", "gold.team_season_feature_matrix", "team_id, season"),
    RelationshipSpec("team", "gold.team_season_elo", "gold.team_season_feature_matrix", "team_id, season"),
    RelationshipSpec("team", "gold.team_season_starter_bench_stats", "gold.team_season_feature_matrix", "team_id, season"),
    RelationshipSpec("team", "gold.team_season_clutch_stats", "gold.team_season_feature_matrix", "team_id, season"),
    RelationshipSpec("team", "gold.team_season_play_type_stats", "gold.team_season_feature_matrix", "team_id, season"),
    RelationshipSpec("team", "silver.fct_possessions", "gold.team_season_clutch_stats", "team_id, season"),
    RelationshipSpec("team", "silver.fct_play_by_play", "gold.team_season_timeout_stats", "team_id, season"),
    RelationshipSpec("team", "silver.fct_play_by_play", "gold.team_season_ato_stats", "team_id, season"),
    RelationshipSpec("team", "silver.fct_games", "gold.team_season_opponent_scouting", "team_id, opponent"),
    RelationshipSpec("play_model_signal", "silver.fct_lineups", "gold.lineup_season_stats", "lineup, season"),
    RelationshipSpec("play_model_signal", "silver.fct_lineups", "gold.player_season_on_off_stats", "player_id, season"),
    RelationshipSpec("play_model_signal", "silver.fct_shots", "gold.player_zone_season_shot_quality", "player_id, zone"),
    RelationshipSpec(
        "play_model_signal",
        "silver.fct_shots",
        "gold.player_zone_season_shot_quality_trained",
        "player_id, zone",
    ),
    RelationshipSpec("play_model_signal", "silver.fct_possessions", "gold.team_season_play_type_stats", "team_id, play"),
    RelationshipSpec("play_model_signal", "silver.fct_possessions", "gold.team_season_play_type_splits", "team_id, play"),
    RelationshipSpec("play_model_signal", "silver.fct_play_by_play", "gold.game_flow_snapshots", "game_id"),
    RelationshipSpec("play_model_signal", "silver.fct_lineups", "gold.player_combo_season_stats", "player combo"),
    RelationshipSpec("play_model_signal", "silver.fct_play_by_play", "gold.model_artifacts", "model training"),
    RelationshipSpec("play_model_signal", "silver.dim_player_external_identities", "gold.player_pageviews_daily", "player_id"),
    RelationshipSpec("play_model_signal", "silver.dim_player_external_identities", "gold.player_media_mentions_daily", "player_id"),
    RelationshipSpec("play_model_signal", "silver.dim_player_external_identities", "gold.player_jersey_rank_snapshots", "player_id"),
)


def _schema_tables() -> dict[str, list[str]]:
    sql = schema_sql_text()
    tables: dict[str, list[str]] = {"bronze": [], "silver": [], "gold": []}
    for schema, table in re.findall(
        r"CREATE TABLE IF NOT EXISTS (bronze|silver|gold)\.([a-z_]+)",
        sql,
    ):
        tables[schema].append(table)
    return {schema: sorted(values) for schema, values in tables.items()}


def _schema_datasets() -> set[str]:
    schema_datasets = {
        f"{schema}.{table}"
        for schema, table_names in _schema_tables().items()
        for table in table_names
    }
    registry_datasets = {
        output
        for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE)
        for output in (*task.outputs, *task.mutates)
    }
    return schema_datasets | registry_datasets


@cache
def _dbt_manifest_lineage_edges() -> set[tuple[str, str]]:
    return dbt_manifest_edges(load_dbt_manifest())


@cache
def _registry_lineage_edges() -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE):
        for output in (*task.outputs, *task.mutates):
            for input_name in (*task.inputs, *task.optional_inputs):
                edges.add((input_name, output))
    return edges


def _lineage_edges() -> set[tuple[str, str]]:
    return _registry_lineage_edges() | _dbt_manifest_lineage_edges()


def _relationship_is_backed_by_lineage(relationship: RelationshipSpec) -> bool:
    edge = (relationship.source, relationship.target)
    if relationship.target in DBT_MODEL_DATASETS:
        return edge in _dbt_manifest_lineage_edges()
    return edge in _registry_lineage_edges()


def _all_relationships() -> tuple[RelationshipSpec, ...]:
    return RELATIONSHIPS


def _dataset_node_id(dataset: str) -> str:
    return dataset.replace(".", "__")


def _quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _table_name(dataset: str) -> str:
    return dataset.split(".", 1)[1]


def _tables_by_dataset() -> dict[str, TableSpec]:
    return {table.dataset: table for table in TABLES}


def _tables_for_diagram(diagram_key: str) -> list[TableSpec]:
    return [table for table in TABLES if table.diagram == diagram_key]


def _relationships_for_diagram(diagram_key: str) -> list[RelationshipSpec]:
    return [rel for rel in RELATIONSHIPS if rel.diagram == diagram_key]


def _domain_artifacts() -> list[tuple[Path, Path, str]]:
    return [
        (diagram.dot_path, diagram.png_path, render_domain_diagram_dot(diagram.key))
        for diagram in DOMAIN_DIAGRAMS
    ]


def _all_diagram_artifacts() -> list[tuple[Path, Path, str]]:
    return _domain_artifacts()


def validate_diagram_specs() -> list[str]:
    errors: list[str] = []
    schema_datasets = _schema_datasets()
    primary_datasets = [table.dataset for table in TABLES]
    primary_dataset_set = set(primary_datasets)
    diagram_keys = set(DOMAIN_DIAGRAM_BY_KEY)
    section_keys = set(SECTION_BY_KEY)

    duplicates = sorted(
        dataset for dataset in primary_dataset_set if primary_datasets.count(dataset) > 1
    )
    missing = sorted(schema_datasets - primary_dataset_set)
    extra = sorted(primary_dataset_set - schema_datasets)
    invalid_diagrams = sorted({table.diagram for table in TABLES if table.diagram not in diagram_keys})
    invalid_sections = sorted({table.section for table in TABLES if table.section not in section_keys})

    if duplicates:
        errors.append(f"duplicate primary diagram table assignments: {', '.join(duplicates)}")
    if missing:
        errors.append(f"missing primary diagram table assignments: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown primary diagram table assignments: {', '.join(extra)}")
    if invalid_diagrams:
        errors.append(f"unknown diagram keys: {', '.join(invalid_diagrams)}")
    if invalid_sections:
        errors.append(f"unknown section keys: {', '.join(invalid_sections)}")

    relationship_endpoints = {
        endpoint for rel in _all_relationships() for endpoint in (rel.source, rel.target)
    }
    stale_endpoints = sorted(relationship_endpoints - schema_datasets)
    invalid_relationship_diagrams = sorted(
        {rel.diagram for rel in RELATIONSHIPS if rel.diagram not in diagram_keys}
    )
    stale_relationships = sorted(
        f"{rel.source} -> {rel.target}"
        for rel in _all_relationships()
        if not _relationship_is_backed_by_lineage(rel)
    )
    if stale_endpoints:
        errors.append(f"unknown relationship endpoints: {', '.join(stale_endpoints)}")
    if invalid_relationship_diagrams:
        errors.append(f"unknown relationship diagram keys: {', '.join(invalid_relationship_diagrams)}")
    if stale_relationships:
        errors.append(f"relationships not backed by lineage edges: {', '.join(stale_relationships)}")

    if not _lineage_edges():
        errors.append("registry and dbt manifest produced no lineage edges")

    return errors


def _table_label(table: TableSpec, section: SectionSpec, *, context: bool = False) -> str:
    name = _html(_table_name(table.dataset))
    grain = _html(table.grain)
    label = "context" if context else "row"
    return (
        "<<TABLE BORDER=\"1\" CELLBORDER=\"0\" CELLSPACING=\"0\" CELLPADDING=\"5\" "
        f"COLOR=\"{_html(section.border)}\" BGCOLOR=\"{_html(section.fill)}\">"
        f"<TR><TD><B>{name}</B></TD></TR>"
        f"<TR><TD><FONT POINT-SIZE=\"9\">{label}: {grain}</FONT></TD></TR>"
        "</TABLE>>"
    )


def render_domain_diagram_dot(diagram_key: str) -> str:
    if diagram_key not in DOMAIN_DIAGRAM_BY_KEY:
        raise ValueError(f"Unknown diagram key: {diagram_key}")

    errors = validate_diagram_specs()
    if errors:
        raise RuntimeError("; ".join(errors))

    diagram = DOMAIN_DIAGRAM_BY_KEY[diagram_key]
    primary_tables = _tables_for_diagram(diagram_key)
    relationships = _relationships_for_diagram(diagram_key)
    tables_by_dataset = _tables_by_dataset()
    primary_dataset_set = {table.dataset for table in primary_tables}
    context_datasets = sorted(
        {
            endpoint
            for rel in relationships
            for endpoint in (rel.source, rel.target)
            if endpoint not in primary_dataset_set
        }
    )

    visible_tables = {
        **{table.dataset: table for table in primary_tables},
        **{dataset: tables_by_dataset[dataset] for dataset in context_datasets},
    }
    sections_in_order = [
        section
        for section in SECTIONS
        if any(
            (table.section == section.key and table.dataset in primary_dataset_set)
            or (section.key == "context" and table.dataset in context_datasets)
            for table in visible_tables.values()
        )
    ]

    lines = [
        f"digraph {diagram.key}_diagram {{",
        "  graph [rankdir=LR, bgcolor=white, pad=0.25, nodesep=0.35, ranksep=0.65, splines=polyline];",
        "  node [shape=plain, fontname=Helvetica];",
        "  edge [fontname=Helvetica, fontsize=8, color=\"#64748b\", arrowsize=0.55];",
        "  label=" + _quote(diagram.title + "\\n" + diagram.description) + ";",
        "  labelloc=t;",
        "  fontsize=22;",
        "  fontname=Helvetica;",
    ]

    for section in sections_in_order:
        lines.append(f"  subgraph cluster_{section.key} {{")
        lines.append(f"    label={_quote(section.title)};")
        lines.append("    labelloc=t;")
        lines.append("    fontsize=16;")
        lines.append("    fontname=Helvetica;")
        lines.append(f"    color={_quote(section.border)};")
        lines.append("    style=\"rounded\";")
        if section.key == "context":
            section_tables = [visible_tables[dataset] for dataset in context_datasets]
        else:
            section_tables = [
                table
                for table in primary_tables
                if table.section == section.key
            ]
        for table in section_tables:
            node_id = _dataset_node_id(table.dataset)
            lines.append(
                "    "
                f"{_quote(node_id)} "
                f"[label={_table_label(table, section, context=section.key == 'context')}];"
            )
        lines.append("  }")

    for rel in relationships:
        lines.append(
            f"  {_quote(_dataset_node_id(rel.source))} -> {_quote(_dataset_node_id(rel.target))} "
            f"[label={_quote(rel.key)}];"
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def _render_png(dot_path: Path, png_path: Path) -> None:
    if shutil.which("dot") is None:
        raise RuntimeError(
            "Graphviz `dot` is required to render diagrams. Install graphviz "
            "or run `make check-diagrams` to validate existing DOT sources."
        )
    subprocess.run(
        ["dot", "-Tpng", str(dot_path), "-o", str(png_path)],
        check=True,
        cwd=ROOT,
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _png_render_failures() -> list[str]:
    if shutil.which("dot") is None:
        print("Graphviz `dot` not found; skipping PNG renderability check")
        return []

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for dot_path, png_path, _content in _all_diagram_artifacts():
            tmp_png = tmp_dir / png_path.name
            try:
                _render_png(dot_path, tmp_png)
            except (RuntimeError, subprocess.CalledProcessError) as exc:
                failures.append(f"{_display_path(png_path)} ({exc})")
                continue
            if not tmp_png.exists() or tmp_png.stat().st_size == 0:
                failures.append(_display_path(png_path))
    return failures


def check_diagrams() -> int:
    spec_errors = validate_diagram_specs()
    missing_or_stale = [
        _display_path(dot_path)
        for dot_path, _png_path, content in _all_diagram_artifacts()
        if not dot_path.exists() or dot_path.read_text() != content
    ]
    missing_pngs = [
        _display_path(png_path)
        for _dot_path, png_path, _content in _all_diagram_artifacts()
        if not png_path.exists()
    ]
    if spec_errors or missing_or_stale or missing_pngs:
        for error in spec_errors:
            print(f"diagram spec error: {error}")
        for path in [*missing_or_stale, *missing_pngs]:
            print(f"diagram artifact is missing or stale: {path}")
        return 1
    render_failures = _png_render_failures()
    if render_failures:
        for path in render_failures:
            print(f"diagram PNG failed renderability check: {path}")
        return 1
    print("Diagram check passed")
    return 0


def generate_diagrams() -> None:
    errors = validate_diagram_specs()
    if errors:
        raise RuntimeError("; ".join(errors))

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for dot_path, png_path, content in _all_diagram_artifacts():
        _write_if_changed(dot_path, content)
        _render_png(dot_path, png_path)
        print(f"Wrote {png_path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check_diagrams()
    generate_diagrams()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

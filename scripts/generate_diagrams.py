#!/usr/bin/env python3
"""Draw the warehouse diagrams in docs/assets/.

- schema.png: every table, grouped by layer, with its description
- er_core.png: the core tables with their keys, a few columns and how they join
- er_full.png: every silver and gold table with its key columns and what they join

Tables and descriptions come from the dbt manifest. Columns come from the smoke
warehouse, so run `make smoke` first. Joins are drawn from column names: a
`game_id` joins fct_games, a `*team_id` joins dim_teams, and so on. Needs
Graphviz.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from html import escape
from pathlib import Path

import duckdb

from nba_duckdb import registry
from nba_duckdb.config import env_overrides, smoke_warehouse_path
from nba_duckdb.dbt_models import DBT_SUMMER_LEAGUE_SELECTOR
from nba_duckdb.dbt_runner import run_dbt_command

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"

# Group key, title and header color.
GROUPS = {
    "bronze": ("bronze: raw API responses", "#b7791f"),
    "silver": ("silver: cleaned-up data", "#2b6cb0"),
    "summer": ("silver: Summer League", "#2b6cb0"),
    "player": ("gold: players", "#2f855a"),
    "team": ("gold: teams and lineups", "#2f855a"),
}
# Arrows drawn top to bottom.
EDGES = ("bronze -> silver", "bronze -> summer", "silver -> player", "silver -> team")

# Core tables in columns, left to right by what one row is. Each table lists its primary key, then a few useful columns.
CORE_COLUMNS = (
    {
        "silver.dim_teams": (("team_id",), ("abbreviation", "full_name")),
        "silver.dim_players": (("player_id",), ("full_name", "position", "current_team_id")),
    },
    {
        "silver.fct_games": (
            ("game_id",),
            ("season", "game_date", "game_type", "home_team_id", "away_team_id", "home_score", "away_score"),
        ),
    },
    {
        "silver.fct_possessions": (
            ("game_id", "possession_number"),
            ("offense_team_id", "start_type", "end_type", "points_scored"),
        ),
        "silver.fct_play_by_play": (("game_id", "action_id"), ("period", "team_id", "player_id", "action_type")),
        "silver.fct_shots": (("game_id", "game_event_id"), ("player_id", "team_id", "shot_zone_basic", "shot_made")),
        "silver.fct_lineups": (("game_id", "stint_number"), ("team_id", "player_ids_str", "points_for")),
        "silver.fct_boxscores": (("game_id", "player_id"), ("team_id", "minutes", "pts", "usg_pct")),
    },
    {
        "gold.team_game_stats": (("game_id", "team_id"), ("season", "margin", "net_rtg")),
        "gold.player_game_stats": (("game_id", "player_id"), ("team_id", "game_score")),
    },
    {
        "gold.team_season_four_factors": (("team_id", "season"), ("pace", "off_efg_pct", "pyth_wins")),
        "gold.team_season_elo": (("team_id", "season"), ("elo_rating", "projected_wins")),
        "gold.lineup_season_stats": (("team_id", "season", "player_ids_str"), ("net_rating_per_48",)),
        "gold.player_season_stats": (("player_id", "season"), ("team_id", "ppg", "bpm_approx", "vorp_approx")),
    },
)
# The main path from each table to the next. Other joins show as "→ table" on the column; fct_games ->
# team_game_stats is one of those, since its line would have to cross the whole event column.
CORE_LINES = (
    ("silver.dim_teams", "team_id", "silver.fct_games", "home_team_id"),
    ("silver.dim_teams", "team_id", "silver.fct_games", "away_team_id"),
    *(
        ("silver.fct_games", "game_id", table, "game_id")
        for table in (
            "silver.fct_possessions", "silver.fct_play_by_play", "silver.fct_shots", "silver.fct_lineups",
            "silver.fct_boxscores",
        )
    ),
    ("silver.dim_players", "player_id", "silver.fct_boxscores", "player_id"),
    ("gold.team_game_stats", "team_id", "gold.team_season_four_factors", "team_id"),
    ("gold.team_game_stats", "team_id", "gold.team_season_elo", "team_id"),
    ("silver.fct_lineups", "player_ids_str", "gold.lineup_season_stats", "player_ids_str"),
    ("silver.fct_boxscores", "player_id", "gold.player_game_stats", "player_id"),
    ("gold.player_game_stats", "player_id", "gold.player_season_stats", "player_id"),
)

# Sections of the full diagram, top to bottom: what one row is, then layer.
FULL_SECTIONS = {
    "reference": ("silver: teams, players, coaches and injuries", "#2b6cb0"),
    "silver_game": ("silver: game data", "#2b6cb0"),
    "silver_season": ("silver: season data", "#2b6cb0"),
    "gold_game": ("gold: game stats", "#2f855a"),
    "gold_player_season": ("gold: player season stats", "#2f855a"),
    "gold_team_season": ("gold: team and lineup season stats", "#2f855a"),
    "summer": ("silver: Summer League", "#2b6cb0"),
}

# Hub tables and the key their joins point at.
HUBS = {
    "silver.fct_games": "game_id",
    "silver.dim_teams": "team_id",
    "silver.dim_players": "player_id",
    "silver.dim_coaches": "coach_id",
    "silver.summer_league_games": "game_id",
}


def join_target(dataset: str, column: str) -> str | None:
    """The hub table a column joins, or None.

    Bronze holds raw payloads, so no joins are drawn from it. Summer League tables only join their own games:
    no warehouse loaded so far has Summer League data to check their player and team ids against.
    """
    schema, table = dataset.split(".", 1)
    if schema == "bronze" or dataset in HUBS and HUBS[dataset] == column:
        return None
    if table.startswith("summer_league_"):
        return "silver.summer_league_games" if column == "game_id" else None
    if column == "game_id":
        return "silver.fct_games"
    if column.endswith("team_id") or column == "opponent_id":
        return "silver.dim_teams"
    if column.endswith("player_id"):
        return "silver.dim_players"
    if column == "coach_id":
        return "silver.dim_coaches"
    return None


def is_key_column(column: str) -> bool:
    return column == "season" or column.endswith("_id") or column.startswith("player_ids")


def group_of(dataset: str) -> str:
    schema, table = dataset.split(".", 1)
    if schema == "bronze":
        return "bronze"
    if schema == "silver":
        return "summer" if table.startswith("summer_league_") else "silver"
    if table.startswith("player_"):
        return "player"
    return "team"


def section_of(dataset: str, columns: list[str]) -> str:
    schema, table = dataset.split(".", 1)
    if table.startswith("summer_league_"):
        return "summer"
    if table.startswith("dim_"):
        return "reference"
    if "game_id" in columns:
        return f"{schema}_game"
    if schema == "silver":
        return "silver_season"
    return "gold_player_season" if table.startswith("player_") else "gold_team_season"


def manifest_tables() -> dict[str, str]:
    run_dbt_command(["parse"])
    manifest = json.loads((ROOT / "dbt" / "target" / "manifest.json").read_text())
    nodes = [
        *(node for node in manifest["nodes"].values() if node["resource_type"] == "model"),
        *manifest["sources"].values(),
    ]
    tables = {f"{node['schema']}.{node['name']}": node["description"] for node in nodes}
    undescribed = sorted(dataset for dataset, description in tables.items() if not description)
    if undescribed:
        raise SystemExit(f"tables without a dbt description: {', '.join(undescribed)}")
    task_outputs = {
        output
        for task in registry.task_defs_for(registry.DEFAULT_GRAPH, registry.LIVE_MODE)
        for output in task.outputs
        if output.split(".", 1)[0] in ("bronze", "silver", "gold")
    }
    if task_outputs - tables.keys():
        missing = ", ".join(sorted(task_outputs - tables.keys()))
        raise SystemExit(f"tables missing from dbt/models/sources.yml: {missing}")
    return tables


def warehouse_columns(warehouse: Path) -> dict[str, list[str]]:
    # The smoke build skips the Summer League models; build them (empty) so their columns exist.
    run_dbt_command(["run", "--select", DBT_SUMMER_LEAGUE_SELECTOR])
    with duckdb.connect(str(warehouse), read_only=True) as conn:
        rows = conn.execute(
            "SELECT table_schema || '.' || table_name, column_name "
            "FROM information_schema.columns WHERE table_schema IN ('bronze', 'silver', 'gold') "
            "ORDER BY table_schema, table_name, ordinal_position"
        ).fetchall()
    columns: dict[str, list[str]] = {}
    for dataset, column in rows:
        columns.setdefault(dataset, []).append(column)
    return columns


def catalogue_dot(tables: dict[str, str]) -> str:
    def group_table(key: str) -> str:
        title, color = GROUPS[key]
        rows = "".join(
            f'<TR><TD ALIGN="LEFT"><B>{escape(dataset.split(".", 1)[1])}</B></TD>'
            f'<TD ALIGN="LEFT"><FONT COLOR="#4a5568">{escape(tables[dataset])}</FONT></TD></TR>'
            for dataset in sorted(tables)
            if group_of(dataset) == key
        )
        return (
            f'<TABLE BORDER="1" COLOR="{color}" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">'
            f'<TR><TD COLSPAN="2" BGCOLOR="{color}" ALIGN="LEFT">'
            f'<FONT COLOR="white" POINT-SIZE="16"><B>{escape(title)}</B></FONT></TD></TR>'
            f"{rows}</TABLE>"
        )

    lines = [
        "digraph schema {",
        "  graph [rankdir=TB, bgcolor=white, pad=0.3, nodesep=0.5, ranksep=0.5];",
        "  node [shape=plain, fontname=Helvetica];",
        '  edge [color="#718096", arrowsize=0.8, penwidth=1.5];',
        *(f"  {key} [label=<{group_table(key)}>];" for key in GROUPS),
        *(f"  {edge};" for edge in EDGES),
        "}",
    ]
    return "\n".join(lines) + "\n"


GRID_COLUMNS = 5  # tables per row in the full diagram
FULL_BOX_WIDTH = 260  # points; wide enough for the longest key column and its note


def node_id(dataset: str) -> str:
    return dataset.replace(".", "__")


def table_label(
    dataset: str, columns: list[str], primary_keys: tuple[str, ...], color: str, *,
    drawn: frozenset[tuple[str, str]] = frozenset(), width: int = 0,
) -> str:
    """A table box: one row per column, bold if it's in the primary key, with "→ table" for the hub it joins.

    `drawn` holds the (table, column) pairs a line already connects to their hub, so they skip the "→" note.
    `width`, if set, is the minimum box width in points, so boxes line up in a grid.
    """
    schema, table = dataset.split(".", 1)
    half = f' WIDTH="{width // 2}"' if width else ""
    rows = []
    for column in columns:
        target = join_target(dataset, column)
        note = f"→ {target.split('.', 1)[1]}" if target and (dataset, column) not in drawn else ""
        name = f"<B>{escape(column)}</B>" if column in primary_keys else escape(column)
        # Graphviz rejects an empty FONT element, so a column with no note gets an empty cell.
        note_cell = f'<FONT COLOR="#718096">{escape(note)}</FONT>' if note else ""
        rows.append(
            f'<TR><TD ALIGN="LEFT" PORT="{column}_in"{half}>{name}</TD>'
            f'<TD ALIGN="LEFT" PORT="{column}_out"{half}>{note_cell}</TD></TR>'
        )
    return (
        f'<TABLE BORDER="1" COLOR="{color}" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">'
        f'<TR><TD ALIGN="LEFT" BGCOLOR="{color}"><FONT COLOR="white"><B>{escape(table)}</B></FONT></TD>'
        f'<TD ALIGN="RIGHT" BGCOLOR="{color}"><FONT COLOR="#e2e8f0" POINT-SIZE="9">{schema}</FONT></TD></TR>'
        f"{''.join(rows)}</TABLE>"
    )


def layer_color(dataset: str) -> str:
    return GROUPS[group_of(dataset)][1]


def legend(lines: tuple[str, ...]) -> str:
    """A small key, as a plain node."""
    silver, gold = GROUPS["silver"][1], GROUPS["player"][1]
    rows = "".join(f'<TR><TD ALIGN="LEFT" COLSPAN="2">{line}</TD></TR>' for line in lines)
    return (
        '  legend [label=<<TABLE BORDER="1" COLOR="#cbd5e0" CELLBORDER="0" CELLSPACING="2" CELLPADDING="3">'
        f'<TR><TD BGCOLOR="{silver}"><FONT COLOR="white">silver</FONT></TD><TD ALIGN="LEFT">cleaned-up NBA data</TD></TR>'
        f'<TR><TD BGCOLOR="{gold}"><FONT COLOR="white">gold</FONT></TD><TD ALIGN="LEFT">stats calculated from silver</TD></TR>'
        f"{rows}</TABLE>>];"
    )


def er_core_dot(columns: dict[str, list[str]]) -> str:
    drawn = frozenset(
        (target, target_column)
        for source, _, target, target_column in CORE_LINES
        if source == join_target(target, target_column)
    )
    columns_dot = []
    for index, tables in enumerate(CORE_COLUMNS):
        nodes = "".join(
            f"    {node_id(d)} [label=<{table_label(d, columns[d], keys, layer_color(d), drawn=drawn)}>];\n"
            for d, (keys, _) in tables.items()
        )
        if index == 0:
            nodes += "  " + legend(("<B>bold</B>: primary key", "team_id → dim_teams: you can join team_id to dim_teams")) + "\n"
        columns_dot.append(f"  {{ rank=same;\n{nodes}  }}")
    edges = [
        f"  {node_id(source)}:{source_column}_out:e -> {node_id(target)}:{target_column}_in:w;"
        for source, source_column, target, target_column in CORE_LINES
    ]
    lines = [
        "digraph er_core {",
        "  graph [rankdir=LR, bgcolor=white, pad=0.3, nodesep=0.3, ranksep=0.9, newrank=true, splines=polyline,",
        "         fontname=Helvetica, fontsize=16];",
        "  node [shape=plain, fontname=Helvetica, fontsize=11];",
        '  edge [color="#a0aec0", arrowhead=crow, arrowsize=0.7, penwidth=1.2];',
        *columns_dot,
        *edges,
        "}",
    ]
    return "\n".join(lines) + "\n"


def er_full_dot(shown: dict[str, list[str]]) -> str:
    """Every silver and gold table in a grid by section, each join column naming its hub table."""
    clusters, order = [], []
    for key, (title, color) in FULL_SECTIONS.items():
        members = sorted(
            (d for d in shown if section_of(d, shown[d]) == key), key=lambda d: (d not in HUBS, d)
        )
        clusters.append(
            f'  subgraph cluster_{key} {{ label="{title}"; color="{color}"; fontcolor="{color}";\n'
            + "".join(
                f"    {node_id(d)} [label=<"
                f"{table_label(d, shown[d], (HUBS[d],) if d in HUBS else (), color, width=FULL_BOX_WIDTH)}>];\n"
                for d in members
            )
            + "  }"
        )
        order.append(members)
    # Invisible edges stack each section's tables in rows, and the sections under each other.
    layout = [f"  legend -> {node_id(order[0][0])};"]
    for index, members in enumerate(order):
        layout += [
            f"  {node_id(members[i])} -> {node_id(members[i + GRID_COLUMNS])};"
            for i in range(len(members) - GRID_COLUMNS)
        ]
        if index + 1 < len(order):
            last_row_start = (len(members) - 1) // GRID_COLUMNS * GRID_COLUMNS
            layout.append(f"  {node_id(members[last_row_start])} -> {node_id(order[index + 1][0])};")
    lines = [
        "digraph er_full {",
        "  graph [rankdir=TB, bgcolor=white, pad=0.3, nodesep=0.3, ranksep=0.3, fontname=Helvetica, fontsize=16];",
        "  node [shape=plain, fontname=Helvetica, fontsize=11];",
        "  edge [style=invis];",
        legend(("<B>bold</B>: primary key", "team_id → dim_teams: you can join team_id to dim_teams")),
        *clusters,
        *layout,
        "}",
    ]
    return "\n".join(lines) + "\n"


def render_all() -> dict[str, str]:
    warehouse = smoke_warehouse_path()
    if not warehouse.exists():
        raise SystemExit(f"{warehouse} not found; run `make smoke` first")
    # dbt opens the database even to parse, so point it at the smoke warehouse.
    with env_overrides({"NBA_DUCKDB_PATH": str(warehouse)}):
        tables = manifest_tables()
        columns = warehouse_columns(warehouse)
    missing = sorted(tables.keys() - columns.keys())
    if missing:
        raise SystemExit(f"tables missing from {warehouse}: {', '.join(missing)}; run `make smoke` first")

    core = {}
    for core_tables in CORE_COLUMNS:
        for dataset, (keys, extras) in core_tables.items():
            unknown = [column for column in (*keys, *extras) if column not in columns[dataset]]
            if unknown:
                raise SystemExit(f"{dataset} has no column {', '.join(unknown)}; update CORE_COLUMNS in {Path(__file__).name}")
            core[dataset] = [*keys, *extras]
    for source, source_column, target, target_column in CORE_LINES:
        if source_column not in core[source] or target_column not in core[target]:
            raise SystemExit(f"CORE_LINES joins a column not drawn: {source}.{source_column} -> {target}.{target_column}")
    full = {
        dataset: [c for c in columns[dataset] if is_key_column(c)]
        for dataset in sorted(tables)
        if not dataset.startswith("bronze.")
    }
    return {
        "schema": catalogue_dot(tables),
        "er_core": er_core_dot(core),
        "er_full": er_full_dot(full),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if a diagram is out of date")
    args = parser.parse_args()
    dots = render_all()
    if args.check:
        stale = [name for name, dot in dots.items() if not (ASSETS / f"{name}.dot").exists()
                 or (ASSETS / f"{name}.dot").read_text() != dot]
        if stale:
            print(f"out of date: {', '.join(f'docs/assets/{name}.dot' for name in stale)}; run `make diagrams`",
                  file=sys.stderr)
            return 1
        return 0
    for name, dot in dots.items():
        dot_path, png_path = ASSETS / f"{name}.dot", ASSETS / f"{name}.png"
        dot_path.write_text(dot)
        subprocess.run(["dot", "-Tpng", "-Gdpi=144", str(dot_path), "-o", str(png_path)], check=True)
        print(f"Wrote {png_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

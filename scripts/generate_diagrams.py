#!/usr/bin/env python3
"""Draw docs/assets/schema.png: every warehouse table, grouped by layer.

Tables and descriptions come from the dbt manifest: the models plus the sources
in dbt/models/sources.yml. Needs Graphviz.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from html import escape
from pathlib import Path

from nba_duckdb import registry
from nba_duckdb.dbt_runner import run_dbt_command

ROOT = Path(__file__).resolve().parents[1]
DOT_PATH = ROOT / "docs" / "assets" / "schema.dot"
PNG_PATH = ROOT / "docs" / "assets" / "schema.png"

# Group key, title and header color.
GROUPS = {
    "bronze": ("bronze: raw API responses", "#b7791f"),
    "silver": ("silver: cleaned games, players and events", "#2b6cb0"),
    "summer": ("silver: Summer League", "#2b6cb0"),
    "player": ("gold: players", "#2f855a"),
    "team": ("gold: teams", "#2f855a"),
    "other": ("gold: lineups, games and models", "#2f855a"),
}
# Arrows drawn top to bottom. "other" sits under "teams" with a hidden edge.
EDGES = ("bronze -> silver", "bronze -> summer", "silver -> player", "silver -> team", "team -> other [style=invis]")

def group_of(dataset: str) -> str:
    schema, table = dataset.split(".", 1)
    if schema == "bronze":
        return "bronze"
    if schema == "silver":
        return "summer" if table.startswith("summer_league_") else "silver"
    if table.startswith("player_"):
        return "player"
    if table.startswith("team_"):
        return "team"
    return "other"


def render_dot() -> str:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if schema.dot is out of date")
    args = parser.parse_args()
    dot = render_dot()
    if args.check:
        if not DOT_PATH.exists() or DOT_PATH.read_text() != dot:
            print("docs/assets/schema.dot is out of date; run `make diagrams`", file=sys.stderr)
            return 1
        return 0
    DOT_PATH.write_text(dot)
    subprocess.run(["dot", "-Tpng", "-Gdpi=144", str(DOT_PATH), "-o", str(PNG_PATH)], check=True)
    print(f"Wrote {PNG_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

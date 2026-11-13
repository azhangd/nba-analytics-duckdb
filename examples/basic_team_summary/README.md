# Basic team summary

Prints a summary for each team from a few gold tables. It's small on purpose,
and CI runs it against the fake smoke data.

    make smoke
    uv run python examples/basic_team_summary/analysis.py

To run it on your real data:

    NBA_DUCKDB_PATH=data/warehouse/nba.duckdb uv run python examples/basic_team_summary/analysis.py

The numbers only cover the games you've loaded. On the fake data you'll see
season `2099-00` and made-up teams.

# NBA Analytics DuckDB

Pull NBA stats into a DuckDB file on your laptop and query them with SQL.

It grabs schedules, box scores, play-by-play and shot charts from the NBA's
stats endpoints, then builds a few dozen tables on top:

- per-game and per-season player and team stats
- box plus-minus (BPM), VORP and a ridge-regression RAPM
- four factors, pace and Elo ratings for teams
- shot quality: actual vs. expected FG% by zone
- lineup and on/off numbers, clutch splits, play types

Not affiliated with the NBA, and no NBA data lives in this repo.

## Installation

You'll need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

    git clone https://github.com/azhangd/nba-analytics-duckdb.git
    cd nba-analytics-duckdb
    make install-full

## Trying it out

The repo ships with a fake season (made-up teams and players) so you can see
everything work without touching the NBA's servers:

    $ uv run nba-duckdb run-smoke

That writes `data/warehouse/smoke.duckdb`. Open it with the
[DuckDB CLI](https://duckdb.org/docs/installation/) and poke around:

    $ duckdb data/warehouse/smoke.duckdb
    D SELECT player_name, ppg, rpg, apg FROM gold.player_season_stats ORDER BY ppg DESC LIMIT 3;
    ┌──────────────┬────────┬────────┬────────┐
    │ player_name  │  ppg   │  rpg   │  apg   │
    ├──────────────┼────────┼────────┼────────┤
    │ Harper Cove  │   26.0 │    5.0 │    4.8 │
    │ Harper Drift │   25.0 │    5.0 │    4.0 │
    │ Harper Arc   │   25.0 │    5.0 │    4.6 │
    └──────────────┴────────┴────────┴────────┘

## Loading a real season

    $ uv run nba-duckdb run-live --season 2026-27

A full season is a lot of requests. The client sends about one a second so
the NBA doesn't block you, which means it takes a while. If you just want to
check that everything works, add `--team-ids 1610612737` to load only
Atlanta's games. Data goes to
`data/warehouse/nba.duckdb`.

If a run dies halfway through, `run-live --resume-latest` picks up where it
left off. Running `run-live` again later grabs any new games. If you want that
to happen every night, there are Airflow DAGs for it; see
[docs/AIRFLOW.md](docs/AIRFLOW.md).

Summer League works too: `uv run nba-duckdb run-summer-league --season 2026-27`.

## More

- [docs/DIAGRAMS.md](docs/DIAGRAMS.md) has diagrams of how the tables fit together
- [VALIDATION.md](VALIDATION.md) covers how the metrics are calculated and where they're approximate
- `.env.example` lists the settings (database path, seasons, rate limits)
- [CONTRIBUTING.md](CONTRIBUTING.md) if you want to help out

MIT licensed.

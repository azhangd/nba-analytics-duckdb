# Test fixtures

A fake season (2099-00) with made-up teams and players, used by the tests and
`run-smoke`. None of it comes from real games.

To regenerate it:

    uv run nba-duckdb generate-test-fixtures --fixtures-dir tests/fixtures/generated

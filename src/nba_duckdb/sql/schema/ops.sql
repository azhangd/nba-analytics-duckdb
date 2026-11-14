-- Ops.

CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id              TEXT PRIMARY KEY,
    command             TEXT NOT NULL,
    graph               TEXT,
    scope_json          JSON,
    status              TEXT NOT NULL,
    started_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at         TIMESTAMP,
    task_count          INTEGER DEFAULT 0,
    success_count       INTEGER DEFAULT 0,
    degraded_count      INTEGER DEFAULT 0,
    deferred_count      INTEGER DEFAULT 0,
    failed_count        INTEGER DEFAULT 0,
    interrupted_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops.task_runs (
    run_id              TEXT NOT NULL,
    task_name           TEXT NOT NULL,
    task_type           TEXT NOT NULL,
    status              TEXT NOT NULL,
    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 1,
    started_at          TIMESTAMP,
    heartbeat_at        TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at         TIMESTAMP,
    worker_pid          INTEGER,
    progress_json       JSON,
    result_json         JSON,
    error_text          TEXT,
    PRIMARY KEY (run_id, task_name)
);

CREATE TABLE IF NOT EXISTS ops.ingestion_items (
    source              TEXT NOT NULL,
    season              TEXT NOT NULL,
    item_key            TEXT NOT NULL,
    game_id             TEXT NOT NULL,
    team_id             INTEGER,
    status              TEXT NOT NULL DEFAULT 'pending',
    attempts            INTEGER NOT NULL DEFAULT 0,
    rows_written        INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    first_seen_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at          TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at         TIMESTAMP,
    next_retry_at       TIMESTAMP,
    PRIMARY KEY (source, season, item_key)
);

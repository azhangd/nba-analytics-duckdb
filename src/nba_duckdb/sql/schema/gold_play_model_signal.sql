-- Python-owned gold model and external signal tables.

CREATE TABLE IF NOT EXISTS gold.model_artifacts (
    model_name      TEXT NOT NULL,
    season          TEXT NOT NULL,
    trained_at      TIMESTAMP DEFAULT current_timestamp,
    metadata_json   JSON,
    PRIMARY KEY (model_name, season)
);

CREATE TABLE IF NOT EXISTS gold.player_pageviews_daily (
    player_id       INTEGER NOT NULL,
    view_date       DATE NOT NULL,
    wikipedia_title TEXT,
    views           INTEGER NOT NULL DEFAULT 0,
    source_name     TEXT NOT NULL DEFAULT 'Wikipedia',
    source_url      TEXT,
    updated_at      TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (player_id, view_date)
);

CREATE TABLE IF NOT EXISTS gold.player_media_mentions_daily (
    player_id        INTEGER NOT NULL,
    mention_date     DATE NOT NULL,
    article_count    INTEGER NOT NULL DEFAULT 0,
    headline_count   INTEGER NOT NULL DEFAULT 0,
    tone_avg         REAL,
    query            TEXT,
    sample_headlines JSON,
    source_name      TEXT NOT NULL DEFAULT 'GDELT',
    source_url       TEXT,
    updated_at       TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (player_id, mention_date)
);

CREATE TABLE IF NOT EXISTS gold.player_jersey_rank_snapshots (
    player_id      INTEGER NOT NULL,
    snapshot_date  DATE NOT NULL,
    season         TEXT NOT NULL DEFAULT '2025-26',
    rank           INTEGER NOT NULL,
    list_name      TEXT NOT NULL DEFAULT 'Top-Selling Jerseys',
    release_title  TEXT,
    source_name    TEXT NOT NULL DEFAULT 'NBA/NBPA',
    source_url     TEXT,
    updated_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (player_id, snapshot_date, list_name)
);

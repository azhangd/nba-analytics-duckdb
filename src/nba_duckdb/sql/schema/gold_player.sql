-- Python-owned gold player and model tables.

CREATE TABLE IF NOT EXISTS gold.player_season_similarity (
    id                   BIGINT,
    season               TEXT NOT NULL DEFAULT '2025-26',
    player_id            INTEGER NOT NULL,
    similar_player_id    INTEGER NOT NULL,
    similar_player_name  TEXT,
    similar_team_id      INTEGER,
    similar_position     TEXT,
    similar_ppg          REAL,
    similar_rpg          REAL,
    similar_apg          REAL,
    similarity_score     REAL,
    rank                 INTEGER
);

CREATE TABLE IF NOT EXISTS gold.player_season_rapm (
    player_id       INTEGER NOT NULL,
    player_name     TEXT,
    season          TEXT NOT NULL DEFAULT '2025-26',
    team_id         INTEGER,
    minutes_played  REAL,
    possessions     REAL,
    stints          INTEGER,
    orapm           REAL,
    drapm           REAL,
    rapm            REAL,
    orapm_prior     REAL,
    drapm_prior     REAL,
    rapm_blended    REAL,
    rapm_ci_lower   REAL,
    rapm_ci_upper   REAL,
    ridge_lambda    REAL,
    PRIMARY KEY (player_id, season)
);

CREATE TABLE IF NOT EXISTS gold.player_zone_season_shot_quality_trained (
    id                        BIGINT,
    season                    TEXT NOT NULL DEFAULT '2025-26',
    player_id                 INTEGER,
    player_name               TEXT,
    team_id                   INTEGER,
    shot_zone_basic           TEXT,
    attempts                  INTEGER,
    makes                     INTEGER,
    actual_fg_pct             REAL,
    expected_fg_pct_baseline  REAL,
    expected_fg_pct_trained   REAL,
    quality_delta_trained     REAL,
    model_version             TEXT
);

CREATE TABLE IF NOT EXISTS gold.player_season_embeddings (
    player_id       INTEGER NOT NULL,
    season          TEXT NOT NULL DEFAULT '2025-26',
    player_name     TEXT,
    team_id         INTEGER,
    position        TEXT,
    pca_1           REAL,
    pca_2           REAL,
    pca_3           REAL,
    pca_4           REAL,
    pca_5           REAL,
    umap_x          REAL,
    umap_y          REAL,
    cluster_id      INTEGER,
    cluster_label   TEXT,
    PRIMARY KEY (player_id, season)
);

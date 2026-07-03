-- Bronze.

CREATE TABLE IF NOT EXISTS bronze.schedule (
    game_id        TEXT PRIMARY KEY,
    game_date      TEXT,
    home_team_id   INTEGER,
    away_team_id   INTEGER,
    home_team_abbr TEXT,
    away_team_abbr TEXT,
    game_status    INTEGER,
    game_status_text TEXT,
    season         TEXT,
    raw_json       JSON,
    ingested_at    TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.rosters (
    player_id     INTEGER NOT NULL,
    team_id       INTEGER NOT NULL,
    player_name   TEXT,
    jersey_number TEXT,
    position      TEXT,
    height        TEXT,
    weight        TEXT,
    birth_date    TEXT,
    experience    TEXT,
    season        TEXT,
    raw_json      JSON,
    ingested_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (player_id, team_id, season)
);

CREATE TABLE IF NOT EXISTS bronze.coaches (
    coach_id      TEXT NOT NULL,
    team_id       INTEGER NOT NULL,
    season        TEXT NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    coach_name    TEXT,
    is_assistant  SMALLINT,
    coach_type    TEXT,
    sort_sequence INTEGER,
    school        TEXT,
    birth_date    TEXT,
    raw_json      JSON,
    ingested_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (coach_id, team_id, season)
);

CREATE TABLE IF NOT EXISTS bronze.boxscores (
    game_id           TEXT PRIMARY KEY,
    traditional_json  JSON,
    advanced_json     JSON,
    ingested_at       TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.play_by_play (
    game_id     TEXT PRIMARY KEY,
    pbp_json    JSON,
    source      TEXT DEFAULT 'unknown',
    ingested_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.shot_charts (
    game_id         TEXT NOT NULL,
    team_id         INTEGER NOT NULL,
    shot_chart_json JSON,
    ingested_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (game_id, team_id)
);

CREATE TABLE IF NOT EXISTS bronze.standings (
    season         TEXT PRIMARY KEY,
    standings_json JSON,
    ingested_at    TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.tracking_stats (
    season        TEXT NOT NULL,
    category      TEXT NOT NULL,
    level         TEXT NOT NULL DEFAULT 'player',
    tracking_json JSON,
    ingested_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (season, category, level)
);

CREATE TABLE IF NOT EXISTS bronze.hustle (
    season      TEXT NOT NULL,
    level       TEXT NOT NULL,
    hustle_json JSON,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (season, level)
);

CREATE TABLE IF NOT EXISTS bronze.matchups (
    season       TEXT NOT NULL,
    team_id      BIGINT NOT NULL,
    direction    TEXT NOT NULL,
    matchup_json JSON,
    ingested_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (season, team_id, direction)
);

CREATE TABLE IF NOT EXISTS bronze.defense (
    season         TEXT NOT NULL,
    play_type      TEXT,
    type_grouping  TEXT,
    player_or_team TEXT,
    defense_json   JSON,
    ingested_at    TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (season, play_type, type_grouping, player_or_team)
);

CREATE TABLE IF NOT EXISTS bronze.game_detail (
    game_id      TEXT PRIMARY KEY,
    detail_json  JSON,
    ingested_at  TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.tracking (
    season        TEXT PRIMARY KEY,
    tracking_json JSON,
    ingested_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze.injuries (
    fetched_date  TEXT PRIMARY KEY,
    injuries_json JSON,
    ingested_at   TIMESTAMP DEFAULT current_timestamp
);

-- Metadata for models trained by Python tasks.

CREATE TABLE IF NOT EXISTS gold.model_artifacts (
    model_name      TEXT NOT NULL,
    season          TEXT NOT NULL,
    trained_at      TIMESTAMP DEFAULT current_timestamp,
    metadata_json   JSON,
    PRIMARY KEY (model_name, season)
);

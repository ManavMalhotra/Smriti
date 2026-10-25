-- v4 -> v5: stage-based batching and stage artifact persistence.
PRAGMA journal_mode = WAL;

BEGIN;

ALTER TABLE jobs ADD COLUMN stage TEXT DEFAULT 'stage_ocr';

CREATE TABLE stage_artifact (
    content_hash  TEXT NOT NULL,
    page          INTEGER NOT NULL CHECK (page >= 1),
    stage         TEXT NOT NULL,
    model_version TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (content_hash, page, stage, model_version)
);

CREATE INDEX idx_stage_artifact_lookup ON stage_artifact(content_hash, page, stage);

PRAGMA user_version = 5;

COMMIT;

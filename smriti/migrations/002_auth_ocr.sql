-- v1 -> v2: per-patient accounts, OCR page text, and extraction metadata.
PRAGMA journal_mode = WAL;

BEGIN;

ALTER TABLE patient ADD COLUMN username TEXT;
ALTER TABLE patient ADD COLUMN password_hash TEXT;

ALTER TABLE document ADD COLUMN doc_type_confidence REAL;
ALTER TABLE document ADD COLUMN processed_at TEXT;

ALTER TABLE observation ADD COLUMN label_raw TEXT;

CREATE TABLE auth_session (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE page_text (
    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL CHECK (page >= 1),
    text        TEXT NOT NULL,
    engine      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (document_id, page)
);

CREATE UNIQUE INDEX idx_patient_username ON patient(username COLLATE NOCASE)
    WHERE username IS NOT NULL;
CREATE INDEX idx_auth_session_patient ON auth_session(patient_id, expires_at);

PRAGMA user_version = 2;

COMMIT;

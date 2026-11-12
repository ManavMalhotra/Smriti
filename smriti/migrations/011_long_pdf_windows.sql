-- v10 -> v11: relax only operational page/window counts; retain frozen membership.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE stage_batches_next (
    id                 TEXT NOT NULL PRIMARY KEY,
    state              TEXT NOT NULL CHECK (state IN ('preparing', 'processing', 'cleanup_failed', 'done', 'failed', 'cancelled')),
    owner_token        TEXT NOT NULL,
    owner_pid          INTEGER NOT NULL CHECK (owner_pid >= 1),
    owner_created_at   REAL NOT NULL CHECK (owner_created_at > 0),
    membership_json    TEXT NOT NULL CHECK (CASE WHEN json_valid(membership_json) THEN
                           json_type(membership_json) = 'array' AND json_array_length(membership_json) BETWEEN 1 AND 10
                           AND length(CAST(membership_json AS BLOB)) <= 4096 ELSE 0 END),
    worksets_json      TEXT CHECK (worksets_json IS NULL OR CASE WHEN json_valid(worksets_json) THEN
                           json_type(worksets_json) = 'array' AND json_array_length(worksets_json) <= 10
                           AND length(CAST(worksets_json AS BLOB)) <= 65536 ELSE 0 END),
    workset_index      INTEGER NOT NULL DEFAULT 0 CHECK (workset_index >= 0),
    stage              TEXT NOT NULL DEFAULT 'preparing',
    attempt            INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    checkpoints_json   TEXT NOT NULL DEFAULT '{}' CHECK (CASE WHEN json_valid(checkpoints_json) THEN
                           json_type(checkpoints_json) = 'object' AND length(CAST(checkpoints_json AS BLOB)) <= 65536 ELSE 0 END),
    telemetry_json     TEXT NOT NULL DEFAULT '{}' CHECK (CASE WHEN json_valid(telemetry_json) THEN
                           json_type(telemetry_json) = 'object' AND length(CAST(telemetry_json AS BLOB)) <= 262144 ELSE 0 END),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    finished_at        TEXT
);

CREATE TABLE submissions_next (
    job_id                     TEXT NOT NULL PRIMARY KEY,
    -- RESTRICT preserves cleanup paths until owner erasure explicitly cleans them.
    patient_id                 TEXT NOT NULL REFERENCES patient(id) ON DELETE RESTRICT,
    content_hash               TEXT NOT NULL,
    spool_path                 TEXT NOT NULL UNIQUE,
    spool_bytes                INTEGER NOT NULL CHECK (spool_bytes >= 1),
    consent_scope              TEXT NOT NULL CHECK (consent_scope IN ('local', 'local_plus_projection')),
    consent_version            TEXT NOT NULL,
    consent_granted_at         TEXT NOT NULL,
    consent_revoked_at         TEXT,
    requested_doc_type         TEXT CHECK (requested_doc_type IN (
                                   'lab_report', 'prescription', 'pharmacy', 'discharge_summary',
                                   'ct', 'mri', 'xray', 'pathology', 'radiology', 'other')),
    requested_doc_date         TEXT,
    requested_collection_date  TEXT,
    state                      TEXT NOT NULL DEFAULT 'pending_intake' CHECK (state IN (
                                   'pending_intake', 'preparing', 'promoted', 'rejected', 'failed', 'cancelled')),
    stage                      TEXT NOT NULL DEFAULT 'pending_intake',
    error_code                 TEXT,
    document_id                TEXT UNIQUE REFERENCES document(id) ON DELETE RESTRICT,
    total_pages                INTEGER CHECK (total_pages >= 1),
    batch_id                   TEXT REFERENCES stage_batches_next(id) ON DELETE RESTRICT,
    batch_position             INTEGER CHECK (batch_position BETWEEN 0 AND 9),
    preparation_manifest_json  TEXT CHECK (preparation_manifest_json IS NULL OR CASE WHEN json_valid(preparation_manifest_json) THEN
                                   json_type(preparation_manifest_json) = 'object'
                                   AND length(CAST(preparation_manifest_json AS BLOB)) <= 262144 ELSE 0 END),
    progress_json              TEXT CHECK (progress_json IS NULL OR CASE WHEN json_valid(progress_json) THEN
                                   json_type(progress_json) = 'object' AND length(CAST(progress_json AS BLOB)) <= 262144 ELSE 0 END),
    spool_cleanup_requested_at TEXT,
    spool_cleanup_state        TEXT NOT NULL DEFAULT 'pending' CHECK (spool_cleanup_state IN ('pending', 'deleted', 'failed', 'debug_retained')),
    spool_cleanup_error_code   TEXT,
    spool_deleted_at           TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    CHECK ((state = 'promoted' AND document_id IS NOT NULL AND total_pages IS NOT NULL)
        OR (state <> 'promoted' AND document_id IS NULL AND total_pages IS NULL)),
    CHECK ((batch_id IS NULL) = (batch_position IS NULL)),
    CHECK ((spool_cleanup_state = 'deleted') = (spool_deleted_at IS NOT NULL)),
    CHECK (spool_cleanup_state = 'pending' OR spool_cleanup_requested_at IS NOT NULL)
);

INSERT INTO stage_batches_next SELECT * FROM stage_batches;
INSERT INTO submissions_next SELECT * FROM submissions;
DROP TABLE submissions;
DROP TABLE stage_batches;
ALTER TABLE stage_batches_next RENAME TO stage_batches;
ALTER TABLE submissions_next RENAME TO submissions;

CREATE UNIQUE INDEX idx_stage_batches_active ON stage_batches((1))
    WHERE state IN ('preparing', 'processing', 'cleanup_failed');
CREATE UNIQUE INDEX idx_submissions_live_hash ON submissions(patient_id, content_hash)
    WHERE state IN ('pending_intake', 'preparing', 'promoted');
CREATE UNIQUE INDEX idx_submissions_batch_position ON submissions(batch_id, batch_position)
    WHERE batch_id IS NOT NULL;
CREATE INDEX idx_submissions_pending ON submissions(state, created_at, job_id);
CREATE INDEX idx_submissions_owner ON submissions(patient_id, created_at);
CREATE INDEX idx_submissions_cleanup ON submissions(spool_cleanup_state)
    WHERE spool_cleanup_requested_at IS NOT NULL;

CREATE TRIGGER stage_batches_membership_frozen
BEFORE UPDATE OF membership_json ON stage_batches
WHEN NEW.membership_json IS NOT OLD.membership_json
BEGIN
    SELECT RAISE(ABORT, 'batch membership is frozen');
END;

CREATE TRIGGER submissions_batch_frozen
BEFORE UPDATE OF batch_id, batch_position ON submissions
WHEN OLD.batch_id IS NOT NULL AND (NEW.batch_id IS NOT OLD.batch_id OR NEW.batch_position IS NOT OLD.batch_position)
BEGIN
    SELECT RAISE(ABORT, 'submission batch membership is frozen');
END;

CREATE TRIGGER submissions_prepared_owner_insert
BEFORE INSERT ON submissions
WHEN NEW.document_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM document d JOIN jobs j ON j.document_id = d.id
    WHERE d.id = NEW.document_id AND d.patient_id = NEW.patient_id AND j.id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'prepared submission must match owner and public job');
END;

CREATE TRIGGER submissions_prepared_owner_update
BEFORE UPDATE OF document_id, patient_id, job_id ON submissions
WHEN NEW.document_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM document d JOIN jobs j ON j.document_id = d.id
    WHERE d.id = NEW.document_id AND d.patient_id = NEW.patient_id AND j.id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'prepared submission must match owner and public job');
END;

CREATE TEMP TABLE long_pdf_fk_guard (valid INTEGER NOT NULL CHECK (valid = 1));
INSERT INTO long_pdf_fk_guard SELECT NOT EXISTS (SELECT 1 FROM pragma_foreign_key_check);
DROP TABLE long_pdf_fk_guard;
PRAGMA user_version = 11;
COMMIT;
PRAGMA foreign_keys = ON;
